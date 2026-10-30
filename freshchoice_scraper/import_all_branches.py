"""All-branch batch importer orchestrator for FreshChoice Supermarkets.

Finds the latest JSONL export for every FreshChoice branch in exports/ and imports
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

from catalog_branches import KNOWN_FRESHCHOICE_STORES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("import_all_branches")

EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


def find_latest_branch_exports(exports_dir: Path) -> dict[str, Path]:
    """Find the newest JSONL export file for each distinct branch slug."""
    branch_files: dict[str, tuple[Path, str]] = {}
    pattern = re.compile(r"^freshchoice_(.+)_(\d{8}T\d{6}Z)\.jsonl$")

    for p in exports_dir.glob("freshchoice_*.jsonl"):
        m = pattern.match(p.name)
        if m:
            slug = m.group(1)
            ts = m.group(2)
            if slug not in branch_files or ts > branch_files[slug][1]:
                branch_files[slug] = (p, ts)

    return {slug: path_ts[0] for slug, path_ts in branch_files.items()}


def import_branch(export_path: Path, branch_slug: str, dry_run: bool = False, full_branch: bool = True) -> dict:
    """Invoke import_products.py as a subprocess for one branch file."""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "import_products.py"),
        "--input", str(export_path),
        "--retailer", "freshchoice",
        "--source-system", "freshchoice_scraper",
        "--branch-slug", branch_slug,
    ]

    if dry_run:
        cmd.append("--dry-run")
    if full_branch:
        cmd.append("--full-branch")

    logger.info(f"Importing {export_path.name} {'(DRY-RUN)' if dry_run else ''}...")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    duration = time.time() - t0

    success = (res.returncode == 0)
    if success:
        logger.info(f"✅ [{branch_slug}] Import succeeded in {duration:.1f}s")
    else:
        logger.error(f"❌ [{branch_slug}] Import failed with code {res.returncode}")
        if res.stderr:
            logger.error(res.stderr[:500])

    return {
        "branch_slug": branch_slug,
        "export_file": export_path.name,
        "success": success,
        "duration": duration,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }


def main():
    parser = argparse.ArgumentParser(description="FreshChoice All-Branch Batch Importer")
    parser.add_argument("--dry-run", action="store_true", help="Parse-only validation, no database writes")
    parser.add_argument("--no-full-branch", action="store_true", help="Do not deactivate unseen products")
    parser.add_argument("--branch", type=str, help="Import a single branch by slug")
    args = parser.parse_args()

    exports = find_latest_branch_exports(EXPORTS_DIR)
    if not exports:
        logger.warning(f"No freshchoice_*.jsonl export files found in {EXPORTS_DIR}")
        return

    if args.branch:
        if args.branch not in exports:
            logger.error(f"No export found for branch '{args.branch}'")
            return
        targets = {args.branch: exports[args.branch]}
    else:
        targets = exports

    logger.info(f"Found {len(targets)} branch export(s) to import:")
    for slug, p in targets.items():
        logger.info(f"  • {slug}: {p.name}")

    results = []
    for slug, p in targets.items():
        res = import_branch(
            export_path=p,
            branch_slug=slug,
            dry_run=args.dry_run,
            full_branch=not args.no_full_branch,
        )
        results.append(res)

    succeeded = sum(1 for r in results if r["success"])
    logger.info(f"All imports finished: {succeeded}/{len(results)} succeeded.")


if __name__ == "__main__":
    main()
