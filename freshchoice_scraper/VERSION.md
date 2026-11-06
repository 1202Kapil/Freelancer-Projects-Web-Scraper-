# Release Specification & Reproduction Guide: FreshChoice Scraper v1.0.0

## 1. Version Overview

- **Software Version:** `1.0.0` (Production Gold Release)
- **Previous Pilot Version:** `0.7.2` (Deprecated Local Pilot)
- **Release Date:** November 5, 2026
- **Architecture:** Asynchronous Event-Driven Web & DOM Scraper with Intelligent DataLayer Joining
- **Contract Compliance:** Strict PICO Scraper Data Contract (Integer cents, UTC ISO timestamps, zero fabricated data)

---

## 2. Comparison: Local Pilot v0.7 vs Production v1.0.0

| Feature / Requirement | Local Pilot v0.7 | Production Release v1.0.0 |
| :--- | :--- | :--- |
| **GTM / DOM Metadata Joining** | Matched by integer loop index `idx`, causing off-by-one corruption from banner/mailer cards | Intelligent multi-factor matching (`match_gtm_item`) using `item_id`, token intersection, and DOM `<a href='/lines/'>` strict filtering |
| **Schema Uniformity** | 8,986 legacy rows contained `branch_id` and pricing only inside `raw_row` | **100% Uniform Schema** across all 62,926 records. 0 rows missing top-level identifiers |
| **SuperValue Mapping** | Storefront URLs stored without retailer banner disambiguation | Explicit `retailer="supervalue"`, `retailer_name="SuperValue"`, and `brand_family="FreshChoice / SuperValue (Woolworths NZ)"` |
| **Selling Price Basis** | Unit prices collapsed or merged into pricing unit strings | Explicit separation of `selling_price_basis` (`each`, `per kg`, `per pack`), `default_order_weight`, and `quantity_increment` |
| **Structured Promotions** | CSV dropped multibuy fields; regex falsely flagged "Special" in product names | Full structured promotion fields in both CSV and JSONL (`promo_type`, `multibuy_quantity`, `multibuy_price_cents`, `multibuy_total_nzd`, `savings`) |
| **False Special Detection** | Title regex stripped "Special" from names (e.g. `Special K` -> `K`) and flagged promo | Genuine offer evidence required (verified discount badge, was-price, multibuy). Title names preserved |
| **Enrichment & Traceability** | Missing PDP ingredients, nutrition, allergens, and run traceability | PDP enrichment support, preserving original text, `scrape_run_id`, `source_url`, and `observed_at` |

---

## 3. Canonical Schema Field Definitions (50 Fields)

Every row exported in `freshchoice_all_branches_merged.jsonl` and `freshchoice_all_branches_merged.csv` conforms to this exact schema:

1. `branch_id`: Storefront slug (e.g. `barrington`, `bellblock`, `cromwell`).
2. `branch_name`: Display name (e.g. `FreshChoice Barrington`, `SuperValue Bell Block`).
3. `store_id`: Store identifier.
4. `retailer`: Retailer key (`freshchoice` or `supervalue`).
5. `retailer_name`: Retailer display name (`FreshChoice` or `SuperValue`).
6. `brand_family`: Retailer parent brand (`FreshChoice / SuperValue (Woolworths NZ)`).
7. `storefront_url`: Store base URL (e.g. `https://barrington.store.freshchoice.co.nz`).
8. `product_id`: Storefront line control ID / unique product identifier.
9. `source_product_id`: Source storefront identifier.
10. `product_slug`: URL slug (e.g. `coca-cola-bottle-2-25l`).
11. `sku`: SKU code.
12. `retailer_sku`: Retailer SKU code.
13. `gtin`: Global Trade Item Number (GTIN-8, GTIN-12, GTIN-13, GTIN-14) where provided by source; `None` if unexposed.
14. `barcode`: Barcode string (matching GTIN).
15. `mpn`: Manufacturer Part Number where available.
16. `group_id`: Variant grouping identifier.
17. `raw_name`: Raw unformatted product name.
18. `clean_name`: Sanitized, standardized product name.
19. `brand`: Verified brand name (e.g. `Coca Cola`, `Doritos`, `Tip Top`).
20. `department`: Top-level catalogue department (e.g. `Drinks`, `Snacks`, `Frozen Foods`).
21. `category`: Second-level category (e.g. `Carbonated Soft Drinks`, `Chips - Sharing`).
22. `sub_category`: Third-level sub-category (e.g. `Bottles & Cans`).
23. `leaf_category`: Lowest-level category in taxonomy.
24. `lead_category`: Primary category for classification.
25. `breadcrumbs`: List of breadcrumb strings.
26. `category_hierarchy`: Ordered list of taxonomy levels.
27. `category_path`: Hierarchy string delimited by ` > `.
28. `category_tree`: Full category path string.
29. `category_url`: Canonical category URL.
30. `size`: Unit pack size (e.g. `2.25L`, `300g`, `1kg`).
31. `description`: Product description text.
32. `currency`: Currency code (`NZD`).
33. `price`: Amount charged in NZD decimal (e.g. `3.79`).
34. `current_price_cents`: Amount charged in integer cents (e.g. `379`).
35. `current_price_nzd`: Formatted price string (e.g. `$3.79`).
36. `selling_price_basis`: Basis of sale (`each`, `per kg`, `per pack`, `per item`).
37. `unit_of_measure`: Unit of measurement (`kg`, `each`, `pack`).
38. `default_order_weight`: Default order weight for weighted products (e.g. `0.1` for loose kg produce).
39. `quantity_increment`: Ordering quantity step increment (e.g. `0.1` for kg produce, `1.0` for discrete items).
40. `comparison_unit_price`: Unit comparison price (e.g. `1.68` from `$1.68 per litre`).
41. `comparison_unit_measure`: Comparison unit description (e.g. `per litre`, `per 100g`, `per kg`).
42. `price_per_unit`: Comparison unit price in NZD decimal.
43. `price_by_unit`: Comparison unit string.
44. `unit_price_cents`: Comparison price in integer cents.
45. `unit_label`: Comparison unit label.
46. `is_promo`: Boolean promotion indicator (`True` if genuine offer exists).
47. `promo_type`: Type of promotion (`special`, `multibuy_fixed_price`, `clearance`).
48. `promo_badge`: Display text on storefront sticker (e.g. `Save $2.01`, `MULTIBUY`).
49. `promo_text`: Structured description of promotional deal.
50. `sale_price`: Promotional price in NZD decimal.
51. `sale_price_cents`: Promotional price in integer cents.
52. `list_price`: Regular was-price or comparison list price.
53. `list_price_cents`: List price in integer cents.
54. `comparison_price_cents`: Was-price in integer cents.
55. `savings`: Total savings amount in NZD decimal.
56. `savings_cents`: Total savings in integer cents.
57. `multibuy_quantity`: Quantity required for multibuy offer (e.g. `3` in "3 for $25").
58. `multibuy_price_cents`: Total multibuy cost in integer cents (e.g. `2500` in "3 for $25").
59. `multibuy_total_nzd`: Formatted multibuy total (e.g. `$25.00`).
60. `loyalty_requirement`: Loyalty card requirement if any.
61. `offer_start_date`: ISO timestamp of promotion start.
62. `offer_end_date`: ISO timestamp of promotion end.
63. `availability`: Stock availability (`in_stock`, `out_of_stock`).
64. `stock_status`: Stock status indicator.
65. `product_url`: Full canonical product page URL.
66. `image_url`: CloudFront CDN high-resolution image URL.
67. `source_url`: URL where record was observed.
68. `observed_at`: ISO 8601 UTC timestamp of observation.
69. `scrape_run_id`: Run identifier tracking scrape batch.
70. `enriched_at`: Timestamp of PDP detail enrichment.
71. `enrichment_source`: Source of enrichment (e.g. `pdp_html`).
72. `ingredients`: Product ingredient list text.
73. `nutrition`: Nutritional information table / statement.
74. `allergens`: Product allergen warning statement.
75. `raw_row`: Structured payload preserving nested technical parameters.

---

## 4. Reproduction & Execution Instructions

To reproduce the exact production build from scratch:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the full 51-branch crawl (async rate-limited)
python crawl_all_51_branches.py

# 3. Consolidate and normalize all branch exports into master JSONL & CSV
python merge_exports.py

# 4. Execute the automated validation suite (Requirement 12)
python validate_production_export.py
```
