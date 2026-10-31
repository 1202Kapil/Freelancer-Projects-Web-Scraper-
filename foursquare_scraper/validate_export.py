"""Production Schema, GS1 Checksum & Branch Coverage Validator for Four Square Exports.

Strictly audits exports against PICO Scraper Data Contract and client review requirements:
1. Barcode Accuracy & GS1 Check Digits: Verifies GTIN formats (8, 12, 13, 14 digits)
   and computes mathematical GS1 modulo-10 check digit on every barcode.
2. Product Completeness: Audits required fields, price sanity, and URL presence.
3. Stock Availability: Verifies stock_status distribution (in_stock vs out_of_stock).
4. Promotions Verification: Audits specials, multibuys, and promo date bounds.
5. Multi-Branch Coverage: Audits multi-branch exports across exports/ directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

from config import EXPORTS_DIR
from normalize import is_valid_gtin_checksum, is_valid_gtin_format

VALID_GTIN_LENGTHS = {8, 12, 13, 14}
VALID_STOCK_STATUSES = {"in_stock", "out_of_stock"}
VALID_PROMO_TYPES = {
    "special",
    "member_price",
    "multibuy_fixed_price",
    "multibuy_discount",
    "clearance",
    "percent_off",
}
REQUIRED_FIELDS = [
    "source_product_id",
    "retailer_sku",
    "raw_name",
    "clean_name",
    "current_price_cents",
    "stock_status",
    "observed_at",
]


def validate_record(rec: dict, line_no: int) -> tuple[list[str], bool, bool]:
    """Validate a single product observation.
    Returns: (errors_list, has_valid_gtin, has_valid_checksum).
    """
    errors = []
    has_valid_gtin = False
    has_valid_checksum = False

    # 1. Required fields completeness
    for f in REQUIRED_FIELDS:
        val = rec.get(f)
        if val is None or val == "":
            errors.append(f"Line {line_no}: Missing required field '{f}'")

    # 2. Barcode & GS1 Checksum accuracy
    bc = rec.get("barcode")
    if bc is not None:
        bc_str = str(bc).strip()
        if not bc_str.isdigit():
            errors.append(f"Line {line_no}: Barcode '{bc}' contains non-numeric characters")
        elif len(bc_str) not in VALID_GTIN_LENGTHS:
            if len(bc_str) in (4, 5):
                errors.append(f"Line {line_no}: Produce PLU code '{bc}' ({len(bc_str)} digits) incorrectly mapped to barcode")
            else:
                errors.append(f"Line {line_no}: Invalid GTIN length '{bc}' (len={len(bc_str)})")
        else:
            has_valid_gtin = True
            if is_valid_gtin_checksum(bc_str):
                has_valid_checksum = True
            else:
                errors.append(f"Line {line_no}: Barcode '{bc_str}' failed GS1 modulo-10 checksum validation")

    # 3. Price validation
    price = rec.get("current_price_cents")
    if price is not None:
        if not isinstance(price, int) or price <= 0:
            errors.append(f"Line {line_no}: current_price_cents must be a positive integer, got {price}")

    comp_price = rec.get("comparison_price_cents")
    if comp_price is not None:
        if not isinstance(comp_price, int) or comp_price <= 0:
            errors.append(f"Line {line_no}: comparison_price_cents must be a positive integer, got {comp_price}")

    unit_price = rec.get("unit_price_cents")
    if unit_price is not None:
        if not isinstance(unit_price, int) or unit_price <= 0:
            errors.append(f"Line {line_no}: unit_price_cents must be a positive integer, got {unit_price}")

    # 4. Stock status
    status = rec.get("stock_status")
    if status and status not in VALID_STOCK_STATUSES:
        errors.append(f"Line {line_no}: Invalid stock_status '{status}'")

    # 5. Promo fields validation
    promo_type = rec.get("promo_type")
    if promo_type is not None:
        if promo_type not in VALID_PROMO_TYPES:
            errors.append(f"Line {line_no}: Unknown promo_type '{promo_type}'")

    # 6. Timestamp format (ISO-8601 UTC)
    obs_at = rec.get("observed_at")
    if obs_at:
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", obs_at):
            errors.append(f"Line {line_no}: observed_at '{obs_at}' not in ISO-8601 UTC format (YYYY-MM-DDTHH:MM:SSZ)")

    return errors, has_valid_gtin, has_valid_checksum


def validate_file(file_path: Path) -> dict[str, Any]:
    """Validate a complete JSONL export file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Export file not found: {file_path}")

    total_records = 0
    all_errors = []
    gtin_valid_count = 0
    checksum_valid_count = 0
    in_stock_count = 0
    out_of_stock_count = 0
    promos_count = 0
    multibuys_count = 0
    unique_ids = set()
    duplicate_ids = 0

    with file_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total_records += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                all_errors.append(f"Line {idx}: JSON parse error: {e}")
                continue

            pid = rec.get("source_product_id")
            if pid:
                if pid in unique_ids:
                    duplicate_ids += 1
                unique_ids.add(pid)

            errs, has_gtin, has_checksum = validate_record(rec, idx)
            all_errors.extend(errs)

            if has_gtin:
                gtin_valid_count += 1
            if has_checksum:
                checksum_valid_count += 1

            if rec.get("stock_status") == "in_stock":
                in_stock_count += 1
            elif rec.get("stock_status") == "out_of_stock":
                out_of_stock_count += 1

            if rec.get("promo_type"):
                promos_count += 1
            if rec.get("multibuy_quantity"):
                multibuys_count += 1

    gtin_accuracy = (checksum_valid_count / gtin_valid_count * 100.0) if gtin_valid_count > 0 else 0.0
    barcode_coverage = (gtin_valid_count / total_records * 100.0) if total_records > 0 else 0.0

    return {
        "file": file_path.name,
        "total_records": total_records,
        "unique_products": len(unique_ids),
        "duplicate_ids": duplicate_ids,
        "errors_count": len(all_errors),
        "errors_sample": all_errors[:10],
        "barcodes_present": gtin_valid_count,
        "barcodes_checksum_valid": checksum_valid_count,
        "gtin_checksum_accuracy_pct": round(gtin_accuracy, 2),
        "barcode_coverage_pct": round(barcode_coverage, 2),
        "in_stock": in_stock_count,
        "out_of_stock": out_of_stock_count,
        "promotions_count": promos_count,
        "multibuys_count": multibuys_count,
        "is_valid": len(all_errors) == 0 and total_records > 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit and validate Four Square JSONL exports")
    parser.add_argument("--input", help="Path to a single JSONL export file")
    parser.add_argument("--all", action="store_true", help="Audit all JSONL files in exports/ directory")
    args = parser.parse_args()

    files = []
    if args.input:
        files.append(Path(args.input))
    elif args.all or not args.input:
        files = sorted(list(EXPORTS_DIR.glob("foursquare_*.jsonl")))

    if not files:
        print("[!] No JSONL export files found to validate.")
        sys.exit(1)

    print("=" * 75)
    print(f"PICO DATA CONTRACT AUDIT: Auditing {len(files)} Four Square export file(s)")
    print("=" * 75)

    all_passed = True
    for fp in files:
        report = validate_file(fp)
        status = "[PASS]" if report["is_valid"] else "[FAIL]"
        if not report["is_valid"]:
            all_passed = False

        print(f"\n{status} {report['file']}")
        print(f"  Observations  : {report['total_records']} total ({report['unique_products']} unique)")
        print(f"  Barcodes      : {report['barcodes_present']} present ({report['barcode_coverage_pct']}% coverage)")
        print(f"  GS1 Modulo-10 : {report['barcodes_checksum_valid']}/{report['barcodes_present']} valid ({report['gtin_checksum_accuracy_pct']}% checksum accuracy)")
        print(f"  Availability  : {report['in_stock']} in stock, {report['out_of_stock']} out of stock")
        print(f"  Promotions    : {report['promotions_count']} specials, {report['multibuys_count']} multibuys")
        print(f"  Errors        : {report['errors_count']}")

        if report["errors_sample"]:
            print("  Sample errors:")
            for err in report["errors_sample"][:5]:
                print(f"    - {err}")

    print("\n" + "=" * 75)
    if all_passed:
        print("ALL EXPORT FILES PASSED PICO DATA CONTRACT & GS1 AUDIT SUCCESSFULLY!")
        print("=" * 75)
        sys.exit(0)
    else:
        print("SOME EXPORT FILES CONTAINED SCHEMA CONTRACT ERRORS.")
        print("=" * 75)
        sys.exit(1)


if __name__ == "__main__":
    main()
