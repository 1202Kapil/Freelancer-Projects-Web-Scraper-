"""All-branch batch importer orchestrator for Four Square.

Finds the latest JSONL export for every branch in exports/ and imports
observations into the PICO catalog database using import_products.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Optional

from catalog_branches import list_branches, get_branch
from config import EXPORTS_DIR
from notify import push as push_notify
from run_log import write_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("import_all_branches")


def find_latest_branch_exports(exports_dir: Path) -> dict[str, Path]:
    """Find the newest JSONL export file for each distinct branch slug."""
    branch_files: dict[str, tuple[Path, str]] = {}
    pattern = re.compile(r"^foursquare_(.+)_(\d{8}T\d{6}Z)\.jsonl$")

    for p in exports_dir.glob("foursquare_*.jsonl"):
        m = pattern.match(p.name)
        if m:
            slug = m.group(1)
            ts = m.group(2)
            if slug not in branch_files or ts > branch_files[slug][1]:
                branch_files[slug] = (p, ts)

    return {slug: path_ts[0] for slug, path_ts in branch_files.items()}


def import_branch(export_path: Path, branch_slug: str, dry_run: bool = False, full_branch: bool = True) -> dict:
    """Invoke import_products.py as a subprocess for one branch file with branch selector."""
    branch = get_branch("foursquare", slug=branch_slug)
    ext_id = branch.get("api_store_id") if branch else None

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "import_products.py"),
        "--input", str(export_path),
        "--retailer", "foursquare",
        "--source-system", "foursquare_scraper",
        "--branch-slug", branch_slug,
    ]
    if ext_id:
        cmd.extend(["--external-store-id", ext_id])

    if dry_run:
        cmd.append("--dry-run")
    if full_branch:
        cmd.append("--full-branch")

    logger.info(f"Importing {export_path.name} {'(DRY-RUN)' if dry_run else ''}...")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    duration = time.time() - t0

    success = (res.returncode == 0)
    output_text = (res.stdout or "") + "\n" + (res.stderr or "")

    # Parse key stats from output
    total_read = 0
    valid_count = 0
    barcodes = 0
    specials = 0

    m_read = re.search(r"rows read\s*:\s*([\d,]+)", output_text, re.IGNORECASE)
    if m_read:
        total_read = int(m_read.group(1).replace(",", ""))
    m_valid = re.search(r"\bvalid\s*:\s*([\d,]+)", output_text, re.IGNORECASE)
    if m_valid:
        valid_count = int(m_valid.group(1).replace(",", ""))
    m_bc = re.search(r"with barcode\s*:\s*([\d,]+)", output_text, re.IGNORECASE)
    if m_bc:
        barcodes = int(m_bc.group(1).replace(",", ""))
    m_sp = re.search(r"on special\s*:\s*([\d,]+)", output_text, re.IGNORECASE)
    if m_sp:
        specials = int(m_sp.group(1).replace(",", ""))

    # Print dry-run or real import output summary
    for line in output_text.splitlines():
        if any(kw in line for kw in ["=== DRY RUN", "rows read", "valid", "unique products", "with barcode", "failure rate"]):
            logger.info(f"  {line.strip()}")

    return {
        "branch_slug": branch_slug,
        "export_file": export_path.name,
        "success": success,
        "duration_sec": round(duration, 2),
        "total_rows": total_read,
        "valid_rows": valid_count,
        "barcodes": barcodes,
        "specials": specials,
        "error": None if success else output_text[-500:],
    }


def main():
    parser = argparse.ArgumentParser(description="Four Square All-Branch Importer Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run parse validation mode without DB writes")
    parser.add_argument("--exports-dir", default=str(EXPORTS_DIR), help="Directory containing JSONL exports")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of branch exports to import")
    args = parser.parse_args()

    exports_dir = Path(args.exports_dir)
    latest_exports = find_latest_branch_exports(exports_dir)

    if not latest_exports:
        logger.warning(f"No Four Square JSONL exports found in {exports_dir}")
        sys.exit(0)

    slugs = sorted(list(latest_exports.keys()))
    if args.limit:
        slugs = slugs[:args.limit]

    logger.info(f"Discovered {len(slugs)} Four Square branch exports to process:")
    for s in slugs:
        logger.info(f"  - {s:<30} -> {latest_exports[s].name}")

    results = []
    has_db = bool(os.getenv("DATABASE_URL"))
    effective_dry_run = args.dry_run or not has_db

    if not has_db and not args.dry_run:
        logger.info("DATABASE_URL not configured — running batch import in --dry-run mode")

    for i, slug in enumerate(slugs, 1):
        path = latest_exports[slug]
        logger.info(f"\n[{i}/{len(slugs)}] Processing {slug}...")
        res = import_branch(path, slug, dry_run=effective_dry_run, full_branch=True)
        results.append(res)

    success_count = sum(1 for r in results if r["success"])
    total_valid = sum(r["valid_rows"] for r in results)
    total_barcodes = sum(r["barcodes"] for r in results)

    logger.info("\n" + "=" * 70)
    logger.info(f"ALL-BRANCH IMPORT SUMMARY ({'DRY-RUN' if effective_dry_run else 'COMMITTED'}):")
    logger.info(f"  Branches Processed : {len(results)} ({success_count} succeeded, {len(results) - success_count} failed)")
    logger.info(f"  Total Valid Rows   : {total_valid}")
    logger.info(f"  Total Barcodes     : {total_barcodes}")
    logger.info("=" * 70)

    if success_count < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
