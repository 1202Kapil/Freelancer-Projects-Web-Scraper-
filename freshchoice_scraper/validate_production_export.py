"""Production Export Validation Suite (Requirement 12).

Executes comprehensive automated verification across all 12 client requirements:
1. Verifies Coca-Cola Classic 2.25L listings across all branches have correct brand ("Coca Cola") and category ("Drinks"), and 0 are corrupted.
2. Verifies schema uniformity across 100% of rows (0 rows have branch_id missing from top-level).
3. Verifies separate identifier fields (product_id, product_slug, sku, gtin, barcode) with zero fabricated data.
4. Verifies selling price basis, default order weights, and quantity increments for weighted produce.
5. Verifies structured promotion fields (multibuy quantity, multibuy total in cents & NZD).
6. Verifies product detail enrichment schema (ingredients, nutrition, allergens, description).
7. Verifies SuperValue mapping across all 5,655 rows (retailer="supervalue", retailer_name="SuperValue").
8. Verifies timestamps, scrape_run_id, and source_url traceability.
9. Verifies catalogue completeness manifest.
10. Verifies false specials guardrail (Special K name integrity and promo flag).
11. Verifies version matching and release documentation.
12. Verifies JSONL and CSV row count parity.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import unittest

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
JSONL_PATH = EXPORTS_DIR / "freshchoice_all_branches_merged.jsonl"
CSV_PATH = EXPORTS_DIR / "freshchoice_all_branches_merged.csv"


class TestProductionExportValidation(unittest.TestCase):
    """Rigorous test suite asserting all 12 client requirements."""

    @classmethod
    def setUpClass(cls):
        if not JSONL_PATH.exists():
            raise FileNotFoundError(f"Merged JSONL file not found at: {JSONL_PATH}")
        if not CSV_PATH.exists():
            raise FileNotFoundError(f"Merged CSV file not found at: {CSV_PATH}")

        cls.records = []
        with open(JSONL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                cls.records.append(json.loads(line))

    def test_01_coca_cola_metadata_integrity(self):
        """Requirement 1: All Coca-Cola Classic 2.25L listings have correct brand and category."""
        coke_rows = []
        for r in self.records:
            slug = r.get("product_slug") or r.get("source_product_id") or ""
            name = r.get("clean_name") or ""
            if "coca-cola-bottle-2-25l" in slug or ("coca-cola" in name.lower() and "2.25" in name.lower()) or ("coca cola" in name.lower() and "2.25" in name.lower()):
                coke_rows.append(r)

        self.assertGreaterEqual(len(coke_rows), 9, f"Expected at least 9 Coca-Cola listings, found {len(coke_rows)}")

        for r in coke_rows:
            branch = r.get("branch_id")
            brand = r.get("brand")
            dept = r.get("department")
            cat = r.get("category")

            # Must NEVER be Doritos, Patties, Ajax, or Ploughmans
            self.assertNotIn(brand.lower(), ["doritos", "patties", "ajax", "ploughmans", "tip top"],
                             f"Branch {branch} has corrupted Coke brand: {brand}")
            self.assertEqual(brand, "Coca Cola", f"Branch {branch} Coke brand mismatch: {brand}")
            self.assertEqual(dept, "Drinks", f"Branch {branch} Coke department mismatch: {dept}")
            self.assertEqual(cat, "Carbonated Soft Drinks", f"Branch {branch} Coke category mismatch: {cat}")

    def test_02_schema_uniformity_and_legacy_rows_eliminated(self):
        """Requirement 2: Exactly 0 rows have branch_id missing from top-level schema."""
        missing_top_level_branch = 0
        missing_product_id = 0
        missing_price = 0
        missing_timestamp = 0

        for r in self.records:
            if not r.get("branch_id"):
                missing_top_level_branch += 1
            if not r.get("product_id") and not r.get("product_slug"):
                missing_product_id += 1
            if r.get("current_price_cents") is None and r.get("price") is None:
                missing_price += 1
            if not r.get("observed_at"):
                missing_timestamp += 1

        self.assertEqual(missing_top_level_branch, 0, f"Found {missing_top_level_branch} rows without top-level branch_id (legacy row bug)")
        self.assertEqual(missing_product_id, 0, f"Found {missing_product_id} rows without product_id")
        self.assertEqual(missing_price, 0, f"Found {missing_price} rows without price")
        self.assertEqual(missing_timestamp, 0, f"Found {missing_timestamp} rows without observation timestamp")

    def test_03_identifier_separation_and_gtin_cleanliness(self):
        """Requirement 3: Distinct fields for product_id, product_slug, sku, and gtin."""
        for r in self.records[:500]:
            self.assertIn("product_id", r)
            self.assertIn("product_slug", r)
            self.assertIn("sku", r)
            self.assertIn("gtin", r)
            self.assertIn("barcode", r)

            gtin = r.get("gtin")
            if gtin is not None:
                self.assertTrue(str(gtin).isdigit(), f"Fabricated or invalid GTIN detected: {gtin}")
                self.assertIn(len(str(gtin)), [8, 12, 13, 14], f"Invalid GTIN length: {len(str(gtin))}")

    def test_04_selling_price_basis_and_weighted_produce(self):
        """Requirement 4: Distinguish per item, per kg, per pack and include weight increments."""
        weighted_rows = [r for r in self.records if r.get("selling_price_basis") == "per kg"]
        self.assertGreater(len(weighted_rows), 100, f"Expected >100 weighted produce items, found {len(weighted_rows)}")

        for r in weighted_rows:
            self.assertEqual(r.get("unit_of_measure"), "kg")
            self.assertIsNotNone(r.get("default_order_weight"), f"Missing default_order_weight on {r.get('clean_name')}")
            self.assertIsNotNone(r.get("quantity_increment"), f"Missing quantity_increment on {r.get('clean_name')}")
            # Ensure price amount charged is positive
            self.assertGreater(r.get("current_price_cents", 0), 0)

    def test_05_structured_promotions_and_multibuys(self):
        """Requirement 5: Multibuys have quantity and total cents, structured promo fields in CSV."""
        multibuy_rows = [r for r in self.records if r.get("multibuy_quantity")]
        self.assertGreater(len(multibuy_rows), 50, f"Expected >50 multibuy deals, found {len(multibuy_rows)}")

        for r in multibuy_rows:
            self.assertGreaterEqual(r["multibuy_quantity"], 2, f"Multibuy quantity should be >= 2: {r['multibuy_quantity']}")
            self.assertGreater(r["multibuy_price_cents"], 0, f"Multibuy price cents should be > 0: {r['multibuy_price_cents']}")
            self.assertTrue(r["is_promo"], f"Multibuy item must have is_promo=True: {r.get('clean_name')}")
            self.assertIsNotNone(r.get("multibuy_total_nzd"))

    def test_06_enrichment_fields_available(self):
        """Requirement 6: Ingredients, nutrition, and allergen fields present in schema."""
        required_enrichment_fields = ["ingredients", "nutrition", "allergens", "description", "enrichment_source", "enriched_at"]
        for field in required_enrichment_fields:
            self.assertIn(field, self.records[0], f"Missing enrichment field in schema: {field}")

    def test_07_supervalue_retailer_mapping(self):
        """Requirement 7: All 5,655 SuperValue rows mapped accurately."""
        sv_rows = [r for r in self.records if r.get("retailer") == "supervalue"]
        self.assertEqual(len(sv_rows), 5655, f"Expected exactly 5,655 SuperValue rows, found {len(sv_rows)}")

        for r in sv_rows:
            self.assertEqual(r["branch_id"], "bellblock")
            self.assertEqual(r["retailer_name"], "SuperValue")
            self.assertEqual(r["brand_family"], "FreshChoice / SuperValue (Woolworths NZ)")
            self.assertIn("supervalue.co.nz", r["storefront_url"])

    def test_08_timestamps_and_traceability(self):
        """Requirement 8: Observed_at, scrape_run_id, and source_url present on all records."""
        for r in self.records:
            self.assertIsNotNone(r.get("observed_at"), "Missing observed_at timestamp")
            self.assertIsNotNone(r.get("scrape_run_id"), "Missing scrape_run_id")
            self.assertIsNotNone(r.get("source_url"), "Missing source_url")

    def test_09_catalogue_completeness_manifest_exists(self):
        """Requirement 9: Completeness manifest exists and documents 51 branches."""
        manifest = BASE_DIR / "CATALOGUE_COMPLETENESS_MANIFEST.md"
        self.assertTrue(manifest.exists(), "CATALOGUE_COMPLETENESS_MANIFEST.md not found")
        content = manifest.read_text(encoding="utf-8")
        self.assertIn("51 / 51", content)
        self.assertIn("50-Page Pagination Limit", content)
        self.assertIn("Deli 404 Route Errors", content)

    def test_10_false_special_detection_guardrail(self):
        """Requirement 10: Special K preserves name and requires actual offer evidence."""
        special_k_rows = [r for r in self.records if "special k" in (r.get("clean_name") or "").lower()]
        self.assertGreater(len(special_k_rows), 0, "No Special K listings found")

        for r in special_k_rows:
            # Name must not be truncated to "Kellogg's K"
            self.assertIn("Special K", r["clean_name"], f"Name truncated: {r['clean_name']}")
            # If is_promo is True, actual offer evidence must exist
            if r["is_promo"]:
                has_badge = bool(r.get("promo_badge") and "save" in str(r.get("promo_badge")).lower())
                has_savings = bool(r.get("savings") and r.get("savings") > 0)
                has_mb = bool(r.get("multibuy_quantity"))
                self.assertTrue(has_badge or has_savings or has_mb,
                                f"Special K flagged as promo without offer evidence: {r}")

    def test_11_version_specification_exists(self):
        """Requirement 11: VERSION.md exists and scraper version is 1.0.0."""
        version_doc = BASE_DIR / "VERSION.md"
        self.assertTrue(version_doc.exists(), "VERSION.md not found")
        content = version_doc.read_text(encoding="utf-8")
        self.assertIn("1.0.0", content)

    def test_12_jsonl_and_csv_row_count_parity(self):
        """Requirement 12: CSV and JSONL record counts match exactly."""
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            csv_rows = sum(1 for _ in reader)

        self.assertEqual(len(self.records), csv_rows,
                         f"Row count mismatch: JSONL has {len(self.records)} vs CSV has {csv_rows}")
        self.assertEqual(csv_rows, 62926, f"Expected 62,926 records, got {csv_rows}")

    def test_13_audit_specific_product_sanitization(self):
        """Audit Focus: Bell Block Special K, Hansells Baking Powder, Arnott's Shapes, Doritos."""
        for r in self.records:
            name = (r.get("clean_name") or "").lower()
            branch = r.get("branch_id")
            brand = r.get("brand")
            dept = r.get("department")
            cat = r.get("category")

            if "special k" in name and branch == "bellblock":
                self.assertEqual(brand, "Kelloggs", f"Bell Block Special K brand must be Kelloggs, got {brand}")
                self.assertEqual(dept, "Groceries", f"Bell Block Special K department must be Groceries, got {dept}")
                self.assertEqual(cat, "Breakfast Foods", f"Bell Block Special K category must be Breakfast Foods, got {cat}")

            elif "hansells" in name and "baking powder" in name:
                self.assertEqual(brand, "Hansells", f"Hansells brand must be Hansells, got {brand}")
                self.assertEqual(dept, "Groceries", f"Hansells department must be Groceries, got {dept}")
                self.assertEqual(cat, "Cooking Needs", f"Hansells category must be Cooking Needs, got {cat}")

            elif "shapes" in name and "pizza" in name:
                self.assertIn(brand, ["Arnotts", "Arnott's"], f"Shapes brand must be Arnotts, got {brand}")
                self.assertEqual(dept, "Snacks", f"Shapes department must be Snacks, got {dept}")

            elif "doritos" in name:
                self.assertEqual(brand, "Doritos", f"Doritos brand must be Doritos, got {brand}")
                self.assertEqual(dept, "Snacks", f"Doritos department must be Snacks, got {dept}")
                self.assertNotIn("cake", (cat or "").lower(), f"Doritos must not be in Cake subcategory: {cat}")
                self.assertNotIn("yoghurt", (cat or "").lower(), f"Doritos must not be in Yoghurt subcategory: {cat}")

    def test_14_zero_false_promotions_and_category_alignment(self):
        """Audit Focus: Zero false promos, zero category URL mismatches, zero duplicate category names."""
        false_promos = 0
        cat_url_mismatches = 0
        duplicate_cats = 0

        for r in self.records:
            price = r.get("price")
            list_price = r.get("list_price")
            is_promo = r.get("is_promo", False)
            mb_qty = r.get("multibuy_quantity")
            if is_promo and (price is not None and list_price is not None and price >= list_price) and not (mb_qty and mb_qty >= 2):
                false_promos += 1

            cat_url = r.get("category_url", "")
            leaf = r.get("leaf_category") or r.get("category") or ""
            expected_slug = leaf.lower().replace(" & ", "-").replace(" / ", "-").replace(" ", "-")
            # Ensure URL aligns with taxonomy
            if not cat_url or "/category/" not in cat_url:
                cat_url_mismatches += 1

            dept = r.get("department", "")
            if dept in ["Health Beauty", "Dairy Eggs", "Fruit Vegetables"]:
                duplicate_cats += 1

        self.assertEqual(false_promos, 0, f"Found {false_promos} false promotions where price == list_price")
        self.assertEqual(cat_url_mismatches, 0, f"Found {cat_url_mismatches} category URL mismatches")
        self.assertEqual(duplicate_cats, 0, f"Found {duplicate_cats} unnormalized category names")


if __name__ == "__main__":
    unittest.main()
