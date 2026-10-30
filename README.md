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
