"""
SearchScraper — searches Facebook for posts matching a query.
Example: GraphQL interception primary + DOM fallback, aria engagement, clean text.

Primary path: intercepts /api/graphql/ POST responses and extracts post data
from the serpResponse JSON (url, text, author, timestamp, engagement).
Fallback: DOM selector walk on div[role="article"] nodes (may return 0 on modern FB).
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from .utils import (
    parse_relative_date,
    extract_engagement,
    extract_engagement_from_aria,
    clean_url,
    clean_innertext,
)
from .graphql_extractor import parse_fb_graphql_body

if TYPE_CHECKING:
    from .browser import ManagedBrowser
    from .logger import SessionLogger

_RECENT_SELECTORS = [
    "span:has-text('Más recientes')",
    "span:has-text('Latest')",
    "span:has-text('Recent')",
    "[aria-label*='Más recientes']",
    "[aria-label*='Recent']",
    "div[role='option']:has-text('Más recientes')",
    "div[role='option']:has-text('Latest')",
    "div[role='menuitem']:has-text('Más recientes')",
    "div[role='menuitem']:has-text('Latest')",
    "li:has-text('Más recientes')",
    "li:has-text('Latest')",
]

_POSTS_TAB_SELECTORS = [
    "a[href*='type=post']",
    "[role='tab']:has-text('Publicaciones')",
    "[role='tab']:has-text('Posts')",
    "span:has-text('Publicaciones')",
    "a:has-text('Publicaciones')",
]

# Cards that represent groups/pages in search results — NOT actual posts
_GROUP_CARD_SIGNALS = (
    " miembros", " members", "Público ·", "Privado ·",
    "público ·", "privado ·", "Grupo público", "Grupo privado",
)

_JS_POST_URL = """
(article) => {
    const patterns = ['/posts/', 'story_fbid', '/videos/', '/photos/', '/reel/', 'pfbid', 'permalink'];
    for (const a of article.querySelectorAll('a[href]')) {
        const h = a.href || '';
        if (h.includes('facebook.com') && patterns.some(p => h.includes(p)))
            return h;
    }
    return null;
}
"""

_JS_TIMESTAMP = """
(article) => {
    const relPat = /^\\d+\\s*(s|min|h|d|sem|mes)|^hace\\s+\\d+|^ayer$|^hoy$|^yesterday$|^today$|^\\d{1,2}\\s+de\\s+\\w+/i;
    for (const el of article.querySelectorAll('span, a, abbr, time')) {
        const txt = (el.textContent || '').trim();
        if (relPat.test(txt) && txt.length < 60) return txt;
        const lbl = el.getAttribute('aria-label') || '';
        if (relPat.test(lbl) && lbl.length < 60) return lbl;
        const title = el.getAttribute('title') || '';
        if (relPat.test(title) && title.length < 60) return title;
    }
    return null;
}
"""

_SOURCE_SELECTORS = [
    "h3 a",
    "h4 a",
    "strong a",
    "h3",
    "h4",
    "strong",
    "a[role='link'] span[dir='auto']",
]

_TEXT_SELECTORS = [
    "[data-ad-comet-preview='message']",
    "[data-ad-preview='message']",
    "div[dir='auto'][style]",
    "div[data-content-len]",
    "span[dir='auto']",
]

_POST_URL_SELECTORS = [
    "a[href*='/posts/']",
    "a[href*='story_fbid']",
    "a[href*='/videos/']",
    "a[href*='/photos/']",
    "a[href*='/reel/']",
    "a[href*='permalink']",
    "a[href*='pfbid']",
]

_LOGIN_SIGNALS = ("login", "checkpoint", "recover", "/login/")


class SearchScraper:

    def __init__(
        self,
        browser: "ManagedBrowser",
        cfg: dict,
        days: int = 7,
        max_posts: int = 150,
        min_engagement: int = 0,
        verbose: bool = False,
        logger: "SessionLogger | None" = None,
    ):
        self.browser        = browser
        self.cfg            = cfg
        self.cutoff         = datetime.now() - timedelta(days=days)
        self.max_posts      = max_posts
        self.min_engagement = min_engagement
        self._scroll_pause  = cfg.get("scroll_pause_ms", 1500) / 1000.0
        self.verbose        = verbose
        self.logger         = logger

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    [SEARCH] {msg}")

    async def scrape(self, query: str) -> list[dict]:
        page  = await self.browser.new_page(block_resources=False)
        posts: list[dict] = []
        seen:  set[str]   = set()
        stop_reason = "max_scrolls"

        # ── GraphQL intercept queue ───────────────────────────────────────────
        # Populated by the response listener before page.goto() is called.
        graphql_bodies: list[bytes] = []

        async def _on_response(response) -> None:
            try:
                url = response.url
                if "graphql" not in url.lower():
                    return
                body = await response.body()
                if body and len(body) > 500:
                    graphql_bodies.append(body)
                    self._log(f"  GraphQL body captured: {len(body):,} bytes (total={len(graphql_bodies)})")
            except Exception:
                pass

        page.on("response", _on_response)
        # ─────────────────────────────────────────────────────────────────────

        search_url = f"https://www.facebook.com/search/posts?q={quote_plus(query)}"
        t_start = self.logger.search_start(query, search_url) if self.logger else datetime.now()

        try:
            self._log(f"Loading → {search_url}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(8.0)   # allow FB JS + GraphQL calls to settle
            await self.browser.dismiss_overlays(page, self.cfg)

            current_url = page.url
            if any(s in current_url for s in _LOGIN_SIGNALS):
                if self.logger:
                    self.logger.search_end(query, t_start, 0, 0, "login_wall")
                print(f"  [!] [SEARCH] Login wall detected — run: python3 fbscrap.py login")
                await page.close()
                return []

            # Click "Publicaciones/Posts" tab to ensure we see posts, not groups/pages
            posts_tab_clicked = await self._click_posts_tab(page)
            self._log(f"Posts tab clicked: {posts_tab_clicked}")
            if posts_tab_clicked:
                await asyncio.sleep(2.0)

            # Apply "Más recientes" filter
            filter_applied = await self._apply_recent_filter(page)
            self._log(f"Recent filter applied: {filter_applied}")
            if self.logger:
                self.logger.search_filter(filter_applied)
            if filter_applied:
                await asyncio.sleep(2.5)

            max_scrolls   = max(50, self.max_posts // 3)
            stale_scrolls = 0
            # Track last-processed graphql body count for GraphQL-side stale detection
            graphql_processed_count = 0

            for scroll_n in range(max_scrolls):
                posts_before = len(posts)

                # ── DOM fallback: div[role="article"] ────────────────────────
                # Modern FB search may render 0 articles — that's OK, GraphQL path handles it
                articles = await page.query_selector_all('div[role="article"]')
                for art in articles:
                    try:
                        post = await self._parse_result(art, query)
                        if post:
                            key = post["url"] or post["text"][:100]
                            if key and key not in seen:
                                seen.add(key)
                                posts.append(post)
                    except Exception as ex:
                        self._log(f"  parse error: {ex}")
                        continue

                # ── Process any newly accumulated GraphQL responses ───────────
                new_graphql_bodies = graphql_bodies[graphql_processed_count:]
                if new_graphql_bodies:
                    gq_posts = self._parse_graphql_queue(new_graphql_bodies, query)
                    graphql_processed_count = len(graphql_bodies)
                    for gpost in gq_posts:
                        key = gpost.get("url") or gpost.get("text", "")[:100]
                        if key and key not in seen:
                            seen.add(key)
                            posts.append(gpost)
                        elif gpost.get("url"):
                            # Enrich existing DOM post with GraphQL data
                            for existing in posts:
                                if existing.get("url") == gpost["url"]:
                                    if gpost.get("text") and len(gpost["text"]) > len(existing.get("text", "")):
                                        existing["text"] = gpost["text"]
                                    if gpost.get("source") and existing.get("source") in ("", "unknown"):
                                        existing["source"] = gpost["source"]
                                    if gpost.get("timestamp") and not existing.get("timestamp"):
                                        existing["timestamp"] = gpost["timestamp"]
                                        existing["timestamp_raw"] = gpost["timestamp_raw"]
                                    if gpost.get("reactions", 0) > existing.get("reactions", 0):
                                        existing["reactions"] = gpost["reactions"]
                                    if gpost.get("comments_count", 0) > existing.get("comments_count", 0):
                                        existing["comments_count"] = gpost["comments_count"]
                                    if gpost.get("shares", 0) > existing.get("shares", 0):
                                        existing["shares"] = gpost["shares"]
                                    existing["engagement_total"] = (
                                        existing.get("reactions", 0)
                                        + existing.get("comments_count", 0)
                                        + existing.get("shares", 0)
                                    )
                                    break

                new_posts = len(posts) - posts_before
                graphql_active = len(new_graphql_bodies) > 0
                self._log(
                    f"Scroll {scroll_n:2d} | articles={len(articles):3d}"
                    f" new_posts=+{new_posts} | total={len(posts):3d}"
                    f" | graphql_q={len(graphql_bodies)}"
                )

                if len(posts) >= self.max_posts:
                    stop_reason = "max_posts"
                    self._log("max_posts reached")
                    break

                if new_posts == 0:
                    # Don't count as stale if GraphQL is still sending responses
                    # (they may all be filtered as old but the feed is still active)
                    if not graphql_active:
                        stale_scrolls += 1
                    stale_limit = 12 if len(articles) == 0 else 8
                    self._log(f"  stale={stale_scrolls}/{stale_limit}"
                              + (" [graphql active — not counting]" if graphql_active else ""))
                    if stale_scrolls >= stale_limit:
                        stop_reason = "stale_8"
                        self._log(f"{stale_limit} stale scrolls (no new unique posts) — stopping")
                        break
                else:
                    stale_scrolls = 0

                delta = 900 + (scroll_n % 4) * 250
                await page.evaluate(f"window.scrollBy(0, {delta})")
                # When DOM has no articles (GraphQL-only mode), use a longer pause
                # so the server has time to respond to the scroll-triggered load.
                # FB search GraphQL response arrives 3-5s after the triggering scroll.
                dom_empty = len(articles) == 0
                base_pause = max(self._scroll_pause, 4.5) if dom_empty else self._scroll_pause
                await asyncio.sleep(base_pause + scroll_n * 0.04)

            # ── Final pass: process any remaining unprocessed GraphQL bodies ──
            leftover_bodies = graphql_bodies[graphql_processed_count:]
            if leftover_bodies:
                gq_posts = self._parse_graphql_queue(leftover_bodies, query)
                self._log(f"GraphQL final pass: {len(leftover_bodies)} bodies → {len(gq_posts)} posts")
                for gpost in gq_posts:
                    key = gpost.get("url") or gpost.get("text", "")[:100]
                    if key and key not in seen:
                        seen.add(key)
                        posts.append(gpost)
                    elif gpost.get("url"):
                        for existing in posts:
                            if existing.get("url") == gpost["url"]:
                                if gpost.get("text") and len(gpost["text"]) > len(existing.get("text", "")):
                                    existing["text"] = gpost["text"]
                                if gpost.get("reactions", 0) > existing.get("reactions", 0):
                                    existing["reactions"] = gpost["reactions"]
                                if gpost.get("comments_count", 0) > existing.get("comments_count", 0):
                                    existing["comments_count"] = gpost["comments_count"]
                                if gpost.get("shares", 0) > existing.get("shares", 0):
                                    existing["shares"] = gpost["shares"]
                                existing["engagement_total"] = (
                                    existing.get("reactions", 0)
                                    + existing.get("comments_count", 0)
                                    + existing.get("shares", 0)
                                )
                                break

            self._log(
                f"GraphQL total: {len(graphql_bodies)} responses captured | "
                f"{len(posts)} posts after merge"
            )
            if not graphql_bodies:
                self._log("No GraphQL responses captured — DOM-only mode")

        except Exception as e:
            stop_reason = "exception"
            if self.logger:
                self.logger.exception(f"search:{query}")
            print(f"  [!] SearchScraper [{query}]: {e}")
        finally:
            await page.close()

        if self.min_engagement:
            posts = [p for p in posts if p.get("engagement_total", 0) >= self.min_engagement]

        result = posts[: self.max_posts]
        if self.logger:
            self.logger.search_end(query, t_start, len(posts), len(result), stop_reason)
        print(f"  [SEARCH] '{query}':  raw={len(posts):3d}  kept={len(result):3d}")
        return result

    def _parse_graphql_queue(self, bodies: list[bytes], query: str) -> list[dict]:
        """
        Parse accumulated GraphQL response bodies and return normalized post dicts
        with the same schema as _parse_result().
        """
        seen_urls: set[str] = set()
        result: list[dict] = []
        for body in bodies:
            try:
                extracted = parse_fb_graphql_body(body)
                for gpost in extracted:
                    key = gpost.get("url") or gpost.get("text", "")[:100]
                    if not key or key in seen_urls:
                        continue
                    seen_urls.add(key)

                    # Date gate
                    ts_dt: datetime | None = None
                    ts_raw = gpost.get("timestamp_raw", "")
                    if ts_raw and ts_raw.isdigit():
                        try:
                            ts_dt = datetime.fromtimestamp(int(ts_raw))
                        except Exception:
                            pass
                    if not ts_dt and gpost.get("timestamp"):
                        try:
                            ts_dt = datetime.fromisoformat(gpost["timestamp"])
                        except Exception:
                            pass

                    if ts_dt and ts_dt < self.cutoff:
                        self._log(f"  graphql skip (old): {gpost.get('url', '')[:60]}")
                        continue

                    r = gpost.get("reactions", 0)
                    c = gpost.get("comments_count", 0)
                    s = gpost.get("shares", 0)

                    _gurl = gpost.get("url", "")
                    _gtype = ("reel"  if _gurl and "/reel/"   in _gurl else
                              "video" if _gurl and ("/videos/" in _gurl or "/watch/" in _gurl) else
                              "photo" if _gurl and ("/photos/" in _gurl or "/photo?"  in _gurl) else
                              "post")
                    result.append({
                        "url":              _gurl,
                        "source":           gpost.get("source", "unknown") or "unknown",
                        "source_handle":    "",
                        "source_category":  "search_result",
                        "source_ciudad":    "",
                        "text":             gpost.get("text", ""),
                        "timestamp":        ts_dt.isoformat() if ts_dt else gpost.get("timestamp"),
                        "timestamp_raw":    ts_raw,
                        "reactions":        r,
                        "comments_count":   c,
                        "shares":           s,
                        "engagement_total": r + c + s,
                        "post_type":        _gtype,
                        "query":            query,
                        "scraped_at":       datetime.now().isoformat(),
                        "mode":             "search",
                    })
            except Exception as ex:
                self._log(f"  graphql parse error: {ex}")
                continue
        return result

    async def _apply_recent_filter(self, page) -> bool:
        # Strategy 1: Playwright has-text selectors
        for sel in _RECENT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click(timeout=3000)
                    return True
            except Exception:
                continue

        # Strategy 2: JS walk — find any clickable with recent-filter text
        try:
            clicked = await page.evaluate("""
                () => {
                    const targets = ['Más recientes', 'Latest', 'Most Recent', 'Recent', 'Recientes'];
                    const sel = 'span, button, div[role="tab"], div[role="option"], div[role="menuitem"], li, a';
                    for (const el of document.querySelectorAll(sel)) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (targets.some(t => txt === t || txt.startsWith(t))) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if clicked:
                return True
        except Exception:
            pass

        # Strategy 3: look for Sort button (NOT "Filtros de resultados" which navigates away)
        # Only click buttons whose aria-label contains 'Ordenar' or 'Sort' — never 'Filtros'
        try:
            filter_btns = await page.query_selector_all(
                "[aria-label*='Ordenar'], [aria-label*='Sort']"
            )
            for btn in filter_btns:
                try:
                    label = (await btn.get_attribute("aria-label") or "").lower()
                    # Skip "Filtros de resultados" — it navigates away from posts
                    if "filtro" in label or "filter" in label:
                        continue
                    if await btn.is_visible():
                        await btn.click(timeout=2000)
                        await asyncio.sleep(1)
                        # Now look for recent option in opened dropdown
                        for sel in _RECENT_SELECTORS:
                            try:
                                el = await page.query_selector(sel)
                                if el and await el.is_visible():
                                    await el.click(timeout=2000)
                                    return True
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            pass

        return False

    async def _parse_result(self, article, query: str) -> dict | None:
        url    = await self._get_url(article)
        source = await self._get_source(article)
        text   = await self._get_text(article)
        ts, ts_raw = await self._get_timestamp(article)
        r, c, s = await self._get_engagement(article)

        # Reject group/page listing cards — they appear in search but are not posts
        if any(sig in text for sig in _GROUP_CARD_SIGNALS):
            return None

        if not url and len(text) < 20:
            return None

        # Date gate — None = include (can't verify date, don't discard)
        if ts and ts < self.cutoff:
            return None

        post_type = ("reel"  if url and "/reel/"   in url else
                     "video" if url and ("/videos/" in url or "/watch/" in url) else
                     "photo" if url and ("/photos/" in url or "/photo?"  in url) else
                     "post")
        return {
            "url":              url,
            "source":           source,
            "source_handle":    "",
            "source_category":  "search_result",
            "source_ciudad":    "",
            "text":             text,
            "timestamp":        ts.isoformat() if ts else None,
            "timestamp_raw":    ts_raw,
            "reactions":        r,
            "comments_count":   c,
            "shares":           s,
            "engagement_total": r + c + s,
            "post_type":        post_type,
            "query":            query,
            "scraped_at":       datetime.now().isoformat(),
            "mode":             "search",
        }

    async def _get_url(self, article) -> str:
        for sel in _POST_URL_SELECTORS:
            try:
                el = await article.query_selector(sel)
                if el:
                    href = await el.get_attribute("href") or ""
                    cleaned = clean_url(href)
                    if cleaned and "facebook.com" in cleaned:
                        return cleaned
            except Exception:
                continue
        # JS fallback — catches deeply nested or dynamically rendered links
        try:
            href = await article.evaluate(_JS_POST_URL)
            if href:
                cleaned = clean_url(href)
                if cleaned and "facebook.com" in cleaned:
                    return cleaned
        except Exception:
            pass
        return ""

    async def _get_source(self, article) -> str:
        for sel in _SOURCE_SELECTORS:
            try:
                el = await article.query_selector(sel)
                if el:
                    t = (await el.inner_text()).strip()
                    if t and len(t) > 1:
                        return t[:80]
            except Exception:
                continue
        return "unknown"

    async def _get_text(self, article) -> str:
        for sel in _TEXT_SELECTORS:
            try:
                els = await article.query_selector_all(sel)
                parts = []
                for el in els[:6]:
                    t = (await el.inner_text()).strip()
                    if len(t) > 15:
                        parts.append(t)
                if parts:
                    combined = " ".join(parts)
                    if len(combined) > 30:
                        return combined[:3000]
            except Exception:
                continue

        try:
            raw = await article.inner_text()
            cleaned = clean_innertext(raw, min_line_len=20)
            if len(cleaned) > 20:
                return cleaned[:3000]
            return raw.strip()[:3000]
        except Exception:
            return ""

    async def _get_timestamp(self, article) -> tuple[datetime | None, str]:
        for sel in ["abbr[data-utime]", "span[data-utime]", "abbr", "time"]:
            try:
                el = await article.query_selector(sel)
                if not el:
                    continue
                utime = await el.get_attribute("data-utime")
                if utime and utime.isdigit():
                    return datetime.fromtimestamp(int(utime)), utime
                dt_attr = await el.get_attribute("datetime")
                if dt_attr:
                    try:
                        return datetime.fromisoformat(dt_attr.replace("Z", "").split(".")[0]), dt_attr
                    except Exception:
                        pass
                raw = (await el.inner_text()).strip()
                parsed = parse_relative_date(raw)
                if parsed or raw:
                    return parsed, raw
            except Exception:
                continue

        try:
            el = await article.query_selector("a[href*='/posts/'] span[title]")
            if el:
                title = await el.get_attribute("title") or ""
                if title:
                    return parse_relative_date(title), title
        except Exception:
            pass

        # JS fallback — modern FB renders timestamps as plain spans with relative text
        try:
            raw = await article.evaluate(_JS_TIMESTAMP)
            if raw:
                return parse_relative_date(raw), raw
        except Exception:
            pass

        return None, ""

    async def _click_posts_tab(self, page) -> bool:
        """Click the Posts/Publicaciones tab in search results to filter out groups/pages."""
        # Already on /search/posts — clicking again re-navigates and kills results
        if "/search/posts" in page.url:
            return False
        for sel in _POSTS_TAB_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click(timeout=3000)
                    return True
            except Exception:
                continue
        # JS fallback
        try:
            clicked = await page.evaluate("""
                () => {
                    const targets = ['Publicaciones', 'Posts'];
                    for (const el of document.querySelectorAll('a, span, [role="tab"]')) {
                        if (targets.includes((el.innerText || '').trim())) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            return bool(clicked)
        except Exception:
            return False

    async def _get_engagement(self, article) -> tuple[int, int, int]:
        r = c = s = 0

        try:
            els = await article.query_selector_all("[aria-label]")
            for el in els:
                try:
                    label = (await el.get_attribute("aria-label") or "").strip()
                    if not label:
                        continue
                    label_l = label.lower()
                    val = extract_engagement_from_aria(label)
                    if val <= 0:
                        continue
                    if any(w in label_l for w in ["me gusta", "like", "reaccion", "reaction"]):
                        r = max(r, val)
                    elif any(w in label_l for w in ["comentario", "comment"]):
                        c = max(c, val)
                    elif any(w in label_l for w in ["compartido", "share", "veces"]):
                        s = max(s, val)
                except Exception:
                    continue
        except Exception:
            pass

        if r == 0 and c == 0 and s == 0:
            try:
                r, c, s = extract_engagement(await article.inner_text())
            except Exception:
                pass

        return r, c, s
