# 🛒 FreshChoice NZ Supermarket Scraper & Data Pipeline

A production-grade, enterprise web scraper and automated ingestion pipeline for **FreshChoice Supermarkets New Zealand** (`https://www.freshchoice.co.nz/`).

Engineered strictly against the **PICO Scraper Data Contract**, following the benchmark maturity standards of the Woolworths and PAK'nSAVE scraper suites.

---

## 📋 Architectural Highlights

1. **PICO Scraper Data Contract Compliant**:
   - Every product observation strictly conforms to the common contract.
   - All prices serialized as integer cents (`current_price_cents`, `comparison_price_cents`, `unit_price_cents`, `multibuy_price_cents`).
   - Timestamps formatted as UTC ISO-8601 (`%Y-%m-%dT%H:%M:%SZ`).
   - Null and empty fields omitted at top level; never invents data.
2. **Multibuy & Unit Price Isolation**:
   - Resolves the critical MyFoodLink pricing regression where bundle offers (e.g. `3 for $25`) previously overwrote unit prices.
   - Extracts independent selling price (`$9.30` $\rightarrow$ `930`), was price (`$9.50` $\rightarrow$ `950`), and isolates multibuy parameters (`qty: 3`, `multibuy_price_cents: 2500`).
3. **Groceries Taxonomy Recovery**:
   - Overcomes MyFoodLink's 50-page (2,400 items) parent listing ceiling by automatically discovering and recovering 13 direct subcategories (e.g. `canned-dried-vegetables`, `pasta-rice`, `cooking-needs`) and 10 Depth-2 Ethnic subcategories (`asian`, `indian`, etc.).
4. **GS1 Modulo-10 Barcode Validation**:
   - Validates GTIN-8, 12, 13, and 14 check digits mathematically.
   - Strictly isolates 4- and 5-digit produce PLUs (e.g. Bananas 4011, Avocado 4224) into `raw_row["plu_code"]` (`barcode = None`).
5. **Multi-Branch Isolation & Batch Importer**:
   - Registry of **76 FreshChoice supermarket locations** across New Zealand.
   - Exports one atomic `.jsonl` file per branch per run (`freshchoice_{branch-slug}_{timestamp}.jsonl`).
   - Scrapers never write directly to the database; imports are executed via `import_products.py` and `import_all_branches.py` with `--dry-run`, `--rollback-test`, and `--full-branch`.

---

## 📂 Project Structure

```text
freshchoice_scraper/
├── config.py                 # Central configurations, categories, recovery paths, rate limits
├── catalog_branches.py       # 76-branch registry and catalog resolver
├── freshchoice_scraper.py    # Main async scraping engine (HTTPX + BeautifulSoup)
├── parsers.py                # HTML & JSON-LD parser, GS1 checksum validator, multibuy engine
├── jsonl_exporter.py         # Atomic JSONL exporter conforming to PICO schema
├── validate_export.py        # Contract & schema compliance auditor
├── import_products.py        # Pico branch database importer (pooler-optimized bulk SQL)
├── import_all_branches.py    # Batch orchestrator for all branch exports
├── test_scraper_parsers.py   # Unit test suite for parsers and pricing regression
├── exports/                  # Directory for exported JSONL datasets
├── logs/                     # Per-run execution logs
└── requirements.txt          # Python dependencies
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

### 3. Run FreshChoice Scraper

* **Scrape Default Benchmark Branches (Merivale, Epsom, Green Island):**
  ```bash
  python freshchoice_scraper.py
  ```

* **Scrape Custom Branches:**
  ```bash
  python freshchoice_scraper.py --branches merivale,epsom,greenisland,barrington
  ```

* **Scrape All Discovered Online Branches:**
  ```bash
  python freshchoice_scraper.py --all-branches
  ```

* **Scrape with Detail Page Enrichment (harvests GTINs & Brands):**
  ```bash
  python freshchoice_scraper.py --branches merivale --enrich-details --max-details 50
  ```

### 4. Audit & Validate Exports
```bash
# Audits all JSONL files in exports/ against GS1 check digits and data contracts
python validate_export.py
```

### 5. Ingestion into Pico Database
```bash
# Safe dry-run validation (no DB writes)
python import_all_branches.py --dry-run

# Single branch dry-run
python import_all_branches.py --branch merivale --dry-run

# Live production import
python import_all_branches.py
```
