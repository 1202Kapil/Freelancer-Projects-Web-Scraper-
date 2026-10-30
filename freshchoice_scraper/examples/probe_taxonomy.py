"""Discover public category URLs from FreshChoice sitemap and hydrated DOM.

Diagnostics only: it neither purchases items nor enumerates guessed API URLs.
Run from project root: python examples/probe_taxonomy.py --branch merivale --browser
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from network import Fetcher

HEADERS = {
    "User-Agent": "FreshChoiceAssessmentScraper/0.1 (+authorized-assessment)",
    "Accept-Language": "en-NZ,en;q=0.9",
}
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_INDEXES = 8
MAX_CATEGORY_LINKS = 1500


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(content: bytes, branch_host: str) -> tuple[list[str], list[str]]:
    """Return same-host category URLs and child sitemaps. No off-domain recursion."""
    if len(content) > MAX_XML_BYTES:
        raise ValueError("Sitemap exceeds maximum parse size")
    root = ET.fromstring(content)
    kind = _local(root.tag)
    if kind not in ("sitemapindex", "urlset"):
        raise ValueError(f"Unexpected XML root: {kind}")
    categories, indexes = [], []
    for item in root:
        if _local(item.tag) not in ("url", "sitemap"):
            continue
        loc = next((str(child.text or "").strip() for child in item if _local(child.tag) == "loc"), "")
        parsed = urlparse(loc)
        if parsed.scheme != "https" or parsed.hostname != branch_host:
            continue
        if _local(item.tag) == "sitemap":
            indexes.append(loc)
        elif re.fullmatch(r"/category/[^/]+/?", parsed.path):
            categories.append(loc.split("?", 1)[0])
    return sorted(set(categories)), sorted(set(indexes))


def html_category_links(html: str, branch_host: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.select('a[href*="/category/"]'):
        parsed = urlparse(urljoin(f"https://{branch_host}", a.get("href", "")))
        if parsed.hostname != branch_host or not re.fullmatch(r"/category/[^/]+/?", parsed.path):
            continue
        key = parsed.path.rstrip("/")
        found.setdefault(key, {"path": key, "label": a.get_text(" ", strip=True)[:100]})
    return list(found.values())[:MAX_CATEGORY_LINKS]


async def gather_sitemap(fetcher: Fetcher, host: str, report: dict) -> None:
    queue = [f"https://{host}/sitemap.xml"]
    seen = set()
    categories = set()
    diagnostics = []
    while queue and len(seen) < MAX_INDEXES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        item = {"url": url}
        try:
            response = await fetcher.get(url)
            item["status"] = response.status_code
            if len(response.content) > MAX_XML_BYTES:
                raise ValueError("Sitemap too large")
            nodes, children = parse_sitemap(response.content, host)
            item["category_count"] = len(nodes)
            item["child_sitemap_count"] = len(children)
            categories.update(nodes)
            for child in children:
                if child not in seen and child not in queue:
                    queue.append(child)
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        diagnostics.append(item)
    report["sitemap"] = {
        "documents": diagnostics,
        "categories_found": len(categories),
        "category_urls": sorted(categories)[:MAX_CATEGORY_LINKS],
        "truncated": len(categories) > MAX_CATEGORY_LINKS,
        "pending_documents": len(queue),
    }


async def gather_browser(host: str, report: dict, timeout_ms: int) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        report["browser"] = {"error": "Playwright is not installed"}
        return
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                url = f"https://{host}/category/groceries"
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(2500)
                html = await page.content()
                links = html_category_links(html, host)
                report["browser"] = {
                    "url": url,
                    "status": response.status if response else None,
                    "title": await page.title(),
                    "category_link_count": len(links),
                    "category_links": links,
                    "dynamic_placeholders_present": "{{category.name}}" in html,
                }
            finally:
                await browser.close()
    except Exception as exc:
        report["browser"] = {"error": f"{type(exc).__name__}: {str(exc)[:280]}"}


async def main(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", args.branch):
        raise SystemExit("Branch must be a valid slug")
    host = f"{args.branch}.store.freshchoice.co.nz"
    report = {"branch": args.branch, "host": host, "purpose": "Public taxonomy discovery; not a product scrape"}
    async with httpx.AsyncClient(headers=HEADERS, timeout=25) as client:
        fetcher = Fetcher(client, rate_per_host=0.5, per_host_concurrency=1, max_retries=0,
                          max_requests=MAX_INDEXES)
        await gather_sitemap(fetcher, host, report)
    if args.browser:
        await gather_browser(host, report, args.timeout_ms)
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Sitemap category URLs:", report["sitemap"]["categories_found"])
    print("Sitemap documents inspected:", len(report["sitemap"]["documents"]))
    if args.browser:
        b = report.get("browser", {})
        print("Browser category links:", b.get("category_link_count", "error"))
        if b.get("error"):
            print("Browser error:", b["error"])
    print("Saved:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="merivale")
    ap.add_argument("--browser", action="store_true", help="Inspect publicly rendered category navigation")
    ap.add_argument("--timeout-ms", type=int, default=30000)
    ap.add_argument("--save", default="output-taxonomy/merivale.json")
    asyncio.run(main(ap.parse_args()))
