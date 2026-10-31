"""Kai Co New Zealand Grocery Scraper.

Scrapes all live products, prices, stock statuses, promotions, and metadata
from Kai Co (https://kaico.co.nz/) and exports them strictly following the
PICO Scraper Data Contract (JSONL, integer cents, ISO-8601 UTC timestamps).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import sys
import time
from typing import Any, Optional

import httpx

from catalog_branches import resolve_branch
from config import (
    BASE_URL,
    PRODUCTS_ENDPOINT,
    COLLECTIONS_ENDPOINT,
    DEFAULT_STORE_NAME,
    DEFAULT_STORE_SLUG,
    DEFAULT_STORE_ID,
    EXPORTS_DIR,
    EXTRA_HEADERS,
    HTTP_TIMEOUT,
    LOGS_DIR,
    RETAILER_NAME,
    RETAILER_SLUG,
    SOURCE_SYSTEM,
    USER_AGENT,
    DELAY_MIN,
    DELAY_MAX,
)
from jsonl_exporter import write_jsonl
from normalize import (
    build_category_path,
    clean_name,
    extract_brand,
    extract_promotions,
    extract_size,
    extract_unit_info,
    is_valid_gtin_checksum,
    is_valid_gtin_format,
    to_cents,
)
from notify import push as push_notify
from run_log import RunLogger
from validate_export import validate_file

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "kaico_scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("kaico_scraper")


class KaiCoScraper:
    """Production scraper for Kai Co (Shopify-based grocery store)."""

    def __init__(
        self,
        branch_slug: str = DEFAULT_STORE_SLUG,
        client: Optional[httpx.Client] = None,
    ):
        self.branch = resolve_branch(branch_slug)
        self.branch_slug = self.branch.get("slug", DEFAULT_STORE_SLUG)
        self.branch_name = self.branch.get("name", DEFAULT_STORE_NAME)
        self.store_id = self.branch.get("external_id") or self.branch.get("store_id", DEFAULT_STORE_ID)

        headers = dict(EXTRA_HEADERS)
        headers["User-Agent"] = USER_AGENT

        self.client = client or httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=HTTP_TIMEOUT,
        )

        self.collections_map: dict[int, list[dict[str, Any]]] = {}
        self.deal_collections: dict[str, str] = {}

    def fetch_collections(self) -> None:
        """Fetch all collections to map category taxonomy and special deals."""
        logger.info("[catalog] Fetching store collections...")
        url = f"{COLLECTIONS_ENDPOINT}?limit=250"
        try:
            resp = self.client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[catalog] Failed to fetch collections: HTTP {resp.status_code}")
                return

            data = resp.json().get("collections", [])
            logger.info(f"[catalog] Found {len(data)} collections on Kai Co")

            for coll in data:
                c_id = coll.get("id")
                c_title = coll.get("title", "")
                c_handle = coll.get("handle", "")

                # Track deal collections
                if any(deal_key in c_handle.lower() for deal_key in ["deal", "special", "low-deals"]):
                    self.deal_collections[c_handle] = c_title

                # Fetch products in collection for precise mapping
                c_url = f"{BASE_URL}/collections/{c_handle}/products.json?limit=250"
                try:
                    c_resp = self.client.get(c_url)
                    if c_resp.status_code == 200:
                        c_products = c_resp.json().get("products", [])
                        for cp in c_products:
                            pid = cp.get("id")
                            if pid not in self.collections_map:
                                self.collections_map[pid] = []
                            self.collections_map[pid].append({
                                "id": c_id,
                                "title": c_title,
                                "handle": c_handle,
                            })
                    time.sleep(random.uniform(0.1, 0.25))
                except Exception as exc:
                    logger.debug(f"[catalog] Error fetching products for collection {c_handle}: {exc}")

        except Exception as e:
            logger.error(f"[catalog] Error querying collections endpoint: {e}")

    def fetch_all_products(self, max_products: Optional[int] = None) -> list[dict[str, Any]]:
        """Fetch all products across all pages from Shopify products API."""
        products = []
        page = 1
        page_size = 250

        logger.info("[scrape] Querying product catalog...")
        while True:
            url = f"{PRODUCTS_ENDPOINT}?limit={page_size}&page={page}"
            try:
                resp = self.client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"[scrape] Page {page} returned HTTP {resp.status_code}")
                    break

                batch = resp.json().get("products", [])
                if not batch:
                    logger.info(f"[scrape] Reached end of catalog at page {page}.")
                    break

                products.extend(batch)
                logger.info(f"[scrape] Page {page}: fetched {len(batch)} products (Total: {len(products)})")

                if max_products and len(products) >= max_products:
                    products = products[:max_products]
                    break

                page += 1
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            except Exception as e:
                logger.error(f"[scrape] Error fetching page {page}: {e}")
                break

        return products

    def transform_product(
        self,
        product: dict[str, Any],
        observed_at: str,
    ) -> list[dict[str, Any]]:
        """Transform a Shopify product entity into normalized PICO records (one per variant)."""
        observations = []
        pid = product.get("id")
        title = product.get("title", "").strip()
        handle = product.get("handle", "")
        vendor = product.get("vendor", "")
        product_type = product.get("product_type", "")
        body_html = product.get("body_html", "") or ""

        # Associated collections
        prod_colls = self.collections_map.get(pid, [])
        coll_titles = [c["title"] for c in prod_colls]
        coll_handles = [c["handle"] for c in prod_colls]

        # Primary Image
        images = product.get("images", [])
        image_url = images[0].get("src") if images else None

        product_url = f"{BASE_URL}/products/{handle}" if handle else None

        # Extract brand, size, clean name
        brand = extract_brand(title, vendor=vendor)
        size = extract_size(title)
        c_name = clean_name(title, brand=brand, size=size)
        category_path = build_category_path(product_type, coll_titles)

        variants = product.get("variants", [])
        for variant in variants:
            vid = variant.get("id")
            sku = variant.get("sku") or ""
            price_raw = variant.get("price")
            compare_price_raw = variant.get("compare_at_price")
            available = variant.get("available", False)
            raw_barcode = variant.get("barcode")

            current_price_cents = to_cents(price_raw)
            # Contract requirement: current_price_cents must be a positive integer!
            if current_price_cents is None or current_price_cents <= 0:
                logger.debug(f"[skip] Product {title} (ID {pid}) has non-positive price: {price_raw}")
                continue

            compare_at_cents = to_cents(compare_price_raw)
            if compare_at_cents is not None and compare_at_cents <= 0:
                compare_at_cents = None

            # Unit pricing
            unit_price_cents, unit_label = extract_unit_info(title, current_price_cents)

            # Barcode GS1 check: strictly exclude PLUs (4-5 digits)
            barcode = None
            if raw_barcode:
                bc_str = str(raw_barcode).strip()
                if is_valid_gtin_format(bc_str) and is_valid_gtin_checksum(bc_str):
                    barcode = bc_str

            # Stock status
            stock_status = "in_stock" if available else "out_of_stock"

            # Promotions detection
            promo_info = extract_promotions(
                title=title,
                body_html=body_html,
                current_price_cents=current_price_cents,
                compare_at_price_cents=compare_at_cents,
                collection_handles=coll_handles,
            )

            # Stable source product id and retailer sku
            source_product_id = f"{pid}-{vid}"
            retailer_sku = str(sku).strip() if sku else str(pid)

            record: dict[str, Any] = {
                "source_product_id": source_product_id,
                "retailer_sku": retailer_sku,
                "barcode": barcode,
                "raw_name": title,
                "clean_name": c_name,
                "brand": brand,
                "category_path": category_path,
                "size": size,
                "current_price_cents": current_price_cents,
                "comparison_price_cents": promo_info["comparison_price_cents"],
                "unit_price_cents": unit_price_cents,
                "unit_label": unit_label,
                "stock_status": stock_status,
                "promo_text": promo_info["promo_text"],
                "promo_type": promo_info["promo_type"],
                "card_required": None,
                "required_loyalty_program_code": None,
                "source_promotion_id": coll_handles[0] if (promo_info["promo_type"] and coll_handles) else None,
                "multibuy_quantity": promo_info["multibuy_quantity"],
                "multibuy_price_cents": promo_info["multibuy_price_cents"],
                "promo_metadata": {
                    "collections": coll_titles,
                    "product_type": product_type,
                    "vendor": vendor,
                } if coll_titles or product_type else None,
                "product_url": product_url,
                "image_url": image_url,
                "observed_at": observed_at,
                "raw_row": {
                    "id": pid,
                    "handle": handle,
                    "variant_id": vid,
                    "sku": sku,
                    "product_type": product_type,
                    "vendor": vendor,
                    "tags": product.get("tags", []),
                    "grams": variant.get("grams"),
                    "created_at": product.get("created_at"),
                    "updated_at": product.get("updated_at"),
                    "body_html": body_html[:500] if body_html else None,
                },
            }

            observations.append(record)

        return observations

    def run(
        self,
        max_products: Optional[int] = None,
        dry_run: bool = False,
        validate: bool = True,
        out_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Execute full scrape, transformation, JSONL export, and validation."""
        run_logger = RunLogger(SOURCE_SYSTEM, branch_label=self.branch_slug)
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info("=" * 60)
        logger.info(f"Starting Kai Co scrape for branch: {self.branch_name} ({self.branch_slug})")
        logger.info(f"Run ID: {run_logger.run_id}")
        logger.info("=" * 60)

        # 1. Fetch collections taxonomy
        self.fetch_collections()

        # 2. Fetch products
        products = self.fetch_all_products(max_products=max_products)
        if not products:
            logger.error("[scrape] No products retrieved. Aborting.")
            run_logger.finish(status="failed")
            return None

        # 3. Transform products into schema records
        all_records = []
        for p in products:
            recs = self.transform_product(p, observed_at)
            all_records.extend(recs)

        logger.info(f"[normalize] Transformed {len(products)} products into {len(all_records)} contract records.")
        run_logger.record_progress(products=len(all_records), categories=len(self.collections_map))

        if dry_run:
            logger.info("[dry-run] Dry run requested — printing first 2 sample records:")
            for s_rec in all_records[:2]:
                print(json.dumps(s_rec, indent=2, ensure_ascii=False))
            run_logger.finish(status="dry_run")
            return None

        # 4. Write to JSONL
        export_file = write_jsonl(
            records=all_records,
            branch_slug=self.branch_slug,
            retailer=RETAILER_SLUG,
            out_dir=out_dir or EXPORTS_DIR,
        )

        if not export_file:
            logger.error("[export] Failed to write JSONL export.")
            run_logger.finish(status="export_failed")
            return None

        logger.info(f"[export] JSONL export generated: {export_file.name}")

        # 5. Schema Validation
        if validate:
            logger.info("[audit] Auditing exported JSONL against contract schema...")
            val_res = validate_file(export_file)
            if not val_res["is_valid"]:
                logger.error(f"[audit] Validation failed with {val_res['errors_count']} errors!")
                run_logger.finish(status="validation_failed", export_path=str(export_file))
                push_notify(
                    message=f"Kai Co {self.branch_slug} validation failed with {val_res['errors_count']} errors.",
                    title="Kai Co Scraper Alert",
                    priority="high",
                    tags=["warning"],
                )
                return export_file
            logger.info("[audit] Validation PASSED: 100% compliant with PICO data contract.")

        run_logger.finish(status="success", export_path=str(export_file))
        push_notify(
            message=f"Kai Co {self.branch_slug} scraped successfully: {len(all_records)} products.",
            title="Kai Co Scraper Success",
            priority="default",
            tags=["white_check_mark"],
        )
        return export_file


def main():
    parser = argparse.ArgumentParser(description="Kai Co Supermarket Web Scraper")
    parser.add_argument("--branch", type=str, default=DEFAULT_STORE_SLUG, help="Branch slug (default: northwood)")
    parser.add_argument("--max-products", type=int, help="Limit number of products for testing")
    parser.add_argument("--dry-run", action="store_true", help="Perform scrape without writing export file")
    parser.add_argument("--no-validate", action="store_true", help="Skip schema audit after export")
    parser.add_argument("--output", type=Path, help="Custom output directory for JSONL exports")
    args = parser.parse_args()

    scraper = KaiCoScraper(branch_slug=args.branch)
    scraper.run(
        max_products=args.max_products,
        dry_run=args.dry_run,
        validate=not args.no_validate,
        out_dir=args.output,
    )


if __name__ == "__main__":
    main()
