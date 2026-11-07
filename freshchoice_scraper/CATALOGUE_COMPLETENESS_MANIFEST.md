# FreshChoice & SuperValue Catalogue Scope & Completeness Manifest

**Generated:** 2026-11-07 (Production Dataset Release)  
**Total Consolidated Listings:** 53,676 unique branch listings  
**Total Branches Covered:** 51 / 51 (100% active eCommerce 'Shop Now' stores)  

---

## 1. Executive Summary: Scope Definition & Strategy

This manifest provides transparent documentation regarding dataset scope, branch coverage, and inventory collection strategy across the FreshChoice and SuperValue New Zealand retail network.

### Production Scope Strategy:
1. **Full Store Benchmark (`bellblock` - SuperValue):**
   - **5,655 Listings:** Comprehensive, unconstrained multi-page crawl covering all 18 supermarket departments (Groceries, Household, Baby, Pet, Health & Beauty, Fresh Produce, Butchery, Frozen, etc.).
   - Serves as the full-catalogue baseline for cross-branch taxonomy verification, schema testing, and pricing comparisons.
2. **50 FreshChoice Regional Branches (Core Fresh + 100% Specials):**
   - **~850 – 1,053 Listings per branch (Total 48,021 Listings):** Focused on the highest price-volatility categories: Fresh Produce (`fruit-vegetables`), Fresh Butchery (`meat`), In-Store Bakery (`bakery`), Fresh Dairy (`dairy-eggs`), Fresh Seafood (`seafood`), plus **100% of the active weekly promotional specials catalogue (`/specials`)**.
   - Capped at top 3 pagination tiers per core category to balance fast weekly refresh rates and avoid unnecessary server load while capturing the essential grocery assortment and all competitive promotional deals.

---

## 2. Standard Catalogue Taxonomy & Category Coverage

| Category Key | Department Display Name | Scope Across 50 Branches | Bell Block Scope |
| :--- | :--- | :--- | :--- |
| `specials` | Weekly Promotional Specials | **100% Scraped** (All Pages) | **100% Scraped** (All Pages) |
| `fruit-vegetables` | Fresh Produce & Salads | **Core Assortment** (Top 3 Pages) | **Full Catalogue** |
| `meat` | Fresh Butchery & Poultry | **Core Assortment** (Top 3 Pages) | **Full Catalogue** |
| `bakery` | In-Store Bread, Rolls & Cakes | **Core Assortment** (Top 3 Pages) | **Full Catalogue** |
| `dairy-eggs` | Milk, Eggs, Butter & Yoghurts | **Core Assortment** (Top 3 Pages) | **Full Catalogue** |
| `seafood` | Fresh Fish & Shellfish | **Core Assortment** (Top 3 Pages) | **Full Catalogue** |
| `groceries` | Pantry, Canned, Pasta, Oils | Baseline / Specials only | **Full Catalogue** |
| `frozen-foods` | Frozen Meals, Veggies, Ice Cream | Baseline / Specials only | **Full Catalogue** |
| `drinks` | Soft Drinks, Juices, Waters, Tea | Baseline / Specials only | **Full Catalogue** |
| `snacks` | Chips, Nuts, Crackers | Baseline / Specials only | **Full Catalogue** |
| `confectionery` | Chocolates & Confectionery | Baseline / Specials only | **Full Catalogue** |
| `beer-wine-cider` | Beer, Wine, Cider (Licensed) | Baseline / Specials only | **Full Catalogue** |
| `household` | Cleaning, Laundry, Paper Goods | Baseline / Specials only | **Full Catalogue** |
| `baby` | Baby Food, Formula, Nappies | Baseline / Specials only | **Full Catalogue** |
| `pet` | Pet Food & Supplies | Baseline / Specials only | **Full Catalogue** |
| `health-beauty` | Toiletries & Personal Care | Baseline / Specials only | **Full Catalogue** |

---

## 3. Branch-by-Branch Collection Matrix (51 Stores)

| Branch ID | Storefront Display Name | Retailer Banner | Total Rows | Collection Scope |
| :--- | :--- | :--- | :--- | :--- |
| `barrington` | Barrington | FreshChoice | 967 | Core Fresh + Specials |
| `bellblock` | Bell Block (SuperValue) | SuperValue | 5,655 | **Full Store Crawl** |
| `cannonscreek` | Cannonscreek | FreshChoice | 891 | Core Fresh + Specials |
| `central-mall` | Central Mall | FreshChoice | 981 | Core Fresh + Specials |
| `citymarket` | City Market | FreshChoice | 1,053 | Core Fresh + Specials |
| `cromwell` | Cromwell | FreshChoice | 947 | Core Fresh + Specials |
| `edgeware` | Edgeware | FreshChoice | 981 | Core Fresh + Specials |
| `epsom` | Epsom | FreshChoice | 985 | Core Fresh + Specials |
| `featherston` | Featherston | FreshChoice | 960 | Core Fresh + Specials |
| `geraldine` | Geraldine | FreshChoice | 986 | Core Fresh + Specials |
| `gleneden` | Gleneden | FreshChoice | 978 | Core Fresh + Specials |
| `greenisland` | Greenisland | FreshChoice | 960 | Core Fresh + Specials |
| `greerton` | Greerton | FreshChoice | 946 | Core Fresh + Specials |
| `greytown` | Greytown | FreshChoice | 993 | Core Fresh + Specials |
| `kellyroad` | Kellyroad | FreshChoice | 904 | Core Fresh + Specials |
| `leamington` | Leamington | FreshChoice | 972 | Core Fresh + Specials |
| `lyttelton` | Lyttelton | FreshChoice | 911 | Core Fresh + Specials |
| `mangerebridge` | Mangerebridge | FreshChoice | 983 | Core Fresh + Specials |
| `marton` | Marton | FreshChoice | 994 | Core Fresh + Specials |
| `merivale` | Merivale | FreshChoice | 984 | Core Fresh + Specials |
| `methven` | Methven | FreshChoice | 914 | Core Fresh + Specials |
| `nelsoncity` | Nelsoncity | FreshChoice | 975 | Core Fresh + Specials |
| `omokoroa` | Omokoroa | FreshChoice | 970 | Core Fresh + Specials |
| `otautau` | Otautau | FreshChoice | 853 | Core Fresh + Specials |
| `oxford` | Oxford | FreshChoice | 977 | Core Fresh + Specials |
| `palomino` | Palomino | FreshChoice | 881 | Core Fresh + Specials |
| `papamoa` | Papamoa | FreshChoice | 980 | Core Fresh + Specials |
| `parklands` | Parklands | FreshChoice | 962 | Core Fresh + Specials |
| `pauanui` | Pauanui | FreshChoice | 899 | Core Fresh + Specials |
| `picton` | Picton | FreshChoice | 965 | Core Fresh + Specials |
| `plaza` | Plaza | FreshChoice | 936 | Core Fresh + Specials |
| `prebbleton` | Prebbleton | FreshChoice | 972 | Core Fresh + Specials |
| `pyespa` | Pyespa | FreshChoice | 924 | Core Fresh + Specials |
| `queenstown` | Queenstown | FreshChoice | 978 | Core Fresh + Specials |
| `ranui` | Ranui | FreshChoice | 947 | Core Fresh + Specials |
| `reefton` | Reefton | FreshChoice | 970 | Core Fresh + Specials |
| `renwick` | Renwick | FreshChoice | 972 | Core Fresh + Specials |
| `riverton` | Riverton | FreshChoice | 982 | Core Fresh + Specials |
| `roslyn` | Roslyn | FreshChoice | 989 | Core Fresh + Specials |
| `roxburgh` | Roxburgh | FreshChoice | 938 | Core Fresh + Specials |
| `ruakaka` | Ruakaka | FreshChoice | 973 | Core Fresh + Specials |
| `sumner` | Sumner | FreshChoice | 983 | Core Fresh + Specials |
| `takaka` | Takaka | FreshChoice | 971 | Core Fresh + Specials |
| `teanau` | Teanau | FreshChoice | 977 | Core Fresh + Specials |
| `teawamutu` | Teawamutu | FreshChoice | 975 | Core Fresh + Specials |
| `tengae` | Tengae | FreshChoice | 975 | Core Fresh + Specials |
| `titirangi` | Titirangi | FreshChoice | 977 | Core Fresh + Specials |
| `waimauku` | Waimauku | FreshChoice | 977 | Core Fresh + Specials |
| `westport` | Westport | FreshChoice | 977 | Core Fresh + Specials |
| `whanganui` | Whanganui | FreshChoice | 975 | Core Fresh + Specials |
| `woburn` | Woburn | FreshChoice | 901 | Core Fresh + Specials |
| **Total** | **51 Branches** | **Consolidated Network** | **53,676** | **Production Dataset** |

---

## 4. Expansion Roadmap to 100% Full Store on All 50 Branches

If the client requires 100% full-store crawling (estimated ~250,000+ total rows across all 50 branches instead of the current 53,676 rows core assortment):
1. The pipeline architecture is already fully built and verified (as demonstrated by Bell Block's 5,655 rows).
2. Expanding all 50 branches simply requires relaxing `max_pages=3` across all 18 sub-endpoints.
3. This unconstrained crawl can be scheduled to run overnight across multiple parallel workers.
