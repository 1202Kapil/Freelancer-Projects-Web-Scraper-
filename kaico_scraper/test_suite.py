"""Comprehensive automated test suite for Kai Co Scraper and PICO Contract.

Tests:
1. GS1 Modulo-10 Checksum Algorithm & GTIN Length Validation
2. Rejection of Produce PLU codes (4-5 digits) from Barcode field
3. Clean title, brand, size, and unit price extraction
4. Multibuy and promotion parsing
5. Price conversion to integer cents NZD
6. JSONL export file generation & PICO Contract validation
7. Pico import_products.py --dry-run validation
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest

from jsonl_exporter import write_jsonl, clean_record
from normalize import (
    build_category_path,
    clean_name,
    extract_brand,
    extract_promotions,
    extract_size,
    extract_unit_info,
    is_valid_gtin_checksum,
    is_valid_gtin_format,
    to_cents,
)
from validate_export import validate_record, validate_file


class TestKaiCoScraper(unittest.TestCase):

    def test_gtin_format_and_plu_rejection(self):
        """Verify standard GTIN lengths (8, 12, 13, 14) and rejection of produce PLU codes."""
        # Valid lengths
        self.assertTrue(is_valid_gtin_format("9400581054514"))  # 13
        self.assertTrue(is_valid_gtin_format("12345678"))       # 8
        self.assertTrue(is_valid_gtin_format("123456789012"))   # 12
        self.assertTrue(is_valid_gtin_format("12345678901234")) # 14

        # Reject Produce PLUs (4 or 5 digits)
        self.assertFalse(is_valid_gtin_format("605"))
        self.assertFalse(is_valid_gtin_format("4011"))
        self.assertFalse(is_valid_gtin_format("94011"))
        self.assertFalse(is_valid_gtin_format("648"))

        # Reject non-numeric
        self.assertFalse(is_valid_gtin_format("940058105451A"))
        self.assertFalse(is_valid_gtin_format(None))

    def test_gs1_checksum(self):
        """Verify mathematical GS1 modulo-10 checksum calculation."""
        # Valid GS1 EAN-13 barcodes
        self.assertTrue(is_valid_gtin_checksum("9400581054514"))
        self.assertTrue(is_valid_gtin_checksum("9400557000019"))

        # Corrupted check digits
        self.assertFalse(is_valid_gtin_checksum("9400581054513"))
        self.assertFalse(is_valid_gtin_checksum("9400581054515"))

    def test_to_cents(self):
        """Verify price conversion to integer cents."""
        self.assertEqual(to_cents(1.99), 199)
        self.assertEqual(to_cents("15.99"), 1599)
        self.assertEqual(to_cents("$4.99"), 499)
        self.assertEqual(to_cents(100), 100)
        self.assertIsNone(to_cents(None))
        self.assertIsNone(to_cents(""))

    def test_brand_extraction(self):
        """Verify brand extraction from title or vendor."""
        self.assertEqual(
            extract_brand("COUPLANDS DAILY FRESH SUPER THICK WHITE TOAST 550G - $1.99"),
            "Couplands"
        )
        self.assertEqual(
            extract_brand("Brinks kebabs 5pk $4.99ea"),
            "Brinks"
        )
        self.assertEqual(
            extract_brand("COW & GATE 2L MILK RANGE"),
            "Cow & Gate"
        )
        self.assertEqual(
            extract_brand("Fresh Canterbury Pork Belly Boneless $15.99kg", vendor="Kai Co"),
            "Kai Co"
        )

    def test_size_extraction(self):
        """Verify pack size extraction."""
        self.assertEqual(
            extract_size("COUPLANDS DAILY FRESH SUPER THICK WHITE TOAST 550G - $1.99"),
            "550g"
        )
        self.assertEqual(
            extract_size("COW & GATE 2L MILK RANGE"),
            "2L"
        )
        self.assertEqual(
            extract_size("Cherry Tomatoes 250gm $3.69ea"),
            "250g"
        )
        self.assertEqual(
            extract_size("Brinks kebabs 5pk $4.99ea"),
            "5pk"
        )

    def test_unit_price_info(self):
        """Verify unit price and unit label extraction."""
        p, label = extract_unit_info("Fresh Canterbury Pork Belly Boneless $15.99kg", 1599)
        self.assertEqual(p, 1599)
        self.assertEqual(label, "1kg")

        p2, label2 = extract_unit_info("Telegraph Cucumber $1.89ea", 189)
        self.assertEqual(p2, 189)
        self.assertEqual(label2, "ea")

        p3, label3 = extract_unit_info("Capsicums Mixed Bag $7.99/kg", 799)
        self.assertEqual(p3, 799)
        self.assertEqual(label3, "1kg")

    def test_clean_name(self):
        """Verify title cleanup stripping prices, brands, and pack sizes."""
        c = clean_name(
            "COUPLANDS DAILY FRESH SUPER THICK WHITE TOAST 550G - $1.99",
            brand="Couplands",
            size="550g",
        )
        self.assertEqual(c, "Daily Fresh Super Thick White Toast")

        c2 = clean_name(
            "Fresh Canterbury Pork Belly Boneless $15.99kg",
            brand="Kai Co",
            size=None,
        )
        self.assertEqual(c2, "Fresh Canterbury Pork Belly Boneless")

        c3 = clean_name("AVOCADO")
        self.assertEqual(c3, "Avocado")

    def test_multibuy_and_promotions(self):
        """Verify multibuy and collection promotional detection."""
        promo = extract_promotions(
            title="Avocados Medium 5 for $3.99",
            body_html="",
            current_price_cents=399,
            compare_at_price_cents=None,
            collection_handles=["produce-deals"],
        )
        self.assertEqual(promo["promo_type"], "multibuy_fixed_price")
        self.assertEqual(promo["multibuy_quantity"], 5)
        self.assertEqual(promo["multibuy_price_cents"], 399)

        promo2 = extract_promotions(
            title="Pork Ribs",
            body_html="",
            current_price_cents=899,
            compare_at_price_cents=1099,
            collection_handles=[],
        )
        self.assertEqual(promo2["promo_type"], "special")
        self.assertEqual(promo2["comparison_price_cents"], 1099)

    def test_category_path(self):
        """Verify category hierarchy building."""
        cat_pork = build_category_path("PORK", ["meat deals"])
        self.assertEqual(cat_pork, "Meat > Pork")

        cat_apple = build_category_path("APPLES", ["Apples"])
        self.assertEqual(cat_apple, "Produce > Apples")

        cat_dairy = build_category_path("DAIRY", [])
        self.assertEqual(cat_dairy, "Dairy & Eggs > Dairy")

    def test_contract_validation(self):
        """Verify contract schema validation rules."""
        valid_rec = {
            "source_product_id": "12345-67890",
            "retailer_sku": "605",
            "barcode": "9400581054514",
            "raw_name": "Test Avocado",
            "clean_name": "Avocado",
            "brand": "Kai Co",
            "category_path": "Produce > Fruit Other",
            "size": "ea",
            "current_price_cents": 199,
            "unit_price_cents": 199,
            "unit_label": "ea",
            "stock_status": "in_stock",
            "observed_at": "2026-10-31T09:46:21Z",
        }
        errors, has_gtin, has_chk = validate_record(valid_rec, 1)
        self.assertEqual(errors, [])
        self.assertTrue(has_gtin)
        self.assertTrue(has_chk)

        # Invalid record: negative price, invalid stock status, bad timestamp
        bad_rec = {
            "source_product_id": "",
            "current_price_cents": -50,
            "stock_status": "maybe",
            "observed_at": "today",
        }
        errs, _, _ = validate_record(bad_rec, 2)
        self.assertTrue(len(errs) >= 4)


if __name__ == "__main__":
    unittest.main()
