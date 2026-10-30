"""Farro Fresh Supermarket production scraper complying with the Pico contract.

Fetches the complete catalog from Farro Fresh's API, parses each product into the
strict client contract format, and exports one JSONL file per branch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Generator, Optional

import httpx

from catalog_branches import KNOWN_FARRO_STORES, get_known_branches, resolve_branch, slugify
from config import (
    BASE_URL,
    BATCH_SIZE,
    DEFAULT_HEADERS,
    DELAY_BETWEEN_REQUESTS,
    EXPORTS_DIR,
    LOYALTY_PROGRAM_CODE,
    MAX_RETRIES,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    RETAILER_SLUG,
)
from jsonl_exporter import export_filename, write_jsonl
from normalize import (
    extract_barcode,
    extract_clean_name,
    extract_size,
    format_category_path,
    infer_brand,
)
from run_log import RunLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("farro_scraper")


def make_client() -> httpx.Client:
    """Create a configured HTTPX client session."""
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )


def fetch_page(client: httpx.Client, skip: int, take: int = PAGE_SIZE) -> dict[str, Any]:
    """Fetch a single page of products from Farro's Search API with retries."""
    payload = {
        "searchPattern": "",
        "sortBy": "Relevance",
        "skip": skip,
        "take": take,
        "filters": [],
        "appliedSearchAggregationFilters": [],
    }

    url = f"{BASE_URL}/api/ViewModel/Search/Search"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "HTTP %d at skip=%d (attempt %d/%d): %s",
                resp.status_code, skip, attempt, MAX_RETRIES, resp.text[:200]
            )
        except Exception as exc:
            logger.warning("Request failed at skip=%d (attempt %d/%d): %s", skip, attempt, MAX_RETRIES, exc)

        backoff = 1.0 * (1.5 ** attempt)
        time.sleep(backoff)

    raise RuntimeError(f"Failed to fetch products page at skip={skip} after {MAX_RETRIES} attempts.")


def parse_product(item: dict[str, Any], observed_at: str) -> Optional[dict[str, Any]]:
    """Transform Farro API product dict into Pico contract format."""
    source_id = str(item.get("id") or "").strip()
    sku = str(item.get("productSKU") or "").strip()
    raw_name = str(item.get("title") or "").strip()

    if not source_id or not raw_name:
        return None

    # Normalization
    size = extract_size(raw_name)
    brand = infer_brand(raw_name, item.get("brand"))
    clean_name = extract_clean_name(raw_name, brand=brand, size=size)
    category_path = format_category_path(item.get("categories"))

    # Barcode
    stamp_img = item.get("productStampImageUrl")
    barcode = extract_barcode(stamp_img, item)

    # Pricing
    sell_price = item.get("sellPrice")
    if sell_price is None or sell_price == "":
        return None
    try:
        current_price_cents = int(round(float(sell_price) * 100))
    except (TypeError, ValueError):
        return None

    # Comparison Price (Was / Original)
    orig_price = item.get("originalPrice")
    comparison_price_cents = None
    is_on_sale = bool(item.get("onSale"))

    if orig_price is not None and orig_price != "":
        try:
            orig_cents = int(round(float(orig_price) * 100))
            if is_on_sale or orig_cents > current_price_cents:
                comparison_price_cents = orig_cents
        except (TypeError, ValueError):
            pass

    # Unit Price
    unit_price_cents = None
    per_unit_price = item.get("perUnitSellPrice")
    if per_unit_price is not None and per_unit_price != "":
        try:
            val = float(per_unit_price)
            if val > 0:
                unit_price_cents = int(round(val * 100))
        except (TypeError, ValueError):
            pass

    unit_label = (item.get("perUnitKind") or "").strip() or None

    # Stock Status
    avail = str(item.get("availability") or "").lower()
    avail_state = str(item.get("availabilityState") or "").lower()
    if "available" in avail or "availableonline" in avail_state:
        stock_status = "in_stock"
    else:
        stock_status = "out_of_stock"

    # Promotions & Loyalty
    is_loyalty = bool(item.get("isLoyaltyCardSpecial"))
    promo_text = None
    promo_type = None
    card_required = None
    required_loyalty = None
    promo_metadata = None

    if is_loyalty:
        promo_type = "member_price"
        promo_text = "Friends of Farro Member Deal"
        card_required = True
        required_loyalty = LOYALTY_PROGRAM_CODE
        promo_metadata = {
            "savings": item.get("savings"),
            "loyalty_program": LOYALTY_PROGRAM_CODE,
        }
    elif is_on_sale or comparison_price_cents is not None:
        promo_type = "special"
        savings = item.get("savings") or ""
        promo_text = f"Save {savings}".strip() if savings and savings != "$0.00" else "Special"
        promo_metadata = {
            "savings": savings,
            "on_sale": True,
        }

    # Product URL
    title_slug = slugify(raw_name)
    product_url = f"{BASE_URL}/shop/product/{source_id}?name={title_slug}"

    # Image URL
    image_url = stamp_img or (item.get("additionalImageUrls") or [None])[0]

    # Raw row for rich audit/enrichment
    raw_row = {
        "description": item.get("description"),
        "ingredients": item.get("ingredients"),
        "country_of_origin": item.get("countryOfOrigin"),
        "fulfilment_type": item.get("fulfilmentType"),
        "categories": item.get("categories"),
        "unit_of_measure": item.get("unitOfMeasure"),
        "weight": item.get("weight"),
        "is_organic": item.get("isOrganic"),
        "is_gluten_free": item.get("isGlutenFree"),
        "is_plant_based": item.get("isPlantBased"),
        "is_vegetarian": item.get("isVegetarian"),
        "is_nz_made": item.get("isNZMade"),
        "raw_brand": item.get("brand"),
    }

    record = {
        "source_product_id": source_id,
        "retailer_sku": sku or source_id,
        "barcode": barcode,
        "raw_name": raw_name,
        "clean_name": clean_name,
        "brand": brand,
        "category_path": category_path,
        "size": size,
        "current_price_cents": current_price_cents,
        "comparison_price_cents": comparison_price_cents,
        "unit_price_cents": unit_price_cents,
        "unit_label": unit_label,
        "stock_status": stock_status,
        "promo_text": promo_text,
        "promo_type": promo_type,
        "card_required": card_required,
        "required_loyalty_program_code": required_loyalty,
        "source_promotion_id": None,
        "multibuy_quantity": None,
        "multibuy_price_cents": None,
        "promo_starts_at": None,
        "promo_ends_at": None,
        "promo_metadata": promo_metadata,
        "product_url": product_url,
        "image_url": image_url,
        "observed_at": observed_at,
        "raw_row": raw_row,
    }

    return record


def scrape_farro_catalog(limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Scrape the full Farro catalog with deduplication and contract validation."""
    logger.info("Initializing Farro Fresh catalog scrape...")
    client = make_client()
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Initial probe to determine total elements
    first_page = fetch_page(client, skip=0, take=PAGE_SIZE)
    total_elements = first_page.get("totalElements") or 0
    logger.info("Reported total catalog elements: %d", total_elements)

    if limit and limit < total_elements:
        total_to_fetch = limit
        logger.info("Limit specified: fetching up to %d products", total_to_fetch)
    else:
        total_to_fetch = total_elements

    all_products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    skip = 0
    while skip < total_to_fetch:
        take = min(PAGE_SIZE, total_to_fetch - skip)
        logger.info("Fetching batch [skip=%d, take=%d] (%.1f%%)...", skip, take, (skip / total_to_fetch) * 100)

        data = fetch_page(client, skip=skip, take=take)
        items = data.get("content") or []
        if not items:
            logger.info("No further items returned at skip=%d. Finished pagination.", skip)
            break

        for item in items:
            rec = parse_product(item, observed_at)
            if rec and rec["source_product_id"] not in seen_ids:
                seen_ids.add(rec["source_product_id"])
                all_products.append(rec)

        skip += len(items)
        if len(items) < take:
            break

        time.sleep(DELAY_BETWEEN_REQUESTS)

    logger.info(
        "Successfully scraped and normalized %d unique Farro Fresh products.",
        len(all_products),
    )
    return all_products


def run_scrape(
    branch_slug: str = "farro-grey-lynn",
    all_branches: bool = False,
    limit: Optional[int] = None,
    out_dir: Optional[Path] = None,
) -> list[Path]:
    """Run Farro scraper for one or all branches and write JSONL files."""
    run_log = RunLogger("farro_scraper", branch_label="all" if all_branches else branch_slug)
    written_files: list[Path] = []

    try:
        products = scrape_farro_catalog(limit=limit)
        run_log.record_stat("products_scraped", len(products))
        run_log.record_stat(
            "specials_count",
            sum(1 for p in products if p.get("promo_type") == "special"),
        )
        run_log.record_stat(
            "member_prices_count",
            sum(1 for p in products if p.get("promo_type") == "member_price"),
        )
        run_log.record_stat(
            "barcodes_count",
            sum(1 for p in products if p.get("barcode")),
        )

        target_branches = (
            get_known_branches() if all_branches else [resolve_branch(branch_slug) or {"slug": branch_slug}]
        )

        now = datetime.now(timezone.utc)
        for b in target_branches:
            slug = b.get("slug") or branch_slug
            logger.info("Writing JSONL export for branch '%s'...", slug)
            path = write_jsonl(products, branch_label=slug, out_dir=out_dir, when=now)
            if path:
                written_files.append(path)

        run_log.record_stat("files_exported", len(written_files))
        run_log.finish("success")
        logger.info("Scrape completed successfully. %d export files generated.", len(written_files))
        return written_files

    except Exception as exc:
        logger.exception("Scrape run failed: %s", exc)
        run_log.add_error(str(exc))
        run_log.finish("error")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Farro Fresh Supermarket production scraper")
    parser.add_argument(
        "--branch",
        default="farro-grey-lynn",
        help="Target branch slug (e.g. farro-grey-lynn, farro-newmarket, or 'all')",
    )
    parser.add_argument("--all-branches", action="store_true", help="Export JSONL for all 8 Farro branches")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of items for testing")
    parser.add_argument("--output-dir", type=Path, default=EXPORTS_DIR, help="Directory to save JSONL exports")
    args = parser.parse_args()

    all_b = args.all_branches or args.branch.lower() == "all"
    slug = "all" if all_b else args.branch

    run_scrape(
        branch_slug=slug,
        all_branches=all_b,
        limit=args.limit,
        out_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
