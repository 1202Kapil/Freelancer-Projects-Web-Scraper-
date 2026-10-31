"""Configuration and constants for Kai Co NZ scraper."""
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
BRANCHES_PATH = SCRAPER_DIR / "branches.json"
CACHE_PATH = SCRAPER_DIR / ".kaico_cache.json"

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Retailer Identity
RETAILER_NAME = "Kai Co"
RETAILER_SLUG = "kaico"
SOURCE_SYSTEM = "kaico_scraper"

# Store & Branch Defaults
DEFAULT_STORE_NAME = "Kai Co Northwood"
DEFAULT_STORE_SLUG = "northwood"
DEFAULT_STORE_ID = "kaico-northwood"

# Endpoints
BASE_URL = "https://kaico.co.nz"
PRODUCTS_ENDPOINT = f"{BASE_URL}/products.json"
COLLECTIONS_ENDPOINT = f"{BASE_URL}/collections.json"
PAGES_ENDPOINT = f"{BASE_URL}/pages.json"

# Proxy and CapSolver Settings
PROXY_URL = os.getenv("PROXY_URL", "")
CAPSOLVER_PROXY = os.getenv("CAPSOLVER_PROXY", "")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")

# Database and Notification Settings
DATABASE_URL = os.getenv("DATABASE_URL", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

# Network Constants
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-NZ,en-GB;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Network and Performance Limits
HTTP_TIMEOUT = 30.0
REQUEST_TIMEOUT_MS = 30_000
DELAY_MIN = 0.3
DELAY_MAX = 0.8
DEFAULT_RATE_LIMIT = 5.0
