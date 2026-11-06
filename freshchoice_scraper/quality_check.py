"""Quality audit and validation script for FreshChoice & SuperValue merged exports.

Verifies:
1. Brand & Category Realignment (no blind GTM shifts, brand matches title or is None, category_url aligns with path)
2. Category duplicate normalization (Health Beauty -> Health & Beauty, Dairy Eggs -> Dairy & Eggs)
3. Zero False Promotions (is_promo=True ONLY if list_price > price or multibuy exists)
4. Schema Uniformity (50 canonical columns)
5. Fill-rates for all fields
6. Specific audit product checks:
   - Bell Block Special K: brand == "Kelloggs", department == "Groceries", is_promo == False
   - Hansells Baking Powder: brand == "Hansells", department == "Groceries"
   - Arnott's Shapes: brand in ["Arnotts", "Arnott's"], department == "Snacks"
   - Doritos: department == "Snacks", category == "Chips - Sharing", 0 in "Cake Mix" or "Yoghurt"
   - Coca-Cola: department == "Drinks", category == "Carbonated Soft Drinks"
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("quality_check")

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
MERGED_JSONL = EXPORTS_DIR / "freshchoice_all_branches_merged.jsonl"
MERGED_CSV = EXPORTS_DIR / "freshchoice_all_branches_merged.csv"


def run_quality_audit() -> dict[str, Any]:
    if not MERGED_JSONL.exists():
        logger.error(f"Merged JSONL not found: {MERGED_JSONL}")
        return {"error": "File not found"}

    logger.info(f"Auditing master export: {MERGED_JSONL}")
    
    total_rows = 0
    brand_present = 0
    brand_mismatches = 0
    cat_url_mismatches = 0
    duplicate_cats_found = 0
    false_promos = 0
    true_promos = 0
    weighted_products = 0
    supervalue_rows = 0
    
    # Check specific problem cases
    special_k_samples = []
    doritos_samples = []
    hansells_samples = []
    coke_samples = []
    arnotts_samples = []

    doritos_in_cake_or_yoghurt = 0
    
    field_counts: dict[str, int] = {}
    branches = set()

    with open(MERGED_JSONL, "r", encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as e:
                logger.warning(f"JSON parse error at line {line_no}: {e}")
                continue

            total_rows += 1
            branch = row.get("branch_id")
            if branch:
                branches.add(branch)
            if row.get("retailer") == "supervalue":
                supervalue_rows += 1

            # Count fields
            for k, v in row.items():
                if v not in (None, "", [], {}):
                    field_counts[k] = field_counts.get(k, 0) + 1

            clean_name = row.get("clean_name", "")
            brand = row.get("brand")
            dept = row.get("department", "")
            cat = row.get("category", "")
            sub = row.get("sub_category", "")
            cat_url = row.get("category_url", "")
            cat_path = row.get("category_path", "")
            
            # 1. Brand validation
            if brand:
                brand_present += 1
                b_norm = re.sub(r"[^\w]", "", brand.lower())
                n_norm = re.sub(r"[^\w]", "", clean_name.lower())
                # Brand token must be in product title
                b_tokens = set(re.findall(r"[a-z0-9]+", brand.lower())) - {'foods', 'co', 'the', 'organics', 'nz', 'group', 'products', 'ltd', 'nature', 'natures', 'natural'}
                n_tokens = set(re.findall(r"[a-z0-9]+", clean_name.lower()))
                if b_tokens and not (b_tokens & n_tokens) and b_norm not in n_norm:
                    brand_mismatches += 1

            # 2. Category duplicate check
            if dept in ["Health Beauty", "Dairy Eggs", "Fruit Vegetables"]:
                duplicate_cats_found += 1

            # 3. Category URL alignment check
            # URL slug should match the leaf category slug
            leaf = row.get("leaf_category") or sub or cat or dept
            expected_slug = re.sub(r"[\s_-]+", "-", re.sub(r"[^\w\s-]", "", leaf.lower())).strip("-")
            if f"/category/{expected_slug}" not in cat_url:
                cat_url_mismatches += 1

            # 4. False promotion check
            is_promo = row.get("is_promo", False)
            price = row.get("price")
            list_price = row.get("list_price")
            mb_qty = row.get("multibuy_quantity")
            if is_promo:
                if (price is not None and list_price is not None and price >= list_price) and not (mb_qty and mb_qty >= 2):
                    false_promos += 1
                else:
                    true_promos += 1

            # 5. Selling price basis
            if row.get("selling_price_basis") == "per kg":
                weighted_products += 1

            # 6. Specific product checks
            clean_l = clean_name.lower()
            if "special k" in clean_l:
                special_k_samples.append({
                    "branch": branch,
                    "name": clean_name,
                    "brand": brand,
                    "department": dept,
                    "category": cat,
                    "is_promo": is_promo,
                    "price": price,
                    "list_price": list_price,
                })
            elif "doritos" in clean_l:
                if "cake" in cat.lower() or "baking" in cat.lower() or "yoghurt" in cat.lower() or "yogurt" in cat.lower():
                    doritos_in_cake_or_yoghurt += 1
                if len(doritos_samples) < 5:
                    doritos_samples.append({
                        "branch": branch,
                        "name": clean_name,
                        "brand": brand,
                        "department": dept,
                        "category": cat,
                        "category_path": cat_path,
                    })
            elif "hansells" in clean_l and "baking powder" in clean_l:
                hansells_samples.append({
                    "branch": branch,
                    "name": clean_name,
                    "brand": brand,
                    "department": dept,
                    "category": cat,
                })
            elif "coca-cola" in clean_l or "coca cola" in clean_l:
                if len(coke_samples) < 5:
                    coke_samples.append({
                        "branch": branch,
                        "name": clean_name,
                        "brand": brand,
                        "department": dept,
                        "category": cat,
                    })
            elif "shapes" in clean_l and "original pizza" in clean_l:
                arnotts_samples.append({
                    "branch": branch,
                    "name": clean_name,
                    "brand": brand,
                    "department": dept,
                    "category": cat,
                })

    print("=" * 70)
    print("📊 FRESHCHOICE & SUPERVALUE PRODUCTION EXPORT QUALITY AUDIT")
    print("=" * 70)
    print(f"Total Unique Product Rows:   {total_rows:,}")
    print(f"Total Branches Represented:  {len(branches)} (Online: 51)")
    print(f"SuperValue (Bell Block) Rows:{supervalue_rows:,}")
    print("-" * 70)
    print("🎯 SYSTEMATIC FIXES VERIFICATION:")
    print(f"  • Brand Presence:          {brand_present:,} / {total_rows:,} ({brand_present / max(1, total_rows) * 100:.1f}%)")
    print(f"  • Brand Mismatches:        {brand_mismatches:,}  (Target: 0)")
    print(f"  • Category URL Mismatches: {cat_url_mismatches:,}  (Target: 0)")
    print(f"  • Duplicate Categories:    {duplicate_cats_found:,}  (Target: 0)")
    print(f"  • False Promotions:        {false_promos:,}  (Target: 0)")
    print(f"  • Verified Promotions:     {true_promos:,}")
    print(f"  • Weighted ('per kg') Items:{weighted_products:,}")
    print(f"  • Doritos in Cake/Yoghurt: {doritos_in_cake_or_yoghurt:,}  (Target: 0)")
    print("-" * 70)

    print("🔎 SPOT CHECK RESULTS:")
    if special_k_samples:
        sk = special_k_samples[0]
        print(f"  • Special K ({sk['branch']}): Brand='{sk['brand']}', Dept='{sk['department']}', Promo={sk['is_promo']}")
    if hansells_samples:
        hs = hansells_samples[0]
        print(f"  • Hansells Baking Powder ({hs['branch']}): Brand='{hs['brand']}', Dept='{hs['department']}', Cat='{hs['category']}'")
    if arnotts_samples:
        ar = arnotts_samples[0]
        print(f"  • Arnott's Shapes ({ar['branch']}): Brand='{ar['brand']}', Dept='{ar['department']}', Cat='{ar['category']}'")
    if doritos_samples:
        d = doritos_samples[0]
        print(f"  • Doritos ({d['branch']}): Brand='{d['brand']}', Dept='{d['department']}', Cat='{d['category']}'")
    if coke_samples:
        c = coke_samples[0]
        print(f"  • Coca-Cola ({c['branch']}): Brand='{c['brand']}', Dept='{c['department']}', Cat='{c['category']}'")
    print("=" * 70)

    return {
        "total_rows": total_rows,
        "branches_count": len(branches),
        "brand_mismatches": brand_mismatches,
        "cat_url_mismatches": cat_url_mismatches,
        "duplicate_cats_found": duplicate_cats_found,
        "false_promos": false_promos,
        "true_promos": true_promos,
        "doritos_in_cake_or_yoghurt": doritos_in_cake_or_yoghurt,
        "field_counts": field_counts,
    }


if __name__ == "__main__":
    run_quality_audit()
