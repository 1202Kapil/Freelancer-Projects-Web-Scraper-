# 🚀 Freelancer Projects — Web Scrapers & Data Pipelines

A curated collection of production-grade, enterprise web scrapers, data pipelines, and reverse-engineered API integrations built for international clients.

Designed and engineered by **Kapil Singhal** ([@1202Kapil](https://github.com/1202Kapil)).

---

## 📂 Repository Structure

```text
Freelancer-Projects-Web-Scraper/
└── paknsave_scraper/           # PAK'nSAVE NZ Supermarket Scraper & Data Pipeline
    ├── paknsave_scraper.py     # Main scraper engine (Algolia API + Cloudflare bypass)
    ├── catalog_branches.py     # PICO PostgreSQL catalog resolver
    ├── import_all_branches.py  # All-branch batch importer
    ├── validate_export.py      # GS1 modulo-10 checksum & contract audit tool
    ├── test_pico_db.py         # Database connectivity & schema diagnostic tool
    ├── deploy/                 # Production systemd timers and bash runner
    ├── exports/                # Verified multi-branch JSONL datasets
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

---

## 🛠️ Core Technologies & Standards
* **Languages & Runtimes**: Python 3.10+, Bash, Systemd
* **Web Scraping & Reverse Engineering**: Asyncio, HTTPX, Patchright, Nodriver, Algolia Search API
* **Bypass & Anti-Bot**: Cloudflare Turnstile automated solver, CapSolver API, Residential Proxies
* **Data Standards**: PICO Scraper Data Contract, GS1 Modulo-10 GTIN Checksums, JSON Lines (JSONL)
* **Databases & DevOps**: PostgreSQL (`catalog` schema, connection pooling), Linux VPS deployment

---

## 👤 Author
**Kapil Singhal**
* GitHub: [@1202Kapil](https://github.com/1202Kapil)
* Email: [singhalkapil717@gmail.com](mailto:singhalkapil717@gmail.com)
