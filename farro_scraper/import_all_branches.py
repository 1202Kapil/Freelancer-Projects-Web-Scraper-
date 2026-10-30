"""All-branch batch importer orchestrator for Farro Fresh Supermarket.

Finds the latest JSONL export for every branch in exports/ and imports
observations into the Pico catalog database using import_products.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Optional

from catalog_branches import KNOWN_FARRO_STORES
from config import EXPORTS_DIR, RETAILER_SLUG
from notify import push as push_notify
from run_log import RunLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("import_all_branches")


def find_latest_branch_exports(exports_dir: Path) -> dict[str, Path]:
    """Find the newest JSONL export file for each distinct Farro branch slug."""
    branch_files: dict[str, tuple[Path, str]] = {}
    pattern = re.compile(rf"^{RETAILER_SLUG}_(.+)_(\d{{8}}T\d{{6}}Z)\.jsonl$")

    for p in exports_dir.glob(f"{RETAILER_SLUG}_*.jsonl"):
        m = pattern.match(p.name)
        if m:
            slug = m.group(1)
            ts = m.group(2)
            if slug not in branch_files or ts > branch_files[slug][1]:
                branch_files[slug] = (p, ts)

    return {slug: path_ts[0] for slug, path_ts in branch_files.items()}


def import_branch(
    export_path: Path,
    branch_slug: str,
    dry_run: bool = False,
    rollback_test: bool = False,
    full_branch: bool = True,
) -> dict:
    """Invoke import_products.py as a subprocess for one branch file."""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "import_products.py"),
        "--input", str(export_path),
        "--retailer", RETAILER_SLUG,
        "--external-store-id", branch_slug,
        "--source-system", "farro_scraper",
    ]

    if dry_run:
        cmd.append("--dry-run")
    elif rollback_test:
        cmd.append("--rollback-test")
    elif full_branch:
        cmd.append("--full-branch")

    logger.info("Executing import for %s: %s", branch_slug, " ".join(cmd))
    t0 = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.monotonic() - t0

    success = result.returncode == 0
    if not success:
        logger.error("Import failed for %s (exit code %d):\n%s", branch_slug, result.returncode, result.stderr)
    else:
        logger.info("Import succeeded for %s in %.1fs", branch_slug, duration)

    return {
        "branch_slug": branch_slug,
        "export_path": str(export_path),
        "success": success,
        "duration_seconds": round(duration, 2),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_batch_import(
    dry_run: bool = False,
    rollback_test: bool = False,
    full_branch: bool = True,
) -> dict:
    """Run batch import across all latest branch JSONL export files."""
    run_log = RunLogger("import_all_branches", branch_label="all")
    exports = find_latest_branch_exports(EXPORTS_DIR)

    if not exports:
        logger.warning("No Farro JSONL exports found in %s", EXPORTS_DIR)
        run_log.finish("skipped")
        return {"total": 0, "succeeded": 0, "failed": 0}

    logger.info("Discovered %d branch export(s) to import:", len(exports))
    for slug, path in exports.items():
        logger.info("  • %s -> %s", slug, path.name)

    results = []
    for slug, path in exports.items():
        res = import_branch(
            path,
            slug,
            dry_run=dry_run,
            rollback_test=rollback_test,
            full_branch=full_branch,
        )
        results.append(res)

    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded

    run_log.record_stat("branches_attempted", len(results))
    run_log.record_stat("branches_succeeded", succeeded)
    run_log.record_stat("branches_failed", failed)

    status = "success" if failed == 0 else "partial_failure"
    run_log.finish(status)

    push_notify(
        f"Farro batch import complete: {succeeded}/{len(results)} branches succeeded.",
        title="Farro Batch Import",
        priority="default" if failed == 0 else "high",
    )

    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import all Farro Fresh branch exports")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only; no database connection")
    parser.add_argument("--rollback-test", action="store_true", help="Execute full database transactions and rollback")
    parser.add_argument("--full-branch", action="store_true", default=True, help="Mark missing products as out_of_stock")
    args = parser.parse_args()

    summary = run_batch_import(
        dry_run=args.dry_run,
        rollback_test=args.rollback_test,
        full_branch=args.full_branch,
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
