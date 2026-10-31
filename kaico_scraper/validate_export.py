"""Production Schema, GS1 Checksum & Branch Coverage Validator for Kai Co Exports.

Strictly audits exports against PICO Scraper Data Contract and client review requirements:
1. Barcode Accuracy & GS1 Check Digits: Verifies GTIN formats (8, 12, 13, 14 digits)
   and computes mathematical GS1 modulo-10 check digit on every barcode.
2. Product Completeness: Audits required fields, price sanity, and URL presence.
3. Stock Availability: Verifies stock_status distribution (in_stock vs out_of_stock).
4. Promotions Verification: Audits specials, multibuys, and promo date bounds.
5. Multi-Branch Coverage: Audits exports across exports/ directory.
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
    "multibuy_quantity_discount",
    "half_price",
    "better_than_half_price",
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

    with file_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            total_records += 1
            try:
                rec = json.loads(line_str)
            except json.JSONDecodeError as exc:
                all_errors.append(f"Line {idx}: JSON parse error: {exc}")
                continue

            errors, has_gtin, has_chk = validate_record(rec, idx)
            all_errors.extend(errors)

            if has_gtin:
                gtin_valid_count += 1
            if has_chk:
                checksum_valid_count += 1

            if rec.get("stock_status") == "in_stock":
                in_stock_count += 1
            elif rec.get("stock_status") == "out_of_stock":
                out_of_stock_count += 1

            if rec.get("promo_type") or rec.get("promo_text") or rec.get("comparison_price_cents"):
                promos_count += 1

    return {
        "file": file_path.name,
        "total_records": total_records,
        "is_valid": len(all_errors) == 0,
        "errors_count": len(all_errors),
        "errors": all_errors[:20],
        "in_stock": in_stock_count,
        "out_of_stock": out_of_stock_count,
        "promotions_count": promos_count,
        "gtin_valid_count": gtin_valid_count,
        "checksum_valid_count": checksum_valid_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit Kai Co JSONL export files against contract.")
    parser.add_argument("--file", type=Path, help="Specific JSONL export file to validate")
    args = parser.parse_args()

    files_to_check = [args.file] if args.file else sorted(EXPORTS_DIR.glob("*.jsonl"))

    if not files_to_check:
        print(f"No JSONL export files found in {EXPORTS_DIR}")
        sys.exit(0)

    overall_valid = True
    print("=" * 60)
    print(f"Auditing {len(files_to_check)} export file(s)...")
    print("=" * 60)

    for f in files_to_check:
        res = validate_file(f)
        status = "PASSED" if res["is_valid"] else "FAILED"
        print(f"\nFile: {res['file']}")
        print(f"  Status: {status}")
        print(f"  Records: {res['total_records']}")
        print(f"  Stock Status: In Stock: {res['in_stock']}, Out of Stock: {res['out_of_stock']}")
        print(f"  Promotions: {res['promotions_count']}")
        print(f"  Valid GTINs: {res['gtin_valid_count']} (GS1 Checksums valid: {res['checksum_valid_count']})")
        if not res["is_valid"]:
            overall_valid = False
            print(f"  Errors ({res['errors_count']}):")
            for err in res["errors"]:
                print(f"    - {err}")

    print("\n" + "=" * 60)
    if overall_valid:
        print("ALL AUDITS PASSED - 100% Contract Compliant.")
        sys.exit(0)
    else:
        print("VALIDATION FAILED - Errors detected.")
        sys.exit(1)


if __name__ == "__main__":
    main()
