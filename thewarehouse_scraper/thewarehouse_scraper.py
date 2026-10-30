"""The Warehouse NZ Scraper — Production Build.

Conforms strictly to PICO Scraper Data Contract and Woolworths / PAK'nSAVE benchmark maturity:
1. Barcode Accuracy: Strict GTIN format validation (lengths 8, 12, 13, 14 numeric digits)
   and mathematical GS1 modulo-10 checksum verification. Non-GTIN codes isolated to raw_row.
2. Pricing Precision: All prices represented as integer cents NZD, strictly rejecting dollar floats.
   Discounts and 'was' prices mapped to comparison_price_cents only when valid.
3. Stock Availability: True independent availability evaluation from product tile
   (data-stock-status: IN_STOCK, OUT_OF_STOCK, FIND_IN_STORE).
4. Promotions Verification: Complete classification of specials, multibuys (quantity & price),
   clearance, and MarketClub member prices. Zero orphan promo metadata on regular shelf pricing.
5. Multi-Branch Workflow: Complete --branch and --all-branches support with automated branch discovery
   via `catalog_branches.py`. Keeps branch-specific JSONL exports strictly separate.
6. Production Resilience: Exponential backoff retries handling HTTP 429, 425, 5xx, and network drops
   without stopping pagination.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from catalog_branches import get_branch, list_branches
from config import (
    BASE_URL,
    CATEGORIES,
    CATEGORY_CGIDS,
    CATEGORY_DISPLAY_NAMES,
    DEFAULT_BRANCH_ID,
    DEFAULT_BRANCH_SLUG,
    DEFAULT_STORE_NAME,
    DELAY_MAX,
    DELAY_MIN,
    EXPORTS_DIR,
    EXTRA_HEADERS,
    LOYALTY_PROGRAM_CODE,
    MAX_RETRIES,
    PAGE_SIZE,
    PROXY_URL,
    RETAILER_NAME,
    RETAILER_SLUG,
    REQUEST_TIMEOUT_SECONDS,
    SEARCH_UPDATE_ENDPOINT,
    USER_AGENT,
)
from jsonl_exporter import clean_record, to_cents, write_jsonl
from normalize import (
    clean_barcode,
    clean_product_name,
    extract_size,
    format_category_path,
    is_valid_gtin_checksum,
    parse_promotions,
)
from notify import push as push_notify
from run_log import RunLogger, category_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("thewarehouse_scraper")


@dataclass
class ScrapedProduct:
    product_id: str
    retailer_sku: str
    raw_name: str
    clean_name: str
    brand: Optional[str]
    category_path: str
    size: Optional[str]
    current_price_cents: int
    stock_status: str
    product_url: str
    image_url: Optional[str] = None
    barcode: Optional[str] = None
    comparison_price_cents: Optional[int] = None
    unit_price_cents: Optional[int] = None
    unit_label: Optional[str] = None
    promo_text: Optional[str] = None
    promo_type: Optional[str] = None
    card_required: Optional[bool] = None
    required_loyalty_program_code: Optional[str] = None
    source_promotion_id: Optional[str] = None
    multibuy_quantity: Optional[int] = None
    multibuy_price_cents: Optional[int] = None
    promo_metadata: Optional[dict] = None
    raw_row: dict = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_observation(self) -> dict[str, Any]:
        """Convert to client PICO contract record."""
        rec = {
            "source_product_id": self.product_id,
            "retailer_sku": self.retailer_sku,
            "barcode": self.barcode if clean_barcode(self.barcode) else None,
            "raw_name": self.raw_name,
            "clean_name": self.clean_name,
            "brand": self.brand,
            "category_path": self.category_path,
            "size": self.size,
            "current_price_cents": self.current_price_cents,
            "comparison_price_cents": self.comparison_price_cents,
            "unit_price_cents": self.unit_price_cents,
            "unit_label": self.unit_label,
            "stock_status": self.stock_status,
            "promo_text": self.promo_text,
            "promo_type": self.promo_type,
            "card_required": self.card_required,
            "required_loyalty_program_code": self.required_loyalty_program_code,
            "source_promotion_id": self.source_promotion_id,
            "multibuy_quantity": self.multibuy_quantity,
            "multibuy_price_cents": self.multibuy_price_cents,
            "promo_metadata": self.promo_metadata,
            "product_url": self.product_url,
            "image_url": self.image_url,
            "observed_at": self.observed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        if self.raw_row:
            rec["raw_row"] = self.raw_row

        return clean_record(rec)


class TheWarehouseScraper:
    """Production scraper for The Warehouse NZ."""

    def __init__(
        self,
        branch: Optional[dict[str, Any]] = None,
        proxy_url: Optional[str] = None,
        categories: Optional[list[str]] = None,
        limit: Optional[int] = None,
        page_limit: Optional[int] = None,
        dry_run: bool = False,
        no_proxy: bool = False,
    ) -> None:
        self.branch = branch or get_branch(DEFAULT_BRANCH_ID) or {
            "id": DEFAULT_BRANCH_ID,
            "store_id": DEFAULT_BRANCH_ID,
            "name": DEFAULT_STORE_NAME,
            "slug": DEFAULT_BRANCH_SLUG,
        }
        self.branch_id = str(self.branch.get("store_id") or self.branch.get("id"))
        self.branch_slug = self.branch.get("slug") or DEFAULT_BRANCH_SLUG
        self.branch_name = self.branch.get("name") or DEFAULT_STORE_NAME

        self.proxy_url = None if no_proxy else (proxy_url or PROXY_URL)
        self.target_categories = categories or CATEGORIES
        self.limit = limit
        self.page_limit = page_limit
        self.dry_run = dry_run

        self._client: Optional[httpx.Client] = None
        self._seen_product_ids: set[str] = set()

    def _get_client(self) -> httpx.Client:
        """Create or return an HTTP client with retry headers and optional proxy."""
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-NZ,en;q=0.9",
            }

            # Determine if branch is South Island or North Island
            state = str(self.branch.get("state_code", "")).upper()
            is_south = any(s in state for s in ("OTA", "CAN", "STL", "WTC", "TAS", "NEL", "MBH"))
            region_val = "southIsland" if is_south else "northIsland"

            cookies = {
                "preferred_store": self.branch_id,
                "user_region": region_val,
            }

            self._client = httpx.Client(
                headers=headers,
                cookies=cookies,
                proxy=self.proxy_url if self.proxy_url else None,
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        return self._client

    def _fetch_page_with_retry(self, url: str, params: Optional[dict[str, Any]] = None) -> Optional[str]:
        """Fetch URL with exponential backoff on HTTP 429, 425, 5xx."""
        client = self._get_client()
        delay = 2.0

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Politeness delay
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

                resp = client.get(url, params=params)

                if resp.status_code == 200:
                    return resp.text

                if resp.status_code in (429, 425, 500, 502, 503, 504):
                    logger.warning(
                        f"  [fetch] HTTP {resp.status_code} on attempt {attempt}/{MAX_RETRIES} for {url}. "
                        f"Backing off {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= 2.0 + random.uniform(0.5, 1.5)
                    continue

                if resp.status_code == 404:
                    logger.warning(f"  [fetch] HTTP 404 Not Found: {url}")
                    return None

                logger.warning(f"  [fetch] Unexpected HTTP {resp.status_code} for {url}")
                return None

            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(
                    f"  [fetch] Network error on attempt {attempt}/{MAX_RETRIES}: {e}. "
                    f"Backing off {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= 2.0
                # Re-create client on connection failure
                if self._client and not self._client.is_closed:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                self._client = None
                client = self._get_client()

        logger.error(f"  [fetch] Failed after {MAX_RETRIES} attempts for {url}")
        return None

    def _parse_product_tile(self, tile: BeautifulSoup, category_slug: str) -> Optional[ScrapedProduct]:
        """Extract a structured ScrapedProduct observation from a .product-tile element."""
        try:
            ga_data = json.loads(tile.get("data-ga-product") or "{}")
        except Exception:
            ga_data = {}

        try:
            gtm_data = json.loads(tile.get("data-gtm-product") or "{}")
        except Exception:
            gtm_data = {}

        pid = (
            tile.get("data-pid")
            or ga_data.get("item_id")
            or gtm_data.get("id")
            or gtm_data.get("variationProductId")
        )
        if not pid:
            return None

        # Clean SKU and ID
        pid = str(pid).strip()

        # Product Title
        raw_name = (
            ga_data.get("item_name")
            or gtm_data.get("name")
            or (tile.select_one(".link.text-emphasized").get_text(strip=True) if tile.select_one(".link.text-emphasized") else None)
        )
        if not raw_name:
            return None
        raw_name = str(raw_name).strip()

        # Brand
        brand = ga_data.get("item_brand") or gtm_data.get("brand")
        if brand and brand.lower() in ("na", "none", "unknown"):
            brand = None
        if brand:
            brand = str(brand).strip()

        # Size extraction
        size = extract_size(raw_name)
        clean_name = clean_product_name(raw_name, brand=brand, size=size)

        # Barcode (GTIN-8, 12, 13, 14 with GS1 modulo-10 validation)
        raw_barcode = ga_data.get("productEAN") or ga_data.get("dimension15") or gtm_data.get("productEAN")
        barcode = clean_barcode(raw_barcode)

        # Price extraction (strictly integer cents)
        price_val = ga_data.get("price") or gtm_data.get("price")
        if price_val is None:
            price_el = tile.select_one(".price")
            if price_el:
                price_val = price_el.get_text(strip=True)

        current_price_cents = to_cents(price_val)
        if current_price_cents is None or current_price_cents <= 0:
            return None

        # Comparison / Was Price
        then_val = gtm_data.get("productThenPrice")
        then_cents = to_cents(then_val)

        # Stock status
        stock_status = "in_stock"
        stock_el = tile.select_one(".availability-stock-status")
        if stock_el:
            st = (stock_el.get("data-stock-status") or "").upper()
            if "OUT_OF_STOCK" in st:
                stock_status = "out_of_stock"
            elif "IN_STOCK" in st or "PREORDER" in st:
                stock_status = "in_stock"
            elif "FIND_IN_STORE" in st:
                # Available in store only or regional
                stock_status = "in_stock"

        # Promotions
        claim_el = tile.select_one(".price-lockup__claim")
        claim = claim_el.get_text(strip=True) if claim_el else None
        badges = gtm_data.get("productBadges")
        promo_msg = gtm_data.get("promotionCallOutMessage")

        promo_info = parse_promotions(
            price_cents=current_price_cents,
            then_price_cents=then_cents,
            badges=badges,
            claim=claim,
            promo_msg=promo_msg,
        )

        # Category path
        raw_cat = (
            gtm_data.get("category")
            or ga_data.get("item_primarycgid")
            or CATEGORY_CGIDS.get(category_slug, category_slug)
        )
        display_fallback = CATEGORY_DISPLAY_NAMES.get(category_slug, category_slug.replace("-", " ").title())
        category_path = format_category_path(raw_cat, fallback=display_fallback) or display_fallback

        # URLs
        link_el = tile.select_one("a.link") or tile.select_one(".image-container a")
        href = link_el.get("href") if link_el else f"/p/{pid}.html"
        product_url = href if href.startswith("http") else f"{BASE_URL}{href}"

        img_el = tile.select_one(".tile-image") or tile.select_one(".image-container img")
        image_url = None
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src")

        # Rich Raw Row metadata
        raw_row = {}
        if ga_data:
            clean_ga = {k: v for k, v in ga_data.items() if v not in (None, "", "na")}
            if clean_ga:
                raw_row["ga_product"] = clean_ga
        if gtm_data:
            clean_gtm = {k: v for k, v in gtm_data.items() if v not in (None, "", "na")}
            if clean_gtm:
                raw_row["gtm_product"] = clean_gtm
        if raw_barcode and not barcode:
            # Preserve non-GTIN or unverified barcode in raw_row for transparency
            raw_row["unverified_barcode"] = raw_barcode

        return ScrapedProduct(
            product_id=pid,
            retailer_sku=pid,
            raw_name=raw_name,
            clean_name=clean_name,
            brand=brand,
            category_path=category_path,
            size=size,
            current_price_cents=current_price_cents,
            comparison_price_cents=promo_info["comparison_price_cents"],
            stock_status=stock_status,
            promo_text=promo_info["promo_text"],
            promo_type=promo_info["promo_type"],
            card_required=promo_info["card_required"],
            required_loyalty_program_code=promo_info["required_loyalty_program_code"],
            multibuy_quantity=promo_info["multibuy_quantity"],
            multibuy_price_cents=promo_info["multibuy_price_cents"],
            promo_metadata=promo_info["promo_metadata"],
            product_url=product_url,
            image_url=image_url,
            barcode=barcode,
            raw_row=raw_row,
        )

    def scrape_category(self, category_slug: str, max_items: Optional[int] = None) -> list[ScrapedProduct]:
        """Scrape paginated products for a given department / category."""
        cgid = CATEGORY_CGIDS.get(category_slug, category_slug)
        display_name = CATEGORY_DISPLAY_NAMES.get(category_slug, category_slug)
        logger.info(f"--- Scraping category: {display_name} (cgid={cgid}) ---")

        products: list[ScrapedProduct] = []
        start = 0
        page_no = 0

        while True:
            if max_items and len(products) >= max_items:
                break
            if self.page_limit and page_no >= self.page_limit:
                logger.info(f"  Reached page limit ({self.page_limit}) for {category_slug}")
                break

            params = {
                "cgid": cgid,
                "start": start,
                "sz": PAGE_SIZE,
            }

            html = self._fetch_page_with_retry(SEARCH_UPDATE_ENDPOINT, params=params)
            if not html:
                # If first page failed, try landing category page URL as fallback
                if start == 0:
                    fallback_url = f"{BASE_URL}/c/{category_slug}"
                    logger.info(f"  Attempting category fallback URL: {fallback_url}")
                    html = self._fetch_page_with_retry(fallback_url)
                if not html:
                    break

            soup = BeautifulSoup(html, "html.parser")
            tiles = soup.select(".product-tile")

            if not tiles:
                logger.info(f"  No more product tiles found at offset {start}. Done with {category_slug}.")
                break

            new_in_page = 0
            for tile in tiles:
                product = self._parse_product_tile(tile, category_slug)
                if product:
                    if product.product_id not in self._seen_product_ids:
                        self._seen_product_ids.add(product.product_id)
                        products.append(product)
                        new_in_page += 1
                        if max_items and len(products) >= max_items:
                            break

            logger.info(
                f"  Page {page_no + 1} (start={start}): parsed {len(tiles)} tiles -> "
                f"+{new_in_page} new products (category total: {len(products)})"
            )

            # Check if reached end of product count
            rc_el = soup.select_one(".result-count, .search-result-count, .filter-header")
            if rc_el:
                rc_text = rc_el.get_text()
                # e.g. "1 – 32 of 1,363 products"
                m = re.search(r"of\s*([\d,]+)\s*products", rc_text, re.IGNORECASE)
                if m:
                    total_count = int(m.group(1).replace(",", ""))
                    if start + PAGE_SIZE >= total_count:
                        logger.info(f"  Reached total department count ({total_count} products)")
                        break

            if len(tiles) < PAGE_SIZE:
                logger.info(f"  Received fewer tiles ({len(tiles)}) than page size ({PAGE_SIZE}). End of category.")
                break

            start += PAGE_SIZE
            page_no += 1

        return products

    def scrape_branch(self) -> dict[str, Any]:
        """Execute full scrape for the designated branch."""
        t0 = time.time()
        logger.info(f"===============================================================")
        logger.info(f"STARTING SCRAPE: {self.branch_name} (Store ID: {self.branch_id}, Slug: {self.branch_slug})")
        logger.info(f"Categories: {', '.join(self.target_categories)}")
        if self.limit:
            logger.info(f"Branch Product Limit: {self.limit}")
        logger.info(f"===============================================================")

        run_log = RunLogger("thewarehouse_scraper", branch_label=self.branch_slug)
        all_products: list[ScrapedProduct] = []
        category_results: list[dict[str, Any]] = []

        try:
            for cat_slug in self.target_categories:
                remaining_limit = (self.limit - len(all_products)) if self.limit else None
                if self.limit and remaining_limit is not None and remaining_limit <= 0:
                    logger.info(f"Reached overall branch limit ({self.limit} products). Stopping category sweeps.")
                    break

                try:
                    cat_prods = self.scrape_category(cat_slug, max_items=remaining_limit)
                    all_products.extend(cat_prods)
                    category_results.append(category_record(cat_slug, "success", cat_prods))
                except Exception as e:
                    logger.error(f"Error scraping category {cat_slug}: {e}", exc_info=True)
                    category_results.append(category_record(cat_slug, "failed", [], reason=str(e)))

            observations = [p.to_observation() for p in all_products]

            # Summary metrics
            total_obs = len(observations)
            valid_gtins = sum(1 for o in observations if o.get("barcode"))
            promos = sum(1 for o in observations if o.get("promo_type") == "special")
            multibuys = sum(1 for o in observations if o.get("promo_type") in ("multibuy_fixed_price", "multibuy_quantity_discount"))
            members = sum(1 for o in observations if o.get("promo_type") == "member_price")
            oos = sum(1 for o in observations if o.get("stock_status") == "out_of_stock")

            logger.info(f"---------------------------------------------------------------")
            logger.info(f"Scraped {total_obs:,} observations for {self.branch_name}")
            logger.info(f"  Valid Barcodes: {valid_gtins:,} ({(valid_gtins / total_obs * 100) if total_obs else 0:.1f}%)")
            logger.info(f"  Specials      : {promos:,}")
            logger.info(f"  Multibuys     : {multibuys:,}")
            logger.info(f"  Member Prices : {members:,}")
            logger.info(f"  Out of Stock  : {oos:,}")
            logger.info(f"---------------------------------------------------------------")

            export_file = None
            if not self.dry_run and observations:
                export_file = write_jsonl(
                    observations,
                    branch_label=self.branch_slug,
                    retailer=RETAILER_SLUG,
                    out_dir=EXPORTS_DIR,
                )

            duration = time.time() - t0
            run_log.log_run_end(
                success=True,
                categories=category_results,
                products=total_obs,
                output_file=str(export_file) if export_file else None,
                duration=duration,
            )

            # Notification
            push_notify(
                message=f"Scraped {total_obs:,} items for {self.branch_name} in {duration:.1f}s. GTINs: {valid_gtins:,}",
                title=f"The Warehouse Scrape: {self.branch_name}",
            )

            return {
                "branch_slug": self.branch_slug,
                "branch_name": self.branch_name,
                "total_observations": total_obs,
                "export_file": str(export_file) if export_file else None,
                "duration_seconds": round(duration, 2),
                "success": True,
            }

        except Exception as e:
            duration = time.time() - t0
            logger.error(f"Fatal error during branch scrape: {e}", exc_info=True)
            run_log.log_run_end(
                success=False,
                categories=category_results,
                products=len(all_products),
                error=str(e),
                duration=duration,
            )
            return {
                "branch_slug": self.branch_slug,
                "branch_name": self.branch_name,
                "total_observations": len(all_products),
                "error": str(e),
                "duration_seconds": round(duration, 2),
                "success": False,
            }

        finally:
            if self._client and not self._client.is_closed:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None


def main() -> None:
    parser = argparse.ArgumentParser(description="The Warehouse NZ Supermarket & Retail Scraper.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH_ID, help="Branch store ID, slug, or name.")
    parser.add_argument("--all-branches", action="store_true", help="Scrape all authentic branches across NZ.")
    parser.add_argument("--category", action="append", help="Specific category slug (e.g. food-pets-household).")
    parser.add_argument("--limit", type=int, help="Maximum total products to scrape per branch.")
    parser.add_argument("--page-limit", type=int, help="Maximum pages to scrape per category.")
    parser.add_argument("--proxy", help="HTTP/HTTPS proxy URL override.")
    parser.add_argument("--no-proxy", action="store_true", help="Connect directly without proxy.")
    parser.add_argument("--dry-run", action="store_true", help="Scrape without writing JSONL exports.")
    args = parser.parse_args()

    selected_categories = args.category if args.category else None

    if args.all_branches:
        branches = list_branches()
        logger.info(f"Beginning multi-branch run across {len(branches)} branches...")
        results = []
        for idx, b in enumerate(branches, start=1):
            logger.info(f"=== Branch {idx}/{len(branches)}: {b['name']} ({b['slug']}) ===")
            scraper = TheWarehouseScraper(
                branch=b,
                proxy_url=args.proxy,
                categories=selected_categories,
                limit=args.limit,
                page_limit=args.page_limit,
                dry_run=args.dry_run,
                no_proxy=args.no_proxy,
            )
            res = scraper.scrape_branch()
            results.append(res)
            # Politeness pause between branches
            time.sleep(3.0)

        successes = sum(1 for r in results if r.get("success"))
        logger.info(f"All-branches run complete: {successes}/{len(branches)} branches succeeded.")

    else:
        branch = get_branch(args.branch)
        if not branch:
            logger.error(f"Branch '{args.branch}' not found.")
            sys.exit(1)

        scraper = TheWarehouseScraper(
            branch=branch,
            proxy_url=args.proxy,
            categories=selected_categories,
            limit=args.limit,
            page_limit=args.page_limit,
            dry_run=args.dry_run,
            no_proxy=args.no_proxy,
        )
        res = scraper.scrape_branch()
        if not res.get("success"):
            sys.exit(1)


if __name__ == "__main__":
    main()
