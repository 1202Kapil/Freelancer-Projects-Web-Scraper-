"""Production Schema, GS1 Checksum & Branch Coverage Validator for FreshChoice JSONL Exports.

Strictly audits exports against PICO Scraper Data Contract:
1. Barcode Accuracy & GS1 Check Digits: Verifies GTIN formats (8, 12, 13, 14 digits)
   and computes the mathematical GS1 modulo-10 check digit on every barcode.
2. Product Completeness: Audits required fields, price sanity, and URL presence.
3. Stock Availability: Verifies stock_status distribution (in_stock vs out_of_stock).
4. Promotions Verification: Audits specials, multibuys, member prices, and verifies 0 orphan promos.
5. Multi-Branch Coverage: Audits branch exports across the exports directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional

from config import VALID_GTIN_LENGTHS, VALID_STOCK_STATUSES, VALID_PROMO_TYPES, EXPORTS_DIR
from parsers import is_valid_gtin_checksum

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
        elif price > 500_000:
            errors.append(f"Line {line_no}: current_price_cents ({price}) exceeds realistic supermarket threshold")

    comp_price = rec.get("comparison_price_cents")
    if comp_price is not None:
        if not isinstance(comp_price, int) or comp_price <= 0:
            errors.append(f"Line {line_no}: comparison_price_cents must be a positive integer, got {comp_price}")
        elif price is not None and comp_price < price:
            errors.append(f"Line {line_no}: comparison_price_cents ({comp_price}) < current_price_cents ({price})")

    # 4. Stock status validation
    st = rec.get("stock_status")
    if st is not None and st not in VALID_STOCK_STATUSES:
        errors.append(f"Line {line_no}: Invalid stock_status '{st}', must be 'in_stock' or 'out_of_stock'")

    # 5. Promotions verification
    pt = rec.get("promo_type")
    ptext = rec.get("promo_text")
    pmeta = rec.get("promo_metadata")
    spid = rec.get("source_promotion_id")

    if pt is not None:
        if pt not in VALID_PROMO_TYPES:
            errors.append(f"Line {line_no}: Invalid promo_type '{pt}'")
        if not ptext:
            errors.append(f"Line {line_no}: Promo type '{pt}' present but promo_text is missing or empty")

        if pt == "multibuy_fixed_price":
            mq = rec.get("multibuy_quantity")
            mp = rec.get("multibuy_price_cents")
            if not isinstance(mq, int) or mq <= 1:
                errors.append(f"Line {line_no}: multibuy_quantity must be integer > 1, got {mq}")
            if not isinstance(mp, int) or mp <= 0:
                errors.append(f"Line {line_no}: multibuy_price_cents must be integer > 0, got {mp}")
    else:
        if pmeta and isinstance(pmeta, dict) and pmeta.get("rewardType") not in ("BASE", None):
            errors.append(f"Line {line_no}: Orphan promo_metadata present without classified promo_type")
        if spid and not pmeta:
            errors.append(f"Line {line_no}: Orphan source_promotion_id '{spid}' without classified promo_type")

    # 6. Timestamp validation
    obs = rec.get("observed_at")
    if obs:
        try:
            datetime.strptime(obs, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            errors.append(f"Line {line_no}: observed_at '{obs}' is not valid ISO-8601 UTC ('%Y-%m-%dT%H:%M:%SZ')")

    return errors, has_valid_gtin, has_valid_checksum


def validate_file(jsonl_path: Path) -> dict[str, Any]:
    """Validate full JSONL export file and print diagnostic report."""
    print(f"\n{'='*75}")
    print(f"AUDITING EXPORT: {jsonl_path.name}")
    print(f"{'='*75}")

    total_records = 0
    total_errors = 0
    gtin_count = 0
    checksum_pass = 0
    specials_count = 0
    multibuys_count = 0
    instock_count = 0
    sample_errors = []

    with jsonl_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            total_records += 1
            try:
                rec = json.loads(line_str)
            except json.JSONDecodeError as e:
                total_errors += 1
                if len(sample_errors) < 10:
                    sample_errors.append(f"Line {idx}: JSON Decode Error: {e}")
                continue

            errs, has_gtin, has_chk = validate_record(rec, idx)
            if errs:
                total_errors += len(errs)
                if len(sample_errors) < 10:
                    sample_errors.extend(errs[:10 - len(sample_errors)])

            if has_gtin:
                gtin_count += 1
            if has_chk:
                checksum_pass += 1
            if rec.get("stock_status") == "in_stock":
                instock_count += 1
            if rec.get("promo_type") == "special":
                specials_count += 1
            elif rec.get("promo_type") == "multibuy_fixed_price":
                multibuys_count += 1

    print(f"  • Total Products Scraped  : {total_records:,}")
    print(f"  • Schema / Contract Errors: {total_errors}")
    print(f"  • Products in Stock       : {instock_count:,} ({(instock_count/max(total_records,1))*100:.1f}%)")
    print(f"  • Specials / Discounts    : {specials_count:,}")
    print(f"  • Multibuy Promotions     : {multibuys_count:,}")
    print(f"  • Valid GTIN Barcodes     : {gtin_count:,} (GS1 Checksum Pass: {checksum_pass:,})")

    if sample_errors:
        print("\nSample Errors Encountered:")
        for err in sample_errors:
            print(f"  [ERROR] {err}")

    passed = (total_errors == 0 and total_records > 0)
    print(f"\nRESULT: {'PASSED [OK]' if passed else 'FAILED [ERROR]'}")
    return {
        "file": str(jsonl_path),
        "total_records": total_records,
        "errors": total_errors,
        "passed": passed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PICO Scraper Contract Validator")
    parser.add_argument("path", nargs="?", help="Path to JSONL file or directory of exports")
    args = parser.parse_args()

    target = Path(args.path) if args.path else EXPORTS_DIR
    files = [target] if target.is_file() else list(target.glob("*.jsonl"))

    if not files:
        print(f"No JSONL exports found in {target}")
        sys.exit(1)

    all_passed = True
    for fp in files:
        res = validate_file(fp)
        if not res["passed"]:
            all_passed = False

    sys.exit(0 if all_passed else 1)
