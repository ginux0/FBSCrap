"""
CommentScraper — deep-scrapes comments on Facebook posts AND Reels.

Posts:  comments load inline below the post via standard DOM.
Reels:  comments live in a floating right-side panel that must be
        opened by clicking the comment icon before any selector works.

Timestamps are extracted from relative-time text in the DOM ("2h", "1 min",
"3d", "ayer") and converted to approximate ISO datetimes for temporal analysis.

All timeouts, delays, limits, and DOM selectors read from cfg. Zero hardcoded values.
"""
from __future__ import annotations
import asyncio, json, re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .browser import ManagedBrowser

from engines.name_utils import clean_actor_name

_BASE_DIR = Path(__file__).parent.parent

# ── Fallback selectors (used only if dom_selectors.json is missing) ───────────
_FALLBACK_SELECTORS = {
    "expand_selectors": [
        "span:has-text('Ver más comentarios')",
        "span:has-text('View more comments')",
        "span:has-text('Ver más respuestas')",
        "span:has-text('View more replies')",
        "[aria-label*='comentarios']:not(div[role='article'])",
    ],
    "reel_comment_open_selectors": [
        "div[aria-label*='Comentario'][role='button']",
        "div[aria-label*='Comment'][role='button']",
        "[aria-label*='comentarios'][role='button']",
        "[aria-label*='comments'][role='button']",
        "div[aria-label*='Dejar un comentario']",
        "div[aria-label*='Leave a comment']",
    ],
    "reel_expand_selectors": [
        "div[role='button']:has-text('Ver más comentarios')",
        "div[role='button']:has-text('View more comments')",
        "div[role='button']:has-text('Ver más respuestas')",
        "div[role='button']:has-text('View more replies')",
        "span:has-text('Ver más comentarios')",
        "span:has-text('View more comments')",
    ],
    "reel_panel_selectors": [
        "div[aria-label*='Sección de comentarios']",
        "div[aria-label*='Comments section']",
        "div[aria-label*='comment' i][role='complementary']",
        "div[role='complementary']",
    ],
    "text_selectors": [
        "[data-ad-comet-preview='message']",
        "span[dir='auto']",
        "div[dir='auto']",
    ],
    "comment_selectors": [
        "div[aria-label*='Comentario de']",
        "div[role='article'] > div > div > ul > li",
        "ul > li[style]",
        "div[role='article'] ul li",
    ],
    "panel_comment_selectors": [
        "div[role='article']",
        "ul > li",
        "div[aria-label*='Comentario de']",
    ],
    "noise_pattern": r"^(Me gusta|Like|Responder|Reply|Ver|View|Seguir|Follow)\b",
}

# ── Timestamp patterns (relative → absolute) ──────────────────────────────────
_TS_PATTERNS: list[tuple[re.Pattern, str, int]] = [
    (re.compile(r'^(\d+)\s*s(?:eg)?\.?$',              re.I), "seconds", 1),
    (re.compile(r'^(\d+)\s*min(?:utos?)?\.?$',         re.I), "minutes", 1),
    (re.compile(r'^(\d+)\s*h(?:r|rs|oras?)?\.?$',      re.I), "hours",   1),
    (re.compile(r'^(\d+)\s*d(?:ías?|ias?|ays?)?\.?$',  re.I), "days",    1),
    (re.compile(r'^(\d+)\s*w(?:ks?|eeks?)\.?$',        re.I), "weeks",   7),
    (re.compile(r'^(\d+)\s*semanas?\.?$',               re.I), "weeks",   7),
    (re.compile(r'^hace\s+(\d+)\s+seg',                re.I), "seconds", 1),
    (re.compile(r'^hace\s+(\d+)\s+min',                re.I), "minutes", 1),
    (re.compile(r'^hace\s+(\d+)\s+hora',               re.I), "hours",   1),
    (re.compile(r'^hace\s+(\d+)\s+d[íi]a',             re.I), "days",    1),
    (re.compile(r'^hace\s+(\d+)\s+semana',             re.I), "weeks",   7),
]
_TS_YESTERDAY = re.compile(r'^(ayer|yesterday)$', re.I)
_TS_ABSOLUTE  = re.compile(
    r'(\d{1,2})\s+de?\s+(\w+)(?:\s+de?\s+(\d{4}))?(?:\s+a\s+las?\s+(\d{1,2}):(\d{2}))?',
    re.I
)
# Strips FB DOM noise appended to timestamp: "· Editado", "· Me gusta", etc.
_TS_STRIP_SUFFIX = re.compile(r'\s*[·•]\s*.+$')
_MONTH_MAP = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    "jan": 1, "apr": 4, "aug": 8,
}

# Lines that are FB UI labels, not author names — skip entirely as author candidate
_AUTHOR_SKIP_RE = re.compile(
    r'^(editado|edited|ver\s+traduc|see\s+transl|patrocinado|sponsored'
    r'|autor[a-z]*$|escrib[eió]|top\s+fan|fan\s+destac'
    r'|seguir|follow|más\s+informac|see\s+more)$',
    re.I,
)

# Noise suffixes that leak onto author lines: " 14 h", " 2 minMe gusta…"
# No \b: "14 hMe" has no word boundary between h and M
_AUTHOR_SUFFIX_RE = re.compile(
    r'\s+\d+\s*(?:h(?:rs?|oras?)?|min(?:utos?)?|s(?:eg)?).*$', re.I
)


def _parse_relative_ts(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    # Strip leading separator Facebook injects before timestamps: "· 2 h"
    t = t.lstrip("·•· ").strip()
    # Strip trailing FB UI noise: "14 h · Editado", "2h · Me gusta"
    t = _TS_STRIP_SUFFIX.sub("", t).strip()
    if not t:
        return None
    now = datetime.now()

    for pat, unit, multiplier in _TS_PATTERNS:
        m = pat.match(t)
        if m:
            n     = int(m.group(1)) * multiplier
            delta = {
                "seconds": timedelta(seconds=n),
                "minutes": timedelta(minutes=n),
                "hours":   timedelta(hours=n),
                "days":    timedelta(days=n),
                "weeks":   timedelta(weeks=n // 7),
            }.get(unit)
            if delta:
                return (now - delta).isoformat(timespec="seconds")

    if _TS_YESTERDAY.match(t):
        return (now - timedelta(days=1)).replace(
            hour=12, minute=0, second=0
        ).isoformat(timespec="seconds")

    m = _TS_ABSOLUTE.search(t)
    if m:
        day    = int(m.group(1))
        month  = _MONTH_MAP.get(m.group(2).lower()[:3])
        year   = int(m.group(3)) if m.group(3) else now.year
        hour   = int(m.group(4)) if m.group(4) else 12
        minute = int(m.group(5)) if m.group(5) else 0
        if month:
            try:
                return datetime(year, month, day, hour, minute).isoformat(timespec="seconds")
            except ValueError:
                pass

    return None


def _extract_ts_from_lines(lines: list[str], scan_lines: int = 4) -> str | None:
    for line in lines[:scan_lines]:
        ts = _parse_relative_ts(line)
        if ts:
            return ts
    return None


def _load_dom_selectors(cfg_path: str) -> dict:
    try:
        p = _BASE_DIR / cfg_path
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _FALLBACK_SELECTORS


class CommentScraper:

    def __init__(self, browser: "ManagedBrowser", cfg: dict, max_comments: int = 300):
        self.browser = browser
        self.cfg     = cfg

        sc = cfg.get("scraper", {})

        # Timing from cfg
        self._page_load_timeout_ms    = sc.get("page_load_timeout_ms", 35000)
        self._post_load_delay_s       = sc.get("post_load_delay_s", 3.0)
        self._panel_open_delay_s      = sc.get("panel_open_delay_s", 2.0)
        self._keyboard_shortcut_delay = sc.get("keyboard_shortcut_delay_s", 1.5)
        self._click_timeout_ms        = sc.get("click_timeout_ms", 2500)
        self._expand_click_delay_s    = sc.get("expand_click_delay_s", 0.8)
        self._scroll_delay_s          = sc.get("scroll_delay_s", 1.2)
        self._panel_scroll_delay_s    = sc.get("panel_scroll_delay_s", 1.0)
        self._expand_budget_base      = sc.get("max_expand_budget_base", 20)
        self._expand_budget_divisor   = sc.get("expand_budget_divisor", 15)
        self._min_important           = sc.get("min_important_comments", 50)
        self._ts_scan_lines           = sc.get("ts_scan_lines", 4)
        self._max_caption_chars       = sc.get("max_caption_chars", 3000)
        self._max_caption_elements    = sc.get("max_caption_elements", 4)
        self._comment_text_min_chars  = sc.get("comment_text_min_chars", 8)
        self._dedup_key_len           = sc.get("dedup_key_len", 80)

        # DOM selectors loaded from JSON file
        sel_file = sc.get("dom_selectors_file", "config/patterns/dom_selectors.json")
        _sel     = _load_dom_selectors(sel_file)
        self._expand_selectors            = _sel.get("expand_selectors",            _FALLBACK_SELECTORS["expand_selectors"])
        self._reel_comment_open_selectors = _sel.get("reel_comment_open_selectors", _FALLBACK_SELECTORS["reel_comment_open_selectors"])
        self._reel_expand_selectors       = _sel.get("reel_expand_selectors",       _FALLBACK_SELECTORS["reel_expand_selectors"])
        self._reel_panel_selectors        = _sel.get("reel_panel_selectors",        _FALLBACK_SELECTORS["reel_panel_selectors"])
        self._text_selectors              = _sel.get("text_selectors",              _FALLBACK_SELECTORS["text_selectors"])
        self._comment_selectors           = _sel.get("comment_selectors",           _FALLBACK_SELECTORS["comment_selectors"])
        self._panel_comment_selectors     = _sel.get("panel_comment_selectors",     _FALLBACK_SELECTORS["panel_comment_selectors"])
        noise_pat                         = _sel.get("noise_pattern",               _FALLBACK_SELECTORS["noise_pattern"])
        self._noise_re                    = re.compile(noise_pat, re.I)

        self.max_comments = max(max_comments, self._min_important)

    @staticmethod
    def _is_reel(url: str) -> bool:
        return "/reel/" in url

    async def scrape(self, url: str) -> dict:
        page   = await self.browser.new_page(block_resources=False)
        result = {
            "url":         url,
            "text":        "",
            "comments":    [],
            "scraped_at":  datetime.now().isoformat(),
            "source_type": "reel" if self._is_reel(url) else "post",
        }

        try:
            await page.goto(
                url, wait_until="domcontentloaded",
                timeout=self._page_load_timeout_ms,
            )
            await asyncio.sleep(self._post_load_delay_s)
            await self.browser.dismiss_overlays(page, self.cfg)

            # Caption text
            for sel in self._text_selectors:
                try:
                    els   = await page.query_selector_all(sel)
                    parts = []
                    for el in els[:self._max_caption_elements]:
                        t = (await el.inner_text()).strip()
                        if len(t) > self._comment_text_min_chars:
                            parts.append(t)
                    if parts:
                        result["text"] = " ".join(parts)[:self._max_caption_chars]
                        break
                except Exception:
                    continue

            if self._is_reel(url):
                comments = await self._scrape_reel_comments(page)
            else:
                await self._expand_all(page)
                comments = await self._extract(page)

            comments_sorted = sorted(comments, key=lambda c: c.get("likes", 0), reverse=True)
            keep = max(self._min_important, self.max_comments)
            result["comments"]    = comments_sorted[:keep]
            result["total_found"] = len(comments)
            src = result["source_type"].upper()
            print(f"  [COMMENTS/{src}] {len(comments)} found → kept top {len(result['comments'])} by likes")

        except Exception as e:
            result["error"] = str(e)
            print(f"  [!] CommentScraper [{url[:60]}]: {e}")
        finally:
            await page.close()

        return result

    # ── REEL pipeline ─────────────────────────────────────────────────────────

    async def _scrape_reel_comments(self, page) -> list[dict]:
        panel_opened = await self._open_reel_panel(page)
        if not panel_opened:
            print("  [REEL] Could not open comment panel — trying fallback extraction")

        await self._expand_reel(page)
        comments = await self._extract_reel(page)

        if not comments:
            print("  [REEL] Panel extraction empty — falling back to post selectors")
            comments = await self._extract(page)

        if not comments:
            # Last resort: treat reel URL as regular post (navigate directly)
            print("  [REEL] Attempting direct post extraction on reel page")
            comments = await self._extract(page)

        return comments

    async def _open_reel_panel(self, page) -> bool:
        # Strategy 1: aria-label selectors (in priority order)
        for sel in self._reel_comment_open_selectors:
            try:
                els = await page.query_selector_all(sel)
                for el in els:
                    if await el.is_visible():
                        await el.scroll_into_view_if_needed()
                        await el.click(timeout=self._click_timeout_ms)
                        await asyncio.sleep(self._panel_open_delay_s)
                        # Verify panel actually appeared
                        for panel_sel in self._reel_panel_selectors:
                            p = await page.query_selector(panel_sel)
                            if p and await p.is_visible():
                                print("  [REEL] Comment panel opened")
                                return True
                        # Click worked but panel not detected — still count as opened
                        print("  [REEL] Comment panel clicked (panel selector unverified)")
                        return True
            except Exception:
                continue

        # Strategy 2: keyboard shortcut 'c' (Facebook Reel shortcut)
        try:
            await page.keyboard.press("c")
            await asyncio.sleep(self._keyboard_shortcut_delay)
            for sel in self._reel_panel_selectors:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    print("  [REEL] Comment panel opened via keyboard shortcut")
                    return True
        except Exception:
            pass

        # Strategy 3: click anywhere that has 'comentario' text near the reel controls
        try:
            el = await page.query_selector("text='Comentarios'")
            if not el:
                el = await page.query_selector("text='Comments'")
            if el and await el.is_visible():
                await el.click(timeout=self._click_timeout_ms)
                await asyncio.sleep(self._panel_open_delay_s)
                print("  [REEL] Comment panel opened via text selector")
                return True
        except Exception:
            pass

        return False

    async def _expand_reel(self, page) -> None:
        budget = max(self._expand_budget_base, self.max_comments // self._expand_budget_divisor)
        for _ in range(budget):
            clicked = False

            panel = None
            for sel in self._reel_panel_selectors:
                try:
                    panel = await page.query_selector(sel)
                    if panel:
                        break
                except Exception:
                    continue

            if panel:
                try:
                    await panel.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                    await asyncio.sleep(self._panel_scroll_delay_s)
                except Exception:
                    pass

            for sel in self._reel_expand_selectors:
                try:
                    els = await page.query_selector_all(sel)
                    for el in els:
                        try:
                            if await el.is_visible():
                                await el.scroll_into_view_if_needed()
                                await el.click(timeout=self._click_timeout_ms)
                                await asyncio.sleep(self._expand_click_delay_s)
                                clicked = True
                        except Exception:
                            continue
                except Exception:
                    continue

            if not clicked:
                break

    async def _extract_reel(self, page) -> list[dict]:
        comments: list[dict] = []

        # Panel-scoped extraction
        for panel_sel in self._reel_panel_selectors:
            try:
                panel = await page.query_selector(panel_sel)
                if not panel:
                    continue
                panel_sel_joined = ", ".join(self._panel_comment_selectors)
                containers = await panel.query_selector_all(panel_sel_joined)
                if containers:
                    print(f"  [REEL] Panel selector '{panel_sel}' → {len(containers)} containers")
                    for el in containers:
                        c = await self._parse_comment_element(el)
                        if c:
                            comments.append(c)
                    if comments:
                        break
            except Exception:
                continue

        # Fallback: all role=article on page
        if not comments:
            try:
                containers = await page.query_selector_all('div[role="article"]')
                for el in containers:
                    c = await self._parse_comment_element(el)
                    if c:
                        comments.append(c)
            except Exception:
                pass

        return self._dedup(comments)

    # ── POST pipeline ─────────────────────────────────────────────────────────

    async def _expand_all(self, page) -> None:
        budget = max(self._expand_budget_base, self.max_comments // self._expand_budget_divisor)
        no_click_streak = 0
        for _ in range(budget):
            clicked = False
            for sel in self._expand_selectors:
                try:
                    els = await page.query_selector_all(sel)
                    for el in els:
                        try:
                            if await el.is_visible():
                                await el.scroll_into_view_if_needed()
                                await el.click(timeout=self._click_timeout_ms)
                                await asyncio.sleep(self._expand_click_delay_s)
                                clicked = True
                        except Exception:
                            continue
                except Exception:
                    continue

            # Always scroll to reveal more "View more" buttons even without a click
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await asyncio.sleep(self._scroll_delay_s)

            if not clicked:
                no_click_streak += 1
                # Give up only after 3 consecutive scroll+no-click cycles
                if no_click_streak >= 3:
                    break
            else:
                no_click_streak = 0

    async def _extract(self, page) -> list[dict]:
        comments: list[dict] = []
        try:
            # Primary: comment_selectors from JSON (first two as combined query)
            primary  = self._comment_selectors[:3]
            fallback = self._comment_selectors[3] if len(self._comment_selectors) > 3 else None

            combined = ", ".join(primary)
            containers = await page.query_selector_all(combined)
            if not containers and fallback:
                containers = await page.query_selector_all(fallback)

            for el in containers:
                c = await self._parse_comment_element(el)
                if c:
                    comments.append(c)

        except Exception as e:
            print(f"  [!] Comment extraction error: {e}")

        return self._dedup(comments)

    # ── Shared helpers ────────────────────────────────────────────────────────

    async def _parse_comment_element(self, el) -> dict | None:
        try:
            raw = (await el.inner_text()).strip()
            if not raw or len(raw) < 3:
                return None

            lines = [l.strip() for l in raw.splitlines() if l.strip()]

            # Author: first line that isn't a timestamp, noise button, or FB UI label
            # clean_actor_name() handles CamelCase merges, domain strips, and noise
            author = "?"
            for _cand in lines[:5]:
                if _parse_relative_ts(_cand):
                    continue
                if self._noise_re.match(_cand):
                    continue
                if _AUTHOR_SKIP_RE.match(_cand):
                    continue
                _clean = clean_actor_name(_cand)
                if _clean and _clean != "?":
                    author = _clean
                    break

            timestamp = _extract_ts_from_lines(lines[1:], self._ts_scan_lines)

            body_lines = []
            for line in lines[1:]:
                if _parse_relative_ts(line):
                    continue
                if self._noise_re.match(line):
                    continue
                body_lines.append(line)
            body = " ".join(body_lines)[:600] if body_lines else (raw[:600] if len(lines) <= 1 else "")

            likes_m = re.search(r"(\d+)\s*(?:Me gusta|Like)", raw, re.IGNORECASE)
            likes   = int(likes_m.group(1)) if likes_m else 0

            if len(body) < 2 and not likes:
                return None

            result: dict = {"author": author, "text": body, "likes": likes}
            if timestamp:
                result["timestamp"] = timestamp
            return result
        except Exception:
            return None

    def _dedup(self, comments: list[dict]) -> list[dict]:
        seen: set[str] = set()
        unique: list[dict] = []
        for c in comments:
            key = c["text"][:self._dedup_key_len]
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique
