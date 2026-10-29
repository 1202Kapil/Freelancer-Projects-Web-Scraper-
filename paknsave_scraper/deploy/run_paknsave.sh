#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# PAK'nSAVE Production Daily Run Pipeline
#
# Steps:
# 1. Activates Python virtualenv
# 2. Runs PAK'nSAVE scraper with --all-branches
# 3. Runs strict PICO Data Contract schema validation on exported JSONL files
# 4. Imports valid observations into PICO Postgres catalog database
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
cd "$APP_DIR"

echo "=== [$(date -u +%FT%TZ)] Starting PAK'nSAVE Scraper Production Run ==="

# 1. Activate Virtual Environment
if [[ -d "$APP_DIR/.venv" ]]; then
    source "$APP_DIR/.venv/bin/activate"
elif [[ -d "/opt/venv" ]]; then
    source "/opt/venv/bin/activate"
fi

# 2. Scrape All Branches
echo ">>> Step 1: Scraping all active PAK'nSAVE branches..."
python paknsave_scraper.py --all-branches

# 3. Validate All Exported JSONL Files
echo ">>> Step 2: Validating all JSONL exports against PICO Data Contract..."
python validate_export.py --all

# 4. Import All Branches into PICO Catalog Database (if DATABASE_URL is configured)
if [[ -n "${DATABASE_URL:-}" ]]; then
    echo ">>> Step 3: Importing observations for all branches into PICO database..."
    python import_all_branches.py
else
    echo ">>> Step 3: DATABASE_URL not set — running dry-run batch validation..."
    python import_all_branches.py --dry-run
fi

echo "=== [$(date -u +%FT%TZ)] PAK'nSAVE Scraper Pipeline Completed Successfully ==="
