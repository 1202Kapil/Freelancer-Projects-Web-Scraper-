# The Warehouse NZ Scraper & Ingestion Pipeline

Production-grade web scraper and data ingestion pipeline for **The Warehouse New Zealand** ([thewarehouse.co.nz](https://www.thewarehouse.co.nz/)), strictly conforming to the **PICO Scraper Data Contract & Schema Specification** established by the Woolworths and PAK'nSAVE benchmark scrapers.

---

## 1. Architecture & Site Reverse Engineering

* **E-Commerce Platform:** Salesforce Commerce Cloud (Demandware), site `Sites-twl-Site`.
* **Product Discovery & Pagination:** Products are extracted from the category grid search update endpoint:
  ```
  GET https://www.thewarehouse.co.nz/search/update?cgid={cgid}&start={offset}&sz=32
  ```
  Paginated at 32 items per page (`start = 0, 32, 64, ...`), with fallback to landing category routes (`/c/{category_slug}`).
* **Data Payloads:** Every `.product-tile` embeds rich structured JSON attributes:
  * `data-ga-product`: Item ID, SKU, product title, brand, manufacturer category, and full `productEAN` / `dimension15` GTIN barcode.
  * `data-gtm-product`: Shelf price, was / comparison price (`productThenPrice`), badges (`productBadges`), and category hierarchy.
  * Tile DOM: Image URLs, product links, live stock availability status (`availability-stock-status`), and promotion claims (`Save $X.XX`).
* **Barcode Accuracy:** Strict Global Trade Item Number (GTIN-8, GTIN-12, GTIN-13, GTIN-14) validation with mathematical **GS1 Modulo-10 Check Digit** calculation. Non-GTIN SKUs and unverified numbers are strictly isolated to `raw_row`.
* **Promotions Verification:** Complete classification of specials (`special`), multibuys (`multibuy_fixed_price`), clearance (`clearance`), and MarketClub loyalty member discounts (`member_price`). Zero orphan promo metadata on regular shelf prices.
* **Network & Cloudflare Resilience:** Clean client header negotiation preventing TLS bot signature mismatches, combined with 4-attempt exponential backoff retries handling HTTP 429, 425, and 5xx responses.

---

## 2. PICO Common Schema Conformance

Each exported row is a single JSON object in a newline-delimited JSON (`JSONL`) file, with one file exported per branch per run:

| Field | Type | Description |
| :--- | :--- | :--- |
| `source_product_id` | `str` | Authentic retailer product identifier (e.g. `"R666174"`, `"R3081779"`) |
| `retailer_sku` | `str` | Retailer SKU code (e.g. `"R666174"`) |
| `barcode` | `str` \| `null` | Verified GS1 GTIN barcode (8, 12, 13, 14 digits) passing modulo-10 checksum |
| `raw_name` | `str` | Original full product title as displayed by the retailer |
| `clean_name` | `str` | Normalized product title with clean whitespace |
| `brand` | `str` \| `null` | Authentic brand name (e.g. `"Indomie"`, `"V"`, `"Trolli"`, `"Palm"`) |
| `category_path` | `str` | Formatted category hierarchy separated by ` > ` |
| `size` | `str` \| `null` | Extracted volume, weight, or pack size (e.g. `"500g"`, `"250ml"`, `"5 Pack"`) |
| `current_price_cents`| `int` | Current active shelf price in **integer cents NZD** (e.g. `$9.99` $\rightarrow$ `999`) |
| `comparison_price_cents`| `int` \| `null` | Original / Was price in integer cents if discounted; omitted otherwise |
| `unit_price_cents` | `int` \| `null` | Price per standard unit in integer cents (when published) |
| `unit_label` | `str` \| `null` | Standard unit label (e.g. `"100ml"`, `"100g"`, `"ea"`) |
| `stock_status` | `str` | Strictly `"in_stock"` or `"out_of_stock"` |
| `promo_text` | `str` \| `null` | Descriptive promotional text (e.g. `"Save $1.00"`, `"2 for $6.00"`) |
| `promo_type` | `str` \| `null` | Standard promo classification (`"special"`, `"member_price"`, `"multibuy_fixed_price"`, `"clearance"`) |
| `card_required` | `bool` \| `null` | `True` if loyalty membership card required (MarketClub), else omitted |
| `required_loyalty_program_code`| `str` \| `null` | `"marketclub"` when `card_required` is `True` |
| `source_promotion_id`| `str` \| `null` | Retailer promotion identifier |
| `multibuy_quantity` | `int` \| `null` | Required multibuy quantity (e.g. `2` for "2 for $6.00") |
| `multibuy_price_cents` | `int` \| `null`| Total bundle price in integer cents (e.g. `600`) |
| `promo_metadata` | `dict` \| `null` | Additional promotional metadata |
| `product_url` | `str` | Canonical full product URL |
| `image_url` | `str` \| `null` | High-resolution primary product image URL |
| `observed_at` | `str` | UTC ISO-8601 timestamp (e.g. `"2026-10-30T13:33:48Z"`) |
| `raw_row` | `dict` | Preserved raw payloads (`ga_product`, `gtm_product`, unverified codes) |

### Contract Rules Followed:
1. **One JSONL per branch:** File naming follows `{retailer}_{branch-slug}_{timestamp}.jsonl`.
2. **Integer Cents:** All prices must be integers in cents NZD, strictly rejecting dollar floats.
3. **UTC Timestamps:** All timestamps end in `Z`.
4. **Omit Absent Keys:** Absent or `None` top-level keys are omitted from output; never invent data.
5. **No Direct DB Writes:** Scrapers write to `exports/`. Ingestion into the database is handled via `import_products.py`.

---

## 3. Store Branch Registry

The Warehouse operates 76 physical retail stores across New Zealand. Branches are cataloged in `branches.json` and resolved via `catalog_branches.py`:

```bash
# List all 76 branches
python catalog_branches.py

# Query branch by ID or slug
python catalog_branches.py --branch 221
python catalog_branches.py --branch thewarehouse-auckland-central
```

Sample Branch Output:
```json
{
  "id": "221",
  "store_id": "221",
  "name": "The Warehouse Auckland Central",
  "branch_name": "Auckland Central",
  "slug": "thewarehouse-auckland-central",
  "city": "Auckland",
  "state_code": "NZ-AUK",
  "postal_code": "1010",
  "address": "The Warehouse Atrium on Elliott, 21 Elliott Street, Auckland Central, Auckland 1010",
  "latitude": -36.849937,
  "longitude": 174.76371,
  "is_active": true
}
```

---

## 4. Usage Instructions

### A. Run Scraper for a Branch
```bash
# Scrape single branch (Auckland Central)
python thewarehouse_scraper.py --branch 221

# Scrape specific department with product limit
python thewarehouse_scraper.py --branch 221 --category food-pets-household --limit 100

# Scrape all 76 branches nationwide (one JSONL file per branch)
python thewarehouse_scraper.py --all-branches
```

### B. Validate Exported JSONL
```bash
# Validate latest export
python validate_export.py

# Validate specific export file
python validate_export.py exports/thewarehouse_thewarehouse-auckland-central_20261030T133350Z.jsonl
```

Sample Audit Report:
```
=================================================================
AUDIT REPORT: thewarehouse_thewarehouse-auckland-central_20261030T133350Z.jsonl
=================================================================
Total Observations : 64
Valid GTIN Barcodes: 64 (100.0%)
GS1 Checksum Pass  : 64 (100.0%)
In Stock           : 64
Out of Stock       : 0
Specials / Promos  : 19
Multibuys          : 1
Member Prices      : 0
Total Errors       : 0
Error Rate         : 0.00%
-----------------------------------------------------------------
RESULT: PASSED PRODUCTION DATA CONTRACT AUDIT
=================================================================
```

### C. Import Products to Pico Database
```bash
# Dry-run parse validation (no DB connection required)
python import_products.py \
  --input exports/thewarehouse_thewarehouse-auckland-central_20261030T133350Z.jsonl \
  --retailer thewarehouse \
  --external-store-id 221 \
  --dry-run

# Rollback test (runs within SQL transaction and rolls back)
python import_products.py \
  --input exports/thewarehouse_thewarehouse-auckland-central_20261030T133350Z.jsonl \
  --retailer thewarehouse \
  --external-store-id 221 \
  --rollback-test

# Batch import across all branches
python import_all_branches.py --dry-run
```

### D. Run Verification Test Suite
```bash
python -m pytest test_thewarehouse.py -v
```

### E. Package Distribution Archive
```bash
python package_submission.py
```
Produces `dist/thewarehouse_scraper_production.zip` containing all code, verified exports, and logs.
