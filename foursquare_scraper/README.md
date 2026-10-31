# 🛒 Four Square Supermarket Scraper & Data Pipeline

Production-grade web scraper, data pipeline, and ingestion orchestrator for **Four Square Supermarkets New Zealand** ([foursquare.co.nz](https://www.foursquare.co.nz/)), engineered strictly to the **PICO Scraper Data Contract** and Foodstuffs NZ enterprise specifications.

Designed and engineered by **Kapil Singhal** ([@1202Kapil](https://github.com/1202Kapil)).

---

## 🎯 Architecture & Key Capabilities

- **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents (`current_price_cents`, `unit_price_cents`), UTC ISO-8601 timestamps, clean titles, brand/size extraction, and omission of null/empty top-level fields.
- **GS1 Modulo-10 Barcode Validation**: Mathematical check-digit computation and validation across GTIN-8, GTIN-12, GTIN-13, and GTIN-14 barcodes. Produce PLUs (e.g. Avocado `4224`, Bananas `4011`) are strictly isolated from the barcode field.
- **Authentic Multi-Branch Store Registry**: Complete 210-branch registry across New Zealand (`branches.json`) dynamically resolvable against PostgreSQL `catalog.branches` or offline fallback.
- **Branch-Specific Availability & Pricing**: Genuine branch-level isolation using Foodstuffs `brands_store_id` GUID cookies.
- **High-Speed Async Direct Engine**: High-throughput HTTP execution retrieving complete branch specials in ~3 seconds with automatic browser & CapSolver Turnstile fallback when challenged.
- **Rich Detail Enrichment**: Enriched with GS1 barcodes, nutritional panels, allergens, ingredients, and country of origin statements.
- **PICO Ingestion Pipeline**: Direct dry-run and live batch ingestion support via `import_products.py` and `import_all_branches.py`.

---

## 📂 Repository Structure

```text
foursquare_scraper/
├── foursquare_scraper.py   # Main high-speed scraping engine (HTTPX + Patchright fallback)
├── catalog_branches.py     # 210-branch PICO catalog resolver & store registry
├── jsonl_exporter.py       # PICO contract JSONL exporter (integer cents, atomic writes)
├── normalize.py            # GS1 Modulo-10 algorithm, brand/size extractors, promo parser
├── validate_export.py      # Contract & schema compliance auditor with GS1 check
├── import_products.py      # Pico branch DB importer (pooler-optimized bulk SQL)
├── import_all_branches.py  # Multi-branch batch importer orchestrator
├── test_suite.py           # Comprehensive pytest suite (GS1, normalization, contract)
├── branches.json           # Authoritative 210-branch registry with Foodstuffs GUIDs
├── .foodstuffs_cache.json  # Foodstuffs product cache (barcodes, nutrition, allergens)
├── exports/                # Verified multi-branch JSONL datasets
├── logs/                   # Execution run logs
├── requirements.txt        # Python dependencies
└── README.md               # Technical documentation
```

---

## 📋 Data Contract Schema (PICO Format)

Each observation conforms to the contract:

| Field | Type | Description |
| :--- | :--- | :--- |
| `source_product_id` | `string` | Foodstuffs product ID (e.g. `5035600-EA-000`) |
| `retailer_sku` | `string` | Same as `source_product_id` |
| `barcode` | `string` (nullable) | Mathematically validated GTIN (GS1 Modulo-10 verified) |
| `raw_name` | `string` | Full product title (e.g. `Cadbury Treatsize Sharepack 120-180g Varieties`) |
| `clean_name` | `string` | Title with brand and size stripped (`Treatsize Sharepack`) |
| `brand` | `string` (nullable) | Recognized brand name (`Cadbury`) |
| `category_path` | `string` | Full hierarchy (`Groceries > Pantry & Grocery`) |
| `size` | `string` (nullable) | Pack size or weight (`120-180g`) |
| `current_price_cents`| `integer` | Price in integer cents NZD (`599`) |
| `comparison_price_cents`| `integer` (nullable) | Original price when on special |
| `unit_price_cents` | `integer` (nullable) | Price per unit label in integer cents |
| `unit_label` | `string` (nullable) | Unit basis (`ea`, `1kg`, `100g`, `1L`) |
| `stock_status` | `string` | `"in_stock"` or `"out_of_stock"` |
| `promo_text` | `string` (nullable) | Visible promo wording (`Special $5.99`) |
| `promo_type` | `string` (nullable) | Promo category (`special`, `multibuy_fixed_price`) |
| `promo_ends_at` | `string` (nullable) | ISO date format `YYYY-MM-DD` (`2026-11-01`) |
| `product_url` | `string` | Storefront specials URL |
| `image_url` | `string` | Foodstuffs high-resolution image URL |
| `observed_at` | `string` | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |
| `raw_row` | `object` (nullable) | Detailed nutrition, allergens, ingredients, country of origin |

---

## 🚀 Quickstart & Usage

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Configuration (`.env`)

```env
PROXY_URL=http://user:password@host:port
CAPSOLVER_PROXY=http://user:password@host:port
CAPSOLVER_API_KEY=your_capsolver_key
# DATABASE_URL=postgresql://user:password@pooler.pico.internal:5432/pico_prod
```

### 3. Run Single Branch Scrape

```bash
# Scrape default branch (Four Square Ascot)
python foursquare_scraper.py

# Scrape specific branch by name or slug
python foursquare_scraper.py --branch "Four Square Ahuriri"
python foursquare_scraper.py --branch "four-square-akaroa"
```

### 4. Run Multi-Branch Scrape

```bash
# Scrape all 210 active branches
python foursquare_scraper.py --all-branches

# Scrape first 10 branches
python foursquare_scraper.py --all-branches --limit 10
```

### 5. Validate Exports Against PICO Contract

```bash
# Audit all JSONL files in exports/ directory
python validate_export.py --all
```

### 6. Ingest into PICO Catalog Database

```bash
# Dry-run validation (no DB required)
python import_all_branches.py --dry-run

# Live PostgreSQL import (when DATABASE_URL is set)
python import_all_branches.py
```

### 7. Run Automated Test Suite

```bash
python -m pytest test_suite.py -v
```

---

## 🏆 Production Audit Benchmark

```text
===========================================================================
PICO DATA CONTRACT AUDIT: Auditing Four Square export file(s)
===========================================================================
[PASS] foursquare_four-square-ahuriri_20261031T092417Z.jsonl
  Observations  : 48 total (48 unique)
  Barcodes      : 37 present (77.08% coverage)
  GS1 Modulo-10 : 37/37 valid (100.0% checksum accuracy)
  Availability  : 48 in stock, 0 out of stock
  Errors        : 0

[PASS] foursquare_four-square-akaroa_20261031T092429Z.jsonl
  Observations  : 48 total (48 unique)
  Barcodes      : 34 present (70.83% coverage)
  GS1 Modulo-10 : 34/34 valid (100.0% checksum accuracy)
  Availability  : 48 in stock, 0 out of stock
  Errors        : 0

[PASS] foursquare_four-square-ascot_20261031T092247Z.jsonl
  Observations  : 48 total (48 unique)
  Barcodes      : 34 present (70.83% coverage)
  GS1 Modulo-10 : 34/34 valid (100.0% checksum accuracy)
  Availability  : 48 in stock, 0 out of stock
  Errors        : 0
===========================================================================
ALL EXPORT FILES PASSED PICO DATA CONTRACT & GS1 AUDIT SUCCESSFULLY!
===========================================================================
```
