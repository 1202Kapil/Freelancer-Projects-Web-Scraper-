"""All-branch batch importer orchestrator for SuperValue Supermarkets.

Finds the latest JSONL export for every SuperValue branch in exports/ and imports
observations into the PICO catalog database using import_products.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("import_all_branches")

EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


def find_latest_branch_exports(exports_dir: Path) -> dict[str, Path]:
    """Find the newest JSONL export file for each distinct branch slug."""
    branch_files: dict[str, tuple[Path, str]] = {}
    pattern = re.compile(r"^supervalue_(.+)_(\d{8}T\d{6}Z)\.jsonl$")

    for p in exports_dir.glob("supervalue_*.jsonl"):
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
        "--retailer", "supervalue",
        "--source-system", "supervalue_scraper",
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
    parser = argparse.ArgumentParser(description="SuperValue All-Branch Batch Importer")
    parser.add_argument("--dry-run", action="store_true", help="Parse-only validation, no database writes")
    parser.add_argument("--no-full-branch", action="store_true", help="Do not deactivate unseen products")
    parser.add_argument("--branch", type=str, help="Import a single branch by slug (e.g. milton)")
    args = parser.parse_args()

    exports = find_latest_branch_exports(EXPORTS_DIR)
    if not exports:
        logger.warning(f"No supervalue_*.jsonl export files found in {EXPORTS_DIR}")
        return

    if args.branch:
        if args.branch not in exports:
            logger.error(f"No export found for branch '{args.branch}'")
            return
        targets = {args.branch: exports[args.branch]}
    else:
        targets = exports

    logger.info(f"Starting batch import of {len(targets)} SuperValue branch export(s)...")
    summary = []
    for slug, path in sorted(targets.items()):
        res = import_branch(path, slug, dry_run=args.dry_run, full_branch=not args.no_full_branch)
        summary.append(res)

    succeeded = sum(1 for r in summary if r["success"])
    logger.info(f"Batch import completed: {succeeded}/{len(summary)} branch files processed successfully.")


if __name__ == "__main__":
    main()
