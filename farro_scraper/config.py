"""Configuration for the Farro Fresh Supermarket scraper."""
from __future__ import annotations

import os
from pathlib import Path

# Paths
REPO_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = REPO_DIR / "exports"
LOGS_DIR = REPO_DIR / "logs"

# Ensure directories exist
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env if present
_env_path = REPO_DIR / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

# Retailer Settings
RETAILER_SLUG = "farro"
RETAILER_NAME = "Farro Fresh"
LOYALTY_PROGRAM_CODE = "friends-of-farro"

# API Endpoints
BASE_URL = "https://www.farro.co.nz"
SEARCH_API_ENDPOINT = "https://www.farro.co.nz/api/ViewModel/Search/Search"
BOOTSTRAP_ENDPOINT = "https://www.farro.co.nz/api/ViewModel/Bootstrap/"
LAYOUT_EVALUATE_ENDPOINT = "https://www.farro.co.nz/api/TraderLayout/BatchEvaluate"
SCOPED_CONFIGS_ENDPOINT = "https://www.farro.co.nz/api/TraderComponent/ScopedConfigs"

# Scraper Parameters
PAGE_SIZE = 24  # Server-enforced max page size
BATCH_SIZE = 24
MAX_RETRIES = 5
REQUEST_TIMEOUT = 30.0
DELAY_BETWEEN_REQUESTS = 0.35  # Politeness delay in seconds

# Headers
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.farro.co.nz",
    "Referer": "https://www.farro.co.nz/shop",
}

# Proxy & Capsolver Settings
CAPSOLVER_PROXY = os.getenv("CAPSOLVER_PROXY")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
