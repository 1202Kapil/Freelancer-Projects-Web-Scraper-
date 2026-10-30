"""Configuration and constants for SuperValue NZ Supermarket Scraper."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
SCRAPER_DIR = Path(__file__).resolve().parent
load_dotenv(SCRAPER_DIR / ".env")

EXPORTS_DIR = SCRAPER_DIR / "exports"
LOGS_DIR = SCRAPER_DIR / "logs"
CACHE_PATH = SCRAPER_DIR / ".supervalue_cache.json"

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Retailer & Endpoints
RETAILER = "supervalue"
BASE_URL = "https://www.supervalue.co.nz"
STORE_URL_TEMPLATE = "https://{branch}.store.supervalue.co.nz"
CATEGORY_PATH_TEMPLATE = "/category/{category_slug}?page={page}"
PRODUCT_DETAIL_PATH_TEMPLATE = "/lines/{slug}"
SITEMAP_PATH = "/sitemap.xml"

# Default benchmark branches
DEFAULT_BRANCHES = ["milton"]

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

# Alternate category slugs for resilient route matching
CATEGORY_ALIASES = {
    "deli": ["deli-kitchen", "delicatessen", "deli", "chilled-deli"],
    "fruit-vegetables": ["fruit-vegetables", "fruit-and-vegetables", "produce", "fruit", "vegetables"],
    "dairy-eggs": ["dairy-eggs", "dairy-and-eggs", "dairy", "milk", "eggs"],
    "beer-wine-cider": ["beer-wine-cider", "beer-wine-and-cider", "liquor", "beer", "wine"],
    "meat": ["meat-poultry", "meat", "butchery"],
}

# Groceries subcategories for comprehensive recovery (bypasses 50-page ceiling if needed)
GROCERIES_SUBCATEGORIES = [
    "canned-dried-vegetables",
    "pasta-rice",
    "cooking-needs",
    "baking",
    "breakfast-cereals",
    "spreads",
    "canned-fruit",
    "canned-fish-meat",
    "soup",
    "world-foods",
    "sauces-dressings",
    "oils-vinegars",
    "condiments",
]

# Contract validation rules
VALID_GTIN_LENGTHS = (8, 12, 13, 14)
VALID_STOCK_STATUSES = ("in_stock", "out_of_stock")
VALID_PROMO_TYPES = (
    "special",
    "multibuy_fixed_price",
    "clearance",
    "member_price",
    "everyday_low_price",
)

# Network and Rate-Limiting Defaults
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-NZ,en;q=0.9",
    "Connection": "keep-alive",
}

REQUEST_TIMEOUT = 25.0
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 15.0
CONCURRENCY = 4
REQUEST_DELAY_SEC = 0.5  # Polite delay between sequential page crawls

# CapSolver Cloudflare Turnstile Configuration
CAPSOLVER_API_KEY = os.environ.get("CAPSOLVER_API_KEY", "")
CAPSOLVER_PROXY = os.environ.get("CAPSOLVER_PROXY", "")
PROXY_URL = os.environ.get("SUPERVALUE_PROXY") or os.environ.get("PROXY_URL", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
