"""Bounded navigation probe for a permitted FreshChoice online store.

Uses the scraper's normal network client, without guessing hidden endpoints.
Collects category anchors, suspected subdepartment markup, and optional HTML.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from network import Fetcher


def collect(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.select('a[href*="/category/"]'):
        url = urljoin(base_url, a.get("href", ""))
        if urlparse(url).netloc != urlparse(base_url).netloc:
            continue
        label = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
        path = urlparse(url).path
        key = (path, label)
        if key in seen:
            continue
        seen.add(key)
        p = a.parent if isinstance(a.parent, Tag) else None
        links.append({
            "label": label[:140],
            "path": path,
            "href": a.get("href"),
            "element_classes": a.get("class", []),
            "parent_classes": p.get("class", []) if p else [],
            "parent_text": p.get_text(" ", strip=True)[:180] if p else "",
        })
    # If nav sections are JS-bound without ordinary <a href>, these snippets
    # reveal which markup was present and can guide an authorized adapter.
    suspect = []
    terms = (
        "Prepared Foods", "Breakfast Foods", "Pasta / Rice", "Canned Fish",
        "Cooking Needs", "Sauces & Condiments", "Deli - Kitchen"
    )
    for token in soup.find_all(string=True):
        text = str(token).strip()
        if text not in terms:
            continue
        node = token.parent
        if node is None:
            continue
        suspect.append({
            "text": text,
            "parent_tag": node.name,
            "parent_html_excerpt": str(node.parent or node)[:550],
        })
        if len(suspect) >= 24:
            break
    return {
        "title": (soup.title.get_text(" ", strip=True) if soup.title else None),
        "category_links": links[:200],
        "category_link_count": len(links),
        "subdepartment_markup_examples": suspect,
    }


async def main(args):
    branch = args.branch.lower().strip()
    if not re.fullmatch(r"[a-z0-9-]+", branch):
        raise SystemExit("Invalid branch slug")
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {"branch": branch, "categories": []}
    headers = {
        "User-Agent": "FreshChoiceAssessmentScraper/0.1 (+authorized-assessment)",
        "Accept-Language": "en-NZ,en;q=0.9",
    }
    async with httpx.AsyncClient(headers=headers, timeout=25) as client:
        fetcher = Fetcher(client, rate_per_host=0.5, per_host_concurrency=1, max_retries=0)
        for category in args.categories.split(","):
            slug = category.lower().strip()
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                raise SystemExit("Invalid category slug")
            url = f"https://{branch}.store.freshchoice.co.nz/category/{slug}"
            entry = {"slug": slug, "url": url}
            try:
                response = await fetcher.get(url)
                entry["status"] = response.status_code
                entry.update(collect(response.text, url))
                if args.save_html:
                    dest = out.parent / f"{branch}-{slug}.html"
                    dest.write_text(response.text, encoding="utf-8")
                    entry["html_snapshot"] = str(dest)
            except httpx.HTTPStatusError as exc:
                entry["status"] = exc.response.status_code
                entry["error"] = str(exc)[:400]
            except Exception as exc:
                entry["error"] = type(exc).__name__ + ": " + str(exc)[:350]
            report["categories"].append(entry)
            print(f"{slug}: status={entry.get('status','error')} links={entry.get('category_link_count',0)}")
            for link in entry.get("category_links", [])[:18]:
                print(" ", repr(link['label']), link['path'])
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", default="merivale")
    parser.add_argument("--categories", default="groceries,household,deli")
    parser.add_argument("--save", default="output-category-probe/merivale.json")
    parser.add_argument("--save-html", action="store_true")
    asyncio.run(main(parser.parse_args()))
