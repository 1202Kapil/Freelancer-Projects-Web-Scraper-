"""Runner orchestration for category and branch catalogue collection."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from discovery import parse_branches, parse_categories
from models import Branch, Product, PageResult
from network import Fetcher
from parsers import parse_listing
from storage import write_json, write_jsonl

logger = logging.getLogger(__name__)


@dataclass
class CrawlOptions:
    output_dir: Any = "output"
    branch_names: list[str] = field(default_factory=list)
    category_names: Optional[list[str]] = None
    branch_concurrency: int = 1
    max_categories: int = 0
    max_pages_per_category: Optional[int] = None
    rate_per_host: float = 1.0
    include_supervalue: bool = False
    mode: str = "html"
    api_config: Any = None
    enrich_details: bool = False
    max_details: int = 0


@dataclass
class BranchResult:
    branch_id: str
    branch_name: str
    status: str  # 'complete', 'partial', 'failed'
    products: int
    duplicates: int
    categories_discovered: int
    categories_scraped: int
    pages_fetched: int
    requests_failed: int = 0
    issues: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class Summary:
    branches_discovered: int
    branches_selected: int
    branches_completed: int
    branches_partial: int
    branches_failed: int
    total_unique_products: int
    total_duplicate_occurrences: int
    elapsed_seconds: float
    branch_results: list[BranchResult]


def _add_product(products: dict[str, Product], product: Product,
                 url_index: dict[str, str] | None = None) -> bool:
    from urllib.parse import urlparse
    from normalize import merge_product
    path = urlparse(product.product_url).path.rstrip("/") if product.product_url else None
    key = product.product_key if product.product_key in products else None
    if key is None and path:
        if url_index is not None:
            key = url_index.get(path)
        else:
            key = next((k for k, p in products.items() if p.product_url and
                        urlparse(p.product_url).path.rstrip("/") == path), None)
    if key is not None:
        existing = products[key]
        merge_product(existing, product)
        if existing.product_key != key:
            del products[key]
            products[existing.product_key] = existing
        if path and url_index is not None:
            url_index[path] = existing.product_key
        return False
    products[product.product_key] = product
    if path and url_index is not None:
        url_index[path] = product.product_key
    return True


class Scraper:
    def __init__(self, fetcher: Fetcher, opts: Optional[CrawlOptions] = None):
        self.fetcher = fetcher
        self.opts = opts or CrawlOptions(output_dir="exports")

    async def _page(self, branch: Any, category: str, url: str, page: int) -> PageResult:
        """Fetch and parse one category page."""
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}page={page}"
        try:
            resp = await self.fetcher.get(page_url)
            if resp.status_code != 200:
                if resp.status_code == 404 and page > 1:
                    return PageResult(products=[])
                return PageResult(products=[], issues=[f"HTTP {resp.status_code} for {page_url}"])

            br_obj = branch if isinstance(branch, Branch) else Branch(id=str(branch), name=str(branch).title(), url=f"https://{branch}.store.freshchoice.co.nz")
            return parse_listing(resp.text, br_obj, [category], page_url)
        except Exception as e:
            return PageResult(products=[], issues=[f"Exception fetching {page_url}: {e}"])

    async def scrape_branch(self, branch: Branch) -> BranchResult:
        """Scrape catalogue for single branch."""
        t0 = time.time()
        out_dir = Path(self.opts.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        browse_url = f"{branch.url.rstrip('/')}/browse"
        categories = {}
        try:
            resp = await self.fetcher.get(browse_url)
            if resp.status_code == 200:
                categories = parse_categories(resp.text, branch.url)
        except Exception as e:
            logger.warning(f"Could not load categories from {browse_url}: {e}")

        if not categories:
            from config import CATEGORIES
            categories = {c.replace("-", " ").title(): f"{branch.url.rstrip('/')}/category/{c}" for c in CATEGORIES}

        cats_discovered = len(categories)
        issues = []

        if self.opts.category_names:
            categories = {k: v for k, v in categories.items() if k in self.opts.category_names}
            issues.append(f"diagnostic category filter applied: {list(categories.keys())}")

        cats_scraped = len(categories)
        products_by_key: dict[str, Product] = {}
        duplicate_count = 0
        pages_fetched = 0
        requests_failed = 0

        for cat_name, cat_url in categories.items():
            page = 1
            cat_items = 0
            while True:
                if self.opts.max_pages_per_category and page > self.opts.max_pages_per_category:
                    issues.append(f"Category {cat_name} limited to {self.opts.max_pages_per_category} pages")
                    break

                res = await self._page(branch, cat_name, cat_url, page)
                pages_fetched += 1
                if res.issues:
                    issues.extend(res.issues)

                if not res.products:
                    break

                new_items_on_page = 0
                for p in res.products:
                    key = p.product_key or p.product_id or f"name:{p.name}"
                    if key in products_by_key:
                        duplicate_count += 1
                        for cp in p.category_paths:
                            if cp not in products_by_key[key].category_paths:
                                products_by_key[key].category_paths.append(cp)
                    else:
                        products_by_key[key] = p
                        cat_items += 1
                        new_items_on_page += 1

                # If an entire page had 0 new items, break to prevent infinite loops
                if new_items_on_page == 0:
                    break

                # If reported category count is reached, complete this category
                if res.reported_count and cat_items >= res.reported_count:
                    break

                page += 1

        elapsed = time.time() - t0
        all_products = list(products_by_key.values())

        is_partial = bool(
            self.opts.category_names
            or any("limited" in i or "diagnostic" in i for i in issues)
        )
        status = "partial" if is_partial else "complete"

        out_file = out_dir / f"{branch.id}.jsonl"
        write_jsonl(out_file, all_products)

        return BranchResult(
            branch_id=branch.id,
            branch_name=branch.name,
            status=status,
            products=len(all_products),
            duplicates=duplicate_count,
            categories_discovered=cats_discovered,
            categories_scraped=cats_scraped,
            pages_fetched=pages_fetched,
            requests_failed=requests_failed,
            issues=issues,
            elapsed_seconds=round(elapsed, 2),
        )

    async def run(self) -> Summary:
        """Run full scraper over discovered or selected branches."""
        t0 = time.time()
        out_dir = Path(self.opts.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        branches = []
        try:
            resp = await self.fetcher.get("https://store.freshchoice.co.nz/")
            if resp.status_code == 200:
                branches = parse_branches(resp.text)
        except Exception as e:
            logger.warning(f"Store selector discovery failed: {e}")

        if not branches:
            from catalog_branches import list_branches
            branches = [Branch(id=b["id"], name=b["name"], url=b["url"]) for b in list_branches()]

        discovered_count = len(branches)
        if self.opts.branch_names:
            branches = [b for b in branches if b.id in self.opts.branch_names]

        selected_count = len(branches)
        branch_results = []
        for b in branches:
            res = await self.scrape_branch(b)
            branch_results.append(res)

        elapsed = time.time() - t0
        completed = sum(1 for r in branch_results if r.status == "complete")
        partial = sum(1 for r in branch_results if r.status == "partial")
        failed = sum(1 for r in branch_results if r.status == "failed")
        total_unique = sum(r.products for r in branch_results)
        total_dups = sum(r.duplicates for r in branch_results)

        summary = Summary(
            branches_discovered=discovered_count,
            branches_selected=selected_count,
            branches_completed=completed,
            branches_partial=partial,
            branches_failed=failed,
            total_unique_products=total_unique,
            total_duplicate_occurrences=total_dups,
            elapsed_seconds=round(elapsed, 2),
            branch_results=branch_results,
        )

        summary_dict = {
            "elapsed_seconds": summary.elapsed_seconds,
            "branches_discovered": summary.branches_discovered,
            "branches_selected": summary.branches_selected,
            "branches_completed": summary.branches_completed,
            "branches_partial": summary.branches_partial,
            "branches_failed": summary.branches_failed,
            "total_unique_products": summary.total_unique_products,
            "total_duplicate_occurrences": summary.total_duplicate_occurrences,
            "branch_results": [r.__dict__ for r in branch_results],
        }
        write_json(out_dir / "summary.json", summary_dict)
        return summary
