# Farro Fresh New Zealand Supermarket Scraper & Importer Pipeline

Production-grade web scraper and data ingestion pipeline for **Farro Fresh New Zealand** ([farro.co.nz](https://www.farro.co.nz/)), strictly conforming to the **Pico Scraper Data Contract & Schema Specification**.

---

## 1. Architecture & Site Reverse Engineering

* **Platform:** ASP.NET Core with Blazor WebAssembly & OlympicTrader Framework.
* **Direct Backend API:** Direct JSON search endpoint at `POST https://www.farro.co.nz/api/ViewModel/Search/Search`. No headless browser or UI simulation is required during production scraping.
* **Catalog Coverage:** ~4,906 products total across Auckland.
* **Pagination:** Capped at 24 items per request (`skip = 0, 24, 48, ...`). Pure HTTP requests complete full catalog discovery in ~205 requests (~2 minutes).
* **Barcodes:** GS1 EAN-8/12/13/14 barcodes extracted with mathematical modulo-10 validation from high-resolution product image URLs.
* **Loyalty Programme:** Farro's *Friends of Farro* (`friends-of-farro`) loyalty card special prices mapped to `member_price`.

---

## 2. Store Branches Registry (Auckland, NZ)

Farro Fresh operates 8 physical retail branches across the Auckland metropolitan region:

| Branch Slug | Store Name | Address | Phone |
| :--- | :--- | :--- | :--- |
| `farro-grey-lynn` | Farro Grey Lynn | 34 Westmoreland St West, Grey Lynn | (09) 892 6300 |
| `farro-newmarket` | Farro Newmarket | 480 Broadway, Newmarket | (09) 892 6364 |
| `farro-epsom` | Farro Epsom | 446 Manukau Road, Epsom | (09) 892 6330 |
| `farro-mt-eden` | Farro Mt Eden | 422 Dominion Road, Mount Eden | (09) 892 6377 |
| `farro-smales-farm` | Farro Smales Farm | Cnr. Taharoto Rd & Shakespeare Rd, Takapuna | (09) 892 6394 |
| `farro-mairangi-bay`| Farro Mairangi Bay | Cnr Constellation Dr & Parkway Dr, Mairangi Bay | (09) 892 6307 |
| `farro-mt-wellington`| Farro Mt Wellington | 80 Lunn Ave, Mt Wellington | (09) 892 6347 |
| `farro-orakei-bay-village`| Farro Orakei Bay Village | 228 Orakei Road, Remuera | (09) 892 6393 |

---

## 3. Data Contract Conformance

Each exported row is a single JSON object in a newline-delimited JSON file (`JSONL`), adhering to:

* **Prices in Integer Cents:** All prices (`current_price_cents`, `comparison_price_cents`, `unit_price_cents`) are strictly positive integers in cents NZD (e.g. `$10.99` $\rightarrow$ `1099`).
* **Clean Null Omission:** Absent or empty top-level fields are completely omitted from the written JSON line.
* **ISO-8601 UTC Timestamps:** `observed_at` uses UTC format `YYYY-MM-DDTHH:MM:SSZ`.
* **Export Filename:** `{retailer}_{branch-slug}_{timestamp}.jsonl` (e.g. `farro_farro-grey-lynn_20261030T084137Z.jsonl`).

---

## 4. Usage Instructions

### A. Run Scraper for a Branch
```bash
# Scrape single branch (e.g. Grey Lynn)
python farro_scraper.py --branch farro-grey-lynn

# Scrape all 8 branches (generates 1 JSONL file per branch)
python farro_scraper.py --all-branches

# Smoke test with limit
python farro_scraper.py --branch farro-grey-lynn --limit 50
```

### B. Validate Export Against Contract
```bash
# Validate latest export
python validate_export.py --latest

# Validate specific export file
python validate_export.py --file exports/farro_farro-grey-lynn_20261030T084137Z.jsonl
```

### C. Import Products to Database
```bash
# Dry-run validation (no DB connection needed)
python import_products.py --input exports/farro_farro-grey-lynn_20261030T084137Z.jsonl \
  --retailer farro --external-store-id farro-grey-lynn --dry-run

# Rollback test (exercises full SQL transactions, then rolls back)
python import_products.py --input exports/farro_farro-grey-lynn_20261030T084137Z.jsonl \
  --retailer farro --external-store-id farro-grey-lynn --rollback-test

# Live batch import across all latest branch exports
python import_all_branches.py --dry-run
```

### D. Package Sanitized Distribution Archive
```bash
python package_submission.py
```
Outputs a clean ZIP archive at `dist/farro_scraper_production.zip` excluding sensitive `.env` files and caches.
