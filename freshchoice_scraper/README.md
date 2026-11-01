# 🛒 FreshChoice NZ Supermarket Scraper & Data Pipeline

A production-grade, enterprise web scraper and automated ingestion pipeline for **FreshChoice Supermarkets New Zealand** (`https://www.freshchoice.co.nz/`) and **SuperValue** (`https://store.supervalue.co.nz/`).

Engineered strictly against the **PICO Scraper Data Contract**, following the benchmark maturity standards of the Woolworths and PAK'nSAVE scraper suites.

---

## 📊 FreshChoice Branch Network (79 Total)

- **Total Registered Branches:** **79 Branches** across New Zealand
- **Online Shopping Branches (`Shop Now`):** **51 Branches** (Active online stores with product catalogues)
- **Physical / In-Store Only (`Store Info`):** **28 Branches** (Physical walk-in stores without online ordering, e.g. *Cuba Street*)

A complete Excel spreadsheet of all 79 branches with addresses, phone numbers, and URLs is available at:  
👉 `exports/freshchoice_branches.csv`

---

## 📋 Comprehensive Schema Reference (All 49 Fields)

Every product observation exported to JSONL and CSV conforms to the complete schema below:

### 1. Schema Field Definitions

| # | Field Name | Data Type | Mandatory / Nullable | Description | Sample Value |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **1** | **`store_id`** | `string` | Mandatory | Store / branch unique identifier | `"bellblock"` |
| **2** | **`branch_id`** | `string` | Mandatory | Retailer branch alias | `"bellblock"` |
| **3** | **`product_id`** | `string` | Mandatory | Product unique identifier / line slug | `"ploughmans-sourdough-bread-750g"` |
| **4** | **`source_product_id`** | `string` | Mandatory | Retailer source product ID | `"ploughmans-sourdough-bread-750g"` |
| **5** | **`sku`** | `string` | Mandatory | Retailer stock keeping unit | `"ploughmans-sourdough-bread-750g"` |
| **6** | **`retailer_sku`** | `string` | Mandatory | Retailer SKU alias | `"ploughmans-sourdough-bread-750g"` |
| **7** | **`gtin`** | `string / null` | Nullable | Global Trade Item Number (GS1 Checksum Pass) | `null` *(not exposed on frontend)* |
| **8** | **`barcode`** | `string / null` | Nullable | Barcode alias (8, 12, 13, 14 digits) | `null` *(not exposed on frontend)* |
| **9** | **`mpn`** | `string / null` | Nullable | Manufacturer Part Number *(N/A for grocery)* | `null` |
| **10** | **`group_id`** | `string / null` | Nullable | Parent variant group *(discrete lines)* | `null` |
| **11** | **`raw_name`** | `string` | Mandatory | Raw title exactly as displayed on site | `"Ploughmans Sourdough Bread"` |
| **12** | **`clean_name`** | `string` | Mandatory | Sanitized title (clean of trailing prices) | `"Ploughmans Sourdough Bread"` |
| **13** | **`brand`** | `string / null` | Conditional | Brand name extracted from GTM / JSON-LD | `"Ploughmans"` |
| **14** | **`department`** | `string` | Mandatory | Level-1 Top Department | `"Bakery"` |
| **15** | **`category`** | `string / null` | Conditional | Level-2 Category | `"Bread"` |
| **16** | **`sub_category`** | `string / null` | Conditional | Level-3 Sub-Category | `"Bread, Buns, Rolls"` |
| **17** | **`leaf_category`** | `string` | Mandatory | Deepest / lowest-level category | `"Bread, Buns, Rolls"` |
| **18** | **`lead_category`** | `string` | Mandatory | Leaf category alias | `"Bread, Buns, Rolls"` |
| **19** | **`breadcrumbs`** | `list[str]` | Mandatory | Ordered array of categories | `["Bakery", "Bread", "Bread, Buns, Rolls"]` |
| **20** | **`category_hierarchy`**| `list[str]` | Mandatory | Full taxonomy list representation | `["Bakery", "Bread", "Bread, Buns, Rolls"]` |
| **21** | **`category_path`** | `string` | Mandatory | Breadcrumb path string | `"Bakery > Bread > Bread, Buns, Rolls"` |
| **22** | **`category_tree`** | `string` | Mandatory | Category tree hierarchy string | `"Bakery > Bread > Bread, Buns, Rolls"` |
| **23** | **`category_url`** | `string` | Mandatory | Canonical URL of leaf subcategory | `"https://bellblock.store.supervalue.co.nz/category/bread-buns-rolls"` |
| **24** | **`size`** | `string / null` | Conditional | Package size or weight | `"750g"` |
| **25** | **`currency`** | `string` | Mandatory | Currency code | `"NZD"` |
| **26** | **`price`** | `float` | Mandatory | Current selling price in NZD dollars | `3.99` |
| **27** | **`current_price_cents`**| `integer` | Mandatory | Current selling price in integer cents | `399` |
| **28** | **`sale_price`** | `float / null` | Conditional | Discounted price in dollars (if on promo) | `3.99` *(null if non-sale)* |
| **29** | **`sale_price_cents`**| `integer / null`| Conditional | Discounted price in integer cents | `399` *(null if non-sale)* |
| **30** | **`list_price`** | `float` | Mandatory | Regular original / WAS price in dollars | `4.79` |
| **31** | **`list_price_cents`**| `integer` | Mandatory | Regular original / WAS price in cents | `479` |
| **32** | **`comparison_price_cents`**| `integer / null`| Conditional | Was-price comparison in integer cents | `479` |
| **33** | **`savings`** | `float / null` | Conditional | Dollar savings on promo | `0.80` *(null if non-sale)* |
| **34** | **`savings_cents`** | `integer / null`| Conditional | Savings in integer cents | `80` *(null if non-sale)* |
| **35** | **`price_per_unit`**| `float / null` | Conditional | Unit price in dollars | `0.53` |
| **36** | **`price_by_unit`** | `string / null`| Conditional | Unit of measure basis | `"100g"` |
| **37** | **`unit_price_cents`**| `integer / null`| Conditional | Unit price in integer cents | `53` |
| **38** | **`unit_label`** | `string / null`| Conditional | Unit label alias | `"100g"` |
| **39** | **`is_promo`** | `boolean` | Mandatory | Promotional deal flag | `true` or `false` |
| **40** | **`promo_badge`** | `string / null`| Conditional | Website promo sticker text | `"save 80c"` or `"SWEET SAVE"` |
| **41** | **`promo_text`** | `string / null`| Conditional | Descriptive promotion text | `"save 80c | Save $0.80"` |
| **42** | **`promo_type`** | `string / null`| Conditional | Deal type (`"special"`, `"multibuy_fixed_price"`)| `"special"` |
| **43** | **`multibuy_quantity`**| `integer / null`| Conditional | Multibuy bundle count (e.g. 3 in "3 for $25") | `null` |
| **44** | **`multibuy_price_cents`**| `integer / null`| Conditional | Multibuy bundle price in integer cents | `null` |
| **45** | **`availability`** | `string` | Mandatory | Availability status (`"in_stock"`, `"out_of_stock"`)| `"in_stock"` |
| **46** | **`stock_status`** | `string` | Mandatory | Contract stock status standard | `"in_stock"` |
| **47** | **`url`** | `string` | Mandatory | Full canonical product URL | `"https://bellblock.store.supervalue.co.nz/lines/ploughmans-sourdough-bread-750g"` |
| **48** | **`product_url`** | `string` | Mandatory | Canonical product URL alias | `"https://bellblock.store.supervalue.co.nz/lines/ploughmans-sourdough-bread-750g"` |
| **49** | **`image_url`** | `string / null`| Conditional | CloudFront CDN image link | `"https://dtgxwmigmg3gc.cloudfront.net/..."` |
| **50** | **`description`** | `string / null`| Conditional | Product description (from PDP enrichment) | `"The Goodness of Grains."` |
| **51** | **`recommended_products`**| `list` | Mandatory | Related products list *(website has 0)* | `[]` |
| **52** | **`observed_at`** | `string` | Mandatory | UTC ISO-8601 scrape timestamp | `"2026-11-01T18:37:34Z"` |
| **53** | **`raw_row`** | `dict` | Mandatory | Debug payload & raw audit info | `{"branch_id": "bellblock", ...}` |

---

### 2. Category Hierarchy Architecture

The scraper maps the complete 3-level grocery taxonomy from MyFoodLink & Google Tag Manager dataLayer:

```
[department]      "Bakery"
      │
      ▼
[category]        "Bread"
      │
      ▼
[sub_category]    "Bread, Buns, Rolls"
      │
      ▼
[leaf_category]   "Bread, Buns, Rolls"
      │
      ▼
[category_path]   "Bakery > Bread > Bread, Buns, Rolls"
[category_tree]   "Bakery > Bread > Bread, Buns, Rolls"
[breadcrumbs]     ["Bakery", "Bread", "Bread, Buns, Rolls"]
[category_url]    "https://bellblock.store.supervalue.co.nz/category/bread-buns-rolls"
```

---

### 3. Concrete Sample JSON Record (Live Bell Block Extract)

```json
{
  "store_id": "bellblock",
  "branch_id": "bellblock",
  "product_id": "ploughmans-sourdough-bread-750g",
  "source_product_id": "ploughmans-sourdough-bread-750g",
  "sku": "ploughmans-sourdough-bread-750g",
  "retailer_sku": "ploughmans-sourdough-bread-750g",
  "gtin": null,
  "barcode": null,
  "mpn": null,
  "group_id": null,
  "raw_name": "Ploughmans Sourdough Bread",
  "clean_name": "Ploughmans Sourdough Bread",
  "brand": "Ploughmans",
  "department": "Bakery",
  "category": "Bread",
  "sub_category": "Bread, Buns, Rolls",
  "leaf_category": "Bread, Buns, Rolls",
  "lead_category": "Bread, Buns, Rolls",
  "breadcrumbs": [
    "Bakery",
    "Bread",
    "Bread, Buns, Rolls"
  ],
  "category_hierarchy": [
    "Bakery",
    "Bread",
    "Bread, Buns, Rolls"
  ],
  "category_path": "Bakery > Bread > Bread, Buns, Rolls",
  "category_tree": "Bakery > Bread > Bread, Buns, Rolls",
  "category_url": "https://bellblock.store.supervalue.co.nz/category/bread-buns-rolls",
  "size": "750g",
  "description": null,
  "currency": "NZD",
  "price": 3.99,
  "current_price_cents": 399,
  "sale_price": 3.99,
  "sale_price_cents": 399,
  "list_price": 4.79,
  "list_price_cents": 479,
  "comparison_price_cents": 479,
  "savings": 0.80,
  "savings_cents": 80,
  "price_per_unit": 0.53,
  "price_by_unit": "100g",
  "unit_price_cents": 53,
  "unit_label": "100g",
  "is_promo": true,
  "promo_badge": "save 80c",
  "promo_text": "save 80c | Save $0.80",
  "promo_type": "special",
  "multibuy_quantity": null,
  "multibuy_price_cents": null,
  "availability": "in_stock",
  "stock_status": "in_stock",
  "url": "https://bellblock.store.supervalue.co.nz/lines/ploughmans-sourdough-bread-750g",
  "product_url": "https://bellblock.store.supervalue.co.nz/lines/ploughmans-sourdough-bread-750g",
  "image_url": "https://dtgxwmigmg3gc.cloudfront.net/imagery/assets/derivations/icon/256/256/true/eyJpZCI6ImNmNzNjNjYyYTdhMzVjMDBkMTExZTA5MWU0YmU0ZDFhLmpwZzIwMjYwODAzLTEyMjIxMTEtaDE3MDAyIiwic3RvcmFnZSI6InB1YmxpY19zdG9yZSJ9?signature=320980c0a75fe98ebc2cdb13aa6bd101dfedcb5e8b8ba9fb83513fa1452bf9ae",
  "recommended_products": [],
  "observed_at": "2026-11-01T18:37:34Z",
  "raw_row": {
    "branch_id": "bellblock",
    "department": "Bakery",
    "category": "Bread",
    "sub_category": "Bread, Buns, Rolls",
    "leaf_category": "Bread, Buns, Rolls",
    "category_url": "https://bellblock.store.supervalue.co.nz/category/bread-buns-rolls",
    "category_tree": "Bakery > Bread > Bread, Buns, Rolls",
    "price_per_unit": 0.53,
    "price_by_unit": "100g"
  }
}
```

---

## 📂 Project Structure

```text
freshchoice_scraper/
├── config.py                 # Central configurations, categories, recovery paths, rate limits
├── catalog_branches.py       # 79-branch registry and catalog resolver
├── check_branches.py         # Branch inspector, live verifier, search & CSV exporter
├── freshchoice_scraper.py    # Main async scraping engine (HTTPX + BeautifulSoup)
├── parsers.py                # HTML, JSON-LD, GTM dataLayer parser & unit price math
├── jsonl_exporter.py         # Atomic JSONL exporter with preserved schema keys
├── validate_export.py        # Contract & schema compliance auditor
├── merge_exports.py          # Consolidates all branch exports into merged JSONL & CSV
├── import_products.py        # Pico branch database importer (bulk SQL)
├── import_all_branches.py    # Batch orchestrator for all branch exports
├── test_scraper_parsers.py   # Unit test suite for parsers and pricing logic
├── test_systematic_fixes.py  # Unit test suite for schema & contract compliance
├── exports/                  # Directory for exported datasets
│   ├── freshchoice_branches.csv              # All 79 branches (open in Excel)
│   ├── freshchoice_branches.json             # JSON format of all 79 branches
│   ├── freshchoice_all_branches_merged.jsonl # Master consolidated JSONL
│   ├── freshchoice_all_branches_merged.csv   # Master consolidated Excel CSV
│   └── freshchoice_{branch}_{stamp}.jsonl    # Per-branch individual datasets
└── requirements.txt          # Python dependencies
```

---

## 🚀 All Commands Guide (Sabhi Commands)

### 1. Requirements Setup
```powershell
pip install -r requirements.txt
```

---

### 2. Branch Verification Commands (`check_branches.py`)

| Purpose | Command |
| :--- | :--- |
| **Total Branch Summary Dekhna** (79 Total, 51 Online, 28 Physical) | `python check_branches.py` |
| **Website Se Live Count Match Karna** | `python check_branches.py --live` |
| **Saare 51 Online (Shop Now) Branches List Karna** | `python check_branches.py --online` |
| **Baki 28 Physical (Store Info) Branches List Karna** | `python check_branches.py --instore` |
| **Saare 79 Branches Ki Numbered List Dekhna** | `python check_branches.py --all` |
| **Kisi Specific Branch Ko Search Karna** | `python check_branches.py --search bellblock` |
| **Branch URL Connectivity Test (Ping) Karna** | `python check_branches.py --ping --limit 10` |
| **Excel CSV File Generate Karna** | `python check_branches.py --export` |

---

### 3. Scraper Execution Commands (`freshchoice_scraper.py`)

Product data scrape karke `exports/` folder me `.jsonl` file generate karne ke liye:

* **Quick Test — Single Category (Fast ~20s, e.g. Bell Block Bakery):**
  ```powershell
  python freshchoice_scraper.py --branches bellblock --category bakery
  ```

* **Kisi Aur Branch Ki Specific Category (e.g. Cromwell Drinks):**
  ```powershell
  python freshchoice_scraper.py --branches cromwell --category drinks
  ```

* **Multiple Branches Ek Saath Scrape Karna:**
  ```powershell
  python freshchoice_scraper.py --branches bellblock,cromwell --category bakery
  ```

* **Ek Branch Ke Saare 18 Departments Scrape Karna:**
  ```powershell
  python freshchoice_scraper.py --branches bellblock
  ```

* **Default Benchmark Branches Scrape Karna (Merivale, Epsom, Green Island):**
  ```powershell
  python freshchoice_scraper.py
  ```

* **Saari 51 Online Branches Ko Scrape Karna:**
  ```powershell
  python freshchoice_scraper.py --all-branches
  ```

* **Detail Page Enrichment Ke Saath (Barcodes & Descriptions):**
  ```powershell
  python freshchoice_scraper.py --branches bellblock --category bakery --enrich-details --max-details 20
  ```

---

### 4. Merging All Exports into One Master File (`merge_exports.py`)

Alag-alag branch runs ko deduplicate karke ek consolidated master dataset banane ke liye:

```powershell
python merge_exports.py
```
*Outputs generated:*
- `exports/freshchoice_all_branches_merged.jsonl`
- `exports/freshchoice_all_branches_merged.csv`

---

### 5. Schema & Quality Audit Validation (`validate_export.py`)

Contract errors, price sanity, stock status, aur promo structure verify karne ke liye:

* **Merged Master Dataset Validate Karna:**
  ```powershell
  python validate_export.py exports/freshchoice_all_branches_merged.jsonl
  ```

* **Specific Branch File Validate Karna:**
  ```powershell
  python validate_export.py exports/freshchoice_bellblock_20261101T183734Z.jsonl
  ```

---

### 6. Unit Tests Run Karna

```powershell
python -m unittest test_scraper_parsers.py test_systematic_fixes.py
```

---

### 7. Quick Data Inspection in Terminal

Merged file ki pehli row ko pretty JSON format me dekhne ke liye:

```powershell
python -c "import json; print(json.dumps(json.loads(open('exports/freshchoice_all_branches_merged.jsonl', 'r', encoding='utf-8').readline()), indent=2))"
```
