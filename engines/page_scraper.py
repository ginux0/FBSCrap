"""
PageScraper — scrapes posts from a specific Facebook page.
Example: aria-label engagement, clean_innertext, stale=8, login-wall detection.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .utils import (
    parse_relative_date,
    extract_engagement,
    extract_engagement_from_aria,
    clean_url,
    clean_innertext,
)

if TYPE_CHECKING:
    from .browser import ManagedBrowser
    from .logger import SessionLogger

_POST_URL_SELECTORS = [
    "a[href*='/posts/']",
    "a[href*='story_fbid']",
    "a[href*='/videos/']",
    "a[href*='/photos/']",
    "a[href*='/reel/']",
    "a[href*='permalink']",
    "a[href*='pfbid']",
    "a[href*='/watch/']",
    "a[href*='/p/']",
]

_JS_POST_URL = """
(article) => {
    const patterns = ['/posts/', 'story_fbid', '/videos/', '/photos/', '/reel/', 'pfbid', 'permalink', '/watch/'];
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

_JS_POST_TEXT = """
(article) => {
    // Stop at engagement bar — take only text ABOVE it
    const stopMarkers = ['me gusta', 'comentar', 'compartir', 'like', 'comment', 'share'];
    const lines = [];
    for (const el of article.querySelectorAll('span[dir], div[dir="auto"]')) {
        const txt = (el.innerText || '').trim();
        if (!txt || txt.length < 15) continue;
        const lower = txt.toLowerCase();
        if (stopMarkers.some(m => lower.startsWith(m))) break;
        if (!/^[\\d\\s.,KMkmil]+$/.test(txt)) lines.push(txt);
        if (lines.join(' ').length > 1000) break;
    }
    return lines.join(' ') || null;
}
"""

# Modern FB text containers — tried in order, first non-empty wins
_TEXT_SELECTORS = [
    "[data-ad-comet-preview='message']",
    "[data-ad-preview='message']",
    "div[dir='auto'][style]",
    "div[data-content-len]",
    "div[dir='auto'] > div > span",
    "span[dir='auto']",
]

_LOGIN_SIGNALS = ("login", "checkpoint", "recover", "/login/")


class PageScraper:

    def __init__(
        self,
        browser: "ManagedBrowser",
        cfg: dict,
        days: int = 7,
        max_posts: int = 150,
        min_engagement: int = 0,
        keywords: list[str] | None = None,
        verbose: bool = False,
        logger: "SessionLogger | None" = None,
    ):
        self.browser        = browser
        self.cfg            = cfg
        self.cutoff         = datetime.now() - timedelta(days=days)
        self.max_posts      = max_posts
        self.min_engagement = min_engagement
        self.keywords       = [k.lower() for k in (keywords or [])]
        self._scroll_pause  = cfg.get("scroll_pause_ms", 1500) / 1000.0
        self.verbose        = verbose
        self.logger         = logger

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    [PAGE] {msg}")

    async def scrape(self, target: dict) -> list[dict]:
        page  = await self.browser.new_page(block_resources=False)
        posts: list[dict] = []
        seen:  set[str]   = set()
        name  = target.get("name", target.get("handle", "?"))
        stop_reason = "max_scrolls"

        url     = target.get("url") or f"https://www.facebook.com/{target.get('handle', '')}"
        t_start = self.logger.page_start(name, url) if self.logger else datetime.now()

        try:
            self._log(f"Loading → {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(5)
            await self.browser.dismiss_overlays(page, self.cfg)

            current_url = page.url
            if self.logger:
                self.logger.page_landed(name, current_url)

            if any(s in current_url for s in _LOGIN_SIGNALS):
                if self.logger:
                    self.logger.page_login_wall(name)
                    self.logger.page_end(name, t_start, 0, 0, "login_wall")
                print(f"  [!] [{name}] Login wall detected — run: python3 fbscrap.py login")
                await page.close()
                return []

            self._log(f"Loaded: {current_url}")

            max_scrolls   = max(40, self.max_posts // 3)
            stale_scrolls = 0

            for scroll_n in range(max_scrolls):
                articles = await page.query_selector_all('div[role="article"]')
                posts_before = len(posts)

                # Iterate ALL visible articles every scroll — seen-set deduplicates.
                # Facebook virtual-DOM removes articles above viewport, so tracking
                # prev_article_count causes empty slices. Re-parse everything; seen
                # prevents duplicates and new ones are picked up naturally.
                for art in articles:
                    try:
                        post = await self._parse_article(art, target)
                        if post:
                            key = post["url"] or post["text"][:100]
                            if key and key not in seen:
                                seen.add(key)
                                posts.append(post)
                    except Exception as ex:
                        self._log(f"  parse error: {ex}")
                        continue

                new_posts = len(posts) - posts_before
                self._log(
                    f"Scroll {scroll_n:2d} | articles={len(articles):3d}"
                    f" new_posts=+{new_posts} | total={len(posts):3d}"
                )
                if self.logger:
                    self.logger.page_scroll(scroll_n, len(articles), new_posts, len(posts))

                if len(posts) >= self.max_posts:
                    stop_reason = "max_posts"
                    self._log("max_posts reached")
                    break

                # Stale = scrolled but zero new unique posts found
                if new_posts == 0:
                    stale_scrolls += 1
                    self._log(f"  stale={stale_scrolls}/8")
                    if self.logger:
                        self.logger.page_stale(name, stale_scrolls, 8)
                    if stale_scrolls >= 8:
                        stop_reason = "stale_8"
                        self._log("8 stale scrolls (no new unique posts) — stopping")
                        break
                else:
                    stale_scrolls = 0

                delta = 800 + (scroll_n % 5) * 200
                await page.evaluate(f"window.scrollBy(0, {delta})")
                await asyncio.sleep(self._scroll_pause + scroll_n * 0.04)

        except Exception as e:
            stop_reason = "exception"
            if self.logger:
                self.logger.exception(name)
            print(f"  [!] PageScraper [{name}]: {e}")
        finally:
            await page.close()

        filtered = self._apply_filters(posts)
        if self.logger:
            self.logger.page_end(name, t_start, len(posts), len(filtered), stop_reason)
        print(f"  [PAGE] {name:40s} → raw={len(posts):3d}  kept={len(filtered):3d}")
        return filtered

    async def _parse_article(self, article, target: dict) -> dict | None:
        # Skip comment sub-articles nested inside a post article
        try:
            is_comment = await article.evaluate(
                "el => !!el.parentElement?.closest('[role=\"article\"]')"
            )
            if is_comment:
                return None
        except Exception:
            pass

        url        = await self._get_url(article)
        text       = await self._get_text(article)
        ts, ts_raw = await self._get_timestamp(article)
        r, c, s    = await self._get_engagement(article)

        # Must have URL or at least 20 chars of real text
        if not url and len(text) < 20:
            return None

        # Date gate — None timestamp = include (can't verify, keep it)
        if ts and ts < self.cutoff:
            return None

        return {
            "url":              url,
            "source":           target.get("name", "unknown"),
            "source_handle":    target.get("handle", ""),
            "source_category":  target.get("category", "media"),
            "source_ciudad":    target.get("ciudad", ""),
            "text":             text,
            "timestamp":        ts.isoformat() if ts else None,
            "timestamp_raw":    ts_raw,
            "reactions":        r,
            "comments_count":   c,
            "shares":           s,
            "engagement_total": r + c + s,
            "scraped_at":       datetime.now().isoformat(),
            "mode":             "page",
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
        # JS fallback — catches deeply nested links missed by CSS selectors
        try:
            href = await article.evaluate(_JS_POST_URL)
            if href:
                cleaned = clean_url(href)
                if cleaned and "facebook.com" in cleaned:
                    return cleaned
        except Exception:
            pass
        return ""

    async def _get_text(self, article) -> str:
        # Strategy 1: JS extraction — stops before engagement bar, avoids comments
        try:
            txt = await article.evaluate(_JS_POST_TEXT)
            if txt and len(txt) > 20:
                return txt[:3000]
        except Exception:
            pass

        # Strategy 2: known text-container selectors
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

        # Strategy 3: clean full article innerText (removes UI noise)
        try:
            raw = await article.inner_text()
            cleaned = clean_innertext(raw, min_line_len=15)
            if len(cleaned) > 15:
                return cleaned[:3000]
            return raw.strip()[:3000]
        except Exception:
            return ""

    async def _get_timestamp(self, article) -> tuple[datetime | None, str]:
        # Strategy 1: legacy data-utime / abbr / time attributes
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

        # Strategy 2: tooltip title on post link
        try:
            el = await article.query_selector("a[href*='/posts/'] span[title]")
            if el:
                title = await el.get_attribute("title") or ""
                if title:
                    return parse_relative_date(title), title
        except Exception:
            pass

        # Strategy 3: JS scan — modern FB uses plain spans with relative text
        try:
            raw = await article.evaluate(_JS_TIMESTAMP)
            if raw:
                return parse_relative_date(raw), raw
        except Exception:
            pass

        return None, ""

    async def _get_engagement(self, article) -> tuple[int, int, int]:
        r = c = s = 0

        # Strategy 1: scan aria-label attributes inside the article
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

        # Strategy 2: full inner_text regex if aria yielded nothing
        if r == 0 and c == 0 and s == 0:
            try:
                r, c, s = extract_engagement(await article.inner_text())
            except Exception:
                pass

        return r, c, s

    def _apply_filters(self, posts: list[dict]) -> list[dict]:
        if self.keywords:
            posts = [
                p for p in posts
                if any(k in p.get("text", "").lower() for k in self.keywords)
            ]
        if self.min_engagement:
            posts = [p for p in posts if p.get("engagement_total", 0) >= self.min_engagement]
        return posts[: self.max_posts]
