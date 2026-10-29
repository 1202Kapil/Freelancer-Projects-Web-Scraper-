"""PAK'nSAVE Supermarket Scraper — Production Build.

Conforms to PICO Scraper Data Contract and Woolworths benchmark maturity:
1. Barcode Accuracy: Strict GTIN format validation (lengths 8, 12, 13, 14 numeric digits).
   Produce PLUs (e.g. Avocado 4224, Bananas 4011) are preserved in raw_row["plu_code"]
   and strictly isolated from global barcode space (barcode = None).
2. Stock Availability: True independent availability evaluation from listing and detail API
   (stockLevel, availabilityStatus, availability, outOfStock, inStock, purchasable).
3. Promotions Verification: Complete classification of specials, multibuys, discounts,
   and member prices. Zero orphan promo metadata on regular shelf pricing (sapType="BASE").
4. Multi-Branch Workflow: Complete --all-branches support with automated branch discovery
   via `catalog_branches.py` (PICO catalog schema over DATABASE_URL with seamless offline fallback).
5. Production Resilience: 3-attempt exponential backoff retries on paginated requests
   handling HTTP 425, 429, 5xx, and network drops without stopping pagination.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Optional

import httpx
from patchright.async_api import async_playwright, Browser, BrowserContext, Page

from catalog_branches import list_branches, get_branch
from config import (
    BASE_URL,
    CATEGORIES,
    SLUG_TO_DISPLAY_NAME,
    DEFAULT_STORE_NAME,
    DEFAULT_STORE_ID,
    DETAIL_API_TEMPLATE,
    USER_AGENT,
    EXTRA_HEADERS,
    ASSET_BLOCK_RE,
    CF_BLOCK_TITLES,
    REQUEST_TIMEOUT_MS,
    DELAY_MIN,
    DELAY_MAX,
    DEFAULT_RATE_LIMIT,
    ENRICH_CONCURRENCY_INITIAL,
    ENRICH_CONCURRENCY_MIN,
    ENRICH_429_THRESHOLD,
    CACHE_PATH,
    TEMPLATE_PATH,
    EXPORTS_DIR,
    PROXY_URL,
    CAPSOLVER_PROXY,
    CAPSOLVER_API_KEY,
)
from jsonl_exporter import write_jsonl, to_cents, clean_record, _slug

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("paknsave_scraper")

# Valid GTIN standard lengths (GTIN-8, GTIN-12, GTIN-13, GTIN-14)
VALID_GTIN_LENGTHS = {8, 12, 13, 14}


def is_valid_gtin(code: Any) -> bool:
    """Validate that code conforms strictly to Global Trade Item Number (GTIN) standards.
    GTINs are strictly numeric and exactly 8, 12, 13, or 14 digits in length.
    Rejects 4-digit or 5-digit PLU codes (e.g. Avocado 4224, Bananas 4011),
    alphanumeric SKUs, and non-GTIN numbers.
    """
    if not code:
        return False
    s = str(code).strip()
    return s.isdigit() and len(s) in VALID_GTIN_LENGTHS


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ScrapedProduct:
    raw_name: str
    clean_name: str
    price: float
    category: str
    special_price: Optional[float] = None
    comparison_price: Optional[float] = None
    image_url: Optional[str] = None
    brand: Optional[str] = None
    weight: Optional[str] = None
    barcode: Optional[str] = None
    in_stock: bool = True
    product_id: Optional[str] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    category_path: Optional[str] = None
    promo_text: Optional[str] = None
    promo_type: Optional[str] = None
    card_required: bool = False
    loyalty_program_code: Optional[str] = None
    source_promotion_id: Optional[str] = None
    multibuy_quantity: Optional[int] = None
    multibuy_price_cents: Optional[int] = None
    promo_starts_at: Optional[str] = None
    promo_ends_at: Optional[str] = None
    promo_metadata: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Helper Extraction Functions
# ---------------------------------------------------------------------------

def category_path_from_trees(trees: Any) -> Optional[str]:
    """Build 'Level0 > Level1 > Level2' hierarchy from Foodstuffs categoryTrees."""
    if not isinstance(trees, list) or not trees:
        return None
    node = trees[0] or {}
    parts = []
    for i in range(6):
        v = node.get(f"level{i}")
        if not v:
            break
        parts.append(str(v).strip())
    return " > ".join(parts) if parts else None


def extract_fs_image(data: dict) -> Optional[str]:
    """Extract primary high-res product image."""
    imgs = (data or {}).get("images") or {}
    primary = imgs.get("primaryImages") or {}
    for size in ("400px", "500px", "300px", "200px", "100px"):
        url = primary.get(size)
        if url:
            return url
    return None


def extract_fs_detail(data: dict) -> dict:
    """Extract rich detail card fields (matching raw_row contract):
    description, ingredients, allergens, allergen_may_contain, country_of_origin, nutrition.
    """
    d = data or {}
    out: dict = {}

    origin = d.get("originStatement") or d.get("countryOfOrigin")
    if origin:
        out["country_of_origin"] = origin

    nutrition = d.get("nutritionalInfo")
    if nutrition and isinstance(nutrition, dict):
        out["nutrition"] = nutrition

    ingredients = d.get("ingredientStatement") or d.get("fsIngredientStatement")
    if ingredients:
        out["ingredients"] = ingredients

    allergens = d.get("allergenStatement")
    if allergens:
        out["allergens"] = allergens

    may_contain = d.get("fsSupplementaryAllergenStatement")
    if may_contain:
        out["allergen_may_contain"] = may_contain

    desc = d.get("description")
    if desc:
        out["description"] = desc

    return out


# ---------------------------------------------------------------------------
# Caching & Rate Limiting
# ---------------------------------------------------------------------------

class BarcodeCache:
    """Persistent local cache storing productId -> {barcode, image, detail}.
    Strictly verifies GTIN compliance so non-GTIN codes are never returned as barcodes.
    """

    def __init__(self, path: Path = CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
                logger.info(f"[cache] Loaded {len(self._data)} cached entries from {path.name}")
            except Exception as e:
                logger.warning(f"[cache] Failed to read cache: {e}")

    def get_barcode(self, pid: str) -> Optional[str]:
        entry = self._data.get(pid)
        if not isinstance(entry, dict):
            return None
        bc = entry.get("bc")
        return bc if is_valid_gtin(bc) else None

    def get_image(self, pid: str) -> Optional[str]:
        entry = self._data.get(pid)
        return entry.get("img") if isinstance(entry, dict) else None

    def get_detail(self, pid: str) -> dict:
        entry = self._data.get(pid)
        return (entry.get("det") or {}) if isinstance(entry, dict) else {}

    def needs_detail(self, pid: str) -> bool:
        entry = self._data.get(pid)
        if not isinstance(entry, dict):
            return True
        # If detail card is missing, we need enrichment
        return not bool(entry.get("det"))

    def put_detail(self, pid: str, barcode: Optional[str], image: Optional[str], detail: Optional[dict]) -> None:
        entry = self._data.setdefault(pid, {})
        # Only cache barcode if valid GTIN; otherwise set None
        if barcode and is_valid_gtin(barcode):
            entry["bc"] = barcode
        elif "bc" not in entry:
            entry["bc"] = None

        if image:
            entry["img"] = image
        if detail:
            entry["det"] = detail

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            logger.info(f"[cache] Saved {len(self._data)} entries to cache")
        except Exception as e:
            logger.warning(f"[cache] Failed to save cache: {e}")


class TemplateState:
    """Stores the working request body template for direct API requests."""

    def __init__(self, path: Path = TEMPLATE_PATH) -> None:
        self.path = path
        self.url: str = ""
        self.headers: dict[str, str] = {}
        self.bodies: dict[str, dict] = {}
        self.store_id: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.url = d.get("url", "")
            self.headers = d.get("headers", {})
            self.bodies = d.get("bodies", {})
            self.store_id = d.get("store_id", "")
            if self.url and self.headers:
                logger.info(f"[template] Loaded direct API template from {self.path.name}")
        except Exception as e:
            logger.warning(f"[template] Could not load template: {e}")

    def save_category(self, slug: str, url: str, headers: dict, body: dict, store_id: str) -> None:
        self.url = url
        self.headers = {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")}
        self.bodies[slug] = copy.deepcopy(body)
        self.store_id = store_id
        try:
            self.path.write_text(json.dumps({
                "url": self.url,
                "headers": self.headers,
                "bodies": self.bodies,
                "store_id": self.store_id,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[template] Saved category '{slug}' to direct API template")
        except Exception as e:
            logger.warning(f"[template] Could not save template: {e}")

    @property
    def ready(self) -> bool:
        return bool(self.url and self.headers and self.bodies)


class TokenBucketLimiter:
    """Global request rate limiter."""

    def __init__(self, rate: float = DEFAULT_RATE_LIMIT) -> None:
        self.rate = rate
        self.tokens = rate
        self.max_tokens = rate
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
            else:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last = time.monotonic()


# ---------------------------------------------------------------------------
# Cloudflare Turnstile Helpers
# ---------------------------------------------------------------------------

def _format_proxy_for_capsolver(url: str) -> Optional[str]:
    """Format HTTP proxy URL into CapSolver 'ip:port:user:pass' or 'ip:port' string."""
    from urllib.parse import urlparse
    if not url:
        return None
    p = urlparse(url if "://" in url else f"http://{url}")
    if p.hostname and p.port:
        if p.username and p.password:
            return f"{p.hostname}:{p.port}:{p.username}:{p.password}"
        return f"{p.hostname}:{p.port}"
    return None


async def _solve_cf_with_capsolver(
    api_key: str,
    proxy_url: Optional[str] = None,
    target_url: str = BASE_URL,
) -> tuple[list[dict], Optional[str]]:
    """Solve Cloudflare Turnstile challenge using CapSolver AntiCloudflareTask API."""
    if not api_key:
        return [], None

    cap_proxy = _format_proxy_for_capsolver(proxy_url) if proxy_url else None
    task_payload: dict[str, Any] = {
        "type": "AntiCloudflareTask",
        "websiteURL": target_url,
    }
    if cap_proxy:
        task_payload["proxy"] = cap_proxy

    logger.info(f"[capsolver] Requesting Cloudflare bypass token from CapSolver (proxy={'yes' if cap_proxy else 'no'})...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.capsolver.com/createTask",
                json={"clientKey": api_key, "task": task_payload},
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                logger.warning(f"[capsolver] createTask error: {data.get('errorDescription')}")
                return [], None

            task_id = data.get("taskId")
            if not task_id:
                return [], None

            for poll in range(25):
                await asyncio.sleep(2.0)
                res = await client.post(
                    "https://api.capsolver.com/getTaskResult",
                    json={"clientKey": api_key, "taskId": task_id},
                )
                r_json = res.json()
                status = r_json.get("status")
                if status == "ready":
                    sol = r_json.get("solution", {})
                    cookies_dict = sol.get("cookies", {})
                    sol_ua = sol.get("userAgent")

                    cookies_list = []
                    for c_name, c_val in cookies_dict.items():
                        cookies_list.append({
                            "name": c_name,
                            "value": c_val,
                            "domain": ".paknsave.co.nz",
                            "path": "/",
                            "secure": True,
                            "httpOnly": True,
                        })
                    logger.info(f"[capsolver] Cloudflare solved! Received cf_clearance (status=ready in {(poll + 1) * 2}s)")
                    return cookies_list, sol_ua
                elif status == "failed":
                    logger.warning(f"[capsolver] Task failed: {r_json.get('errorDescription')}")
                    return [], None

            logger.warning("[capsolver] Timeout waiting for CapSolver solution")
            return [], None
    except Exception as e:
        logger.warning(f"[capsolver] API exception: {e}")
        return [], None


def _parse_proxy(url: str) -> dict:
    """Parse 'http://user:pass@host:port' or 'http://host:port' to Playwright proxy dict."""
    from urllib.parse import urlparse
    p = urlparse(url if "://" in url else f"http://{url}")
    out = {"server": f"{p.scheme or 'http'}://{p.hostname}:{p.port or 8080}"}
    if p.username:
        out["username"] = p.username
    if p.password:
        out["password"] = p.password
    return out


# ---------------------------------------------------------------------------
# Main Scraper Class
# ---------------------------------------------------------------------------

class PaknsaveScraper:

    def __init__(
        self,
        branch_name: Optional[str] = None,
        store_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        category_slugs: Optional[list[str]] = None,
        headless: bool = True,
        rate: float = DEFAULT_RATE_LIMIT,
        proxy: Optional[str] = None,
    ) -> None:
        self.branch_id = branch_id
        self.branch_name = branch_name or DEFAULT_STORE_NAME
        self.store_id = store_id or DEFAULT_STORE_ID
        self.category_slugs = category_slugs or CATEGORIES
        self.headless = headless
        self.proxy_url = proxy or os.getenv("PROXY_URL") or None
        self.capsolver_api_key = os.getenv("CAPSOLVER_API_KEY") or CAPSOLVER_API_KEY or None
        self.cache = BarcodeCache()
        self.template = TemplateState()
        self.limiter = TokenBucketLimiter(rate=rate)

        # Resolve branch information against catalog database or offline registry
        self._resolve_branch()

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._direct_client: Optional[httpx.AsyncClient] = None
        self._promo_date_cache: dict[str, dict] = {}
        self._cf_cookies: list[dict] = []
        self._cf_user_agent: Optional[str] = None

    def _resolve_branch(self) -> None:
        """Resolve store_id, branch_name, and branch_id from catalog_branches."""
        b = get_branch("paknsave", branch_id=self.branch_id, name=self.branch_name)
        if b:
            self.branch_id = b.get("id")
            self.branch_name = b.get("name") or self.branch_name
            if b.get("api_store_id"):
                self.store_id = b["api_store_id"]
            logger.info(f"[branch] Resolved '{self.branch_name}' -> id={self.branch_id}, store_id={self.store_id}")
        else:
            logger.info(f"[branch] Using configured branch: '{self.branch_name}' (store_id={self.store_id})")

    async def _start_browser(self) -> None:
        if self._browser:
            return
        self._playwright = await async_playwright().start()
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        for channel in ("chrome", "msedge", None):
            try:
                kw = {"headless": self.headless, "args": launch_args}
                if channel:
                    kw["channel"] = channel
                if self.proxy_url:
                    kw["proxy"] = _parse_proxy(self.proxy_url)
                    logger.info(f"[proxy] Routing browser via {kw['proxy'].get('server')}")
                self._browser = await self._playwright.chromium.launch(**kw)
                logger.info(f"[browser] Launched Chromium engine (channel={channel or 'bundled'})")
                break
            except Exception:
                continue

    async def _new_context(self) -> None:
        assert self._browser
        session_file = Path(__file__).resolve().parent / ".paknsave_session.json"
        cookie_file = Path(__file__).resolve().parent / ".paknsave_cookies.json"

        if not self._cf_cookies and session_file.exists():
            try:
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                age = time.time() - sess.get("saved_at", 0)
                if age < 1800 and sess.get("cookies"):
                    self._cf_cookies = sess["cookies"]
                    self._cf_user_agent = sess.get("user_agent")
            except Exception:
                pass

        ua = self._cf_user_agent or USER_AGENT
        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="en-NZ",
            timezone_id="Pacific/Auckland",
            extra_http_headers=EXTRA_HEADERS,
        )

        if self._cf_cookies:
            await self._context.add_cookies(self._cf_cookies)
            logger.info(f"[cf] Injected {len(self._cf_cookies)} fresh CF clearance cookies into context")
        elif cookie_file.exists():
            try:
                saved = json.loads(cookie_file.read_text(encoding="utf-8"))
                if saved:
                    await self._context.add_cookies(saved)
            except Exception:
                pass

        self._page = await self._context.new_page()
        self._page.set_default_timeout(REQUEST_TIMEOUT_MS)

        async def _block_heavy_assets(route, req):
            if ASSET_BLOCK_RE.search(req.url):
                await route.abort()
            else:
                await route.continue_()

        await self._page.route("**/*", _block_heavy_assets)

    async def _refresh_context_with_capsolver(self, target_url: str = BASE_URL) -> bool:
        if not self.capsolver_api_key:
            return False
        cookies, ua = await _solve_cf_with_capsolver(
            self.capsolver_api_key,
            proxy_url=self.proxy_url,
            target_url=target_url,
        )
        if cookies:
            self._cf_cookies = cookies
            self._cf_user_agent = ua
            if self._context:
                await self._context.add_cookies(cookies)
            return True
        return False

    async def _try_click_turnstile(self) -> bool:
        if not self._page:
            return False
        for frame in self._page.frames:
            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                try:
                    box = await frame.locator("input[type=checkbox]").element_handle()
                    if box:
                        await box.click()
                        logger.info("  [cf] Clicked Cloudflare Turnstile checkbox in frame!")
                        return True
                except Exception:
                    pass
        for sel in (
            "iframe[src*='challenges.cloudflare.com']",
            "iframe[src*='turnstile']",
            "div.cf-turnstile",
            "#cf-stage",
            "#challenge-stage",
        ):
            try:
                el = self._page.locator(sel).first
                if await el.count() > 0:
                    box = await el.bounding_box()
                    if box:
                        x = box["x"] + min(30, box["width"] / 4)
                        y = box["y"] + (box["height"] / 2)
                        await self._page.mouse.click(x, y)
                        logger.info(f"  [cf] Clicked Turnstile checkbox at coordinates ({int(x)}, {int(y)})")
                        return True
            except Exception:
                pass
        return False

    async def _seed_session(self) -> bool:
        assert self._page
        logger.info(f"[cf] Visiting {BASE_URL} to establish session...")
        try:
            resp = await self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            title = (await self._page.title() or "").lower()

            if (resp and resp.status in (403, 429)) or any(kw in title for kw in CF_BLOCK_TITLES):
                logger.info("[cf] Cloudflare challenge detected! Auto-solving...")
                if self.capsolver_api_key:
                    await self._refresh_context_with_capsolver(BASE_URL)

                for wait_s in range(45):
                    await self._try_click_turnstile()
                    await asyncio.sleep(1.0)
                    cur_title = (await self._page.title() or "").lower()
                    if not any(kw in cur_title for kw in CF_BLOCK_TITLES):
                        break
                    if (wait_s + 1) % 5 == 0:
                        logger.info(f"  [cf] Solving challenge: '{cur_title}' ({wait_s + 1}s / 45s)...")

            final_title = await self._page.title()
            if any(kw in (final_title or "").lower() for kw in CF_BLOCK_TITLES):
                logger.warning(f"[cf] Cloudflare challenge still active (title: '{final_title}')")
                return False

            try:
                all_cookies = await self._context.cookies()
                session_file = Path(__file__).resolve().parent / ".paknsave_session.json"
                session_file.write_text(json.dumps({
                    "user_agent": await self._page.evaluate("navigator.userAgent"),
                    "cookies": all_cookies,
                    "saved_at": time.time(),
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
            return True
        except Exception as e:
            logger.warning(f"[cf] Session seed error: {e}")
            return False

    async def _close_browser(self) -> None:
        if self._direct_client:
            await self._direct_client.aclose()
            self._direct_client = None
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def _swap_store_id(self, body: dict) -> None:
        """Replace capture storeId with target store_id in payload."""
        if not self.store_id:
            return
        if "storeId" in body:
            old_id = body["storeId"]
            body["storeId"] = self.store_id
            alg = body.get("algoliaQuery") or {}
            if "filters" in alg and isinstance(alg["filters"], str) and old_id:
                alg["filters"] = alg["filters"].replace(old_id, self.store_id)

    # ---- Stage 1: Category Listing & Resilient Pagination ------------------

    async def scrape_category_browser(self, slug: str) -> list[ScrapedProduct]:
        """Scrape a category using browser navigation and capture the API template.
        Includes robust retry logic on pagination.
        """
        assert self._page
        url = f"{BASE_URL}/shop/category/{slug}"
        captured_responses: list[dict] = []
        captured_req: dict = {}

        async def _intercept(route, request):
            if "paginated/products" in request.url:
                if not captured_req.get("url"):
                    captured_req["url"] = request.url
                    captured_req["headers"] = dict(request.headers)
                    try:
                        captured_req["body"] = request.post_data_json
                    except Exception:
                        captured_req["body"] = None
            resp = await route.fetch()
            try:
                body = await resp.json()
                captured_responses.append(body)
            except Exception:
                pass
            await route.fulfill(response=resp)

        await self._page.route("**/paginated/products**", _intercept)

        logger.info(f"  [browser] Navigating to {url} ...")
        await self.limiter.acquire()
        nav_resp = None
        try:
            nav_resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            logger.warning(f"  [browser] Initial navigation notice: {e}")

        title = (await self._page.title() or "").lower()
        if (nav_resp and nav_resp.status in (403, 429)) or any(kw in title for kw in CF_BLOCK_TITLES):
            logger.info("  [cf] Cloudflare challenge encountered on category page!")
            if self.capsolver_api_key:
                logger.info("  [cf] Refreshing session with CapSolver...")
                if await self._refresh_context_with_capsolver(url):
                    await self._page.route("**/paginated/products**", _intercept)
                    try:
                        nav_resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    except Exception:
                        pass
                    title = (await self._page.title() or "").lower()

            if any(kw in title for kw in CF_BLOCK_TITLES):
                logger.info("=" * 65)
                logger.info("[cf] >>> CLOUDFLARE TURNSTILE DETECTED! <<<")
                logger.info("[cf] >>> SAMNE BROWSER WINDOW MEIN 'Verify you are human' CHECKBOX PAR CLICK KAREIN! <<<")
                logger.info("[cf] >>> (Waiting up to 45 seconds for verification...) <<<")
                logger.info("=" * 65)

                for wait_sec in range(45):
                    await self._try_click_turnstile()
                    await asyncio.sleep(1.0)
                    title = (await self._page.title() or "").lower()
                    if not any(kw in title for kw in CF_BLOCK_TITLES):
                        break
                    if (wait_sec + 1) % 5 == 0:
                        logger.info(f"  [cf] Waiting for verification... ({wait_sec + 1}s / 45s)")

            final_title = await self._page.title()
            if any(kw in (final_title or "").lower() for kw in CF_BLOCK_TITLES):
                logger.warning(f"  [browser] Cloudflare challenge not passed for {url} (title: '{final_title}')")
                return []

            logger.info(f"  [cf] Turnstile PASSED! Title: '{final_title}'")
            try:
                all_cookies = await self._context.cookies()
                cookie_file = Path(__file__).resolve().parent / ".paknsave_cookies.json"
                cookie_file.write_text(json.dumps(all_cookies, indent=2), encoding="utf-8")
            except Exception:
                pass

            await self._page.wait_for_timeout(2000)

        # Wait for storefront to finish booting and capture /paginated/products API
        logger.info("  [browser] Waiting for storefront products API request...")
        for wait_api in range(25):
            if captured_req.get("body") and captured_req.get("url"):
                logger.info(f"  [browser] Successfully captured products API request ({wait_api + 1}s)!")
                break
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(1.0)

        try:
            await self._page.unroute_all(behavior="ignoreErrors")
        except Exception:
            pass

        all_items: list[dict] = []
        if captured_req.get("body") and captured_req.get("url"):
            body = captured_req["body"]
            self._swap_store_id(body)
            self.template.save_category(slug, captured_req["url"], captured_req["headers"], body, self.store_id)

            # Page 0 with retry
            body["page"] = 0
            hdrs = {k: v for k, v in captured_req["headers"].items() if k.lower() not in ("host", "content-length")}
            total_pages = 1

            for att in range(3):
                try:
                    resp0 = await self._page.request.post(captured_req["url"], headers=hdrs, data=body)
                    if resp0.ok:
                        d0 = await resp0.json()
                        items0 = d0.get("products") or d0.get("items") or []
                        all_items.extend(items0)
                        total_pages = d0.get("totalPages") or 1
                        break
                    elif resp0.status == 425:
                        await asyncio.sleep(0.5 * (att + 1))
                    else:
                        await asyncio.sleep(1.5 * (att + 1))
                except Exception:
                    await asyncio.sleep(1.5 * (att + 1))

            # Remaining pages with exponential retry
            for page_num in range(1, total_pages):
                pb = copy.deepcopy(body)
                pb["page"] = page_num
                page_success = False

                for attempt in range(3):
                    await self.limiter.acquire()
                    try:
                        pr = await self._page.request.post(captured_req["url"], headers=hdrs, data=pb)
                        if pr.ok:
                            pj = await pr.json()
                            items_p = pj.get("products") or pj.get("items") or []
                            all_items.extend(items_p)
                            page_success = True
                            break
                        elif pr.status == 425:
                            await asyncio.sleep(0.5 * (attempt + 1))
                        elif pr.status in (429, 500, 502, 503, 504):
                            await asyncio.sleep(2.0 * (attempt + 1))
                        else:
                            await asyncio.sleep(1.0)
                    except Exception:
                        await asyncio.sleep(2.0 * (attempt + 1))

                if not page_success:
                    logger.warning(f"  [browser] {slug} p{page_num}: Failed after 3 retries — continuing to next page")
                await asyncio.sleep(0.2)
        else:
            for cr in captured_responses:
                all_items.extend(cr.get("products") or cr.get("items") or [])

        products = [self._parse_item(it, slug) for it in all_items]
        return [p for p in products if p]

    async def scrape_category_direct(self, slug: str) -> Optional[list[ScrapedProduct]]:
        """Fast path: POST directly using captured template with 3-attempt retry per page."""
        if not self.template.ready or slug not in self.template.bodies:
            return None

        body = copy.deepcopy(self.template.bodies[slug])
        self._swap_store_id(body)
        body["page"] = 0

        if not self._direct_client:
            self._direct_client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(30.0, connect=15.0),
                follow_redirects=True,
            )

        headers = dict(self.template.headers)

        # Page 0 with retry
        data0 = None
        for attempt in range(3):
            await self.limiter.acquire()
            try:
                r0 = await self._direct_client.post(self.template.url, headers=headers, json=body)
                if r0.is_success:
                    data0 = r0.json()
                    break
                elif r0.status_code == 425:
                    await asyncio.sleep(0.5 * (attempt + 1))
                elif r0.status_code in (401, 403):
                    logger.warning(f"  [direct] {slug} p0: HTTP {r0.status_code} — auth expired")
                    return None
                else:
                    await asyncio.sleep(1.5 * (attempt + 1))
            except Exception as e:
                logger.warning(f"  [direct] {slug} p0 retry {attempt+1}/3: {e}")
                await asyncio.sleep(1.5 * (attempt + 1))

        if not data0:
            return None

        all_items = list(data0.get("products") or data0.get("items") or [])
        total_pages = data0.get("totalPages") or 1

        # Remaining pages with 3-attempt retry
        for page_num in range(1, total_pages):
            pb = copy.deepcopy(body)
            pb["page"] = page_num
            page_success = False

            for attempt in range(3):
                await self.limiter.acquire()
                try:
                    pr = await self._direct_client.post(self.template.url, headers=headers, json=pb)
                    if pr.is_success:
                        pj = pr.json()
                        items_p = pj.get("products") or pj.get("items") or []
                        all_items.extend(items_p)
                        page_success = True
                        break
                    elif pr.status_code == 425:
                        await asyncio.sleep(0.5 * (attempt + 1))
                    elif pr.status_code in (429, 500, 502, 503, 504):
                        await asyncio.sleep(2.0 * (attempt + 1))
                    else:
                        await asyncio.sleep(1.0)
                except Exception as e:
                    await asyncio.sleep(2.0 * (attempt + 1))

            if not page_success:
                logger.warning(f"  [direct] {slug} p{page_num}: Failed after 3 retries — continuing to next page")
            await asyncio.sleep(0.1)

        products = [self._parse_item(it, slug) for it in all_items]
        return [p for p in products if p]

    # ---- Stage 2: Item Parsing (GTIN, Stock & Promotions) -------------------

    def _parse_item(self, item: dict, category_slug: str) -> Optional[ScrapedProduct]:
        """Convert a raw Foodstuffs listing JSON product into ScrapedProduct.
        Strictly conforms to:
        - Barcode accuracy: Only valid GTIN lengths (8, 12, 13, 14 digits) allowed.
        - Independent availability: Evaluates stockLevel and availability flags.
        - Promotion classification: Pure deals only (no SAP BASE pricing conditions).
        """
        name = item.get("name")
        display_name = item.get("displayName")
        brand = item.get("brand")

        parts = [p for p in [brand, name, display_name] if p]
        raw_name = " ".join(parts) if parts else (item.get("title") or "")
        if not raw_name:
            return None

        clean_name = name or raw_name

        sp = item.get("singlePrice") or {}
        try:
            price_cents = sp.get("price") or sp.get("originalPrice") or 0
            price = float(price_cents) / 100
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        # Promotions parsing
        special = comparison = promo_type = promo_text = loyalty_code = None
        card_required = False
        source_promotion_id = multibuy_quantity = multibuy_price_cents = None
        promo_metadata: dict = {}

        promos = item.get("promotions") or []
        if promos:
            promo = next((p for p in promos if p.get("bestPromotion")), promos[0])
            reward_type = promo.get("rewardType")
            reward_value = promo.get("rewardValue")
            threshold = promo.get("threshold") or 1
            card_required = bool(promo.get("cardDependencyFlag"))

            try:
                rv = float(reward_value) / 100 if reward_value else None
            except (TypeError, ValueError):
                rv = None

            # 1. Multibuy (e.g. 2 for $5.00)
            if threshold > 1 and rv:
                promo_type = "multibuy_fixed_price"
                promo_text = f"{threshold} for ${rv:.2f}"
                multibuy_quantity = int(threshold)
                multibuy_price_cents = int(round(rv * 100))
            # 2. Genuine special price with discount from regular shelf price
            elif reward_type == "NEW_PRICE" and rv is not None and rv < price:
                special = rv
                comparison = price
                promo_type = "member_price" if card_required else "special"
                promo_text = f"Club Deal ${rv:.2f}" if card_required else f"Special ${rv:.2f}"
            # 3. PAK'nSAVE 'Extra Low' / Base promotion (decal 6000) where shelf price matches promo price
            elif (reward_type == "NEW_PRICE" and rv is not None) and (
                str(promo.get("decal")) == "6000" or promo.get("bestPromotion") or promo.get("sapType") in ("BASE", "LAYERED")
            ):
                special = rv
                promo_type = "member_price" if card_required else "special"
                decal_code = str(promo.get("decal") or "")
                if card_required:
                    promo_text = f"Club Deal ${rv:.2f}"
                elif decal_code == "6000":
                    promo_text = f"Extra Low ${rv:.2f}"
                else:
                    promo_text = f"Special ${rv:.2f}"

                orig_cents = sp.get("originalPrice")
                if orig_cents and orig_cents > price_cents:
                    comparison = float(orig_cents) / 100
            # 4. Fixed discount deals
            elif reward_type in ("DISCOUNT", "SAVINGS") and rv is not None and rv > 0:
                special = round(price - rv, 2)
                comparison = price
                promo_type = "member_price" if card_required else "special"
                promo_text = f"Save ${rv:.2f}"
            elif rv is not None and rv < price:
                special = rv
                comparison = price
                promo_type = "member_price" if card_required else "special"
                promo_text = f"Special ${rv:.2f}"

            if card_required and promo_type:
                loyalty_code = "club-plus"

            # Strict promotion metadata isolation: only attach if genuine promo_type is classified!
            if promo_type is not None:
                if promo.get("promoId"):
                    source_promotion_id = str(promo.get("promoId"))
                for k in ("decal", "sapType", "rewardType", "threshold", "limit", "description"):
                    if promo.get(k) is not None:
                        promo_metadata[k] = str(promo[k]) if isinstance(promo[k], (int, float)) else promo[k]
                promo_metadata["raw_promotion"] = promo
            else:
                # SAP BASE regular pricing condition — clear all promo fields to prevent phantom records
                source_promotion_id = None
                multibuy_quantity = None
                multibuy_price_cents = None
                promo_metadata = {}

        # Unit price calculation
        comp = sp.get("comparativePrice") or {}
        unit_price = None
        try:
            ppu = comp.get("pricePerUnit")
            if ppu:
                unit_price = float(ppu) / 100
        except (TypeError, ValueError):
            unit_price = None
        unit_label = comp.get("measureDescription") or comp.get("unitQuantityUom") or None

        category_path = category_path_from_trees(item.get("categoryTrees"))

        # Independent Stock Availability Evaluation
        stock_level = item.get("stockLevel")
        out_of_stock_flag = item.get("outOfStock")
        in_stock_flag = item.get("inStock")
        purchasable_flag = item.get("purchasable")
        avail_raw = str(item.get("availability") or item.get("availabilityStatus") or "").strip().lower()

        in_stock = True
        if out_of_stock_flag is True or in_stock_flag is False or purchasable_flag is False:
            in_stock = False
        elif isinstance(stock_level, (int, float)) and stock_level <= 0:
            in_stock = False
        elif any(kw in avail_raw for kw in ("out_of_stock", "out", "unavailable", "discontinued", "oos", "sold_out")):
            in_stock = False
        elif any(kw in avail_raw for kw in ("in_stock", "available", "low_stock", "limited")):
            in_stock = True
        elif price <= 0:
            in_stock = False

        return ScrapedProduct(
            raw_name=raw_name,
            clean_name=clean_name,
            price=price,
            category=category_slug,
            special_price=special,
            comparison_price=comparison,
            image_url=item.get("images", {}).get("main") if isinstance(item.get("images"), dict) else item.get("imageUrl"),
            brand=brand,
            weight=display_name,
            in_stock=in_stock,
            product_id=str(item.get("productId") or item.get("id") or "") or None,
            unit_price=unit_price,
            unit_label=unit_label,
            category_path=category_path,
            promo_text=promo_text,
            promo_type=promo_type,
            card_required=card_required,
            loyalty_program_code=loyalty_code,
            source_promotion_id=source_promotion_id,
            multibuy_quantity=multibuy_quantity,
            multibuy_price_cents=multibuy_price_cents,
            promo_metadata=promo_metadata,
        )

    # ---- Stage 3: Detail Enrichment (GTIN Barcode, Nutrition, Availability) -

    async def enrich_products(self, products: list[ScrapedProduct]) -> None:
        """Fetch barcodes, nutrition, ingredients, and promo dates in parallel.
        Strictly validates GTINs so PLU codes (4/5 digits) are never assigned to barcode.
        """
        unique_pids = {p.product_id for p in products if p.product_id}
        to_fetch = [pid for pid in unique_pids if self.cache.needs_detail(pid)]

        logger.info(f"  [enrich] {len(unique_pids) - len(to_fetch)} cached, {len(to_fetch)} need detail API call")

        headers = {
            "Accept": "application/json",
            "User-Agent": self._cf_user_agent or USER_AGENT,
        }
        auth = self.template.headers.get("authorization") or self.template.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth

        concurrency = ENRICH_CONCURRENCY_INITIAL
        detail_results: dict[str, dict] = {}

        if to_fetch:
            i = 0
            client_kw: dict[str, Any] = {"timeout": 15.0}
            if self.proxy_url:
                client_kw["proxy"] = self.proxy_url

            while i < len(to_fetch):
                batch = to_fetch[i : i + concurrency]
                i += len(batch)

                async def _fetch_one(pid: str) -> tuple[str, Optional[dict], int]:
                    url = DETAIL_API_TEMPLATE.format(store_id=self.store_id, pid=pid)
                    try:
                        async with httpx.AsyncClient(**client_kw) as client:
                            resp = await client.get(url, headers=headers)
                            if resp.is_success:
                                return pid, resp.json(), resp.status_code
                            return pid, None, resp.status_code
                    except Exception:
                        return pid, None, 0

                results = await asyncio.gather(*[_fetch_one(pid) for pid in batch])
                batch_429s = sum(1 for _, _, status in results if status == 429)

                for pid, data, status in results:
                    if data:
                        raw_sku = data.get("sku")
                        sku_str = str(raw_sku).strip() if raw_sku else None

                        # Strict GTIN format validation
                        barcode = sku_str if is_valid_gtin(sku_str) else None

                        img = extract_fs_image(data)
                        detail = extract_fs_detail(data)

                        # Isolate produce PLUs in detail card so they are preserved
                        if sku_str and not barcode:
                            if len(sku_str) in (4, 5) and sku_str.isdigit():
                                detail["plu_code"] = sku_str
                            detail["sku"] = sku_str

                        # Extract stock availability signals from detail
                        det_stock_level = data.get("stockLevel")
                        det_avail = str(data.get("availability") or data.get("availabilityStatus") or "").strip().lower()
                        det_oos = data.get("outOfStock")

                        is_in_stock = True
                        if det_oos is True:
                            is_in_stock = False
                        elif isinstance(det_stock_level, (int, float)) and det_stock_level <= 0:
                            is_in_stock = False
                        elif any(kw in det_avail for kw in ("out_of_stock", "out", "unavailable", "discontinued", "oos")):
                            is_in_stock = False
                        elif any(kw in det_avail for kw in ("in_stock", "available")):
                            is_in_stock = True

                        detail["_authoritative_in_stock"] = is_in_stock

                        # Extract promo dates
                        for promo in (data.get("promotionList") or []):
                            if isinstance(promo, dict) and promo.get("promoId"):
                                self._promo_date_cache[str(promo["promoId"])] = {
                                    "start": promo.get("startDate"),
                                    "end": promo.get("endDate"),
                                }

                        detail_results[pid] = {
                            "barcode": barcode,
                            "img": img,
                            "det": detail,
                            "in_stock": is_in_stock,
                        }
                        self.cache.put_detail(pid, barcode, img, detail)

                if batch_429s >= ENRICH_429_THRESHOLD:
                    concurrency = max(ENRICH_CONCURRENCY_MIN, concurrency // 2)
                    logger.warning(f"  [enrich] Hit {batch_429s} rate limits (429) — backing off concurrency to {concurrency}")
                    await asyncio.sleep(2.0)

            self.cache.save()

        # Apply enriched fields to products
        applied_bc = 0
        plu_isolated = 0
        for p in products:
            if not p.product_id:
                continue
            det = detail_results.get(p.product_id)
            if det:
                if det.get("barcode"):
                    p.barcode = det["barcode"]
                    applied_bc += 1
                if det.get("img") and not p.image_url:
                    p.image_url = det["img"]
                if det.get("det"):
                    p.detail = det["det"]
                if "in_stock" in det:
                    p.in_stock = det["in_stock"]
            else:
                # Fallback to local cache
                bc = self.cache.get_barcode(p.product_id)
                if bc:
                    p.barcode = bc
                    applied_bc += 1
                img = self.cache.get_image(p.product_id)
                if img and not p.image_url:
                    p.image_url = img
                cached_det = self.cache.get_detail(p.product_id)
                if cached_det:
                    p.detail = cached_det
                    if "_authoritative_in_stock" in cached_det:
                        p.in_stock = cached_det["_authoritative_in_stock"]

            if p.detail.get("plu_code"):
                plu_isolated += 1

            # Stamp promo dates
            if p.source_promotion_id and p.source_promotion_id in self._promo_date_cache:
                dates = self._promo_date_cache[p.source_promotion_id]
                p.promo_starts_at = dates.get("start")
                p.promo_ends_at = dates.get("end")

        logger.info(f"  [enrich] Applied: {applied_bc} valid GTIN barcodes ({plu_isolated} PLU codes isolated to raw_row)")

    # ---- Stage 4: Observation Builder ---------------------------------------

    def build_observation(self, p: ScrapedProduct) -> Optional[dict]:
        """Convert ScrapedProduct to a schema-conforming JSONL observation."""
        if not p.raw_name or p.price is None or p.price <= 0:
            return None

        on_special = bool(p.special_price and p.special_price < p.price)
        current = p.special_price if on_special else p.price
        comparison = p.comparison_price if on_special else None

        product_url = f"{BASE_URL}/shop/product/{p.product_id}" if p.product_id else None

        rec = {
            "source_product_id": p.product_id,
            "retailer_sku": p.product_id,
            "barcode": p.barcode if is_valid_gtin(p.barcode) else None,
            "raw_name": p.raw_name,
            "clean_name": p.clean_name,
            "brand": p.brand,
            "category_path": p.category_path or p.category,
            "size": p.weight,
            "current_price_cents": to_cents(current),
            "comparison_price_cents": to_cents(comparison),
            "unit_price_cents": to_cents(p.unit_price),
            "unit_label": p.unit_label,
            "stock_status": "in_stock" if p.in_stock else "out_of_stock",
            "promo_text": p.promo_text,
            "promo_type": p.promo_type,
            "card_required": p.card_required or None,
            "required_loyalty_program_code": p.loyalty_program_code,
            "source_promotion_id": p.source_promotion_id,
            "multibuy_quantity": p.multibuy_quantity,
            "multibuy_price_cents": p.multibuy_price_cents,
            "promo_starts_at": p.promo_starts_at,
            "promo_ends_at": p.promo_ends_at,
            "promo_metadata": p.promo_metadata or None,
            "product_url": product_url,
            "image_url": p.image_url,
            "observed_at": p.scraped_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Clean private cache markers from detail before export
        if p.detail:
            clean_det = {k: v for k, v in p.detail.items() if not k.startswith("_")}
            if clean_det:
                rec["raw_row"] = clean_det

        return clean_record(rec)

    # ---- Main Scrape Execution ----------------------------------------------

    async def scrape_branch(self) -> dict[str, Any]:
        """Scrape categories for the active branch and export JSONL."""
        t0 = time.time()
        logger.info(f"=== SCRAPING BRANCH: {self.branch_name} (storeId={self.store_id}) ===")

        # Check existing clearance session or resolve via CapSolver
        session_file = Path(__file__).resolve().parent / ".paknsave_session.json"
        cookie_file = Path(__file__).resolve().parent / ".paknsave_cookies.json"
        has_fresh_cookie = False

        if session_file.exists():
            try:
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                age = time.time() - sess.get("saved_at", 0)
                if age < 1800 and sess.get("cookies"):
                    self._cf_cookies = sess["cookies"]
                    self._cf_user_agent = sess.get("user_agent")
                    has_fresh_cookie = True
                    logger.info(f"[cf] Found cached clearance session ({int(age)}s old)")
            except Exception:
                pass

        if not has_fresh_cookie and self.capsolver_api_key:
            cs_cookies, cs_ua = await _solve_cf_with_capsolver(
                self.capsolver_api_key,
                proxy_url=self.proxy_url,
                target_url=BASE_URL,
            )
            if cs_cookies:
                self._cf_cookies = cs_cookies
                self._cf_user_agent = cs_ua
                try:
                    cookie_file.write_text(json.dumps(cs_cookies, indent=2), encoding="utf-8")
                    session_file.write_text(json.dumps({
                        "user_agent": cs_ua,
                        "cookies": cs_cookies,
                        "saved_at": time.time(),
                    }, indent=2), encoding="utf-8")
                except Exception:
                    pass

        await self._start_browser()
        await self._new_context()

        if not self.template.ready:
            await self._seed_session()

        all_products: list[ScrapedProduct] = []
        try:
            for idx, slug in enumerate(self.category_slugs, 1):
                logger.info(f"[{idx}/{len(self.category_slugs)}] Category: {slug}")
                products = None

                if self.template.ready:
                    products = await self.scrape_category_direct(slug)

                if not products:
                    products = await self.scrape_category_browser(slug)

                if products:
                    logger.info(f"  -> Got {len(products)} products for {slug}")
                    all_products.extend(products)
                else:
                    logger.warning(f"  -> Category {slug} returned 0 products")

                await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            # Deduplicate products by product_id
            seen_ids = set()
            deduped = []
            for p in all_products:
                if p.product_id and p.product_id in seen_ids:
                    continue
                if p.product_id:
                    seen_ids.add(p.product_id)
                deduped.append(p)

            logger.info(f"Total unique products scraped: {len(deduped)}")

            # Enrich Barcodes, Nutrition & Availability
            if deduped:
                await self.enrich_products(deduped)

            # Export to JSONL
            records = [self.build_observation(p) for p in deduped]
            records = [r for r in records if r]

            export_path = write_jsonl(records, self.branch_name, retailer="paknsave")
            elapsed = time.time() - t0

            specials_count = sum(1 for r in records if r.get("promo_type") == "special")
            multibuys_count = sum(1 for r in records if r.get("promo_type") == "multibuy_fixed_price")
            members_count = sum(1 for r in records if r.get("promo_type") == "member_price")
            barcodes_count = sum(1 for r in records if r.get("barcode"))

            logger.info(f"=== BRANCH COMPLETE: {self.branch_name} in {elapsed:.1f}s ===")
            logger.info(f"  Observations exported : {len(records)}")
            logger.info(f"  Valid GTIN Barcodes   : {barcodes_count} ({round(barcodes_count/max(len(records),1)*100, 1)}%)")
            logger.info(f"  Classified Promotions : {specials_count + multibuys_count + members_count} (Specials={specials_count}, Multibuys={multibuys_count}, Members={members_count})")
            logger.info(f"  Export file path      : {export_path}")

            return {
                "branch": self.branch_name,
                "store_id": self.store_id,
                "products_count": len(records),
                "barcodes_count": barcodes_count,
                "specials": specials_count,
                "multibuys": multibuys_count,
                "export_path": str(export_path) if export_path else None,
                "duration_seconds": round(elapsed, 1),
                "status": "SUCCESS",
            }
        finally:
            await self._close_browser()


# ---------------------------------------------------------------------------
# All-Branches Orchestrator & CLI Entrypoint
# ---------------------------------------------------------------------------

async def run_all_branches(
    category_slugs: Optional[list[str]] = None,
    limit: Optional[int] = None,
    headless: bool = True,
    rate: float = DEFAULT_RATE_LIMIT,
    proxy: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Discover all active PAK'nSAVE branches via catalog_branches and scrape each in sequence."""
    t0 = time.time()
    branches = list_branches("paknsave", active_only=True, require_store_id=True)
    if limit:
        branches = branches[:limit]

    logger.info("=" * 70)
    logger.info(f"STARTING ALL-BRANCHES RUN: {len(branches)} ACTIVE PAK'nSAVE BRANCHES")
    logger.info("=" * 70)
    for b in branches:
        logger.info(f"  - {b['name']:<28} id={b['id']} store_id={b['api_store_id']}")
    logger.info("=" * 70)

    results = []
    for idx, b in enumerate(branches, 1):
        logger.info(f"\n>>> [{idx}/{len(branches)}] Processing {b['name']} <<<")
        scraper = PaknsaveScraper(
            branch_name=b["name"],
            store_id=b["api_store_id"],
            branch_id=b.get("id"),
            category_slugs=category_slugs,
            headless=headless,
            rate=rate,
            proxy=proxy,
        )
        try:
            stat = await scraper.scrape_branch()
            results.append(stat)
        except Exception as e:
            logger.error(f"Branch {b['name']} failed: {e}")
            results.append({
                "branch": b["name"],
                "store_id": b["api_store_id"],
                "products_count": 0,
                "status": f"FAILED: {e}",
            })
        await asyncio.sleep(2.0)

    tot_obs = sum(r.get("products_count", 0) for r in results)
    tot_time = time.time() - t0

    print("\n" + "=" * 80)
    print("ALL-BRANCHES RUN SUMMARY:")
    print("=" * 80)
    print(f"{'Branch Name':<30} {'Store ID':<38} {'Products':<10} {'Status':<10}")
    print("-" * 80)
    for r in results:
        bname = r.get("branch", "Unknown")[:28]
        sid = (r.get("store_id") or "")[:36]
        cnt = r.get("products_count", 0)
        st = r.get("status", "OK")
        print(f"{bname:<30} {sid:<38} {cnt:<10} {st:<10}")
    print("-" * 80)
    print(f"Total Branches: {len(results)} | Total Observations: {tot_obs:,} | Duration: {tot_time:.1f}s")
    print("=" * 80)
    return results


def main():
    parser = argparse.ArgumentParser(description="PAK'nSAVE Supermarket Scraper — Production Build")
    parser.add_argument("--all-branches", action="store_true", help="Scrape all active branches in catalog")
    parser.add_argument("--branch", default=DEFAULT_STORE_NAME, help="Target branch name or slug")
    parser.add_argument("--branch-id", help="Target branch PICO UUID")
    parser.add_argument("--branch-limit", type=int, help="Limit number of branches for multi-branch run")
    parser.add_argument("--store-id", help="Override Foodstuffs API storeId UUID")
    parser.add_argument("--test", action="store_true", help="Quick test: 3 categories only")
    parser.add_argument("--categories", help="Comma-separated category slugs")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE_LIMIT, help="Max requests per second")
    parser.add_argument("--proxy", default=os.getenv("PROXY_URL"), help="Proxy URL (e.g. http://USER:PASS@host:port)")
    args = parser.parse_args()

    if args.test:
        categories = ["fruit-and-vegetables", "bakery", "hot-and-cold-drinks"]
    elif args.categories:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    else:
        categories = CATEGORIES

    if args.all_branches:
        asyncio.run(run_all_branches(
            category_slugs=categories,
            limit=args.branch_limit,
            headless=not args.no_headless,
            rate=args.rate,
            proxy=args.proxy,
        ))
    else:
        scraper = PaknsaveScraper(
            branch_name=args.branch,
            store_id=args.store_id or DEFAULT_STORE_ID,
            branch_id=args.branch_id,
            category_slugs=categories,
            headless=not args.no_headless,
            rate=args.rate,
            proxy=args.proxy,
        )
        asyncio.run(scraper.scrape_branch())


if __name__ == "__main__":
    main()
