"""Unit tests for SuperValue scraper parsers, GS1 checksums, and PICO contract compliance."""
from __future__ import annotations

from decimal import Decimal
import pytest
from bs4 import BeautifulSoup

from models import Branch, Product, Promotion
from parsers import (
    is_valid_gtin_checksum,
    clean_product_name,
    extract_size_from_name,
    parse_multibuy,
    parse_talker_card,
    parse_detail_page,
)
from jsonl_exporter import to_cents, clean_record
from validate_export import validate_record


def test_gs1_modulo10_checksum():
    """Verify GS1 Modulo-10 check digit algorithm across valid and invalid barcodes."""
    # Valid GTIN-13
    assert is_valid_gtin_checksum("9400559001014") is True
    # Valid GTIN-12 (UPC-A)
    assert is_valid_gtin_checksum("012345678905") is True
    # Valid GTIN-8
    assert is_valid_gtin_checksum("96385074") is True
    # Valid GTIN-14
    assert is_valid_gtin_checksum("10012345678902") is True

    # Invalid check digit (tampered last digit)
    assert is_valid_gtin_checksum("9400559001019") is False
    assert is_valid_gtin_checksum("9400559001018") is False

    # Produce PLU codes (4 and 5 digits) must NOT be validated as GTINs
    assert is_valid_gtin_checksum("4011") is False  # Bananas PLU
    assert is_valid_gtin_checksum("4224") is False  # Avocado PLU
    assert is_valid_gtin_checksum("94011") is False  # Organic Bananas PLU

    # Non-numeric or empty
    assert is_valid_gtin_checksum("") is False
    assert is_valid_gtin_checksum(None) is False
    assert is_valid_gtin_checksum("ABC1234567890") is False


def test_to_cents():
    """Test safe conversion of dollar strings, floats, ints to integer cents."""
    assert to_cents(4.79) == 479
    assert to_cents("4.79") == 479
    assert to_cents("$4.79") == 479
    assert to_cents("$12.50") == 1250
    assert to_cents("0.99") == 99
    assert to_cents(100) == 100
    assert to_cents(None) is None
    assert to_cents("") is None


def test_parse_multibuy():
    """Test bundle promo parsing and parameter isolation."""
    qty, cents, text = parse_multibuy("Any 3 for $25.00 Mix & Match")
    assert qty == 3
    assert cents == 2500
    assert "3 for $25.00" in text

    qty, cents, text = parse_multibuy("2 for $5")
    assert qty == 2
    assert cents == 500

    qty, cents, text = parse_multibuy("Regular single item $4.50")
    assert qty is None
    assert cents is None


def test_clean_product_name():
    """Test product name sanitation and removal of packaging units and promo banners."""
    assert clean_product_name("Tip Top Bread Oatilicious Toast 700g") == "Tip Top Bread Oatilicious Toast"
    assert clean_product_name("SPECIAL Kit Kat Milk Chocolate Block 160g") == "Kit Kat Milk Chocolate Block"
    assert clean_product_name("Bluebird Potato Chips 150g $1.99") == "Bluebird Potato Chips"
    assert clean_product_name("Fresh Milk 2L") == "Fresh Milk"


def test_extract_size_from_name():
    """Test extraction of size units."""
    assert extract_size_from_name("Tip Top Bread 700g") == "700g"
    assert extract_size_from_name("Anchor Blue Milk 2L") == "2L"
    assert extract_size_from_name("Banana Bunch 1.5kg") == "1.5kg"
    assert extract_size_from_name("Eggs 12 pack") == "12 pack"


def test_parse_talker_card():
    """Test parsing of a real SuperValue MyFoodLink talker DOM structure."""
    html_card = """
    <div class="talker talker--row special" data-line-control='{"quantity":{"id":"5e7957ebf605cc7534075790"}}' id="line_5e7957ebf605cc7534075790">
      <div class="talker__imagery">
        <a href="/lines/tip-top-bread-oatilicious-toast-700g">
          <img src="https://dtgxwmigmg3gc.cloudfront.net/imagery/assets/img.jpg" alt="Photo of Tip Top Bread Oatilicious Toast" />
        </a>
        <div class="talker__stickers">
          <span>save $1.20</span>
        </div>
      </div>
      <div class="talker__details">
        <div class="talker__name" title="Tip Top Bread Oatilicious Toast 700g">
          <span class="talker__product-name">Tip Top Bread Oatilicious Toast</span>
          <span class="weak size talker__name__size">700g</span>
        </div>
        <div class="talker__prices">
          <span>was $5.99</span>
          <span class="talker__prices__sell"><strong class="price__sell">$4.79</strong><span class="price__units">each</span></span>
          <span class="talker__prices__comparison talker__prices__comparison--UnitPrice">$0.68 per 100g</span>
        </div>
      </div>
    </div>
    """
    soup = BeautifulSoup(html_card, "html.parser")
    card = soup.find("div", class_="talker")

    branch = Branch(
        id="milton",
        name="Milton",
        url="https://milton.store.supervalue.co.nz",
    )

    product = parse_talker_card(card, branch, ["Bakery", "Bread"], "https://milton.store.supervalue.co.nz/category/bakery")
    assert product is not None
    assert product.product_id == "5e7957ebf605cc7534075790"
    assert product.name == "Tip Top Bread Oatilicious Toast"
    assert product.pricing_unit == "700g"
    assert product.price_nzd == Decimal("4.79")
    assert product.unit_price_nzd == Decimal("0.68")
    assert product.unit_price_basis == "100g"
    assert product.promotion is not None
    assert product.promotion.previous_price_nzd == Decimal("5.99")
    assert product.promotion.savings_nzd == Decimal("1.20")
    assert product.availability == "in_stock"

    # Convert to PICO contract
    contract = product.to_pico_contract()
    assert contract["source_product_id"] == "5e7957ebf605cc7534075790"
    assert contract["retailer_sku"] == "5e7957ebf605cc7534075790"
    assert contract["clean_name"] == "Tip Top Bread Oatilicious Toast"
    assert contract["current_price_cents"] == 479
    assert contract["comparison_price_cents"] == 599
    assert contract["unit_price_cents"] == 68
    assert contract["unit_label"] == "100g"
    assert contract["stock_status"] == "in_stock"
    assert contract["promo_type"] == "special"
    assert contract["promo_metadata"]["savings_cents"] == 120
    assert contract["category_path"] == "Bakery > Bread"

    # Validate against production auditor
    errors, has_gtin, has_cs = validate_record(contract, 1)
    assert len(errors) == 0


def test_pico_contract_validation():
    """Verify that validate_record detects contract violations."""
    valid_rec = {
        "source_product_id": "test_123",
        "retailer_sku": "sku_123",
        "barcode": "9400559001014",
        "raw_name": "Test Bread 500g",
        "clean_name": "Test Bread",
        "current_price_cents": 350,
        "stock_status": "in_stock",
        "observed_at": "2026-10-30T12:00:00Z",
    }
    errs, has_gtin, has_cs = validate_record(valid_rec, 1)
    assert len(errs) == 0
    assert has_gtin is True
    assert has_cs is True

    # Bad price float / negative
    bad_price = dict(valid_rec, current_price_cents=-10)
    errs, _, _ = validate_record(bad_price, 1)
    assert any("positive integer" in e for e in errs)

    # Bad barcode checksum
    bad_bc = dict(valid_rec, barcode="9400559001019")
    errs, _, _ = validate_record(bad_bc, 1)
    assert any("checksum validation" in e for e in errs)

    # Produce PLU leak into barcode
    plu_leak = dict(valid_rec, barcode="4011")
    errs, _, _ = validate_record(plu_leak, 1)
    assert any("PLU code" in e for e in errs)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
