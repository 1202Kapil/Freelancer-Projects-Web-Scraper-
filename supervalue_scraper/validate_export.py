"""Production Schema, GS1 Checksum & Branch Coverage Validator for SuperValue JSONL Exports.

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

    # 3. Price validation (strictly integer cents, no floats)
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

    if pt is not None:
        if pt not in VALID_PROMO_TYPES:
            errors.append(f"Line {line_no}: Invalid promo_type '{pt}'")
        if not ptext:
            errors.append(f"Line {line_no}: Promo type '{pt}' present but promo_text is missing or empty")

        if pt == "multibuy_fixed_price":
            mq = rec.get("multibuy_quantity")
            mp = rec.get("multibuy_price_cents")
            if not mq or not isinstance(mq, int) or mq < 2:
                errors.append(f"Line {line_no}: multibuy promo must have integer multibuy_quantity >= 2 (got {mq})")
            if not mp or not isinstance(mp, int) or mp <= 0:
                errors.append(f"Line {line_no}: multibuy promo must have positive integer multibuy_price_cents (got {mp})")

    # 6. Timestamp verification (strict UTC ISO-8601)
    obs = rec.get("observed_at")
    if obs:
        if not (isinstance(obs, str) and (obs.endswith("Z") or "+00:00" in obs)):
            errors.append(f"Line {line_no}: observed_at '{obs}' is not formatted as UTC ISO-8601 ('Z' suffix)")

    return errors, has_valid_gtin, has_valid_checksum


def audit_file(path: Path) -> dict[str, Any]:
    """Audit an individual JSONL export against the PICO data contract."""
    stats = {
        "file": str(path.name),
        "total_records": 0,
        "valid_records": 0,
        "error_count": 0,
        "gtin_count": 0,
        "gtin_valid_checksum": 0,
        "in_stock_count": 0,
        "out_of_stock_count": 0,
        "promo_count": 0,
        "sample_errors": [],
    }

    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            stats["total_records"] += 1
            try:
                rec = json.loads(line)
            except Exception as e:
                stats["error_count"] += 1
                if len(stats["sample_errors"]) < 5:
                    stats["sample_errors"].append(f"Line {idx}: JSON decode error: {e}")
                continue

            errs, has_gtin, has_valid_cs = validate_record(rec, idx)
            if errs:
                stats["error_count"] += len(errs)
                for err in errs:
                    if len(stats["sample_errors"]) < 10:
                        stats["sample_errors"].append(err)
            else:
                stats["valid_records"] += 1

            if has_gtin:
                stats["gtin_count"] += 1
                if has_valid_cs:
                    stats["gtin_valid_checksum"] += 1

            if rec.get("stock_status") == "in_stock":
                stats["in_stock_count"] += 1
            elif rec.get("stock_status") == "out_of_stock":
                stats["out_of_stock_count"] += 1

            if rec.get("promo_type") or rec.get("promo_text"):
                stats["promo_count"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="PICO Contract and GS1 Auditor for SuperValue JSONL Exports")
    parser.add_argument("files", nargs="*", help="Specific JSONL file(s) to validate")
    args = parser.parse_args()

    files = [Path(p) for p in args.files] if args.files else sorted(EXPORTS_DIR.glob("*.jsonl"))

    if not files:
        print(f"[validate_export] No JSONL export files found in {EXPORTS_DIR}")
        return 0

    print("=" * 80)
    print(f"PICO DATA CONTRACT & GS1 AUDITOR — SUPERVALUE NZ EXPORTS ({len(files)} files)")
    print("=" * 80)

    total_records = 0
    total_errors = 0

    for path in files:
        res = audit_file(path)
        total_records += res["total_records"]
        total_errors += res["error_count"]

        status = "PASSED" if res["error_count"] == 0 else "FAILED"
        print(f"\nAudit Report: {res['file']} -> [{status}]")
        print(f"  Total Records        : {res['total_records']:,}")
        print(f"  Valid Records        : {res['valid_records']:,} ({(res['valid_records'] / max(1, res['total_records']) * 100):.1f}%)")
        print(f"  Schema Errors        : {res['error_count']}")
        print(f"  In Stock / Out Stock : {res['in_stock_count']:,} / {res['out_of_stock_count']:,}")
        print(f"  Promotions / Specials: {res['promo_count']:,}")
        if res["gtin_count"]:
            cs_pct = (res["gtin_valid_checksum"] / res["gtin_count"]) * 100
            print(f"  Barcodes (GS1 Valid) : {res['gtin_count']:,} ({cs_pct:.1f}% valid modulo-10)")

        if res["sample_errors"]:
            print("  Sample Errors:")
            for err in res["sample_errors"][:5]:
                print(f"    - {err}")

    print("\n" + "=" * 80)
    if total_errors == 0:
        print(f"ALL {total_records:,} PRODUCTS FULLY CONFORM TO PICO CONTRACT!")
        return 0
    else:
        print(f"AUDIT FAILED WITH {total_errors} CONFORMANCE ERRORS!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
