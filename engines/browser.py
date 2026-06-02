"""
Browser manager — patchright persistent context with anti-detect profile.
Saves session across runs so Facebook login only happens once.
"""
from __future__ import annotations
import asyncio
from pathlib import Path

try:
    from patchright.async_api import async_playwright, BrowserContext, Page
except ImportError:
    raise SystemExit("patchright required: pip install patchright && patchright install chromium")

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_BLOCK_TYPES = ["image", "media", "font"]  # block to speed up scraping


class ManagedBrowser:
    """Thin wrapper around a persistent BrowserContext."""

    def __init__(self, ctx: BrowserContext):
        self._ctx = ctx

    async def new_page(self, block_resources: bool = True) -> Page:
        page = await self._ctx.new_page()
        if block_resources:
            await page.route(
                "**/*",
                lambda route: (
                    asyncio.ensure_future(route.abort())
                    if route.request.resource_type in _BLOCK_TYPES
                    else asyncio.ensure_future(route.continue_())
                ),
            )
        return page

    async def do_login(self) -> None:
        """Open browser for manual FB login — blocks until user closes tab."""
        page = await self.new_page(block_resources=False)
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
        print("\n  [LOGIN] Facebook opened — log in manually.")
        print("  [LOGIN] When done, CLOSE THE TAB (not the whole window).")
        print("  [LOGIN] Session will be saved to profile directory.\n")
        try:
            await page.wait_for_event("close", timeout=300_000)
        except Exception:
            pass
        print("  [LOGIN] Session saved. Run scraper commands normally now.")

    async def dismiss_overlays(self, page: Page, cfg: dict) -> None:
        for selector in cfg.get("selectors", {}).get("overlay_close", "").split(", "):
            try:
                el = await page.query_selector(selector.strip())
                if el and await el.is_visible():
                    await el.click(timeout=1500)
                    await asyncio.sleep(0.4)
            except Exception:
                continue


class BrowserManager:
    """Async context manager — launches/tears down patchright."""

    def __init__(self, profile_dir: str, headless: bool = False, slow_mo: int = 0):
        self.profile_dir = str(Path(profile_dir).expanduser())
        self.headless    = headless
        self.slow_mo     = slow_mo
        self._pw         = None
        self._ctx        = None
        self._managed: ManagedBrowser | None = None

    async def __aenter__(self) -> ManagedBrowser:
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self._pw  = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1366,900",
            ],
            viewport={"width": 1366, "height": 900},
            locale="es-MX",
            timezone_id="America/Mazatlan",
            user_agent=_UA,
            ignore_https_errors=True,
        )
        self._managed = ManagedBrowser(self._ctx)
        return self._managed

    async def __aexit__(self, *_) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
