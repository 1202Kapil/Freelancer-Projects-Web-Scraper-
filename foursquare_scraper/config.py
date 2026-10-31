"""Configuration and constants for Four Square NZ scraper."""
from __future__ import annotations

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
SCRAPER_DIR = Path(__file__).resolve().parent
load_dotenv(SCRAPER_DIR / ".env")

EXPORTS_DIR = SCRAPER_DIR / "exports"
BRANCHES_PATH = SCRAPER_DIR / "branches.json"
CACHE_PATH = SCRAPER_DIR / ".foodstuffs_cache.json"

# Proxy and CapSolver Settings
PROXY_URL = os.getenv("PROXY_URL", "")
CAPSOLVER_PROXY = os.getenv("CAPSOLVER_PROXY", "")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")

# Four Square Endpoints
BASE_URL = "https://www.foursquare.co.nz"
SPECIALS_URL = f"{BASE_URL}/local-specials-and-promotions"
STORE_FINDER_URL = f"{BASE_URL}/store-finder"
DETAIL_API_TEMPLATE = "https://api-prod.paknsave.co.nz/v1/edge/store/{store_id}/product/{pid}"

# Default Store (Four Square Ascot)
DEFAULT_STORE_NAME = "Four Square Ascot"
DEFAULT_STORE_ID = "2a8a3352-e5d0-4483-bdae-4fc75a76e38c"
DEFAULT_STORE_GUID = "{2A8A3352-E5D0-4483-BDAE-4FC75A76E38C}"

# Network and Browser Constants
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-NZ,en-GB;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

ASSET_BLOCK_RE = re.compile(
    r"\.(woff2?|ttf|otf|mp4|mp3|css)(\?|$)|"
    r"(google-analytics|googletagmanager|doubleclick|facebook|hotjar)",
    re.I,
)

CF_BLOCK_TITLES = (
    "access denied", "just a moment", "security check",
    "attention required", "error 403", "403 forbidden"
)

# Concurrency & Delays
REQUEST_TIMEOUT_MS = 30_000
HTTP_TIMEOUT = 30.0
DELAY_MIN = 0.5
DELAY_MAX = 1.5
DEFAULT_RATE_LIMIT = 5.0  # requests per second
