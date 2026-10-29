"""Configuration and constants for PAK'nSAVE scraper."""
from __future__ import annotations

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
SCRAPER_DIR = Path(__file__).resolve().parent
load_dotenv(SCRAPER_DIR / ".env")

EXPORTS_DIR = SCRAPER_DIR / "exports"
CACHE_PATH = SCRAPER_DIR / ".paknsave_cache.json"
TEMPLATE_PATH = SCRAPER_DIR / ".paknsave_direct_template.json"

# Proxy and CapSolver Settings
PROXY_URL = os.getenv("PROXY_URL", "")
CAPSOLVER_PROXY = os.getenv("CAPSOLVER_PROXY", "")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")

# PAK'nSAVE Endpoints
BASE_URL = "https://www.paknsave.co.nz"
DETAIL_API_TEMPLATE = "https://api-prod.paknsave.co.nz/v1/edge/store/{store_id}/product/{pid}"

# Default Branch Details (PAK'nSAVE Sylvia Park)
DEFAULT_STORE_NAME = "PAK'nSAVE Sylvia Park"
# PAK'nSAVE storefront storeId for Sylvia Park
DEFAULT_STORE_ID = "3c5e3145-0767-4066-9349-6c0a1313acc5"

# Full verified categories list on paknsave.co.nz
CATEGORIES = [
    "fruit-and-vegetables",
    "meat-poultry-and-seafood",
    "fridge-deli-and-eggs",
    "bakery",
    "frozen",
    "pantry",
    "hot-and-cold-drinks",
    "snacks-treats-and-easy-meals",
    "health-and-body",
    "household-and-cleaning",
    "baby-and-toddler",
    "pets",
    "beer-wine-and-cider",
]

# URL slug to category display name for Algolia queries
SLUG_TO_DISPLAY_NAME = {
    "fruit-and-vegetables": "Fruit & Vegetables",
    "meat-poultry-and-seafood": "Meat, Poultry & Seafood",
    "fridge-deli-and-eggs": "Fridge, Deli & Eggs",
    "bakery": "Bakery",
    "frozen": "Frozen",
    "pantry": "Pantry",
    "hot-and-cold-drinks": "Hot & Cold Drinks",
    "snacks-treats-and-easy-meals": "Snacks, Treats & Easy Meals",
    "health-and-body": "Health & Body",
    "household-and-cleaning": "Household & Cleaning",
    "baby-and-toddler": "Baby & Toddler",
    "pets": "Pets",
    "beer-wine-and-cider": "Beer, Wine & Cider",
}

# Network and Browser Constants
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept-Language": "en-NZ,en-GB;q=0.9,en;q=0.8",
}

ASSET_BLOCK_RE = re.compile(
    r"\.(png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf|otf|mp4|mp3|css)(\?|$)|"
    r"(google-analytics|googletagmanager|doubleclick|facebook|hotjar)",
    re.I,
)

CF_BLOCK_TITLES = (
    "access denied", "just a moment", "security check",
    "attention required", "error 403", "403 forbidden"
)

# Concurrency & Delays
REQUEST_TIMEOUT_MS = 30_000
DELAY_MIN = 1.0
DELAY_MAX = 2.5
DEFAULT_RATE_LIMIT = 15.0  # requests per second

ENRICH_CONCURRENCY_INITIAL = 12
ENRICH_CONCURRENCY_MIN = 1
ENRICH_429_THRESHOLD = 3
ALGOLIA_PAGE_CAP = 20
