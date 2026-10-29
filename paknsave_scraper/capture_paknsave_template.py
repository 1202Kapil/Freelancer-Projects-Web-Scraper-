"""One-time template capturer for PAK'nSAVE.

Connects to a real Google Chrome instance to bypass Cloudflare Turnstile naturally.
Once you click the checkbox in Chrome and the page loads, it intercepts the
/paginated/products API request and saves:
  1. .paknsave_direct_template.json
  2. .paknsave_cookies.json

After this is saved ONCE, all future scrapes run directly via HTTPX without
ever opening or needing Cloudflare again!
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("capture_template")

THIS_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = THIS_DIR / ".paknsave_direct_template.json"
COOKIE_PATH = THIS_DIR / ".paknsave_cookies.json"
TARGET_URL = "https://www.paknsave.co.nz/shop/category/fruit-and-vegetables"


async def main():
    logger.info("=" * 65)
    logger.info("PAK'nSAVE One-Time API Template Capturer")
    logger.info("=" * 65)

    # 1. Path to real Chrome
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    chrome_exe = next((p for p in chrome_paths if os.path.exists(p)), None)

    if not chrome_exe:
        logger.error("Google Chrome executable not found. Please verify Chrome is installed.")
        return 1

    profile_dir = Path(os.path.expanduser(r"~\paknsave_chrome_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[chrome] Launching real Google Chrome with remote debugging on port 9222...")
    logger.info(f"[chrome] Executable: {chrome_exe}")

    cmd = [
        chrome_exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        TARGET_URL,
    ]

    proc = subprocess.Popen(cmd)
    await asyncio.sleep(2)

    captured = {"ready": False}

    async with async_playwright() as p:
        browser = None
        for attempt in range(10):
            try:
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                break
            except Exception:
                await asyncio.sleep(1)

        if not browser:
            logger.error("Could not connect to Chrome on port 9222. Ensure Chrome is running.")
            return 1

        contexts = browser.contexts
        if not contexts:
            logger.error("No browser context found on Chrome.")
            return 1

        context = contexts[0]
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        async def on_request(request):
            url = request.url or ""
            if "paginated/products" in url and request.method == "POST":
                try:
                    body = request.post_data_json
                except Exception:
                    body = None
                if body and not captured["ready"]:
                    headers = dict(request.headers)
                    cookies = await context.cookies()

                    template_data = {
                        "url": url,
                        "headers": {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")},
                        "bodies": {"fruit-and-vegetables": body},
                        "store_id": body.get("storeId", ""),
                    }
                    TEMPLATE_PATH.write_text(json.dumps(template_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    COOKIE_PATH.write_text(json.dumps(cookies, indent=2), encoding="utf-8")

                    captured["ready"] = True
                    logger.info("=" * 65)
                    logger.info(">>> SUCCESS! CLOUDFLARE BYPASSED & TEMPLATE CAPTURED! <<<")
                    logger.info(f"  Saved template to: {TEMPLATE_PATH.name}")
                    logger.info(f"  Saved cookies to:  {COOKIE_PATH.name}")
                    logger.info("=" * 65)
                    logger.info("Ab aap seedha 'python paknsave_scraper.py --test' run kar sakte hain!")

        page.on("request", on_request)

        logger.info("\n" + "=" * 65)
        logger.info(">>> REAL CHROME WINDOW IS OPEN <<<")
        logger.info("1. Samne khule Chrome window mein 'Verify you are human' checkbox par click karein.")
        logger.info("2. Jaise hi page load hoga, template automatically capture ho jayega!")
        logger.info("=" * 65)

        for sec in range(180):
            if captured["ready"]:
                break
            await asyncio.sleep(1)

        if not captured["ready"]:
            logger.warning("Template capture timed out. Refresh the page in Chrome if needed.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
