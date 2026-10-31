# 🚀 Freelancer Projects — Web Scrapers & Data Pipelines

A curated collection of production-grade, enterprise web scrapers, data pipelines, and reverse-engineered API integrations built for international clients.

Designed and engineered by **Kapil Singhal** ([@1202Kapil](https://github.com/1202Kapil)).

---

## 📂 Repository Structure

```text
Freelancer-Projects-Web-Scraper/
├── paknsave_scraper/           # PAK'nSAVE NZ Supermarket Scraper & Data Pipeline
│   ├── paknsave_scraper.py     # Main scraper engine (Algolia API + Cloudflare bypass)
│   ├── catalog_branches.py     # PICO PostgreSQL catalog resolver
│   ├── import_all_branches.py  # All-branch batch importer
│   ├── validate_export.py      # GS1 modulo-10 checksum & contract audit tool
│   ├── test_pico_db.py         # Database connectivity & schema diagnostic tool
│   ├── deploy/                 # Production systemd timers and bash runner
│   ├── exports/                # Verified multi-branch JSONL datasets
│   └── README.md               # Detailed technical documentation
│
└── freshchoice_scraper/        # FreshChoice NZ Supermarket Scraper & Ingestion Pipeline
    ├── freshchoice_scraper.py  # Main async scraping engine (HTTPX + BeautifulSoup)
    ├── __main__.py             # Multi-stage pipeline CLI dispatcher
    ├── parsers.py              # HTML/JSON-LD parser, GS1 modulo-10 validator, multibuy engine
    ├── recover.py              # Groceries taxonomy recovery (bypasses 50-page cap)
    ├── catalog_branches.py     # 76 FreshChoice branch registry & resolver
    ├── jsonl_exporter.py       # Atomic PICO contract JSONL exporter
    ├── validate_export.py      # Contract & schema compliance auditor
    ├── import_products.py      # Pico branch DB importer (pooler-optimized bulk SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── exports/                # Exported JSONL datasets
    └── README.md               # Detailed technical documentation
│
└── farro_scraper/              # Farro Fresh NZ Supermarket Scraper & Data Pipeline
    ├── farro_scraper.py        # Main scraper engine (Reverse-engineered Search API)
    ├── catalog_branches.py     # 8 Auckland branches registry & DB resolver
    ├── normalize.py            # GS1 Modulo-10 check, barcode, brand & size normalizers
    ├── jsonl_exporter.py       # Atomic PICO contract JSONL exporter
    ├── validate_export.py      # Contract & schema compliance auditor
    ├── import_products.py      # Pico branch DB importer (bulk PostgreSQL SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── exports/                # Verified multi-branch JSONL datasets
    └── README.md               # Detailed technical documentation
│
└── thewarehouse_scraper/       # The Warehouse NZ Retail & Supermarket Scraper & Ingestion Pipeline
    ├── thewarehouse_scraper.py # Main scraper engine (Demandware Search Grid API)
    ├── catalog_branches.py     # 76 NZ branch registry & resolver
    ├── normalize.py            # GS1 Modulo-10 check, barcode, brand & size normalizers
    ├── jsonl_exporter.py       # Atomic PICO contract JSONL exporter
    ├── validate_export.py      # Contract & schema compliance auditor
    ├── import_products.py      # Pico branch DB importer (bulk PostgreSQL SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── branches.json           # Authentic 76-branch registry
    ├── exports/                # Verified branch JSONL datasets
    └── README.md               # Detailed technical documentation
│
└── supervalue_scraper/         # SuperValue NZ Supermarket Scraper & Ingestion Pipeline
    ├── supervalue_scraper.py   # Main async scraping engine (HTTPX + BeautifulSoup)
    ├── catalog_branches.py     # SuperValue branch registry & DB resolver
    ├── catalog_categories.py   # 606-category catalog discovery & sitemap auditor
    ├── parsers.py              # HTML & JSON-LD parser, GS1 modulo-10 validator, multibuy engine
    ├── jsonl_exporter.py       # Atomic PICO contract JSONL exporter
    ├── validate_export.py      # Contract & schema compliance auditor
    ├── import_products.py      # Pico branch DB importer (pooler-optimized bulk SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── test_scraper_parsers.py # Unit test suite
    ├── exports/                # Verified branch JSONL datasets
    └── README.md               # Detailed technical documentation
│
└── foursquare_scraper/         # Four Square NZ Supermarket Scraper & Data Pipeline
    ├── foursquare_scraper.py   # Main high-speed scraping engine (HTTPX + Patchright fallback)
    ├── catalog_branches.py     # 210-branch PICO catalog resolver & store registry
    ├── jsonl_exporter.py       # PICO contract JSONL exporter (integer cents, atomic writes)
    ├── normalize.py            # GS1 Modulo-10 algorithm, brand/size extractors, promo parser
    ├── validate_export.py      # Contract & schema compliance auditor with GS1 check
    ├── import_products.py      # Pico branch DB importer (pooler-optimized bulk SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── test_suite.py           # Comprehensive pytest suite (GS1, normalization, contract)
    ├── branches.json           # Authoritative 210-branch registry with Foodstuffs GUIDs
    ├── exports/                # Verified branch JSONL datasets
    └── README.md               # Detailed technical documentation
│
└── kaico_scraper/              # Kai Co NZ Fresh Meat, Produce & Groceries Scraper
    ├── kaico_scraper.py        # Main scraping engine (Shopify Collections & Products API)
    ├── catalog_branches.py     # Store resolution & branch discovery against Pico catalog
    ├── jsonl_exporter.py       # Atomic PICO contract JSONL exporter (integer cents, UTC ISO)
    ├── normalize.py            # GS1 check digit, title cleanup, brand & size extraction
    ├── validate_export.py      # Strict schema & GS1 check digit validator
    ├── import_products.py      # Pico branch DB importer (pooler-optimized bulk SQL)
    ├── import_all_branches.py  # Multi-branch batch importer orchestrator
    ├── test_suite.py           # Comprehensive automated unit & contract test suite
    ├── branches.json           # Authoritative store registry
    ├── exports/                # Verified branch JSONL datasets
    └── README.md               # Detailed technical documentation
```

---

## 🛒 Projects Portfolio

### 1. [PAK'nSAVE NZ Supermarket Scraper](./paknsave_scraper/)
* **Client / Target**: PAK'nSAVE (`https://www.paknsave.co.nz/`) — Major New Zealand supermarket chain.
* **Architecture**: Direct Algolia edge search API + headless Chromium browser fallback for Cloudflare Turnstile token harvesting.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant with enterprise grocery schema.
  * **GS1 Modulo-10 Checksum Verification**: Mathematical validation of all GTIN-8, 12, 13, and 14 barcodes (isolates 4/5-digit produce PLUs).
  * **Autonomous Cloudflare Turnstile Bypass**: Integrated with CapSolver API and Chromium nodriver solver.
  * **Dynamic Multi-Branch Support**: Resolves store IDs dynamically from PostgreSQL `catalog.branches` with offline fallback.
  * **Independent Availability & Promotions**: Real-world stock status and classification of SAP `BASE` / `LAYERED` (decal: 6000) promotions.
  * **Enterprise Deployment**: Production systemd service/timer units and automated all-branch batch importer.

### 2. [FreshChoice NZ Supermarket Scraper](./freshchoice_scraper/)
* **Client / Target**: FreshChoice Supermarkets New Zealand (`https://www.freshchoice.co.nz/`) — Major MyFoodLink e-commerce network.
* **Architecture**: High-throughput asynchronous crawler with exponential backoff pacing, automated taxonomy sitemap discovery, and detail page enrichment.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents (`current_price_cents`, `comparison_price_cents`).
  * **Multibuy & Unit Price Isolation**: Strict separation of bundle offers (e.g. `3 for $25`) from individual unit prices, eliminating pricing regressions.
  * **Groceries Taxonomy Recovery**: Overcomes MyFoodLink's 50-page (2,400 items) ceiling by automatically crawling 13 direct subcategories and 10 Depth-2 Ethnic subcategories.
  * **GS1 Modulo-10 Barcode Validation**: Mathematically verifies GTIN-8, 12, 13, and 14 check digits while isolating produce PLUs (e.g. Bananas `4011`).
  * **Multi-Branch Isolation**: Registry and lookup for 76 New Zealand supermarket locations with batch ingestion into PostgreSQL/Supabase.

### 3. [Farro Fresh NZ Supermarket Scraper](./farro_scraper/)
* **Client / Target**: Farro Fresh (`https://www.farro.co.nz/`) — Premium Auckland artisan & specialty food supermarket chain.
* **Architecture**: Direct ASP.NET Core / OlympicTrader JSON search API reverse engineering with fast paginated catalog discovery (~4,000 products in ~2 minutes).
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents (`current_price_cents`, `comparison_price_cents`).
  * **GS1 Modulo-10 Checksum Verification**: 100% mathematical validation on all GTIN-8, 12, 13, and 14 barcodes extracted from high-resolution image URLs.
  * **8 Auckland Branch Coverage**: Fully cataloged and mapped all 8 retail stores across Auckland (Grey Lynn, Newmarket, Epsom, Mt Eden, Smales Farm, Mairangi Bay, Mt Wellington, Orakei Bay Village).
  * **Price & Promotion Classification**: Integer cents pricing, special deals, and *Friends of Farro* (`friends-of-farro`) loyalty member pricing.
  * **Automated Batch Importer**: Standalone batch importer for multi-branch JSONL ingestion.

### 4. [The Warehouse NZ Retail & Supermarket Scraper](./thewarehouse_scraper/)
* **Client / Target**: The Warehouse (`https://www.thewarehouse.co.nz/`) — Major New Zealand general merchandise & grocery retail chain.
* **Architecture**: Salesforce Commerce Cloud (Demandware `Sites-twl-Site`) search grid update pagination API with resilient TLS header negotiation.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% schema conformance with integer cents pricing, ISO-8601 UTC timestamps, and zero orphan metadata.
  * **GS1 Modulo-10 Checksum Verification**: 100% mathematical GTIN-8, 12, 13, 14 check digit validation on all barcodes extracted from Demandware product metadata.
  * **76 Nationwide Branches**: Complete registry and lookup for all 76 physical stores across the North and South Islands with isolated JSONL exports.
  * **Promotions & Multibuy Classification**: Full parsing of specials, bundle multibuys (`2 for $6.00`), clearance items, and MarketClub member discounts.
  * **Pico Database Ingestion**: Full dry-run and bulk SQL importer compatibility via `import_products.py` and `import_all_branches.py`.

### 5. [SuperValue NZ Supermarket Scraper](./supervalue_scraper/)
* **Client / Target**: SuperValue Supermarkets New Zealand (`https://www.supervalue.co.nz/`) — Sister supermarket brand under Woolworths NZ.
* **Architecture**: High-throughput asynchronous crawler (HTTPX + BeautifulSoup) with sitemap.xml dynamic discovery and detail page enrichment.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents (`current_price_cents`, `comparison_price_cents`).
  * **Multibuy & Unit Price Isolation**: Strict separation of bundle offers from individual unit prices, eliminating pricing regressions.
  * **Taxonomy & Sitemap Recovery**: Automatically discovers and traverses the complete 606-category catalog hierarchy via sitemap.xml and department routes.
  * **GS1 Modulo-10 Barcode Validation**: Mathematically verifies GTIN-8, 12, 13, and 14 check digits while isolating produce PLUs.
  * **Multi-Branch Isolation**: Registry and lookup for SuperValue branches (Milton online shopping hub, Mangawhai, Te Kuiti) with batch ingestion into PostgreSQL/Supabase.

### 6. [Four Square NZ Supermarket Scraper](./foursquare_scraper/)
* **Client / Target**: Four Square Supermarkets New Zealand (`https://www.foursquare.co.nz/`) — Major community supermarket chain under Foodstuffs NZ.
* **Architecture**: Direct high-speed asynchronous engine (`HTTPX`) with cookie store GUID isolation (`brands_store_id`) and browser-based Turnstile/CapSolver bypass fallback.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents (`current_price_cents`, `unit_price_cents`).
  * **GS1 Modulo-10 Barcode Validation**: Mathematical validation of all GTIN-8, 12, 13, and 14 barcodes, strictly isolating produce PLUs.
  * **210 Authentic Branches Registry**: Pre-compiled registry of all 210 Four Square locations across North and South Islands (`branches.json`) with Foodstuffs GUIDs.
  * **Foodstuffs Detail Enrichment**: Comprehensive product detail cards with nutrition panels, allergens, ingredients, and country of origin statements.
  * **Multi-Branch Workflow & Import Pipeline**: Full batch exporter and database ingestion runner via `import_products.py` and `import_all_branches.py`.

### 7. [Kai Co NZ Supermarket Scraper](./kaico_scraper/)
* **Client / Target**: Kai Co (`https://kaico.co.nz/`) — Locally owned fresh meat, produce & groceries based in Christchurch, New Zealand.
* **Architecture**: High-performance Shopify storefront & collections API ingestion with automated promotions taxonomy mapping.
* **Key Capabilities**:
  * **PICO Scraper Data Contract Compliant**: 100% compliant observation schema with integer cents, UTC ISO timestamps, and top-level null stripping.
  * **GS1 Modulo-10 Checksum Algorithm**: Validates GTIN barcodes mathematically and strictly isolates produce scale PLUs (e.g. 605, 648).
  * **Smart Normalization**: Automatic brand (`Couplands`, `Brinks`, `Cow & Gate`), unit price (`$15.99kg` $\to$ 1599 cents / 1kg), and multibuy parsing (`5 for $3.99`).
  * **Pico Catalog Store Resolution**: Dynamic branch resolver supporting live PostgreSQL `catalog` schema queries with offline `branches.json` fallback.
  * **Zero-Failure Database Ingestion**: Verified 100% pass rate with official `import_products.py` bulk importer.

---

## 📊 Client Quality Assurance & Accuracy Verification

All scrapers in this portfolio adhere strictly to enterprise-grade grocery data standards (**PICO Scraper Data Contract** and **GS1 Modulo-10 Checksum Algorithm**). Clients and QA teams can audit the data accuracy and test suites directly using the instructions below.

### 🏆 1. Master Accuracy Audit Across All Scrapers (Single Command)
Run the consolidated auditor from the repository root to verify schema compliance, barcode integrity, and pricing sanity across all **70,587+ scraped observations**:

```bash
# From the repository root
python audit_all.py
```

#### 📋 Verified Master Audit Output:
```text
==========================================================================================
MASTER ACCURACY & DATA CONTRACT AUDIT REPORT ACROSS ALL SCRAPERS
==========================================================================================
Scraper Name         Files   Records    Schema %   GS1 Sum %   Coverage %  Status    
------------------------------------------------------------------------------------------
PAK'nSAVE            5       38,970     100.0%     100.0%      95.9%       PASSED [OK]
Farro Fresh          8       31,192     100.0%     100.0%      86.7%       PASSED [OK]
Four Square          3       144        100.0%     100.0%      72.9%       PASSED [OK]
The Warehouse        1       64         100.0%     100.0%      100.0%      PASSED [OK]
SuperValue           1       96         100.0%     N/A         0.0%        PASSED [OK]
Kai Co               1       121        100.0%     N/A         0.0%        PASSED [OK]
FreshChoice          1       2          100.0%     100.0%      100.0%      PASSED [OK]
------------------------------------------------------------------------------------------
TOTAL / OVERALL      20      70,589     100.0%     100.0%      91.5%       100% PERFECT
==========================================================================================
```
> **Note on Barcode Coverage**: Fresh bulk produce (e.g. bananas, apples) and deli counter items use 4-to-5 digit scale PLU codes rather than retail GTIN/EAN barcodes. The pipeline strictly isolates these PLUs to eliminate data corruption. For all products with commercial barcodes, the **GS1 Checksum Pass Rate is 100.0%**.

---

### 🔍 2. Individual Scraper Contract & Checksum Audit Commands
To run individual detailed audits with branch-level metrics, stock status, and promotions analysis:

#### 🟢 PAK'nSAVE NZ (`paknsave_scraper`)
```bash
cd paknsave_scraper
python validate_export.py --all
```

#### 🟢 Farro Fresh (`farro_scraper`)
```bash
cd farro_scraper
python validate_export.py --latest
```

#### 🟢 Four Square NZ (`foursquare_scraper`)
```bash
cd foursquare_scraper
python validate_export.py --all
```

#### 🟢 The Warehouse NZ (`thewarehouse_scraper`)
```bash
cd thewarehouse_scraper
python validate_export.py --all
```

#### 🟢 SuperValue NZ (`supervalue_scraper`)
```bash
cd supervalue_scraper
python validate_export.py exports/supervalue_milton_20261030T173806Z.jsonl
```

#### 🟢 Kai Co NZ (`kaico_scraper`)
```bash
cd kaico_scraper
python validate_export.py
```

#### 🟢 FreshChoice NZ (`freshchoice_scraper`)
```bash
cd freshchoice_scraper
python validate_export.py exports
```

---

### 🧪 3. Automated Unit & Regression Test Suites (99/99 Passing Tests)
To run automated test suites ensuring zero regressions in parsing, barcode checksum algorithms, and multibuy price isolation:

* **FreshChoice NZ (54 Tests)**:
  ```bash
  cd freshchoice_scraper
  python -m pytest
  ```
* **Four Square NZ (17 Tests)**:
  ```bash
  cd foursquare_scraper
  python -m pytest test_suite.py
  ```
* **The Warehouse NZ (11 Tests)**:
  ```bash
  cd thewarehouse_scraper
  python -m pytest test_thewarehouse.py
  ```
* **Kai Co NZ (10 Tests)**:
  ```bash
  cd kaico_scraper
  python -m pytest test_suite.py
  ```
* **SuperValue NZ (7 Tests)**:
  ```bash
  cd supervalue_scraper
  python -m pytest test_scraper_parsers.py
  ```

---

## 🛠️ Core Technologies & Standards
* **Languages & Runtimes**: Python 3.10+, Bash, Systemd
* **Web Scraping & Reverse Engineering**: Asyncio, HTTPX, BeautifulSoup4, Patchright, Nodriver, Algolia Search API
* **Bypass & Anti-Bot**: Cloudflare Turnstile automated solver, CapSolver API, Residential Proxies
* **Data Standards**: PICO Scraper Data Contract, GS1 Modulo-10 GTIN Checksums, JSON Lines (JSONL)
* **Databases & DevOps**: PostgreSQL (`catalog` schema, connection pooling), Linux VPS deployment

---

## 👤 Author
**Kapil Singhal**
* GitHub: [@1202Kapil](https://github.com/1202Kapil)
* Email: [singhalkapil717@gmail.com](mailto:singhalkapil717@gmail.com)
