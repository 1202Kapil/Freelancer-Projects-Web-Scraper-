"""Merge all FreshChoice JSONL exports into a single consolidated dataset.

Combines per-branch exports from exports/ into:
1. exports/freshchoice_all_branches_merged.jsonl (Standard JSONL format)
2. exports/freshchoice_all_branches_merged.csv   (Excel-friendly CSV format)

Deduplicates identical product observations across multiple runs while preserving branch isolation.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
import sys
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("merge_exports")

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"


def merge_jsonl_files(
    out_jsonl_name: str = "freshchoice_all_branches_merged.jsonl",
    out_csv_name: str = "freshchoice_all_branches_merged.csv",
    deduplicate: bool = True,
) -> dict[str, Any]:
    """Merge all export jsonl files in EXPORTS_DIR into one file."""
    if not EXPORTS_DIR.exists():
        logger.error(f"Exports directory not found: {EXPORTS_DIR}")
        return {}

    # Target all jsonl files except existing merged files
    jsonl_files = sorted([
        f for f in EXPORTS_DIR.glob("*.jsonl")
        if not f.name.endswith("_merged.jsonl") and "merged" not in f.name.lower()
    ])

    if not jsonl_files:
        logger.warning(f"No source JSONL files found in {EXPORTS_DIR}")
        return {}

    logger.info(f"Found {len(jsonl_files)} source export files to merge:")
    total_raw_rows = 0
    file_summaries = []

    # Map to hold records: key is (branch_id, product_id)
    unique_records: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_records: list[dict[str, Any]] = []

    for f in jsonl_files:
        count = 0
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid JSON on line {line_no} in {f.name}: {e}")
                    continue

                total_raw_rows += 1
                count += 1

                branch_id = rec.get("raw_row", {}).get("branch_id") or rec.get("branch_id") or "unknown"
                product_id = rec.get("source_product_id") or rec.get("retailer_sku") or f"row_{total_raw_rows}"

                key = (branch_id, product_id)
                # Keep latest observation
                unique_records[key] = rec
                if not deduplicate:
                    ordered_records.append(rec)

        file_summaries.append({"file": f.name, "rows": count, "size_kb": round(f.stat().st_size / 1024, 1)})
        logger.info(f"  - {f.name}: {count:,} rows")

    final_records = list(unique_records.values()) if deduplicate else ordered_records
    logger.info(f"Consolidation complete: {total_raw_rows:,} raw rows -> {len(final_records):,} unique products")

    # 1. Write Merged JSONL
    out_jsonl_path = EXPORTS_DIR / out_jsonl_name
    temp_jsonl = out_jsonl_path.with_suffix(".tmp")
    with open(temp_jsonl, "w", encoding="utf-8") as f:
        for rec in final_records:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    temp_jsonl.replace(out_jsonl_path)
    logger.info(f"Saved merged JSONL to: {out_jsonl_path} ({out_jsonl_path.stat().st_size / (1024 * 1024):.2f} MB)")

    # 2. Write Merged CSV for easy viewing in Excel
    out_csv_path = EXPORTS_DIR / out_csv_name
    temp_csv = out_csv_path.with_suffix(".tmp")
    fieldnames = [
        "branch_id",
        "clean_name",
        "brand",
        "department",
        "category",
        "sub_category",
        "leaf_category",
        "category_path",
        "category_tree",
        "category_url",
        "currency",
        "current_price_nzd",
        "current_price_cents",
        "sale_price",
        "list_price",
        "savings",
        "price_per_unit",
        "price_by_unit",
        "size",
        "availability",
        "stock_status",
        "is_promo",
        "promo_badge",
        "promo_text",
        "source_product_id",
        "sku",
        "gtin",
        "barcode",
        "product_url",
        "image_url",
        "observed_at",
    ]

    with open(temp_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for rec in final_records:
            price_cents = rec.get("current_price_cents")
            price_nzd = f"${price_cents / 100:.2f}" if isinstance(price_cents, int) else ""
            branch = rec.get("raw_row", {}).get("branch_id") or rec.get("branch_id", "")
            leaf_cat = rec.get("leaf_category") or rec.get("lead_category") or rec.get("sub_category") or rec.get("category", "")
            cat_tree = rec.get("category_tree") or rec.get("category_path", "")
            cat_url = rec.get("category_url", "")
            unit_price_cents = rec.get("unit_price_cents")
            price_per_unit = rec.get("price_per_unit") or (f"{unit_price_cents / 100:.2f}" if isinstance(unit_price_cents, int) else "")
            price_by_unit = rec.get("price_by_unit") or rec.get("unit_label", "")
            avail = rec.get("availability") or rec.get("stock_status", "in_stock")

            writer.writerow([
                branch,
                rec.get("clean_name") or rec.get("raw_name", ""),
                rec.get("brand", ""),
                rec.get("department", ""),
                rec.get("category", ""),
                rec.get("sub_category", ""),
                leaf_cat,
                rec.get("category_path", ""),
                cat_tree,
                cat_url,
                rec.get("currency", "NZD"),
                price_nzd,
                price_cents if price_cents is not None else "",
                rec.get("sale_price", ""),
                rec.get("list_price", ""),
                rec.get("savings", ""),
                price_per_unit,
                price_by_unit,
                rec.get("size", ""),
                avail,
                rec.get("stock_status", ""),
                rec.get("is_promo", False),
                rec.get("promo_badge", ""),
                rec.get("promo_text", ""),
                rec.get("source_product_id", ""),
                rec.get("sku") or rec.get("retailer_sku", ""),
                rec.get("gtin", ""),
                rec.get("barcode", ""),
                rec.get("product_url", ""),
                rec.get("image_url", ""),
                rec.get("observed_at", ""),
            ])
    temp_csv.replace(out_csv_path)
    logger.info(f"Saved merged CSV to: {out_csv_path} ({out_csv_path.stat().st_size / (1024 * 1024):.2f} MB)")

    return {
        "source_files": file_summaries,
        "total_source_files": len(jsonl_files),
        "total_raw_rows": total_raw_rows,
        "unique_products": len(final_records),
        "merged_jsonl": str(out_jsonl_path),
        "merged_csv": str(out_csv_path),
    }


def main():
    print("=" * 70)
    print("🔄 FRESHCHOICE EXPORTS MERGE UTILITY")
    print("=" * 70)
    result = merge_jsonl_files()
    if not result:
        print("❌ No files merged.")
        return

    print("-" * 70)
    print("📊 MERGE SUMMARY:")
    print(f"  • Files Merged:      {result['total_source_files']} files")
    print(f"  • Total Raw Rows:    {result['total_raw_rows']:,}")
    print(f"  • Unique Products:   {result['unique_products']:,}")
    print(f"  • Merged JSONL File: {result['merged_jsonl']}")
    print(f"  • Merged CSV (Excel):{result['merged_csv']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
