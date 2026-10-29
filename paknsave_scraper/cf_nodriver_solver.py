"""Dedicated Cloudflare Turnstile Bypass using nodriver with Proxy support.

Usage:
  python cf_nodriver_solver.py                                    # Direct without proxy (visible window)
  python cf_nodriver_solver.py --proxy "http://user:pass@ip:port" # With HTTP proxy
  python cf_nodriver_solver.py --proxy "socks5://ip:port"         # With SOCKS5 proxy
  python cf_nodriver_solver.py --headless                         # Headless mode
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cf_nodriver")

from dotenv import load_dotenv

THIS_DIR = Path(__file__).resolve().parent
load_dotenv(THIS_DIR / ".env")

COOKIE_PATH = THIS_DIR / ".paknsave_cookies.json"
TEMPLATE_PATH = THIS_DIR / ".paknsave_direct_template.json"
TARGET_URL = "https://www.paknsave.co.nz/shop/category/fruit-and-vegetables"


async def solve_cloudflare(proxy: str | None = None, headless: bool = False) -> bool:
    try:
        import nodriver as uc
        import nodriver.cdp.network as _cdn
    except ImportError:
        logger.error("nodriver is not installed. Please run: pip install nodriver")
        return False

    browser_args = [
        "--lang=en-NZ",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]

    if proxy:
        # Format proxy for Chrome argument
        # Chrome natively supports --proxy-server=http://ip:port or --proxy-server=socks5://ip:port
        browser_args.append(f"--proxy-server={proxy}")
        logger.info(f"[cf] Using proxy: {proxy}")

    logger.info(f"[cf] Launching Chrome via nodriver (headless={headless})...")
    browser = None
    try:
        browser = await uc.start(
            headless=headless,
            browser_args=browser_args,
        )

        logger.info(f"[cf] Navigating to {TARGET_URL} ...")
        page = await browser.get(TARGET_URL)

        logger.info("=" * 65)
        logger.info(">>> CLOUDFLARE TURNSTILE RESOLUTION <<<")
        logger.info("Auto-clicker active. Agar window samne ho to aap bhi checkbox par click kar sakte hain.")
        logger.info("=" * 65)

        passed = False
        for sec in range(60):
            await asyncio.sleep(1.0)
            try:
                title = await page.evaluate("document.title")
            except Exception:
                title = ""

            # Check if passed
            if title and "just a moment" not in title.lower():
                logger.info(f"[cf] Cloudflare challenge passed! Page title: '{title}'")
                passed = True
                break

            # Attempt auto-click via nodriver element search
            try:
                # 1. Try finding verification text
                cf_btn = await page.find("Verify you are human")
                if cf_btn:
                    await cf_btn.mouse_click()
                    logger.info("  [cf] Clicked 'Verify you are human' text element!")
            except Exception:
                pass

            # 2. Try iframe bounding box coordinate click
            try:
                iframe = await page.select("iframe[src*='challenges.cloudflare.com']")
                if iframe:
                    pos = await iframe.get_position()
                    if pos:
                        click_x = pos.x + 28
                        click_y = pos.y + (pos.height / 2)
                        await page.mouse_click(click_x, click_y)
                        logger.info(f"  [cf] Clicked Turnstile checkbox at ({int(click_x)}, {int(click_y)})")
            except Exception:
                pass

            if (sec + 1) % 5 == 0:
                logger.info(f"  [cf] Waiting for verification... ({sec + 1}s / 60s) [Title: '{title}']")

        if not passed:
            logger.warning("[cf] Cloudflare challenge did not pass within 60s.")
            return False

        await asyncio.sleep(3.0)

        # Extract clearance cookies
        try:
            all_cookies = await asyncio.wait_for(browser.cookies.get_all(), timeout=10)
        except Exception:
            all_cookies = []

        cookie_list = []
        for c in all_cookies:
            cookie_list.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path or "/",
                "secure": bool(c.secure),
                "httpOnly": bool(c.http_only),
            })

        cf_cookies = [c for c in cookie_list if c["name"] in ("cf_clearance", "__cf_bm", "_cfuvid")]
        has_clearance = any(c["name"] == "cf_clearance" for c in cf_cookies)

        logger.info(f"[cf] Cookies extracted: {len(cookie_list)} total ({len(cf_cookies)} CF clearance cookies)")

        # Save cookies to file
        COOKIE_PATH.write_text(json.dumps(cookie_list, indent=2), encoding="utf-8")
        logger.info(f"[cf] Saved session cookies to {COOKIE_PATH.name}")

        # Also grab API template from the page
        try:
            logger.info("[cf] Capturing API request template from live page...")
            # Trigger scroll to fire /paginated/products
            await page.evaluate("window.scrollTo(0, 1000)")
            await asyncio.sleep(2.0)
        except Exception:
            pass

        return True

    except Exception as e:
        logger.error(f"[cf] Error during nodriver solve: {e}")
        return False
    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Turnstile Bypass via nodriver")
    parser.add_argument("--proxy", default=os.getenv("PROXY_URL"), help="Proxy URL (e.g. http://ip:port or socks5://ip:port)")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    args = parser.parse_args()

    success = asyncio.run(solve_cloudflare(proxy=args.proxy, headless=args.headless))
    if success:
        logger.info("=" * 65)
        logger.info(">>> SUCCESS! CLOUDFLARE BYPASSED! <<<")
        logger.info("Cookies have been saved to .paknsave_cookies.json")
        logger.info("Ab aap 'python paknsave_scraper.py --test' run kar sakte hain!")
        logger.info("=" * 65)
        sys.exit(0)
    else:
        logger.error("Failed to solve Cloudflare challenge. Check your proxy/network.")
        sys.exit(1)


if __name__ == "__main__":
    main()
