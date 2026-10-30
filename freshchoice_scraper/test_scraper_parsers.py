"""Unit tests for FreshChoice Scraper parsers and data contract compliance."""
import unittest
from decimal import Decimal
from bs4 import BeautifulSoup

from parsers import (
    is_valid_gtin_checksum,
    clean_product_name,
    extract_size_from_name,
    parse_multibuy,
    parse_product_card,
    parse_product_detail_page,
)
from jsonl_exporter import to_cents, clean_record
from validate_export import validate_record


class TestFreshChoiceParsers(unittest.TestCase):

    def test_gs1_checksum(self):
        # Valid GTIN-13
        self.assertTrue(is_valid_gtin_checksum("9400559000017"))
        # Invalid check digit
        self.assertFalse(is_valid_gtin_checksum("9400559000011"))
        # PLU codes (4 or 5 digits) must fail GTIN check
        self.assertFalse(is_valid_gtin_checksum("4011"))
        self.assertFalse(is_valid_gtin_checksum("4224"))

    def test_to_cents(self):
        self.assertEqual(to_cents(9.30), 930)
        self.assertEqual(to_cents("$9.50"), 950)
        self.assertEqual(to_cents("25.00"), 2500)
        self.assertIsNone(to_cents(None))
        self.assertIsNone(to_cents(""))

    def test_multibuy_parsing(self):
        qty, cents, text = parse_multibuy("Special 3 for $25.00 offer")
        self.assertEqual(qty, 3)
        self.assertEqual(cents, 2500)
        self.assertEqual(text, "3 for $25.00")

    def test_clean_product_name(self):
        self.assertEqual(clean_product_name("SPECIAL Wattie's Baked Beans 420g"), "Wattie's Baked Beans")
        self.assertEqual(clean_product_name("Anchor Blue Milk 2L"), "Anchor Blue Milk")

    def test_size_extraction(self):
        self.assertEqual(extract_size_from_name("Ocean Blue Salmon Smoked Cooking Pieces 125g"), "125g")
        self.assertEqual(extract_size_from_name("Meadow Fresh Milk 2L"), "2L")

    def test_product_card_parsing_regression_multibuy(self):
        # Test case matching v0.7 Green Island regression:
        # "$9.30 each, previously $9.50, and a separate 3-for-$25 offer.
        # The historical export had incorrectly used $25 as the individual price."
        html = """
        <div class="product-item">
            <a href="/lines/ocean-blue-salmon-smoked-cooking-pieces-125g">
                <h3 class="product-title">Ocean Blue Salmon Smoked Cooking Pieces 125g</h3>
            </a>
            <img src="/media/salmon.jpg" alt="Ocean Blue Salmon" />
            <div class="price">$9.30 each</div>
            <div class="was-price">Was $9.50</div>
            <div class="promo-badge">3 for $25</div>
            <button class="add-to-cart">Add</button>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div", class_="product-item")
        parsed = parse_product_card(card, branch_slug="greenisland", category_path="Seafood")

        self.assertIsNotNone(parsed)
        # Regular price must be 930 cents, NOT 2500 cents
        self.assertEqual(parsed["current_price_cents"], 930)
        # Previous price 950 cents
        self.assertEqual(parsed["comparison_price_cents"], 950)
        # Multibuy quantity 3, multibuy price 2500 cents
        self.assertEqual(parsed["multibuy_quantity"], 3)
        self.assertEqual(parsed["multibuy_price_cents"], 2500)
        self.assertEqual(parsed["promo_type"], "multibuy_fixed_price")
        self.assertEqual(parsed["stock_status"], "in_stock")

        # Validate against PICO contract
        clean = clean_record(parsed)
        errs, has_gtin, has_chk = validate_record(clean, line_no=1)
        self.assertEqual(len(errs), 0, f"Validation errors: {errs}")

    def test_product_detail_jsonld(self):
        base_record = {
            "source_product_id": "test-item",
            "retailer_sku": "test-item",
            "raw_name": "Test Item 500g",
            "clean_name": "Test Item",
            "current_price_cents": 500,
            "stock_status": "in_stock",
            "observed_at": "2026-10-29T12:00:00Z",
        }
        detail_html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Test Item 500g",
                "gtin13": "9400559000017",
                "sku": "SKU-999",
                "brand": {"@type": "Brand", "name": "Sanitarium"},
                "description": "Delicious healthy breakfast.",
                "offers": {
                    "availability": "https://schema.org/InStock",
                    "price": "5.00"
                }
            }
            </script>
        </head>
        <body>
            <div class="ingredients">Contains whole wheat, oats.</div>
        </body>
        </html>
        """
        enriched = parse_product_detail_page(detail_html, base_record)
        self.assertEqual(enriched["barcode"], "9400559000017")
        self.assertEqual(enriched["brand"], "Sanitarium")
        self.assertEqual(enriched["retailer_sku"], "SKU-999")
        self.assertIn("Contains whole wheat", enriched["raw_row"].get("ingredients", ""))


if __name__ == "__main__":
    unittest.main()
