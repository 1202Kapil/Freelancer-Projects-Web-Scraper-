"""Package The Warehouse scraper into a clean, distributable submission zip bundle."""
from __future__ import annotations

import os
from pathlib import Path
import zipfile

SCRAPER_DIR = Path(__file__).resolve().parent
DIST_DIR = SCRAPER_DIR / "dist"
DIST_DIR.mkdir(parents=True, exist_ok=True)

ARCHIVE_NAME = "thewarehouse_scraper_production.zip"
OUTPUT_ZIP = DIST_DIR / ARCHIVE_NAME

INCLUDE_FILES = [
    "thewarehouse_scraper.py",
    "catalog_branches.py",
    "config.py",
    "normalize.py",
    "jsonl_exporter.py",
    "validate_export.py",
    "import_all_branches.py",
    "import_products.py",
    "notify.py",
    "run_log.py",
    "branches.json",
    "requirements.txt",
    "README.md",
    ".env.example",
]

INCLUDE_DIRS = [
    "exports",
    "logs",
]

EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.tmp",
    ".git",
    ".pytest_cache",
    ".DS_Store",
]


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        for pat in EXCLUDE_PATTERNS:
            if Path(part).match(pat):
                return True
    return False


def main() -> None:
    print(f"Creating submission package at {OUTPUT_ZIP}...")

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fname in INCLUDE_FILES:
            fpath = SCRAPER_DIR / fname
            if fpath.exists():
                print(f"  Adding file: {fname}")
                zf.write(fpath, arcname=f"thewarehouse_scraper/{fname}")
            else:
                print(f"  [Skipped missing file: {fname}]")

        # Add directories
        for dname in INCLUDE_DIRS:
            dpath = SCRAPER_DIR / dname
            if dpath.exists():
                for item in dpath.rglob("*"):
                    if item.is_file() and not should_exclude(item):
                        rel = item.relative_to(SCRAPER_DIR)
                        print(f"  Adding: {rel}")
                        zf.write(item, arcname=f"thewarehouse_scraper/{rel}")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"Successfully created {OUTPUT_ZIP.name} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
