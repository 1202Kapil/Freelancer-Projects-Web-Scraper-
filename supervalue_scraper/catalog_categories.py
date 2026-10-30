"""Category discovery and audit utility for SuperValue Supermarkets."""
import argparse
import re
import urllib.request
import json
from collections import defaultdict

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def fetch_categories(branch: str = "milton"):
    sitemap_url = f"https://{branch}.store.supervalue.co.nz/sitemap.xml"
    print(f"Fetching sitemap from: {sitemap_url} ...")
    
    req = urllib.request.Request(sitemap_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as res:
        xml_data = res.read().decode("utf-8", errors="ignore")
        
    category_urls = re.findall(rf"<loc>https://{re.escape(branch)}\.store\.supervalue\.co\.nz/category/([^<]+)</loc>", xml_data)
    
    unique_slugs = sorted(set(category_urls))
    print("=" * 70)
    print(f"SUPERVALUE [{branch.upper()}] TOTAL CATEGORIES DISCOVERED: {len(unique_slugs)}")
    print("=" * 70)
    
    # Categorize into top departments and subcategories
    departments = defaultdict(list)
    for slug in unique_slugs:
        parts = slug.split("-")
        dept = parts[0]
        departments[dept].append(slug)
        
    print(f"\nTop Category Groups ({len(departments)} groups):")
    for dept, items in sorted(departments.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
        print(f"  • {dept:20} : {len(items):3} subcategories (e.g. {items[0]})")
        
    print(f"\nSample Categories (First 20):")
    for idx, slug in enumerate(unique_slugs[:20], 1):
        name = slug.replace("-", " ").title()
        print(f"  {idx:2}. {name:30} (/category/{slug})")
        
    return unique_slugs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit SuperValue categories from live sitemap")
    parser.add_argument("--branch", type=str, default="milton", help="Store branch slug (default: milton)")
    args = parser.parse_args()
    fetch_categories(args.branch)
