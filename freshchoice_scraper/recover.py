"""Sitemap and taxonomy category recovery to bypass MyFoodLink 50-page result limits."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Optional
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from models import Branch, Product, PageResult
from network import Fetcher
from storage import write_jsonl, read_jsonl

logger = logging.getLogger(__name__)


def safe_category_url(raw_url: str, host: str) -> Optional[str]:
    """Canonicalize same-host category URL. Rejects external hosts, admin, and nested non-category paths."""
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.netloc and parsed.netloc != host:
        return None

    path = parsed.path
    # Must match single category level: /category/{slug}
    match = re.match(r"^/category/([a-zA-Z0-9\-_]+)/?$", path)
    if not match:
        return None

    clean_slug = match.group(1)
    return f"https://{host}/category/{clean_slug}"


def sitemap_categories(xml_data: bytes | str, host: str) -> set[str]:
    """Extract category URLs from sitemap XML strictly matching the same host."""
    categories = set()
    try:
        root = ET.fromstring(xml_data)
        # Handle default namespace
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = root.findall(".//ns:loc", ns) or root.findall(".//loc")
        for elem in locs:
            loc = (elem.text or "").strip()
            safe = safe_category_url(loc, host)
            if safe:
                categories.add(safe)
    except Exception as e:
        logger.warning(f"Error parsing sitemap XML: {e}")
    return categories


def rendered_children(html: str, host: str, parent_url: str) -> dict[str, str]:
    """Extract child category links filtering out primary nav, pagination, and external links."""
    soup = BeautifulSoup(html, "html.parser")
    children: dict[str, str] = {}

    # Strip primary nav and pagination elements
    for el in soup.find_all(class_=re.compile(r"fc-nav|mfl-pagination|pagination", re.I)):
        el.decompose()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        safe = safe_category_url(href, host)
        if safe and safe != parent_url:
            label = a.get_text(" ", strip=True) or safe.split("/")[-1].replace("-", " ").title()
            children[safe] = label

    return children


GLOBAL_NAV = {
    "bakery",
    "fruit-vegetables",
    "meat",
    "deli",
    "seafood",
    "dairy-eggs",
    "groceries",
    "snacks-1",
}


def snapshot_children(snap: dict, host: str, parent_url: str, allowed: set[str]) -> dict[str, str]:
    """Extract child category links from pre-rendered browser snapshot with host validation."""
    snap_host = snap.get("host")
    if snap_host and snap_host != host:
        raise ValueError(f"Cross-branch snapshot mismatch: snapshot host {snap_host} != expected {host}")

    children: dict[str, str] = {}
    links = snap.get("browser", {}).get("category_links", [])
    for item in links:
        path = item.get("path", "")
        safe = safe_category_url(path, host)
        slug = urlparse(safe).path.rstrip("/").rsplit("/", 1)[-1]
        if safe and safe in allowed and safe != parent_url and slug not in GLOBAL_NAV:
            children[safe] = item.get("label") or safe.split("/")[-1].replace("-", " ").title()

    return children


def reported_groceries(result: dict) -> int | None:
    for issue in result.get("issues", []):
        match = re.search(r"Groceries: extracted\s+\d+/(\d+)\s+unique", issue)
        if match:
            return int(match.group(1))
    return None


def grocery_keys(products: dict[str, Product]) -> set[str]:
    return {
        key
        for key, product in products.items()
        if any(
            path and any(label.casefold() == "groceries" for label in path)
            for path in product.category_paths
        )
    }


def index_product(products: dict[str, Product], url_index: dict[str, str], other: Product) -> bool:
    """Index or merge Product into products collection. Returns True if newly added, False if duplicate merged."""
    from runner import _add_product
    return _add_product(products, other, url_index)


async def recover_branch(
    branch_summary: dict[str, Any],
    input_dir: Path,
    output_dir: Path,
    fetcher: Fetcher,
    snapshot_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Recover child categories for one branch and union with baseline pilot output."""
    branch_id = branch_summary["branch_id"]
    branch_name = branch_summary.get("branch_name", branch_id.title())
    host = f"{branch_id}.store.freshchoice.co.nz"
    branch_url = f"https://{host}"
    output_dir.mkdir(parents=True, exist_ok=True)

    input_file = input_dir / f"{branch_id}.jsonl"
    existing_records = read_jsonl(input_file)
    original_count = len(existing_records)

    products: dict[str, Product] = {}
    url_index: dict[str, str] = {}

    for r in existing_records:
        p = Product.model_validate(r) if hasattr(Product, "model_validate") else Product(**r)
        index_product(products, url_index, p)

    initial_groceries = len(grocery_keys(products))
    target = reported_groceries(branch_summary)

    parent = f"{branch_url}/category/groceries"
    sitemap_resp = await fetcher.get(f"{branch_url}/sitemap.xml")
    allowed = sitemap_categories(sitemap_resp.content, host)
    if not allowed:
        raise RuntimeError("Sitemap returned no category URLs")

    snapshot = snapshot_dir / f"{branch_id}.json" if snapshot_dir else None
    if snapshot and snapshot.exists():
        children = snapshot_children(json.loads(snapshot.read_text(encoding="utf-8")), host, parent, allowed)
    else:
        children = {u: u.rstrip("/").split("/")[-1].replace("-", " ").title() for u in allowed if u != parent}

    from runner import Scraper, CrawlOptions
    scraper = Scraper(fetcher, CrawlOptions(output_dir=str(output_dir)))
    recovered_occurrences = 0
    recovered_new = 0

    branch_obj = Branch(id=branch_id, name=branch_name, url=branch_url)

    for url, label in children.items():
        page = 1
        while page <= 50:
            batch = await scraper._page(branch_obj, label, url, page)
            if not batch.products:
                break
            for prod in batch.products:
                if ["Groceries", label] not in prod.category_paths:
                    prod.category_paths.append(["Groceries", label])
                recovered_occurrences += 1
                if index_product(products, url_index, prod):
                    recovered_new += 1
            if batch.reported_count and len(products) >= batch.reported_count:
                break
            page += 1

    outfile = output_dir / f"{branch_id}.jsonl"
    write_jsonl(outfile, list(products.values()))

    grocery_total = len(grocery_keys(products))
    complete_groceries = bool(target and grocery_total >= target)

    return {
        "branch": branch_id,
        "status": "reconciled" if complete_groceries else "partial",
        "original_products": original_count,
        "merged_products": len(products),
        "new_products": recovered_new,
        "recovered_occurrences": recovered_occurrences,
        "previous_groceries_count": initial_groceries,
        "grocery_union_count": grocery_total,
        "previous_reported_groceries_total": target,
        "output_file": str(outfile),
    }


async def recover_run(args: argparse.Namespace) -> int:
    import copy
    import time
    import httpx
    from storage import write_json

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = input_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"branch_results": [], "elapsed_seconds": 0}
    branches = {b["branch_id"]: b for b in summary.get("branch_results", [])}
    ids = [x.strip() for x in args.branches.split(",") if x.strip()]
    if not ids or ids == ["all"]:
        ids = list(branches.keys())

    t0 = time.perf_counter()
    headers = {"User-Agent": "FreshChoiceAssessmentScraper/0.1 (+authorized-assessment)", "Accept-Language": "en-NZ,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        fetcher = Fetcher(client, rate_per_host=args.rate_per_host, per_host_concurrency=1, max_retries=2, max_requests=args.max_requests)
        sem = asyncio.Semaphore(args.branch_concurrency)

        async def run_one(bid):
            async with sem:
                b_data = branches.get(bid, {"branch_id": bid, "branch_name": bid.title()})
                return await recover_branch(
                    b_data,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    fetcher=fetcher,
                    snapshot_dir=Path(args.taxonomy_dir) if getattr(args, "taxonomy_dir", None) and Path(args.taxonomy_dir).exists() else None,
                )

        results = await asyncio.gather(*(run_one(bid) for bid in ids))

    elapsed = round(time.perf_counter() - t0, 3)
    recovery_summary = {
        "source": str(input_dir),
        "branches": results,
        "new_products": sum(x.get("new_products", 0) for x in results),
        "total_merged_products_selected": sum(x.get("merged_products", 0) for x in results),
        "elapsed_seconds": elapsed,
        "note": "Original pilot output untouched. These results do not resolve the Deli 404 or degraded text-only records.",
    }
    write_json(output_dir / "recovery_summary.json", recovery_summary)

    updated = copy.deepcopy(summary)
    updated["source_pilot_dir"] = str(input_dir)
    updated["recovery_elapsed_seconds"] = elapsed
    for new in results:
        match_br = next((b for b in updated.get("branch_results", []) if b.get("branch_id") == new["branch"]), None)
        if match_br:
            match_br["products"] = new["merged_products"]
            match_br["output_file"] = str(output_dir / f"{new['branch']}.jsonl")
    write_json(output_dir / "summary.json", updated)
    return 0 if all(b.get("status") == "reconciled" for b in results) else 1


def add_recover_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-dir", default="output-pilot")
    parser.add_argument("--output-dir", default="output-recovered")
    parser.add_argument("--branches", default="merivale,epsom,greenisland")
    parser.add_argument("--taxonomy-dir", default="output-taxonomy", help="Reuse per-branch v0.4 JSON snapshots when available")
    parser.add_argument("--branch-concurrency", type=int, default=2)
    parser.add_argument("--rate-per-host", type=float, default=0.5)
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--max-pages-per-category", type=int, default=50)
    parser.add_argument("--max-subcategories", type=int, default=80)
    parser.add_argument("--max-depth", type=int, default=2)
