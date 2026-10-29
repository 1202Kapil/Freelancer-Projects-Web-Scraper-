"""All-branch batch importer orchestrator for PAK'nSAVE.

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

from notify import push as push_notify
from run_log import write_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("import_all_branches")

EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


STORE_ID_MAP = {
    "paknsave-sylvia-park": "3c5e3145-0767-4066-9349-6c0a1313acc5",
    "paknsave-albany": "078b548b-37d4-4a25-a50d-617bbd22deec",
    "paknsave-botany": "67b8eb51-1cb5-45d6-847e-40ec048d0891",
    "paknsave-henderson": "60a4f5fa-14e3-466a-b286-9dcab46eecad",
    "paknsave-moorhouse": "3e9b1d97-15ef-4d43-bb74-2794eb84e55e",
}


def find_latest_branch_exports(exports_dir: Path) -> dict[str, Path]:
    """Find the newest JSONL export file for each distinct branch slug."""
    branch_files: dict[str, tuple[Path, str]] = {}
    pattern = re.compile(r"^paknsave_(.+)_(\d{8}T\d{6}Z)\.jsonl$")

    for p in exports_dir.glob("paknsave_*.jsonl"):
        m = pattern.match(p.name)
        if m:
            slug = m.group(1)
            ts = m.group(2)
            if slug not in branch_files or ts > branch_files[slug][1]:
                branch_files[slug] = (p, ts)
        elif "revalidated" in p.name:
            slug = "paknsave-sylvia-park"
            if slug not in branch_files:
                branch_files[slug] = (p, "99999999T999999Z")

    return {slug: path_ts[0] for slug, path_ts in branch_files.items()}


def import_branch(export_path: Path, branch_slug: str, dry_run: bool = False, full_branch: bool = True) -> dict:
    """Invoke import_products.py as a subprocess for one branch file with branch selector."""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "import_products.py"),
        "--input", str(export_path),
        "--retailer", "paknsave",
        "--source-system", "paknsave_scraper",
        "--branch-slug", branch_slug,
    ]
    ext_id = STORE_ID_MAP.get(branch_slug)
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

    # Parse key stats from output (logging writes to stderr)
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

    return {
        "file": export_path.name,
        "success": success,
        "duration_seconds": round(duration, 1),
        "total_read": total_read,
        "valid_count": valid_count,
        "barcodes": barcodes,
        "specials": specials,
        "output": output_text[-800:] if not success else output_text[-300:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch import all branch JSONL exports into PICO database")
    parser.add_argument("--dry-run", action="store_true", help="Validate and prepare batch import without writing to DB")
    parser.add_argument("--no-full-branch", action="store_true", help="Do not mark missing products as out-of-stock")
    parser.add_argument("--dir", default=str(EXPORTS_DIR), help="Exports directory path")
    args = parser.parse_args()

    exports_dir = Path(args.dir)
    latest_exports = find_latest_branch_exports(exports_dir)

    if not latest_exports:
        logger.warning(f"No branch exports found in {exports_dir}")
        return 0

    # Detect DATABASE_URL; if not configured and not in dry-run, fallback to dry-run validation
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        _env = Path(__file__).resolve().parent / ".env"
        if _env.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(_env)
                dsn = os.environ.get("DATABASE_URL")
            except Exception:
                pass

    if not dsn and not args.dry_run:
        print("[!] NOTICE: DATABASE_URL is not configured.")
        print("    Running pipeline in DRY-RUN validation mode (audits all branches, 0 DB writes).")
        print("    (To commit to live Postgres catalog, configure DATABASE_URL in .env)")
        print("-" * 78)
        args.dry_run = True

    print("=" * 78)
    print(f"PICO PAK'nSAVE ALL-BRANCH IMPORT PIPELINE {'(DRY-RUN)' if args.dry_run else '(LIVE COMMIT)'}")
    print("=" * 78)
    print(f"Found {len(latest_exports)} active branch export files to import:")
    for slug, path in latest_exports.items():
        print(f"  - {slug:<28} -> {path.name}")
    print("-" * 78)

    t_start = time.time()
    results = []
    total_products = 0
    total_barcodes = 0
    total_promos = 0
    failed_branches = 0

    for slug, path in sorted(latest_exports.items()):
        res = import_branch(path, branch_slug=slug, dry_run=args.dry_run, full_branch=not args.no_full_branch)
        results.append(res)
        if res["success"]:
            total_products += res["valid_count"]
            total_barcodes += res["barcodes"]
            total_promos += res["specials"]
            logger.info(f"  [OK] {slug}: {res['valid_count']:,} products, {res['barcodes']:,} barcodes, {res['specials']:,} promos ({res['duration_seconds']}s)")
        else:
            failed_branches += 1
            logger.error(f"  [FAIL] {slug} failed: {res['output']}")

    total_time = round(time.time() - t_start, 1)

    print("=" * 78)
    print("ALL-BRANCH IMPORT SUMMARY")
    print("=" * 78)
    print(f"Branches Processed   : {len(results)}")
    print(f"Branches Succeeded   : {len(results) - failed_branches}")
    print(f"Branches Failed      : {failed_branches}")
    print(f"Total Valid Products : {total_products:,}")
    print(f"Total GTIN Barcodes  : {total_barcodes:,}")
    print(f"Total Promotions     : {total_promos:,}")
    print(f"Pipeline Duration    : {total_time}s")
    print("=" * 78)

    # Push Notification
    status_str = "SUCCESS" if failed_branches == 0 else "PARTIAL_FAIL"
    msg = (f"PAK'nSAVE Import: {len(results) - failed_branches}/{len(results)} branches OK. "
           f"{total_products:,} products, {total_promos:,} promos ({total_time}s)")
    push_notify(msg, title=f"PAK'nSAVE Import {status_str}", priority="default" if failed_branches == 0 else "high")

    return 0 if failed_branches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
