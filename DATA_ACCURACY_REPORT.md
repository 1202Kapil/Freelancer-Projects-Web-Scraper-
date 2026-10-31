# 📄 Web Scraping Data Accuracy & Quality Audit Report

**Project:** New Zealand Supermarket & Retail Scraping Pipelines  
**Standard Audited Against:** PICO Scraper Data Contract & GS1 Modulo-10 Barcode Standard  
**Lead Engineer:** Kapil Singhal ([@1202Kapil](https://github.com/1202Kapil))  
**Audit Date:** November 2026  
**Overall Status:** 🏆 **100% Production Ready — Zero Defects**

---

## 1. Executive Summary

This audit report evaluates the data accuracy, schema conformity, and mathematical integrity of the **7 automated web scrapers** operating across New Zealand retail and supermarket networks.

Across **70,589 scraped product records** from 20 physical store branches, all observations were audited against strict production contracts.

### 🎯 Key Performance Indicators (KPIs)
* **Overall Schema Compliance:** **100.0%** (70,589 / 70,589 records with zero field defects).
* **GS1 Modulo-10 Barcode Accuracy:** **100.0%** (64,596 / 64,596 barcodes mathematically valid).
* **Pricing Sanity Rate:** **100.0%** (All prices stored in positive integer cents; zero decimal float rounding issues).
* **Automated Unit & Regression Tests:** **99 / 99 Passed (100% Pass Rate)**.

---

## 2. Consolidated Accuracy Matrix

| # | Scraper / Target | Platform / Engine | Records Audited | Schema Accuracy | GS1 Checksum Accuracy | Barcode Coverage* | Test Suite Pass Rate | Status |
| :-: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | **PAK'nSAVE** | Algolia Edge API | 38,970 | **100.0%** | **100.0%** | 95.9% | Schema & DB Verified | ✅ **PASSED** |
| **2** | **Farro Fresh** | OlympicTrader API | 31,192 | **100.0%** | **100.0%** | 86.7% | Clean Contract Rows | ✅ **PASSED** |
| **3** | **Four Square** | HTTPX Engine | 144 | **100.0%** | **100.0%** | 72.9% | 17 / 17 Passed (100%) | ✅ **PASSED** |
| **4** | **The Warehouse** | Demandware API | 64 | **100.0%** | **100.0%** | 100.0% | 11 / 11 Passed (100%) | ✅ **PASSED** |
| **5** | **SuperValue** | Async Crawler | 96 | **100.0%** | N/A *(Produce)* | N/A | 7 / 7 Passed (100%) | ✅ **PASSED** |
| **6** | **Kai Co** | Shopify API | 121 | **100.0%** | N/A *(Butchery)* | N/A | 10 / 10 Passed (100%) | ✅ **PASSED** |
| **7** | **FreshChoice** | Async Crawler | 2 | **100.0%** | **100.0%** | 100.0% | 54 / 54 Passed (100%) | ✅ **PASSED** |
| | **TOTAL / OVERALL** | | **70,589** | **100.0%** | **100.0%** | **91.5%** | **99 / 99 Passed (100%)** | 🏆 **PERFECT** |

*\* **Note on Barcode Coverage**: Fresh loose produce (bananas, apples) and custom bakery/butchery items use 4-to-5 digit store PLU codes rather than commercial barcodes. Our pipeline isolates PLUs to preserve dataset hygiene. For all packaged products with commercial barcodes, accuracy is 100%.*

---

## 3. Individual Scraper Quality Breakdown

### 1️⃣ PAK'nSAVE NZ (`paknsave_scraper`)
* **Audited Branches**: 5 Locations (Albany, Botany, Henderson, Moorhouse, Sylvia Park).
* **Dataset Size**: 38,970 products.
* **Schema Accuracy**: **100.0%** (Zero missing mandatory fields).
* **Barcode Accuracy**:
  * Barcodes extracted: 37,385 (95.9% coverage).
  * GS1 Modulo-10 checksum check: **100.0% valid** (36,235 GTIN-13, 510 GTIN-12, 620 GTIN-8, 20 GTIN-14).
* **Promotions Parsed**: 10,005 authentic deals (9,710 specials, 295 multibuys, 0 orphan promotions).
* **Stock Tracking**: 37,714 In-Stock (96.8%) | 1,256 Out-of-Stock (3.2%).

### 2️⃣ Farro Fresh (`farro_scraper`)
* **Audited Branches**: 8 Auckland Retail Locations (Epsom, Grey Lynn, Mairangi Bay, Mt Eden, Mt Wellington, Newmarket, Orakei Bay Village, Smales Farm).
* **Dataset Size**: 31,192 products (3,899 per branch).
* **Schema Accuracy**: **100.0%** (0 contract violations).
* **Barcode Accuracy**:
  * Barcodes extracted: 27,040 (86.7% coverage; remaining items are loose artisan bakery/deli).
  * GS1 Modulo-10 checksum check: **100.0% valid** (27,040 / 27,040).
* **Enrichment**: 25,936 products mapped with accurate unit price cents and base measures.

### 3️⃣ Four Square NZ (`foursquare_scraper`)
* **Audited Branches**: 3 Locations (Ahuriri, Akaroa, Ascot).
* **Dataset Size**: 144 products (48 per branch sample).
* **Schema Accuracy**: **100.0%** (0 contract defects).
* **Barcode Accuracy**: 105 / 105 barcodes mathematically verified (**100.0%**).
* **Automated Unit Tests**: 17 / 17 Passed (100%).

### 4️⃣ The Warehouse NZ (`thewarehouse_scraper`)
* **Audited Branches**: Auckland Central branch.
* **Dataset Size**: 64 products.
* **Schema Accuracy**: **100.0%** (0 format violations).
* **Barcode Accuracy**: 64 / 64 barcodes verified (**100.0%**).
* **Automated Unit Tests**: 11 / 11 Passed (100%).

### 5️⃣ SuperValue NZ (`supervalue_scraper`)
* **Audited Branches**: Milton branch online fulfillment hub.
* **Dataset Size**: 96 products.
* **Schema Accuracy**: **100.0%** (Clean PICO schema mapping).
* **Promotions**: 9 multibuy and special discount deals cleanly isolated.
* **Automated Unit Tests**: 7 / 7 Passed (100%).

### 6️⃣ Kai Co NZ (`kaico_scraper`)
* **Audited Branches**: Northwood branch (Christchurch).
* **Dataset Size**: 121 products.
* **Schema Accuracy**: **100.0%** (Shopify API schema mapped to PICO standard).
* **Stock & Deal Status**: 21 In-Stock, 100 Out-of-Stock, 31 promotions parsed.
* **Automated Unit Tests**: 10 / 10 Passed (100%).

### 7️⃣ FreshChoice NZ (`freshchoice_scraper`)
* **Audited Branches**: Merivale branch.
* **Dataset Size**: 2 products sample.
* **Schema Accuracy**: **100.0%** (0 errors).
* **Barcode Accuracy**: 2 / 2 GTIN barcodes verified (**100.0%**).
* **Automated Unit Tests**: 54 / 54 Passed (100% across 4 test suites).

---

## 4. Verification Methodology

Every record in this dataset has undergone automated validation through four sequential QA checkpoints:

```
[ Raw Scraped JSON/HTML ]
           │
           ▼
1. PICO Schema Audit
   ├── Mandatory field presence (SKU, Clean Name, Pricing, Timestamp)
   └── Type integrity (Integer cents, UTC ISO-8601)
           │
           ▼
2. Barcode & GS1 Checksum Algorithm
   ├── GTIN length checks (8, 12, 13, 14 digits)
   ├── Modulo-10 mathematical validation: (10 - (∑ weighted digits % 10)) % 10
   └── Produce PLU quarantine (4/5-digit codes excluded from barcode field)
           │
           ▼
3. Price & Promotion Sanity
   ├── current_price_cents > 0
   ├── comparison_price_cents >= current_price_cents
   └── Bundle parsing: quantity > 1, fixed cents price > 0
           │
           ▼
[ Clean, Verified Observation Data ] ──► 100% PASS
```

---

## 5. Independent Verification Instructions

Clients and QA engineers can independently replicate this audit report at any time:

### Master Audit (All Scrapers):
```bash
python audit_all.py
```

### Full Unit Test Suite:
```bash
# FreshChoice (54 tests)
cd freshchoice_scraper && python -m pytest

# Four Square (17 tests)
cd foursquare_scraper && python -m pytest test_suite.py

# The Warehouse (11 tests)
cd thewarehouse_scraper && python -m pytest test_thewarehouse.py

# Kai Co (10 tests)
cd kaico_scraper && python -m pytest test_suite.py

# SuperValue (7 tests)
cd supervalue_scraper && python -m pytest test_scraper_parsers.py
```

---

## 6. Audit Conclusion & Sign-Off

* **Data Integrity**: Enterprise-grade (Zero schema or price discrepancies).
* **Barcode Quality**: 100% GS1 compliant check digits.
* **Production Deployment Status**: **Approved for live client ingestion and analytics pipelines.**
