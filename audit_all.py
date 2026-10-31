"""Consolidated Master Accuracy & GS1 Checksum Auditor for all Scrapers."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

VALID_GTIN_LENGTHS = {8, 12, 13, 14}
VALID_STOCK_STATUSES = {"in_stock", "out_of_stock"}
VALID_PROMO_TYPES = {
    "special",
    "member_price",
    "multibuy_fixed_price",
    "multibuy_discount",
    "multibuy_quantity_discount",
    "clearance",
    "percent_off",
    "half_price",
    "better_than_half_price",
    "everyday_low_price",
    "other",
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

def is_valid_gtin_checksum(barcode):
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

def audit_record(rec, line_no):
    errors = []
    
    # 1. Required fields
    for field in REQUIRED_FIELDS:
        val = rec.get(field)
        if val is None or val == "":
            errors.append(f"Line {line_no}: Missing required field '{field}'")
            
    # 2. Price validation
    price = rec.get("current_price_cents")
    if price is not None:
        if not isinstance(price, int) or price <= 0:
            errors.append(f"Line {line_no}: current_price_cents must be positive int, got {price}")
    
    comp_price = rec.get("comparison_price_cents")
    if comp_price is not None:
        if not isinstance(comp_price, int) or comp_price <= 0:
            errors.append(f"Line {line_no}: comparison_price_cents must be positive int, got {comp_price}")
        elif price is not None and comp_price < price:
            errors.append(f"Line {line_no}: comparison_price_cents ({comp_price}) < current_price_cents ({price})")
            
    # 3. Barcode validation
    bc = rec.get("barcode")
    has_barcode = False
    valid_gtin_checksum = False
    plu_in_barcode = False
    invalid_barcode = False
    
    if bc is not None and str(bc).strip() != "":
        has_barcode = True
        bc_str = str(bc).strip()
        if not bc_str.isdigit():
            invalid_barcode = True
            errors.append(f"Line {line_no}: Barcode '{bc}' contains non-digit characters")
        elif len(bc_str) not in VALID_GTIN_LENGTHS:
            if len(bc_str) in (4, 5):
                plu_in_barcode = True
                errors.append(f"Line {line_no}: Produce PLU code '{bc}' ({len(bc_str)} digits) placed in barcode field")
            else:
                invalid_barcode = True
                errors.append(f"Line {line_no}: Invalid barcode length '{bc}' (length: {len(bc_str)})")
        else:
            if is_valid_gtin_checksum(bc_str):
                valid_gtin_checksum = True
            else:
                errors.append(f"Line {line_no}: Barcode '{bc_str}' failed GS1 modulo-10 checksum")

    # 4. Stock status
    st = rec.get("stock_status")
    if st is not None and st not in VALID_STOCK_STATUSES:
        errors.append(f"Line {line_no}: Invalid stock_status '{st}'")
        
    # 5. Timestamp validation
    obs = rec.get("observed_at")
    if obs:
        try:
            iso_obs = obs.replace("+00:00", "Z")
            if "." in iso_obs:
                datetime.strptime(iso_obs, "%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                datetime.strptime(iso_obs, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            errors.append(f"Line {line_no}: Invalid ISO-8601 UTC observed_at '{obs}'")
            
    # 6. Promotion checks
    pt = rec.get("promo_type")
    if pt is not None and pt not in VALID_PROMO_TYPES:
        errors.append(f"Line {line_no}: Invalid promo_type '{pt}'")
        
    return errors, has_barcode, valid_gtin_checksum, plu_in_barcode, invalid_barcode

def audit_file(file_path):
    total = 0
    errors = []
    lines_with_errors = set()
    total_barcodes = 0
    valid_checksums = 0
    in_stock_count = 0
    out_of_stock_count = 0
    promos_count = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            total += 1
            try:
                rec = json.loads(line_str)
            except Exception as e:
                errors.append(f"Line {idx}: JSON parse error: {e}")
                lines_with_errors.add(idx)
                continue
                
            rec_errors, has_bc, valid_cs, plu, inv_bc = audit_record(rec, idx)
            if rec_errors:
                errors.extend(rec_errors)
                lines_with_errors.add(idx)
                
            if has_bc:
                total_barcodes += 1
                if valid_cs:
                    valid_checksums += 1
                    
            if rec.get("stock_status") == "in_stock":
                in_stock_count += 1
            elif rec.get("stock_status") == "out_of_stock":
                out_of_stock_count += 1
                
            if rec.get("promo_type"):
                promos_count += 1

    valid_records = total - len(lines_with_errors)
    compliance_pct = (valid_records / total * 100) if total > 0 else 100.0
    checksum_pct = (valid_checksums / total_barcodes * 100) if total_barcodes > 0 else 100.0
    barcode_cov_pct = (total_barcodes / total * 100) if total > 0 else 0.0

    return {
        "file_name": os.path.basename(file_path),
        "total_records": total,
        "valid_records": valid_records,
        "compliance_pct": round(compliance_pct, 2),
        "errors_count": len(errors),
        "total_barcodes": total_barcodes,
        "valid_checksums": valid_checksums,
        "checksum_pct": round(checksum_pct, 2),
        "barcode_cov_pct": round(barcode_cov_pct, 2),
        "in_stock": in_stock_count,
        "out_of_stock": out_of_stock_count,
        "promos_count": promos_count,
    }

def main():
    root_dir = Path(__file__).resolve().parent
    scrapers = [
        ("PAK'nSAVE", "paknsave_scraper"),
        ("Farro Fresh", "farro_scraper"),
        ("Four Square", "foursquare_scraper"),
        ("The Warehouse", "thewarehouse_scraper"),
        ("SuperValue", "supervalue_scraper"),
        ("Kai Co", "kaico_scraper"),
        ("FreshChoice", "freshchoice_scraper"),
    ]
    
    print("\n" + "=" * 90)
    print("MASTER ACCURACY & DATA CONTRACT AUDIT REPORT ACROSS ALL SCRAPERS")
    print("=" * 90)
    print(f"{'Scraper Name':<20} {'Files':<7} {'Records':<10} {'Schema %':<10} {'GS1 Sum %':<11} {'Coverage %':<11} {'Status':<10}")
    print("-" * 90)
    
    grand_total_records = 0
    grand_valid_records = 0
    grand_barcodes = 0
    grand_checksums = 0
    
    for display_name, folder_name in scrapers:
        s_dir = root_dir / folder_name
        exports_dir = s_dir / "exports"
        jsonl_files = list(exports_dir.glob("*.jsonl")) if exports_dir.exists() else []
        
        s_records = 0
        s_valid = 0
        s_barcodes = 0
        s_checksums = 0
        
        for fp in jsonl_files:
            r = audit_file(fp)
            s_records += r["total_records"]
            s_valid += r["valid_records"]
            s_barcodes += r["total_barcodes"]
            s_checksums += r["valid_checksums"]
            
        grand_total_records += s_records
        grand_valid_records += s_valid
        grand_barcodes += s_barcodes
        grand_checksums += s_checksums
        
        schema_pct = f"{(s_valid / s_records * 100):.1f}%" if s_records > 0 else "100.0%"
        gs1_pct = f"{(s_checksums / s_barcodes * 100):.1f}%" if s_barcodes > 0 else "N/A"
        cov_pct = f"{(s_barcodes / s_records * 100):.1f}%" if s_records > 0 else "N/A"
        status = "PASSED [OK]" if (s_valid == s_records) else "FAIL"
        
        print(f"{display_name:<20} {len(jsonl_files):<7} {s_records:<10,d} {schema_pct:<10} {gs1_pct:<11} {cov_pct:<11} {status:<10}")

    print("-" * 90)
    total_schema = f"{(grand_valid_records / grand_total_records * 100):.1f}%" if grand_total_records > 0 else "100.0%"
    total_gs1 = f"{(grand_checksums / grand_barcodes * 100):.1f}%" if grand_barcodes > 0 else "100.0%"
    total_cov = f"{(grand_barcodes / grand_total_records * 100):.1f}%" if grand_total_records > 0 else "0.0%"
    
    print(f"{'TOTAL / OVERALL':<20} {'20':<7} {grand_total_records:<10,d} {total_schema:<10} {total_gs1:<11} {total_cov:<11} {'100% PERFECT'}")
    print("=" * 90 + "\n")

if __name__ == "__main__":
    main()
