"""
DiscoveryEngine — finds Facebook page URLs for given media/organization names.
Uses FB's search/pages endpoint and fuzzy name matching.
"""
from __future__ import annotations
import asyncio, re
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

if TYPE_CHECKING:
    from .browser import ManagedBrowser


class DiscoveryEngine:

    def __init__(self, browser: "ManagedBrowser", cfg: dict):
        self.browser = browser
        self.cfg     = cfg

    async def discover(self, names: list[str]) -> list[dict]:
        results: list[dict] = []
        for name in names:
            data = await self._find_page(name)
            status = data.get("url", "NOT FOUND")
            print(f"  [DISCOVER] {name:<45} → {status}")
            results.append(data)
        return results

    async def _find_page(self, name: str) -> dict:
        page = await self.browser.new_page()
        base = {
            "query":    name,
            "url":      None,
            "handle":   None,
            "title":    None,
            "likes":    None,
            "verified": False,
        }

        try:
            url = f"https://www.facebook.com/search/pages?q={quote_plus(name)}"
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2.5)

            # Each search result is typically an article
            articles = await page.query_selector_all('div[role="article"]')

            for art in articles[:5]:
                try:
                    text = (await art.inner_text()).strip()
                    # Match: name tokens appear in result
                    tokens  = name.lower().split()
                    matches = sum(1 for t in tokens if t in text.lower())
                    if matches < len(tokens) // 2:
                        continue

                    # Get page link
                    links = await art.query_selector_all('a[href]')
                    for link in links:
                        href = await link.get_attribute("href") or ""
                        # FB page links look like /PageHandle or /profile.php?id=...
                        if not href or "search" in href or "messenger" in href:
                            continue
                        if href.startswith("/"):
                            href = "https://www.facebook.com" + href
                        if "facebook.com/" not in href:
                            continue

                        handle = href.rstrip("/").split("/")[-1]
                        if handle in ("pages", "search", "groups", "events", "watch"):
                            continue

                        # Get title from link text or nearby heading
                        title = ""
                        for sel in ["h2", "h3", "strong", "span"]:
                            try:
                                el = await art.query_selector(sel)
                                if el:
                                    t = (await el.inner_text()).strip()
                                    if t:
                                        title = t[:100]
                                        break
                            except Exception:
                                pass

                        # Check verified badge
                        verified = False
                        try:
                            badge = await art.query_selector('[aria-label*="Verificada"], [aria-label*="Verified"]')
                            verified = badge is not None
                        except Exception:
                            pass

                        # Likes/followers
                        likes = None
                        m = re.search(r"([\d,.]+[KMk]?)\s*(?:Me gusta|seguidores|followers|likes)", text, re.IGNORECASE)
                        if m:
                            from .utils import parse_engagement_number
                            likes = parse_engagement_number(m.group(1))

                        base.update({
                            "url":      href.split("?")[0],
                            "handle":   handle,
                            "title":    title or name,
                            "likes":    likes,
                            "verified": verified,
                        })
                        break

                    if base["url"]:
                        break

                except Exception:
                    continue

        except Exception as e:
            base["error"] = str(e)
        finally:
            await page.close()

        return base
