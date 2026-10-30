"""FreshChoice Supermarket Scraper — Production Build.

Conforms strictly to PICO Scraper Data Contract and Woolworths / PAK'nSAVE benchmark maturity:
1. Barcode Accuracy: Strict GTIN format validation (8, 12, 13, 14 digits) and GS1 modulo-10 checksums.
   Produce PLUs (4-5 digits) isolated from global barcode space.
2. Stock Availability: True independent stock availability evaluation.
3. Promotions Verification: Complete separation of individual selling price vs multibuy bundle prices.
4. Groceries Taxonomy Recovery: Recovers subcategories beyond MyFoodLink 50-page (2,400 items) cap.
5. Multi-Branch Workflow: Exports independent JSONL file per branch per run.
6. Rate Pacing & Retries: Exponential backoff on HTTP 429, 5xx, and connection drops.
"""
from __future__ import annotations

import argparse
import asyncio
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

from catalog_branches import list_branches, get_branch
from config import (
    BASE_URL,
    STORE_URL_TEMPLATE,
    CATEGORY_PATH_TEMPLATE,
    PRODUCT_DETAIL_PATH_TEMPLATE,
    DEFAULT_BRANCHES,
    CATEGORIES,
    CATEGORY_ALIASES,
    GROCERIES_RECOVERY_SUBCATEGORIES,
    ETHNIC_DEPTH2_SUBCATEGORIES,
    USER_AGENT,
    EXTRA_HEADERS,
    REQUEST_TIMEOUT_SECONDS,
    PER_HOST_CONCURRENCY,
    BRANCH_CONCURRENCY,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    RETRY_ATTEMPTS,
    BACKOFF_FACTOR,
    EXPORTS_DIR,
    LOGS_DIR,
)
from jsonl_exporter import write_jsonl, to_cents, clean_record, _slug
from parsers import parse_product_card, parse_product_detail_page, is_valid_gtin_checksum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("freshchoice_scraper")


class FreshChoiceScraper:
    def __init__(
        self,
        branch_id: str,
        enrich_details: bool = False,
        max_details: Optional[int] = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ):
        self.branch_info = get_branch(branch_id)
        if not self.branch_info:
            raise ValueError(f"Unknown branch identifier: {branch_id}")

        self.branch_id = self.branch_info["id"]
        self.branch_name = self.branch_info["name"]
        self.base_store_url = STORE_URL_TEMPLATE.format(branch=self.branch_id)
        self.enrich_details = enrich_details
        self.max_details = max_details
        self.timeout = timeout

        self.client: Optional[httpx.AsyncClient] = None
        self.rate_limiter = asyncio.Semaphore(PER_HOST_CONCURRENCY)

    async def _init_client(self) -> None:
        headers = dict(EXTRA_HEADERS)
        headers["User-Agent"] = USER_AGENT
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    async def _close_client(self) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _fetch_html(self, url: str) -> Optional[str]:
        """Fetch URL with rate limiting and exponential backoff retry."""
        if not self.client:
            await self._init_client()

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            async with self.rate_limiter:
                # Polite request delay
                delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                await asyncio.sleep(delay)

                try:
                    resp = await self.client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    elif resp.status_code == 404:
                        logger.debug(f"[404] Resource not found: {url}")
                        return None
                    elif resp.status_code in (429, 500, 502, 503, 504):
                        backoff = (BACKOFF_FACTOR ** attempt) + random.uniform(0.5, 1.5)
                        logger.warning(f"[HTTP {resp.status_code}] Retrying {url} in {backoff:.2f}s (attempt {attempt}/{RETRY_ATTEMPTS})")
                        await asyncio.sleep(backoff)
                    else:
                        logger.warning(f"[HTTP {resp.status_code}] Unexpected status for {url}")
                        return None
                except (httpx.RequestError, httpx.TimeoutException) as e:
                    backoff = (BACKOFF_FACTOR ** attempt) + random.uniform(0.5, 1.5)
                    logger.warning(f"[NetError] {e} on {url}, retrying in {backoff:.2f}s")
                    await asyncio.sleep(backoff)

        logger.error(f"[Failed] All {RETRY_ATTEMPTS} attempts failed for: {url}")
        return None

    async def scrape_category(self, category_slug: str, category_name: Optional[str] = None) -> list[dict[str, Any]]:
        """Scrape all paginated pages of a category."""
        display_name = category_name or category_slug.replace("-", " ").title()
        products_by_id: dict[str, dict[str, Any]] = {}
        page = 1
        consecutive_empty = 0

        logger.info(f"[{self.branch_id}] Scraping category: {display_name} (/category/{category_slug})")

        while True:
            url = f"{self.base_store_url}/category/{category_slug}?page={page}"
            html = await self._fetch_html(url)
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            # MyFoodLink product cards
            cards = soup.find_all(
                ["div", "article", "li"],
                class_=re.compile(r"product|line-item|card", re.I),
            )

            # If no class matched, find any elements containing /lines/
            if not cards:
                line_links = soup.find_all("a", href=re.compile(r"/lines/"))
                cards = [l.parent for l in line_links]

            page_products = 0
            for card in cards:
                parsed = parse_product_card(card, self.branch_id, category_path=display_name)
                if parsed and parsed.get("source_product_id"):
                    pid = parsed["source_product_id"]
                    if pid not in products_by_id:
                        products_by_id[pid] = parsed
                        page_products += 1

            if page_products == 0:
                consecutive_empty += 1
                if consecutive_empty >= 1:
                    break
            else:
                consecutive_empty = 0

            # MyFoodLink standard pagination limit check
            if page >= 50:
                logger.info(f"[{self.branch_id}] Reached 50-page cap on {category_slug} ({len(products_by_id)} items)")
                break

            page += 1

        logger.info(f"[{self.branch_id}] Finished {display_name}: {len(products_by_id)} unique products across {page} pages")
        return list(products_by_id.values())

    async def recover_groceries(self, existing_products: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Recover subcategories under Groceries to beat the 50-page (2,400 items) ceiling."""
        logger.info(f"[{self.branch_id}] Initiating Groceries taxonomy recovery...")
        recovered_count = 0

        # Subcategories
        for sub_slug in GROCERIES_RECOVERY_SUBCATEGORIES:
            sub_name = f"Groceries > {sub_slug.replace('-', ' ').title()}"
            sub_prods = await self.scrape_category(sub_slug, category_name=sub_name)
            for p in sub_prods:
                pid = p["source_product_id"]
                if pid not in existing_products:
                    existing_products[pid] = p
                    recovered_count += 1

        # Depth-2 Ethnic subcategories
        for eth_slug in ETHNIC_DEPTH2_SUBCATEGORIES:
            eth_name = f"Groceries > Ethnic, Gourmet Food > {eth_slug.replace('-', ' ').title()}"
            eth_prods = await self.scrape_category(eth_slug, category_name=eth_name)
            for p in eth_prods:
                pid = p["source_product_id"]
                if pid not in existing_products:
                    existing_products[pid] = p
                    recovered_count += 1

        logger.info(f"[{self.branch_id}] Groceries recovery completed: +{recovered_count} new products recovered")
        return existing_products

    async def enrich_product_details(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Optionally visit detail pages (/lines/{slug}) to harvest GTIN barcodes, brand, and descriptions."""
        to_enrich = products if self.max_details is None else products[:self.max_details]
        logger.info(f"[{self.branch_id}] Enriching {len(to_enrich)} products with detail pages...")

        for idx, p in enumerate(to_enrich, start=1):
            url = p.get("product_url")
            if not url:
                continue
            html = await self._fetch_html(url)
            if html:
                enriched = parse_product_detail_page(html, p)
                p.update(enriched)
            if idx % 100 == 0 or idx == len(to_enrich):
                logger.info(f"[{self.branch_id}] Enriched {idx}/{len(to_enrich)} products")

        return products

    async def scrape_branch(self) -> dict[str, Any]:
        """Perform full branch scrape and export JSONL conforming to data contract."""
        t0 = time.time()
        logger.info(f"=== STARTING SCRAPE: {self.branch_name} ({self.branch_id}) ===")

        all_products: dict[str, dict[str, Any]] = {}

        # 1. Scrape standard categories
        for cat_slug in CATEGORIES:
            # Handle aliases for delicate routes like Deli 404
            aliases = CATEGORY_ALIASES.get(cat_slug, [cat_slug])
            cat_products = []
            for alias in aliases:
                cat_products = await self.scrape_category(alias)
                if cat_products:
                    break

            for p in cat_products:
                pid = p["source_product_id"]
                if pid not in all_products:
                    all_products[pid] = p

        # 2. Recover Groceries taxonomy beyond 50-page cap
        all_products = await self.recover_groceries(all_products)

        final_records = list(all_products.values())

        # 3. Optional detail enrichment
        if self.enrich_details:
            final_records = await self.enrich_product_details(final_records)

        # 4. Export JSONL
        out_path = write_jsonl(
            records=final_records,
            branch_label=self.branch_id,
            retailer="freshchoice",
            out_dir=EXPORTS_DIR,
        )

        elapsed = time.time() - t0
        logger.info(f"=== SCRAPE COMPLETE: {self.branch_name} | {len(final_records):,} items in {elapsed:.1f}s ===")
        if out_path:
            logger.info(f"Export saved to: {out_path}")

        await self._close_client()
        return {
            "branch_id": self.branch_id,
            "branch_name": self.branch_name,
            "total_products": len(final_records),
            "export_file": str(out_path) if out_path else None,
            "elapsed_seconds": round(elapsed, 2),
        }


async def run_scraper(
    branches: list[str],
    enrich_details: bool = False,
    max_details: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Run scraper across selected branches."""
    results = []
    for branch_id in branches:
        scraper = FreshChoiceScraper(
            branch_id=branch_id,
            enrich_details=enrich_details,
            max_details=max_details,
        )
        res = await scraper.scrape_branch()
        results.append(res)
    return results


def main():
    parser = argparse.ArgumentParser(description="FreshChoice NZ Supermarket Scraper")
    parser.add_argument(
        "--branches",
        type=str,
        default=",".join(DEFAULT_BRANCHES),
        help="Comma-separated branch slugs (e.g. merivale,epsom,greenisland)",
    )
    parser.add_argument(
        "--all-branches",
        action="store_true",
        help="Scrape all discovered FreshChoice branches with online capability",
    )
    parser.add_argument(
        "--enrich-details",
        action="store_true",
        help="Visit product detail pages to extract barcodes and brand",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=None,
        help="Limit number of detail pages to enrich per branch",
    )

    args = parser.parse_args()

    if args.all_branches:
        active_stores = list_branches(online_only=True)
        target_branches = [b["id"] for b in active_stores]
    else:
        target_branches = [b.strip() for b in args.branches.split(",") if b.strip()]

    logger.info(f"Target FreshChoice Branches ({len(target_branches)}): {target_branches}")
    asyncio.run(run_scraper(
        branches=target_branches,
        enrich_details=args.enrich_details,
        max_details=args.max_details,
    ))


if __name__ == "__main__":
    main()
