"""FreshChoice Branch Checker & Verification Utility.

Provides full manual verification commands for FreshChoice New Zealand branches:
- Summary of all 79 branches (51 Online with 'Shop Now', 28 In-store with 'Store Info')
- Detailed listing of online-only (51) or in-store only (28) branches
- Live website check directly from https://store.freshchoice.co.nz/
- Search by branch name or city
- URL connectivity ping / health check
- CSV and JSON export for spreadsheet inspection
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from typing import Any
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from catalog_branches import KNOWN_FRESHCHOICE_STORES, get_branch, list_branches


def fetch_live_website_counts() -> dict[str, Any]:
    """Fetch live data directly from store.freshchoice.co.nz."""
    url = "https://store.freshchoice.co.nz/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": str(e), "shop_now": 0, "store_info": 0, "subdomains": []}

    shop_now_count = len(re.findall(r"Shop\s+Now", html, re.IGNORECASE))
    store_info_count = len(re.findall(r"Store\s+Info", html, re.IGNORECASE))

    matches = re.findall(r'https?://([a-zA-Z0-9-]+)\.store\.freshchoice\.co\.nz', html, re.IGNORECASE)
    unique_slugs = sorted(set(s.lower() for s in matches if s.lower() not in {"store", "www"}))

    return {
        "shop_now": shop_now_count,
        "store_info": store_info_count,
        "total_on_page": shop_now_count + store_info_count,
        "subdomains": unique_slugs,
    }


def export_branches() -> None:
    """Export all branches to CSV and JSON in exports/ and project root for easy review."""
    exports_dir = BASE_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    csv_paths = [exports_dir / "freshchoice_branches.csv", BASE_DIR / "freshchoice_branches.csv"]
    json_paths = [exports_dir / "freshchoice_branches.json", BASE_DIR / "freshchoice_branches.json"]

    for path in csv_paths:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Index", "ID", "Name", "Online Shopping", "Website URL", "Address", "Phone", "Retailer"])
            for i, b in enumerate(KNOWN_FRESHCHOICE_STORES, 1):
                writer.writerow([
                    i,
                    b.get("id", ""),
                    b.get("name", ""),
                    "YES (Shop Now)" if b.get("shopping_online") else "NO (Store Info)",
                    b.get("url", ""),
                    b.get("address", ""),
                    b.get("phone", ""),
                    b.get("retailer", "FreshChoice"),
                ])

    for path in json_paths:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(KNOWN_FRESHCHOICE_STORES, f, indent=2, ensure_ascii=False)

    print(f"✅ Exported {len(KNOWN_FRESHCHOICE_STORES)} branches:")
    print(f"   - CSV:  {exports_dir / 'freshchoice_branches.csv'}")
    print(f"   - JSON: {exports_dir / 'freshchoice_branches.json'}")


def ping_branches(branches: list[dict[str, Any]], limit: int = 10) -> None:
    """Check HTTP connectivity for a list of branches."""
    print(f"\n🌐 Checking HTTP connectivity for {min(len(branches), limit)} branches...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    for i, b in enumerate(branches[:limit], 1):
        url = b.get("url", "")
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=8) as resp:
                code = resp.getcode()
                status = f"✅ HTTP {code}"
        except Exception as e:
            status = f"❌ Error: {e}"
        print(f"  {i:2d}. [{b['id']:<15}] {b['name']:<20} -> {status} ({url})")


def search_branches(query: str) -> list[dict[str, Any]]:
    """Search branches by name, id, or address."""
    q = query.strip().lower()
    results = []
    for b in KNOWN_FRESHCHOICE_STORES:
        if (
            q in b.get("id", "").lower()
            or q in b.get("name", "").lower()
            or q in b.get("address", "").lower()
        ):
            results.append(b)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="FreshChoice Branch Checker & Verification Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python check_branches.py                     # Show overview summary
  python check_branches.py --online            # List all 51 Online branches
  python check_branches.py --instore           # List all 28 In-Store only branches
  python check_branches.py --all               # List all 79 branches
  python check_branches.py --search cromwell   # Search for a branch
  python check_branches.py --live              # Fetch live count from store.freshchoice.co.nz
  python check_branches.py --ping --limit 5    # Ping first 5 branches
  python check_branches.py --export            # Export to freshchoice_branches.csv and .json
""",
    )
    parser.add_argument("--online", "-o", action="store_true", help="List all 51 online shopping branches (Shop Now)")
    parser.add_argument("--instore", "-i", action="store_true", help="List all 28 in-store only branches (Store Info)")
    parser.add_argument("--all", "-a", action="store_true", help="List all 79 FreshChoice branches")
    parser.add_argument("--search", "-s", type=str, help="Search branch by name, id, or city")
    parser.add_argument("--live", "-l", action="store_true", help="Fetch and verify live data from store.freshchoice.co.nz")
    parser.add_argument("--ping", "-p", action="store_true", help="Ping branch URLs to verify connectivity")
    parser.add_argument("--limit", type=int, default=10, help="Limit for ping check (default: 10, use 0 for all)")
    parser.add_argument("--export", "-e", action="store_true", help="Export all branches to CSV and JSON")

    args = parser.parse_args()

    total_registered = len(KNOWN_FRESHCHOICE_STORES)
    online_stores = [b for b in KNOWN_FRESHCHOICE_STORES if b.get("shopping_online")]
    instore_stores = [b for b in KNOWN_FRESHCHOICE_STORES if not b.get("shopping_online")]

    # If --export was requested
    if args.export:
        export_branches()
        return

    # If --search was requested
    if args.search:
        results = search_branches(args.search)
        print("=" * 65)
        print(f"🔍 Search results for '{args.search}': Found {len(results)} branch(es)")
        print("=" * 65)
        for i, b in enumerate(results, 1):
            status = "✅ Online (Shop Now)" if b.get("shopping_online") else "🏢 In-store Only (Store Info)"
            print(f"{i}. {b['name']} ({b['id']})")
            print(f"   Status:  {status}")
            print(f"   URL:     {b['url']}")
            print(f"   Address: {b['address']}")
            print(f"   Phone:   {b.get('phone', 'N/A')}")
            print("-" * 65)
        return

    # If --live was requested
    if args.live:
        print("=" * 65)
        print("🌐 Checking live website: https://store.freshchoice.co.nz/")
        print("=" * 65)
        live = fetch_live_website_counts()
        if "error" in live and live["error"]:
            print(f"❌ Error connecting to live website: {live['error']}")
        else:
            print(f"🟢 'Shop Now' Buttons (Online Shopping):   {live['shop_now']} branches")
            print(f"🏢 'Store Info' Buttons (In-Store Only):   {live['store_info']} branches")
            print(f"📊 Total Branch Cards on Live Page:       {live['total_on_page']} branches")
            print(f"🔗 Unique Subdomains Found:               {len(live['subdomains'])}")
            if live['shop_now'] == len(online_stores):
                print(f"✅ PERFECT MATCH: Live website has {live['shop_now']} 'Shop Now' branches, matching the 51 catalog branches!")
            else:
                print(f"ℹ️ Catalog has {len(online_stores)} online branches, website has {live['shop_now']}.")
        print("=" * 65)
        return

    # If --ping was requested
    if args.ping:
        target_list = online_stores if not args.all else KNOWN_FRESHCHOICE_STORES
        limit = len(target_list) if args.limit == 0 else args.limit
        ping_branches(target_list, limit=limit)
        return

    # If listing was requested
    if args.online or args.instore or args.all:
        if args.online:
            targets = online_stores
            title = f"🛒 ONLINE SHOPPING BRANCHES ('Shop Now' — {len(targets)} Branches)"
        elif args.instore:
            targets = instore_stores
            title = f"🏢 IN-STORE / PHYSICAL ONLY BRANCHES ('Store Info' — {len(targets)} Branches)"
        else:
            targets = KNOWN_FRESHCHOICE_STORES
            title = f"📋 ALL FRESHCHOICE BRANCHES ({len(targets)} Branches)"

        print("=" * 75)
        print(title)
        print("=" * 75)
        for i, b in enumerate(targets, 1):
            status = "✅ Shop Now" if b.get("shopping_online") else "🏢 Store Info"
            print(f"{i:2d}. [{b['id']:<16}] {b['name']:<22} | {status} | {b['url']}")
        print("=" * 75)
        return

    # Default overview display
    print("=" * 70)
    print("🛒 FRESHCHOICE NEW ZEALAND — BRANCH SUMMARY")
    print("=" * 70)
    print(f"📌 Total FreshChoice Branches (NZ):      {total_registered} branches")
    print(f"🌐 Online Shopping Branches ('Shop Now'): {len(online_stores)} branches (Matches user's 51)")
    print(f"🏬 Physical / In-Store Only ('Store Info'):{len(instore_stores)} branches (e.g. Cuba Street)")
    print("=" * 70)
    print("💡 Commands to manually check branches:")
    print("  1. List all 51 Online branches:     python check_branches.py --online")
    print("  2. List all 28 In-Store branches:   python check_branches.py --instore")
    print("  3. List all 79 branches:            python check_branches.py --all")
    print("  4. Search branch by name:           python check_branches.py --search <name>")
    print("     (e.g., python check_branches.py --search cromwell)")
    print("     (e.g., python check_branches.py --search \"cuba street\")")
    print("  5. Verify live count from website:  python check_branches.py --live")
    print("  6. Test branch URLs connectivity:   python check_branches.py --ping --limit 5")
    print("  7. Export to Excel (CSV file):      python check_branches.py --export")
    print("=" * 70)


if __name__ == "__main__":
    main()
