# 🛒 SuperValue NZ Supermarket Scraper & Data Pipeline

A production-grade, enterprise web scraper and automated ingestion pipeline for **SuperValue Supermarkets New Zealand** (`https://www.supervalue.co.nz/`).

Engineered strictly against the **PICO Scraper Data Contract**, following the benchmark maturity standards of the Woolworths, FreshChoice, and PAK'nSAVE scraper suites.

---

## 📋 Architectural Highlights

1. **PICO Scraper Data Contract Compliant**:
   - Every product observation strictly conforms to the common contract.
   - All prices serialized as integer cents (`current_price_cents`, `comparison_price_cents`, `unit_price_cents`, `multibuy_price_cents`).
   - Timestamps formatted as UTC ISO-8601 (`%Y-%m-%dT%H:%M:%SZ`).
   - Null and empty fields omitted at top level; never invents data.

2. **Multibuy & Unit Price Isolation**:
   - Resolves the critical MyFoodLink pricing regression where bundle offers (e.g. `3 for $25`) previously risked overwriting individual unit prices.
   - Extracts independent selling price (`$4.00` $\rightarrow$ `400`), was price (`$7.30` $\rightarrow$ `730`), and isolates multibuy parameters (`qty: 3`, `multibuy_price_cents: 2500`).

3. **Taxonomy & Sitemap Crawling**:
   - High-throughput asynchronous crawling leveraging `httpx.AsyncClient` with jittered exponential backoff and rate limiting.
   - Dynamically parses the 606 store taxonomy categories via sitemap.xml and pagination endpoints.
   - Bypasses category page caps with Groceries subcategory recovery paths.

4. **GS1 Modulo-10 Barcode Validation**:
   - Validates GTIN-8, 12, 13, and 14 check digits mathematically.
   - Strictly isolates 4- and 5-digit produce PLUs (e.g. Bananas 4011, Avocado 4224) into `raw_row["plu_code"]` (`barcode = None`).

5. **Multi-Branch Isolation & Batch Importer**:
   - Authoritative registry for SuperValue locations across New Zealand (e.g. Milton online shopping hub, Mangawhai, Te Kuiti).
   - Exports one atomic `.jsonl` file per branch per run (`supervalue_{branch-slug}_{timestamp}.jsonl`).
   - Scrapers never write directly to the database; imports are executed via `import_products.py` and `import_all_branches.py` with `--dry-run`, `--rollback-test`, and `--full-branch`.

---

## 📂 Project Structure

```text
supervalue_scraper/
├── config.py                 # Central configurations, categories, recovery paths, rate limits
├── catalog_branches.py       # SuperValue branch registry and catalog resolver
├── catalog_categories.py     # 606-category catalog discovery & sitemap auditor
├── supervalue_scraper.py     # Main async scraping engine (HTTPX + BeautifulSoup)
├── parsers.py                # HTML & JSON-LD parser, GS1 checksum validator, multibuy engine
├── jsonl_exporter.py         # Atomic JSONL exporter conforming to PICO schema
├── validate_export.py        # Contract & schema compliance auditor
├── import_products.py        # Pico branch database importer (pooler-optimized bulk SQL)
├── import_all_branches.py    # Batch orchestrator for all branch exports
├── run_log.py                # Structured per-run JSON logging
├── notify.py                 # Push notification dispatcher (ntfy.sh)
├── test_scraper_parsers.py   # Comprehensive unit test suite
├── exports/                  # Directory for exported JSONL datasets
├── logs/                     # Per-run execution logs
├── requirements.txt          # Python dependencies
└── .env.example              # Environment variables template
```

---

## 🚀 Setup & Execution

### 1. Requirements Installation
```bash
pip install -r requirements.txt
```

### 2. Run Parser Unit Tests
```bash
python test_scraper_parsers.py
```

### 3. Discover & Audit Store Categories (606 Categories)

Audit all 606 categories and department breakdowns directly from the live supermarket sitemap:

* **Complete Category Hierarchy & Breakdown:**
  ```bash
  python catalog_categories.py
  ```

* **Inspect Custom Branch Categories:**
  ```bash
  python catalog_categories.py --branch milton
  ```

* **One-Liner Category Counter (Terminal):**
  ```bash
  python -c "import urllib.request, re; r = urllib.request.Request('https://milton.store.supervalue.co.nz/sitemap.xml', headers={'User-Agent': 'Mozilla/5.0'}); data = urllib.request.urlopen(r).read().decode('utf-8'); cats = set(re.findall(r'/category/([^<]+)', data)); print(f'Total SuperValue Categories: {len(cats)}')"
  ```

* **Check Unique Categories inside Exported JSONL Dataset:**
  ```bash
  python -c "import json, glob; f = sorted(glob.glob('exports/supervalue_milton_*.jsonl'))[-1]; cats = {json.loads(line).get('category_path') for line in open(f, encoding='utf-8') if line.strip()}; print(f'Unique categories in {f}: {len(cats)}'); print('\n'.join(sorted(filter(None, cats))))"
  ```

### 4. Run SuperValue Scraper

* **Scrape Milton Online Branch (Benchmark):**
  ```bash
  python supervalue_scraper.py
  ```

* **Scrape with Detail Page Enrichment (harvests GTINs & Brands):**
  ```bash
  python supervalue_scraper.py --branches milton --enrich-details --max-details 100
  ```

* **Quick Pilot Smoke Test (e.g. 50 products):**
  ```bash
  python supervalue_scraper.py --branches milton --limit 50
  ```

* **Dry-Run Mode (crawl without writing JSONL to disk):**
  ```bash
  python supervalue_scraper.py --branches milton --dry-run
  ```

### 5. Audit & Validate Exports
```bash
# Audits all JSONL files in exports/ against GS1 check digits and data contracts
python validate_export.py
```

### 6. Ingestion into Pico Database
```bash
# Safe dry-run validation (no DB writes)
python import_all_branches.py --dry-run

# Single branch dry-run
python import_all_branches.py --branch milton --dry-run

# Live production import
python import_all_branches.py
```

---

## 📊 Data Contract Mapping Reference

| Contract Field | Type | SuperValue Source Mapping |
| :--- | :--- | :--- |
| `source_product_id` | `str` | MyFoodLink line ID (e.g. `5e7957ebf605cc7534075790`) |
| `retailer_sku` | `str` | Product line identifier or slug |
| `barcode` | `str \| null` | GS1 modulo-10 verified GTIN-8/12/13/14; `null` for produce PLU |
| `raw_name` | `str` | Full product title as published by retailer |
| `clean_name` | `str` | Stripped title (no packaging sizes or promo words) |
| `brand` | `str \| null` | Brand extracted from detail JSON-LD Schema.org / title |
| `category_path` | `str` | Hierarchical department breadcrumbs (e.g. `Bakery > Bread`) |
| `size` | `str \| null` | Net quantity/size (e.g. `700g`, `2L`, `12 pack`) |
| `current_price_cents` | `int` | Current selling price in integer cents NZD |
| `comparison_price_cents`| `int \| null` | Strikethrough / was price in integer cents NZD |
| `unit_price_cents` | `int \| null` | Normalized unit price in integer cents NZD |
| `unit_label` | `str \| null` | Unit basis (e.g. `100g`, `kg`, `each`) |
| `stock_status` | `str` | `in_stock` or `out_of_stock` |
| `promo_text` | `str \| null` | Descriptive promo text (e.g. `Save $3.30`, `3 for $25.00`) |
| `promo_type` | `str \| null` | Standardized type: `special`, `multibuy_fixed_price` |
| `multibuy_quantity` | `int \| null` | Required item count for multibuy offer |
| `multibuy_price_cents` | `int \| null` | Total bundle price in integer cents NZD |
| `product_url` | `str` | Canonical product detail URL |
| `image_url` | `str \| null` | CloudFront / Imgix high-resolution image asset URL |
| `observed_at` | `str` | UTC ISO-8601 timestamp (`%Y-%m-%dT%H:%M:%SZ`) |
| `raw_row` | `dict` | Branch ID, produce PLU (if applicable), and raw metadata |
