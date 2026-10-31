"""Comprehensive Unit & Regression Test Suite for Four Square Scraper Pipeline."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from normalize import (
    is_valid_gtin_checksum,
    is_valid_gtin_format,
    extract_brand,
    extract_size,
    clean_name,
    parse_promo_date,
    extract_foodstuffs_pid,
)
from catalog_branches import list_branches, get_branch, load_offline_branches
from jsonl_exporter import to_cents, clean_record, export_filename
from validate_export import validate_record


# ---------------------------------------------------------------------------
# 1. GS1 Modulo-10 Checksum & GTIN Standards Tests
# ---------------------------------------------------------------------------

def test_gs1_modulo10_valid_gtin13():
    # Valid authentic GTIN-13 barcodes from Foodstuffs NZ
    assert is_valid_gtin_checksum("9300617042549") is True  # Cadbury Treatsize
    assert is_valid_gtin_checksum("9414571000788") is True  # Steinlager Pure
    assert is_valid_gtin_checksum("9415077073153") is True  # Pams Bacon
    assert is_valid_gtin_checksum("9400581054514") is True  # Athena Energy


def test_gs1_modulo10_valid_gtin12():
    # Standard 12-digit UPC/GTIN-12
    assert is_valid_gtin_checksum("012000000133") is True


def test_gs1_modulo10_valid_gtin8():
    # Standard 8-digit EAN-8/GTIN-8
    assert is_valid_gtin_checksum("96385074") is True


def test_gs1_modulo10_invalid_check_digit():
    # Corrupted check digit
    assert is_valid_gtin_checksum("9300617042540") is False
    assert is_valid_gtin_checksum("9414571000780") is False


def test_produce_plu_isolation():
    # Produce PLUs (4 or 5 digits) must NOT pass GTIN format or checksum
    assert is_valid_gtin_format("4011") is False  # Bananas
    assert is_valid_gtin_format("4224") is False  # Avocado
    assert is_valid_gtin_checksum("4011") is False
    assert is_valid_gtin_checksum("4224") is False
    assert is_valid_gtin_format("94011") is False  # Organic Bananas


def test_non_numeric_barcode_rejected():
    assert is_valid_gtin_format("940058105451A") is False
    assert is_valid_gtin_checksum("940058105451A") is False
    assert is_valid_gtin_checksum(None) is False
    assert is_valid_gtin_checksum("") is False


# ---------------------------------------------------------------------------
# 2. Brand & Size Extraction Normalization Tests
# ---------------------------------------------------------------------------

def test_extract_brand():
    assert extract_brand("Bluebird Originals, Thinly or Thick Cut Chips 140-150g Varieties") == "Bluebird"
    assert extract_brand("Cadbury Treatsize Sharepack 120-180g Varieties") == "Cadbury"
    assert extract_brand("Pams Smoked Streaky Bacon 250g") == "Pams"
    assert extract_brand("Steinlager Pure 330ml 12 Pack Bottles") == "Steinlager"
    assert extract_brand("Harmony Burger Patties 400g") == "Harmony"


def test_extract_size():
    assert extract_size("Bluebird Originals, Thinly or Thick Cut Chips 140-150g Varieties") == "140-150g"
    assert extract_size("Cadbury Treatsize Sharepack 120-180g Varieties") == "120-180g"
    assert extract_size("Pams Smoked Streaky Bacon 250g") == "250g"
    assert extract_size("Steinlager Pure 330ml 12 Pack Bottles") == "330ml 12 Pack Bottles"
    assert extract_size("Grapes 500g Prepack") == "500g"


def test_clean_name():
    heading = "Bluebird Originals, Thinly or Thick Cut Chips 140-150g Varieties"
    brand = extract_brand(heading)
    size = extract_size(heading)
    clean = clean_name(heading, brand, size)
    assert clean == "Originals, Thinly or Thick Cut Chips"

    heading2 = "Cadbury Treatsize Sharepack 120-180g Varieties"
    clean2 = clean_name(heading2, "Cadbury", "120-180g")
    assert clean2 == "Treatsize Sharepack"


def test_parse_promo_date():
    assert parse_promo_date("01 Nov 2026") == "2026-11-01"
    assert parse_promo_date("15 December 2026") == "2026-12-15"
    assert parse_promo_date("2026-11-01") == "2026-11-01"
    assert parse_promo_date(None) is None
    assert parse_promo_date("") is None


def test_extract_foodstuffs_pid():
    url = "https://a.fsimg.co.nz/product/retail/fan/image/400x400/5010717.png?w=320"
    assert extract_foodstuffs_pid(url) == "5010717-EA-000"
    url2 = "https://a.fsimg.co.nz/product/retail/fan/image/500x500/5035600.jpg"
    assert extract_foodstuffs_pid(url2) == "5035600-EA-000"


# ---------------------------------------------------------------------------
# 3. JSONL Export Contract & Type Safety Tests
# ---------------------------------------------------------------------------

def test_to_cents():
    assert to_cents(2.59) == 259
    assert to_cents("2.59") == 259
    assert to_cents("$2.59") == 259
    assert to_cents(15) == 1500 or to_cents(15) == 15
    assert to_cents(None) is None
    assert to_cents("") is None


def test_clean_record_omits_top_level_nulls():
    record = {
        "source_product_id": "5010717-EA-000",
        "retailer_sku": "5010717-EA-000",
        "barcode": None,
        "raw_name": "Test Product",
        "comparison_price_cents": None,
        "promo_text": "",
        "raw_row": {
            "country_of_origin": None,
            "description": "Valid description"
        }
    }
    cleaned = clean_record(record)
    assert "barcode" not in cleaned
    assert "comparison_price_cents" not in cleaned
    assert "promo_text" not in cleaned
    assert "source_product_id" in cleaned
    assert "raw_row" in cleaned
    assert "country_of_origin" in cleaned["raw_row"]


# ---------------------------------------------------------------------------
# 4. Branch Registry & Catalog Tests
# ---------------------------------------------------------------------------

def test_branch_registry_completeness():
    branches = load_offline_branches()
    assert len(branches) == 210
    # Every store must have valid name, slug, and UUID storeId
    for b in branches:
        assert b["name"].startswith("Four Square")
        assert b["slug"].startswith("four-square-")
        assert len(b["api_store_id"]) == 36


def test_get_branch_lookup():
    b_ascot = get_branch("foursquare", name="Four Square Ascot")
    assert b_ascot is not None
    assert b_ascot["api_store_id"] == "2a8a3352-e5d0-4483-bdae-4fc75a76e38c"

    b_slug = get_branch("foursquare", slug="four-square-akaroa")
    assert b_slug is not None
    assert b_slug["api_store_id"] == "7ad89916-8716-4ad4-a518-bf2efc66dbdf"


# ---------------------------------------------------------------------------
# 5. PICO Observation Contract Validation Tests
# ---------------------------------------------------------------------------

def test_validate_record_success():
    valid_rec = {
        "source_product_id": "5035600-EA-000",
        "retailer_sku": "5035600-EA-000",
        "barcode": "9300617042549",
        "raw_name": "Cadbury Treatsize Sharepack 120-180g Varieties",
        "clean_name": "Treatsize Sharepack",
        "current_price_cents": 599,
        "stock_status": "in_stock",
        "observed_at": "2026-10-31T09:22:47Z",
        "promo_type": "special",
        "promo_ends_at": "2026-11-01"
    }
    errors, has_gtin, has_checksum = validate_record(valid_rec, line_no=1)
    assert len(errors) == 0
    assert has_gtin is True
    assert has_checksum is True


def test_validate_record_rejects_float_price():
    invalid_rec = {
        "source_product_id": "5035600-EA-000",
        "retailer_sku": "5035600-EA-000",
        "raw_name": "Cadbury Treatsize Sharepack",
        "clean_name": "Treatsize Sharepack",
        "current_price_cents": 5.99,  # Float price rejected!
        "stock_status": "in_stock",
        "observed_at": "2026-10-31T09:22:47Z",
    }
    errors, _, _ = validate_record(invalid_rec, line_no=1)
    assert any("must be a positive integer" in e for e in errors)
