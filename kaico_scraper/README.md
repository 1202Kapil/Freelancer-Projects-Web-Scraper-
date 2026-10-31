# Kai Co New Zealand Supermarket Web Scraper & Pico Importer

A high-performance, contract-compliant scraper suite and batch database importer for [Kai Co](https://kaico.co.nz/) (Fresh Meat, Produce & Groceries based in Christchurch, New Zealand).

Strictly adheres to the **PICO Scraper Data Contract & Import Guide**, identical to the Woolworths, PAK'nSAVE, and Four Square scrapers.

---

## 🏬 Retailer Overview
* **Retailer Name:** Kai Co
* **Retailer Slug:** `kaico`
* **Source System:** `kaico_scraper`
* **Flagship Branch:** Kai Co Northwood (`kaico-northwood`)
* **Physical Store Location:** Northwood Supa Centa, Main North Road, Christchurch 8051, New Zealand
* **Platform:** Shopify Storefront & Product Catalog

---

## 📋 Data Contract Compliance

Each product observation strictly implements the universal Pico grocery schema:

| Field Name | Type | Nullable | Example / Description |
| :--- | :--- | :--- | :--- |
| `source_product_id` | string | No | Stable unique ID (`{product_id}-{variant_id}`). |
| `retailer_sku` | string | No | SKU code or primary identity. |
| `barcode` | string | Yes | EAN-13 / GTIN with mathematical GS1 Modulo-10 checksum. Produce PLUs (4-5 digits) strictly excluded. |
| `raw_name` | string | No | Full product title as shown. |
| `clean_name` | string | No | Product title with brand, size, price, and multibuy strings stripped. |
| `brand` | string | Yes | Extracted brand (`Couplands`, `Brinks`, `Cow & Gate`, `Kai Co`, etc.). |
| `category_path` | string | Yes | Hierarchy joined by ` > ` (e.g. `Meat > Pork`, `Produce > Apples`). |
| `size` | string | Yes | Normalized pack size (`550g`, `2L`, `250g`, `5pk`). |
| `current_price_cents`| integer| No | Price in integer cents NZD (never dollar float). |
| `comparison_price_cents`| integer| Yes | Original / shelf price when item is discounted or on special. |
| `unit_price_cents` | integer | Yes | Unit price in integer cents NZD. |
| `unit_label` | string | Yes | Unit label (`1kg`, `ea`, `100g`, `1L`). |
| `stock_status` | string | No | Enum: `in_stock` or `out_of_stock`. |
| `promo_text` | string | Yes | Promo text (`5 for $3.99`, `Sizzling Special`, `Produce Deal`, etc.). |
| `promo_type` | string | Yes | Enum: `special`, `multibuy_fixed_price`, `percent_off`, etc. |
| `card_required` | boolean | Yes | `null` (omitted) — no loyalty card required. |
| `source_promotion_id`| string | Yes | Promotion / deal collection handle. |
| `multibuy_quantity` | integer | Yes | Multibuy threshold (e.g. `5` for "5 for $3.99"). |
| `multibuy_price_cents`| integer| Yes | Multibuy bundle price in integer cents (e.g. `399`). |
| `promo_metadata` | object | Yes | Badges and collection metadata. |
| `product_url` | string | Yes | Full canonical product URL (`https://kaico.co.nz/products/...`). |
| `image_url` | string | Yes | Primary high-resolution product image. |
| `observed_at` | string | No | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`). |
| `raw_row` | object | Yes | Verbatim raw item details (tags, grams, body HTML, etc.). |

### Golden Rules Followed
1. **One JSONL per branch:** File format `{retailer}_{branch-slug}_{UTC timestamp}.jsonl`.
2. **Integer cents:** All prices are strictly integer cents NZD (`$1.99` $\to$ `199`).
3. **UTC Timestamps:** All observations stamped in UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).
4. **No invented data:** Missing or unavailable fields are `null` or omitted.
5. **No direct database writes by scrapers:** Scrapers output JSONL files; the official `import_products.py` importer handles database transactions and matching.

---

## 🗂️ Project Directory Structure

```text
kaico_scraper/
├── .env                     # Local credentials (git-ignored)
├── .env.example             # Example environment template
├── .gitignore               # Standard git ignore
├── branches.json            # Authoritative store branch registry
├── catalog_branches.py      # Store resolution against Pico catalog schema
├── config.py                # Central scraper and network configuration
├── exports/                 # Atomic JSONL exports per branch
├── import_all_branches.py   # Multi-branch import orchestrator
├── import_products.py       # Canonical Pico bulk branch importer
├── jsonl_exporter.py        # Contract-compliant atomic JSONL exporter
├── kaico_scraper.py         # Main scraper and normalizer
├── logs/                    # Structured run logs and runs-index.json
├── normalize.py             # GS1 check digit, title cleanup, brand & size extraction
├── notify.py                # Push notification alert helper (ntfy.sh)
├── package_submission.py    # Sanitized client distribution packager
├── requirements.txt         # Python project dependencies
├── run_log.py               # Structured per-run JSON logging engine
├── test_suite.py            # Automated unit and contract validation tests
└── validate_export.py       # Strict schema & GS1 check digit validator
```

---

## 🚀 Quickstart & Usage

### 1. Setup Environment
```bash
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run Automated Test Suite
```bash
python test_suite.py
```

### 3. Check Connected Retailer Branches & Store Resolution
```bash
# List all active/connected retailer branches (queries live catalog database or offline branches.json)
python catalog_branches.py --list

# Resolve specific branch store details (address, phone, external store ID)
python catalog_branches.py --resolve northwood
```

### 4. Run Kai Co Scraper
```bash
# Run full scrape and automatic validation
python kaico_scraper.py

# Run dry-run (prints sample records without saving)
python kaico_scraper.py --dry-run

# Scrape with limited products for debugging
python kaico_scraper.py --max-products 10
```

### 5. Validate Export Against Contract
```bash
python validate_export.py
```

### 6. Import into Pico Catalog Database
```bash
# Dry run verification (validates 100% of rows without touching database)
python import_products.py --input exports/kaico_northwood_*.jsonl --retailer kaico --external-store-id kaico-northwood --source-system kaico_scraper --dry-run

# Full branch import orchestrator
python import_all_branches.py --dry-run
```

### 7. Package Sanitized Submission Archive
```bash
python package_submission.py
```
Outputs `dist/kaico_scraper_production.zip` with zero credential leaks.
