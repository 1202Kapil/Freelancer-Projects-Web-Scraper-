"""Configuration and constants for The Warehouse NZ scraper."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
SCRAPER_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = SCRAPER_DIR / "exports"
LOGS_DIR = SCRAPER_DIR / "logs"
BRANCHES_FILE = SCRAPER_DIR / "branches.json"

# Ensure directories exist
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables
_env_path = SCRAPER_DIR / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Retailer Settings
RETAILER_SLUG = "thewarehouse"
RETAILER_NAME = "The Warehouse"
DEFAULT_BRANCH_SLUG = "thewarehouse-auckland-central"
DEFAULT_BRANCH_ID = "221"
DEFAULT_STORE_NAME = "The Warehouse Auckland Central"
LOYALTY_PROGRAM_CODE = "marketclub"

# URLs
BASE_URL = "https://www.thewarehouse.co.nz"
SEARCH_UPDATE_ENDPOINT = "https://www.thewarehouse.co.nz/search/update"
STORES_API_ENDPOINT = "https://www.thewarehouse.co.nz/on/demandware.store/Sites-twl-Site/default/Stores-FindStores"

# Top-Level Categories
CATEGORIES = [
    "food-pets-household",
    "health-beauty",
    "home-garden-appliances",
    "electronics-gaming",
    "clothing-shoes-accessories",
    "toys-baby",
    "craft-party-stationery",
    "sports-outdoors",
    "auto-diy",
    "specials",
]

# Demandware cgid mappings for verified departments
CATEGORY_CGIDS = {
    "food-pets-household": "foodhouseholdpets",
    "health-beauty": "healthbeauty",
    "home-garden-appliances": "homegarden",
    "electronics-gaming": "electronicsgaming",
    "clothing-shoes-accessories": "clothingshoesaccessories",
    "toys-baby": "toysbaby",
    "craft-party-stationery": "stationerycraftparty",
    "sports-outdoors": "sportsoutdoors",
    "auto-diy": "autodiy",
    "specials": "specials",
}

CATEGORY_DISPLAY_NAMES = {
    "food-pets-household": "Food, Pets & Household",
    "health-beauty": "Health & Beauty",
    "home-garden-appliances": "Home, Garden & Appliances",
    "electronics-gaming": "Electronics & Gaming",
    "clothing-shoes-accessories": "Clothing, Shoes & Accessories",
    "toys-baby": "Toys & Baby",
    "craft-party-stationery": "Craft, Party & Stationery",
    "sports-outdoors": "Sports & Outdoors",
    "auto-diy": "Auto & DIY",
    "specials": "Specials",
}

# Network and Browser Constants
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-NZ,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

PAGE_SIZE = 32
MAX_RETRIES = 4
REQUEST_TIMEOUT_SECONDS = 30.0
DELAY_MIN = 1.0
DELAY_MAX = 2.0
BACKOFF_BASE = 3.0

# Credentials & Database
PROXY_URL = os.getenv("PROXY_URL", "")
CAPSOLVER_PROXY = os.getenv("CAPSOLVER_PROXY", "")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
