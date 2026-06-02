#!/usr/bin/env python3
"""
Step 1 debug script: capture Facebook GraphQL API responses
during a search results page load.
Saves each JSON response to /tmp/fb_graphql_responses/
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

# Add fbscrap root to path so engines/ imports work
sys.path.insert(0, str(Path(__file__).parent))

from engines.browser import BrowserManager

OUT_DIR    = Path("/tmp/fb_graphql_responses")
SEARCH_URL = "https://www.facebook.com/search/posts?q=Gerardo+Vargas+Landeros"
PROFILE    = str(Path(__file__).parent / ".fb_profile")


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clean previous run
    for f in OUT_DIR.glob("*.json"):
        f.unlink()

    captured: list[dict] = []
    counter = {"n": 0}

    async def handle_response(response):
        url = response.url
        if "graphql" not in url.lower():
            return
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct and "javascript" not in ct:
                # Some FB graphql responses come as text/html or application/x-www-form-urlencoded
                # Try body anyway
                pass
            body = await response.body()
            if not body:
                return
            text = body.decode("utf-8", errors="replace")
            # FB often returns multiple JSON objects line by line
            # Try parsing whole body first, then line by line
            data = None
            try:
                data = json.loads(text)
            except Exception:
                # Try line-by-line (FB streaming JSON)
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                for line in lines:
                    try:
                        data = json.loads(line)
                        break
                    except Exception:
                        continue
                # If still none, save raw text for manual inspection
                if data is None:
                    n = counter["n"]
                    counter["n"] += 1
                    out_f = OUT_DIR / f"response_{n:03d}_raw.txt"
                    out_f.write_text(text[:50000])
                    captured.append({"file": str(out_f), "url": url, "size": len(text), "parsed": False})
                    return

            n = counter["n"]
            counter["n"] += 1
            out_f = OUT_DIR / f"response_{n:03d}.json"
            # Save COMPACT (not prettified) so we don't truncate large responses
            compact = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            out_f.write_bytes(compact.encode("utf-8"))
            size = len(text)
            captured.append({"file": str(out_f), "url": url[:100], "size": size, "parsed": True})
            print(f"  [CAPTURE] #{n:03d}  size={size:7d}  {url[:80]}")
        except Exception as ex:
            print(f"  [CAPTURE ERROR] {url[:60]}: {ex}")

    print(f"[*] Launching browser with profile: {PROFILE}")
    async with BrowserManager(PROFILE, headless=True, slow_mo=0) as browser:
        page = await browser.new_page(block_resources=False)

        # Wire up response listener BEFORE navigation
        page.on("response", handle_response)

        print(f"[*] Navigating to: {SEARCH_URL}")
        try:
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as ex:
            print(f"[!] goto error (continuing anyway): {ex}")

        print("[*] Waiting 8s for FB JS to execute and load search results...")
        await asyncio.sleep(8)

        # Check login state
        cur = page.url
        print(f"[*] Current URL: {cur}")
        if any(s in cur for s in ("login", "checkpoint", "recover")):
            print("[!] LOGIN WALL — session expired, run: python3 fbscrap.py login")
            await page.close()
            return

        # Scroll once to trigger more GraphQL loads
        print("[*] Scrolling to trigger more loads...")
        await page.evaluate("window.scrollBy(0, 1500)")
        await asyncio.sleep(4)
        await page.evaluate("window.scrollBy(0, 1500)")
        await asyncio.sleep(4)

        await page.close()

    print(f"\n[+] Captured {len(captured)} GraphQL responses")
    for item in captured:
        status = "JSON" if item["parsed"] else "RAW "
        print(f"    [{status}] {item['file'].split('/')[-1]}  size={item['size']:7,}  {item['url'][:70]}")

    # Save index
    idx_f = OUT_DIR / "_index.json"
    idx_f.write_text(json.dumps(captured, indent=2))
    print(f"\n[+] Index saved: {idx_f}")


if __name__ == "__main__":
    asyncio.run(main())
