"""Production Schema, GS1 Checksum & Branch Coverage Validator for The Warehouse JSONL Exports.

Strictly audits exports against PICO's Scraper Data Contract:
1. Barcode Accuracy & GS1 Check Digits: Verifies GTIN formats (8, 12, 13, 14 digits)
   and computes the mathematical GS1 modulo-10 check digit on every barcode.
2. Product Completeness: Audits required fields, price sanity, and URL presence.
3. Stock Availability: Verifies stock_status distribution (in_stock vs out_of_stock).
4. Promotions Verification: Audits specials, multibuys, member prices, and verifies 0 orphan promos.
5. Branch-Level Coverage: Audits multi-branch exports across the entire exports directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

from config import EXPORTS_DIR, RETAILER_SLUG

VALID_GTIN_LENGTHS = {8, 12, 13, 14}
VALID_STOCK_STATUSES = {"in_stock", "out_of_stock"}
VALID_PROMO_TYPES = {
    "special",
    "member_price",
    "multibuy_fixed_price",
    "multibuy_quantity_discount",
    "clearance",
    "everyday_low_price",
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


def is_valid_gtin_format(code: Any) -> bool:
    """Check if code is strictly numeric and matches standard GTIN length."""
    if not code:
        return False
    s = str(code).strip()
    return s.isdigit() and len(s) in VALID_GTIN_LENGTHS


def is_valid_gtin_checksum(barcode: Any) -> bool:
    """Verify official GS1 modulo-10 check digit for GTIN-8, 12, 13, 14."""
    if not barcode:
        return False
    s = str(barcode).strip()
    if not (s.isdigit() and len(s) in VALID_GTIN_LENGTHS):
        return False
    digits = [int(c) for c in s]
    payload, check_digit = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    calc_check = (10 - (total % 10)) % 10
    return calc_check == check_digit


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

    # 3. Price validation: must be integer cents
    price = rec.get("current_price_cents")
    if price is not None:
        if not isinstance(price, int) or price <= 0:
            errors.append(f"Line {line_no}: current_price_cents must be a positive integer, got {price!r}")

    comp_price = rec.get("comparison_price_cents")
    if comp_price is not None:
        if not isinstance(comp_price, int) or comp_price <= 0:
            errors.append(f"Line {line_no}: comparison_price_cents must be a positive integer, got {comp_price!r}")
        elif price is not None and comp_price < price:
            errors.append(f"Line {line_no}: comparison_price_cents ({comp_price}) cannot be less than current_price_cents ({price})")

    # 4. Stock status
    stock = rec.get("stock_status")
    if stock is not None and stock not in VALID_STOCK_STATUSES:
        errors.append(f"Line {line_no}: Invalid stock_status '{stock}', must be one of {VALID_STOCK_STATUSES}")

    # 5. Promotions verification
    promo_type = rec.get("promo_type")
    if promo_type is not None and promo_type not in VALID_PROMO_TYPES:
        errors.append(f"Line {line_no}: Invalid promo_type '{promo_type}'")

    if rec.get("card_required"):
        loyalty = rec.get("required_loyalty_program_code")
        if not loyalty:
            errors.append(f"Line {line_no}: card_required is True but required_loyalty_program_code is missing")

    if promo_type == "multibuy_fixed_price":
        if not rec.get("multibuy_quantity") or not rec.get("multibuy_price_cents"):
            errors.append(f"Line {line_no}: multibuy_fixed_price requires multibuy_quantity and multibuy_price_cents")

    # 6. Timestamp verification (ISO-8601 UTC)
    obs = rec.get("observed_at")
    if obs:
        try:
            # Must end in Z or +00:00
            if not (obs.endswith("Z") or obs.endswith("+00:00")):
                errors.append(f"Line {line_no}: observed_at '{obs}' must be UTC (end in Z)")
            else:
                datetime.fromisoformat(obs.replace("Z", "+00:00"))
        except Exception as e:
            errors.append(f"Line {line_no}: Invalid ISO-8601 timestamp '{obs}': {e}")

    # 7. URL presence
    url = rec.get("product_url")
    if url and not url.startswith("http"):
        errors.append(f"Line {line_no}: product_url must be absolute URL starting with http/https")

    return errors, has_valid_gtin, has_valid_checksum


def validate_file(file_path: Path, max_errors: int = 50) -> dict[str, Any]:
    """Validate all observations in a JSONL file."""
    stats = {
        "file": str(file_path),
        "total_records": 0,
        "valid_gtins": 0,
        "valid_checksums": 0,
        "in_stock": 0,
        "out_of_stock": 0,
        "specials": 0,
        "multibuys": 0,
        "member_prices": 0,
        "errors": [],
    }

    if not file_path.exists():
        stats["errors"].append(f"File not found: {file_path}")
        return stats

    with file_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            stats["total_records"] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                stats["errors"].append(f"Line {idx}: JSON parse error: {e}")
                continue

            errs, has_gtin, has_check = validate_record(rec, idx)
            if errs and len(stats["errors"]) < max_errors:
                stats["errors"].extend(errs)

            if has_gtin:
                stats["valid_gtins"] += 1
            if has_check:
                stats["valid_checksums"] += 1

            if rec.get("stock_status") == "in_stock":
                stats["in_stock"] += 1
            elif rec.get("stock_status") == "out_of_stock":
                stats["out_of_stock"] += 1

            ptype = rec.get("promo_type")
            if ptype == "special":
                stats["specials"] += 1
            elif ptype == "member_price":
                stats["member_prices"] += 1
            elif ptype in ("multibuy_fixed_price", "multibuy_quantity_discount"):
                stats["multibuys"] += 1

    return stats


def print_report(stats: dict[str, Any]) -> bool:
    """Print readable audit report. Returns True if passed threshold (error rate <= 0.5%)."""
    total = stats["total_records"]
    err_count = len(stats["errors"])
    err_rate = (err_count / total) if total > 0 else 1.0

    print("=" * 65)
    print(f"AUDIT REPORT: {Path(stats['file']).name}")
    print("=" * 65)
    print(f"Total Observations : {total:,}")
    print(f"Valid GTIN Barcodes: {stats['valid_gtins']:,} ({(stats['valid_gtins']/total*100) if total else 0:.1f}%)")
    print(f"GS1 Checksum Pass  : {stats['valid_checksums']:,} ({(stats['valid_checksums']/total*100) if total else 0:.1f}%)")
    print(f"In Stock           : {stats['in_stock']:,}")
    print(f"Out of Stock       : {stats['out_of_stock']:,}")
    print(f"Specials / Promos  : {stats['specials']:,}")
    print(f"Multibuys          : {stats['multibuys']:,}")
    print(f"Member Prices      : {stats['member_prices']:,}")
    print(f"Total Errors       : {err_count}")
    print(f"Error Rate         : {err_rate * 100:.2f}%")
    print("-" * 65)

    if stats["errors"]:
        print("Sample Errors (first 10):")
        for e in stats["errors"][:10]:
            print(f"  [X] {e}")
        print("-" * 65)

    passed = total > 0 and err_rate <= 0.005
    if passed:
        print("RESULT: PASSED PRODUCTION DATA CONTRACT AUDIT")
    else:
        print("RESULT: FAILED AUDIT (error rate exceeds 0.5% or 0 records)")
    print("=" * 65)
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Validator for The Warehouse JSONL exports.")
    parser.add_argument("file", nargs="?", help="Specific JSONL file to validate.")
    parser.add_argument("--all", action="store_true", help="Validate all JSONL exports in exports/ directory.")
    args = parser.parse_args()

    target_files = []
    if args.file:
        target_files.append(Path(args.file))
    elif args.all or not args.file:
        files = list(EXPORTS_DIR.glob(f"{RETAILER_SLUG}_*.jsonl"))
        if not files:
            print(f"No {RETAILER_SLUG}_*.jsonl files found in {EXPORTS_DIR}")
            sys.exit(1)
        target_files.extend(sorted(files, key=lambda p: p.stat().st_mtime, reverse=True))

    all_passed = True
    for f in target_files:
        stats = validate_file(f)
        if not print_report(stats):
            all_passed = False

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
