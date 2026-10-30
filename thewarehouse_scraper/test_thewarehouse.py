"""Comprehensive verification test suite for The Warehouse NZ scraper pipeline."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from catalog_branches import get_branch, list_branches
from config import RETAILER_SLUG
from jsonl_exporter import clean_record, export_filename, to_cents
from normalize import (
    clean_barcode,
    clean_product_name,
    extract_size,
    format_category_path,
    is_valid_gtin_checksum,
    parse_promotions,
)
from validate_export import validate_record


def test_gtin_checksum_validation():
    """Verify authentic New Zealand GTIN barcodes and check digit math."""
    # GTIN-8
    assert is_valid_gtin_checksum("94150957") is True
    # GTIN-13
    assert is_valid_gtin_checksum("9415767677685") is True
    assert is_valid_gtin_checksum("4003084880700") is True
    assert is_valid_gtin_checksum("9415767018204") is True
    assert is_valid_gtin_checksum("6941607366479") is True

    # Bad check digit
    assert is_valid_gtin_checksum("9415767677684") is False
    assert is_valid_gtin_checksum("4003084880701") is False

    # Invalid lengths / formats (e.g. 4-digit produce PLU)
    assert is_valid_gtin_checksum("4011") is False
    assert is_valid_gtin_checksum("4224") is False
    assert is_valid_gtin_checksum("R151415") is False
    assert is_valid_gtin_checksum(None) is False
    assert is_valid_gtin_checksum("") is False


def test_clean_barcode_sanitization():
    """clean_barcode must return valid GTIN or None."""
    assert clean_barcode("9415767677685") == "9415767677685"
    assert clean_barcode("94150957") == "94150957"
    assert clean_barcode("4011") is None
    assert clean_barcode("invalid_sku") is None
    assert clean_barcode(None) is None


def test_to_cents_conversion():
    """Prices must convert to integer cents, never floats."""
    assert to_cents("9.49") == 949
    assert to_cents("$9.49") == 949
    assert to_cents(9.49) == 949
    assert to_cents(15) == 1500
    assert to_cents("15") == 1500
    assert to_cents("$1,299.99") == 129999
    assert to_cents(None) is None
    assert to_cents("") is None


def test_extract_size():
    """Extract product volume, weight, and pack descriptors."""
    assert extract_size("V Energy Drink Original 250ml 4 Pack") == "250ml"
    assert extract_size("Trolli Multi Mix 500g") == "500g"
    assert extract_size("Indomie Mi Goreng 5 Pack White 85g") == "5 Pack"
    assert extract_size("Bestway Steel Pro Max 4.27m 14ft") == "4.27m"
    assert extract_size("Generic Item No Size") is None


def test_clean_product_name():
    """Verify clean name formatting."""
    assert clean_product_name("V Energy Drink Original 250ml 4 Pack", brand="V") == "Energy Drink Original 250ml 4 Pack"
    assert clean_product_name("Trolli Multi Mix 500g", brand="Trolli") == "Multi Mix 500g"
    assert clean_product_name("Indomie Mi Goreng", brand=None) == "Indomie Mi Goreng"


def test_format_category_path():
    """Format category hierarchy into standard breadcrumb string."""
    cgid = "foodhouseholdpets-fooddrink-colddrinks-sportsenergydrinks"
    formatted = format_category_path(cgid)
    assert "Food" in formatted
    assert "Cold Drinks" in formatted
    assert " > " in formatted

    # Slashed path
    assert format_category_path("food/drinks/cola") == "Food > Drinks > Cola"


def test_parse_promotions():
    """Audits specials, multibuys, member prices, and verifies 0 orphan promos."""
    # 1. Multibuy
    mb = parse_promotions(
        price_cents=300,
        then_price_cents=None,
        badges="badge_2_for_6.00",
        claim=None,
    )
    assert mb["promo_type"] == "multibuy_fixed_price"
    assert mb["multibuy_quantity"] == 2
    assert mb["multibuy_price_cents"] == 600
    assert mb["promo_text"] == "2 for $6.00"

    # 2. Special with Was / Then Price
    sp = parse_promotions(
        price_cents=999,
        then_price_cents=1099,
        badges="badge_specials",
        claim="Save $1.00",
    )
    assert sp["promo_type"] == "special"
    assert sp["comparison_price_cents"] == 1099
    assert sp["promo_text"] == "Save $1.00"

    # 3. MarketClub Member Price
    mc = parse_promotions(
        price_cents=800,
        then_price_cents=1000,
        badges="badge_marketclub_exclusive",
        claim="MarketClub Price",
    )
    assert mc["promo_type"] == "member_price"
    assert mc["card_required"] is True
    assert mc["required_loyalty_program_code"] == "marketclub"
    assert mc["comparison_price_cents"] == 1000

    # 4. Regular Shelf Pricing (no promo)
    reg = parse_promotions(
        price_cents=949,
        then_price_cents=949,
        badges="na",
        claim=None,
    )
    assert reg["promo_type"] is None
    assert reg["comparison_price_cents"] is None
    assert reg["promo_text"] is None
    assert reg["card_required"] is None


def test_clean_record():
    """Ensure None and empty top-level fields are omitted per client contract."""
    raw = {
        "source_product_id": "R12345",
        "clean_name": "Test Product",
        "current_price_cents": 500,
        "comparison_price_cents": None,
        "promo_text": "",
        "raw_row": {"original_id": "12345"},
    }
    cleaned = clean_record(raw)
    assert "source_product_id" in cleaned
    assert "comparison_price_cents" not in cleaned
    assert "promo_text" not in cleaned
    assert "raw_row" in cleaned


def test_export_filename_format():
    """Verify filename format: {retailer}_{branch-slug}_{timestamp}.jsonl."""
    fn = export_filename("thewarehouse", "thewarehouse-auckland-central")
    assert fn.startswith("thewarehouse_thewarehouse-auckland-central_")
    assert fn.endswith(".jsonl")


def test_branch_catalog():
    """Verify branch discovery and lookup."""
    branches = list_branches()
    assert len(branches) >= 70

    b = get_branch("221")
    assert b is not None
    assert b["slug"] == "thewarehouse-auckland-central"
    assert "Auckland Central" in b["name"]


def test_validate_record():
    """Test validation logic against contract rules."""
    valid_rec = {
        "source_product_id": "R666174",
        "retailer_sku": "R666174",
        "barcode": "9415767677685",
        "raw_name": "V Energy Drink Original 250ml 4 Pack",
        "clean_name": "Energy Drink Original 250ml 4 Pack",
        "current_price_cents": 949,
        "stock_status": "in_stock",
        "observed_at": "2026-10-30T12:00:00Z",
        "product_url": "https://www.thewarehouse.co.nz/p/v-energy-drink/R666174.html",
    }
    errs, has_gtin, has_check = validate_record(valid_rec, 1)
    assert len(errs) == 0
    assert has_gtin is True
    assert has_check is True

    # Bad check digit record
    bad_rec = dict(valid_rec)
    bad_rec["barcode"] = "9415767677684"  # wrong check digit
    errs, has_gtin, has_check = validate_record(bad_rec, 2)
    assert any("failed GS1 modulo-10 checksum" in e for e in errs)
    assert has_check is False

    # Float price instead of cents
    bad_price = dict(valid_rec)
    bad_price["current_price_cents"] = 9.49  # float!
    errs, _, _ = validate_record(bad_price, 3)
    assert any("must be a positive integer" in e for e in errs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
