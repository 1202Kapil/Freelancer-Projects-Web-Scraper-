"""Configuration and constants for FreshChoice NZ Supermarket Scraper."""
from __future__ import annotations

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
SCRAPER_DIR = Path(__file__).resolve().parent
load_dotenv(SCRAPER_DIR / ".env")

EXPORTS_DIR = SCRAPER_DIR / "exports"
LOGS_DIR = SCRAPER_DIR / "logs"
CACHE_PATH = SCRAPER_DIR / ".freshchoice_cache.json"

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Retailer & Endpoints
RETAILER = "freshchoice"
BASE_URL = "https://www.freshchoice.co.nz"
STORE_URL_TEMPLATE = "https://{branch}.store.freshchoice.co.nz"
CATEGORY_PATH_TEMPLATE = "/category/{category_slug}?page={page}"
PRODUCT_DETAIL_PATH_TEMPLATE = "/lines/{slug}"
SITEMAP_PATH = "/sitemap.xml"

# Default benchmark branches
DEFAULT_BRANCHES = ["merivale", "epsom", "greenisland"]

# Top-level catalogue categories
CATEGORIES = [
    "fruit-vegetables",
    "bakery",
    "meat",
    "seafood",
    "deli",
    "dairy-eggs",
    "groceries",
    "frozen-foods",
    "drinks",
    "snacks",
    "confectionery",
    "beer-wine-cider",
    "household",
    "baby",
    "pet",
    "health-beauty",
    "supplements",
    "bulk-foods",
]

# Alternate category slugs for resilient route matching (e.g. Deli 404 fallback)
CATEGORY_ALIASES = {
    "deli": ["deli-kitchen", "delicatessen", "deli", "chilled-deli"],
    "fruit-vegetables": ["fruit-vegetables", "fruit-and-vegetables", "produce"],
    "dairy-eggs": ["dairy-eggs", "dairy-and-eggs"],
    "beer-wine-cider": ["beer-wine-cider", "beer-wine-and-cider", "liquor"],
}

# Groceries recovery subcategories to overcome MyFoodLink 50-page (2,400 items) cap
GROCERIES_RECOVERY_SUBCATEGORIES = [
    "prepared-foods",
    "breakfast-foods",
    "pasta-rice",
    "sauces-condiments",
    "biscuits-muesli-bars",
    "canned-dried-vegetables",
    "canned-fruit-desserts",
    "canned-fish-chicken",
    "cooking-needs",
    "ethnic-gourmet-food",
    "jams-spreads",
    "oils-vinegars",
    "health-foods",
]

# Depth-2 subcategories under Ethnic, Gourmet Food
ETHNIC_DEPTH2_SUBCATEGORIES = [
    "general-1",
    "asian",
    "indian",
    "middle-eastern",
    "uk",
    "nz",
    "italian",
    "south-african",
    "dutch",
    "mexican",
]

# Network & Pacing
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
)

EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT_SECONDS = 30.0
PER_HOST_CONCURRENCY = 1
BRANCH_CONCURRENCY = 2
REQUEST_DELAY_MIN = 1.0
REQUEST_DELAY_MAX = 2.0
RETRY_ATTEMPTS = 3
BACKOFF_FACTOR = 1.5

# Validation & Constraints
ITEMS_PER_PAGE_EXPECTED = 48
MAX_PAGE_PER_CATEGORY = 50  # MyFoodlink ceiling
VALID_GTIN_LENGTHS = {8, 12, 13, 14}
VALID_STOCK_STATUSES = {"in_stock", "out_of_stock"}
VALID_PROMO_TYPES = {
    "special",
    "member_price",
    "multibuy_fixed_price",
    "multibuy_discount",
    "clearance",
}
