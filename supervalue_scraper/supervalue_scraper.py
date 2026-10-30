"""SuperValue New Zealand Supermarket Scraper & Data Pipeline.

High-throughput crawler engineered against the PICO Scraper Data Contract.
Scrapes SuperValue branches (e.g. Milton) via category pagination and sitemap discovery,
extracting complete product observations with integer cents pricing, GS1 check digits,
isolated multibuy promotions, and detail-page enrichment.
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

from config import (
    BASE_URL,
    CATEGORIES,
    CATEGORY_ALIASES,
    GROCERIES_SUBCATEGORIES,
    CONCURRENCY,
    DEFAULT_BRANCHES,
    DEFAULT_HEADERS,
    EXPORTS_DIR,
    INITIAL_BACKOFF,
    LOGS_DIR,
    MAX_BACKOFF,
    MAX_RETRIES,
    PROXY_URL,
    REQUEST_DELAY_SEC,
    REQUEST_TIMEOUT,
    RETAILER,
    STORE_URL_TEMPLATE,
)
from catalog_branches import get_branches, get_branch_by_id
from jsonl_exporter import write_jsonl, to_cents
from models import Branch, Product, PageResult
from parsers import parse_listing, parse_detail_page, is_valid_gtin_checksum, clean_product_name

# Logger setup
logger = logging.getLogger("supervalue_scraper")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.setLevel(level)
    logger.addHandler(handler)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_handler = logging.FileHandler(LOGS_DIR / f"supervalue_scraper_{stamp}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)


class SuperValueScraper:
    """Async scraper engine for SuperValue Supermarkets New Zealand."""

    def __init__(
        self,
        branch: Branch,
        proxy_url: Optional[str] = None,
        concurrency: int = CONCURRENCY,
        enrich_details: bool = False,
        max_details: Optional[int] = None,
        max_pages: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        self.branch = branch
        self.proxy_url = proxy_url or PROXY_URL
        self.concurrency = concurrency
        self.enrich_details = enrich_details
        self.max_details = max_details
        self.max_pages = max_pages
        self.limit = limit

        self.products: dict[str, Product] = {}
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.client: Optional[httpx.AsyncClient] = None

    async def _init_client(self) -> None:
        proxies = self.proxy_url if self.proxy_url else None
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            proxy=proxies,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=self.concurrency * 2, max_keepalive_connections=self.concurrency),
        )

    async def _close_client(self) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _fetch_with_retry(self, url: str) -> Optional[str]:
        """Fetch URL with jittered exponential backoff and error recovery."""
        if not self.client:
            await self._init_client()

        backoff = INITIAL_BACKOFF
        for attempt in range(1, MAX_RETRIES + 1):
            async with self.semaphore:
                try:
                    await asyncio.sleep(REQUEST_DELAY_SEC)
                    resp = await self.client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    elif resp.status_code == 404:
                        return None
                    elif resp.status_code in (429, 502, 503, 504):
                        logger.warning(f"HTTP {resp.status_code} for {url} (Attempt {attempt}/{MAX_RETRIES})")
                    else:
                        logger.warning(f"Unexpected status {resp.status_code} for {url}")
                except Exception as e:
                    logger.warning(f"Network error on {url} (Attempt {attempt}/{MAX_RETRIES}): {e}")

            if attempt < MAX_RETRIES:
                sleep_time = min(MAX_BACKOFF, backoff * (1.5 + random.random()))
                await asyncio.sleep(sleep_time)
                backoff *= 2
        return None

    async def scrape_category(self, category_slug: str) -> None:
        """Paginate through a category until exhaust or max_pages."""
        page = 1
        empty_pages = 0
        cat_name = category_slug.replace("-", " ").title()

        logger.info(f"[{self.branch.id}] Crawling category: {category_slug}")
        while True:
            if self.max_pages and page > self.max_pages:
                break
            if self.limit and len(self.products) >= self.limit:
                break

            url = f"{self.branch.url}/category/{category_slug}?page={page}"
            html = await self._fetch_with_retry(url)
            if not html:
                break

            result = parse_listing(html, self.branch, [cat_name], url)
            new_in_page = 0
            for p in result.products:
                if p.product_id not in self.products:
                    self.products[p.product_id] = p
                    new_in_page += 1
                else:
                    # Merge category paths
                    existing = self.products[p.product_id]
                    if [cat_name] not in existing.category_paths:
                        existing.category_paths.append([cat_name])

            logger.debug(f"[{self.branch.id}] {category_slug} p.{page}: {len(result.products)} found ({new_in_page} new). Total: {len(self.products)}")

            if len(result.products) == 0:
                empty_pages += 1
                if empty_pages >= 2:
                    break
            else:
                empty_pages = 0

            # MyFoodLink default per-page is 48 products
            if len(result.products) < 48:
                break

            page += 1

    async def scrape_sitemap(self) -> None:
        """Crawl products discovered directly via store sitemap.xml."""
        sitemap_url = f"{self.branch.url}/sitemap.xml"
        logger.info(f"[{self.branch.id}] Fetching store sitemap: {sitemap_url}")
        xml_data = await self._fetch_with_retry(sitemap_url)
        if not xml_data:
            logger.warning(f"[{self.branch.id}] Sitemap unavailable; using category pagination fallback")
            return

        category_urls = re.findall(rf"<loc>({re.escape(self.branch.url)}/category/[^<]+)</loc>", xml_data)
        logger.info(f"[{self.branch.id}] Sitemap yielded {len(category_urls)} category endpoints")

        # Prioritize top-level and broad categories
        unique_slugs = []
        for u in category_urls:
            slug = u.split("/category/")[-1].strip()
            if slug and slug not in unique_slugs:
                unique_slugs.append(slug)

        for slug in unique_slugs:
            if self.limit and len(self.products) >= self.limit:
                break
            await self.scrape_category(slug)

    async def enrich_product_details(self) -> None:
        """Harvest Brand, GTIN, and complete Breadcrumbs from product detail pages."""
        if not self.products:
            return

        to_enrich = list(self.products.values())
        if self.max_details:
            to_enrich = to_enrich[: self.max_details]

        logger.info(f"[{self.branch.id}] Enriching {len(to_enrich)} products with detail page metadata...")
        enriched_count = 0

        for idx, p in enumerate(to_enrich, start=1):
            if not p.product_url:
                continue
            html = await self._fetch_with_retry(p.product_url)
            if not html:
                continue

            details = parse_detail_page(html, self.branch.url)
            if details.get("brand") and not p.brand:
                p.brand = details["brand"]
            if details.get("description") and not p.description:
                p.description = details["description"]
            if details.get("gtin") and not p.gtin:
                p.gtin = details["gtin"]
            if details.get("sku") and not p.sku:
                p.sku = details["sku"]
            if details.get("category_path"):
                p.category_paths = [[s.strip() for s in details["category_path"].split(">")]]

            enriched_count += 1
            if idx % 50 == 0 or idx == len(to_enrich):
                logger.info(f"[{self.branch.id}] Enriched {idx}/{len(to_enrich)} products ({enriched_count} updated)")

    async def run(self, use_sitemap: bool = True) -> list[dict[str, Any]]:
        """Execute full branch scraping lifecycle and export JSONL conforming to contract."""
        t0 = time.time()
        logger.info(f"=== Starting scrape for SuperValue branch: {self.branch.name} ({self.branch.id}) ===")

        try:
            await self._init_client()

            # 1. First crawl specials if available
            await self.scrape_category("specials")

            # 2. Crawl sitemap categories or standard category list
            if use_sitemap:
                await self.scrape_sitemap()
            else:
                for cat in CATEGORIES:
                    if self.limit and len(self.products) >= self.limit:
                        break
                    await self.scrape_category(cat)

            # 3. If groceries has reached ceiling, crawl recovery subcategories
            for subcat in GROCERIES_SUBCATEGORIES:
                if self.limit and len(self.products) >= self.limit:
                    break
                await self.scrape_category(subcat)

            # 4. Optional detail page enrichment
            if self.enrich_details:
                await self.enrich_product_details()

        finally:
            await self._close_client()

        # Convert to strict PICO Scraper Data Contract
        contract_records: list[dict[str, Any]] = []
        for p in self.products.values():
            rec = p.to_pico_contract()
            contract_records.append(rec)

        duration = time.time() - t0
        logger.info(
            f"=== Finished scrape for {self.branch.name}: {len(contract_records):,} products "
            f"extracted in {duration:.1f}s ==="
        )
        return contract_records


async def run_pipeline(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)

    # Resolve target branches
    if args.all_branches:
        target_branches = get_branches(online_only=True)
    elif args.branches:
        slugs = [s.strip() for s in args.branches.split(",") if s.strip()]
        target_branches = [get_branch_by_id(s) for s in slugs if get_branch_by_id(s)]
    else:
        target_branches = [get_branch_by_id(s) for s in DEFAULT_BRANCHES if get_branch_by_id(s)]

    if not target_branches:
        logger.error("No valid SuperValue branches resolved to scrape.")
        return 1

    logger.info(f"Target SuperValue branches ({len(target_branches)}): {[b.id for b in target_branches]}")

    for branch in target_branches:
        if not branch.shopping_online:
            logger.warning(f"Branch '{branch.id}' ({branch.name}) does not have online ordering enabled. Skipping.")
            continue

        scraper = SuperValueScraper(
            branch=branch,
            proxy_url=args.proxy,
            concurrency=args.concurrency,
            enrich_details=args.enrich_details,
            max_details=args.max_details,
            max_pages=args.max_pages,
            limit=args.limit,
        )

        records = await scraper.run(use_sitemap=not args.no_sitemap)

        if not args.dry_run and records:
            out_path = write_jsonl(records, branch_label=branch.id, retailer=RETAILER)
            logger.info(f"Export completed: {out_path}")
        elif args.dry_run:
            logger.info(f"[DRY-RUN] Extracted {len(records)} products (no file written)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="SuperValue NZ Supermarket Web Scraper")
    parser.add_argument("--branches", type=str, help="Comma-separated branch slugs (e.g. milton)")
    parser.add_argument("--all-branches", action="store_true", help="Scrape all active online branches")
    parser.add_argument("--enrich-details", action="store_true", help="Enrich items with Brand and GTIN from line detail pages")
    parser.add_argument("--max-details", type=int, help="Cap number of detail pages to enrich")
    parser.add_argument("--max-pages", type=int, help="Maximum pages per category")
    parser.add_argument("--limit", type=int, help="Total products ceiling for pilot/smoke tests")
    parser.add_argument("--no-sitemap", action="store_true", help="Disable sitemap discovery and use static category list")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help="Async request concurrency")
    parser.add_argument("--proxy", type=str, help="HTTP/HTTPS proxy URL override")
    parser.add_argument("--dry-run", action="store_true", help="Scrape without writing JSONL to disk")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    code = asyncio.run(run_pipeline(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
