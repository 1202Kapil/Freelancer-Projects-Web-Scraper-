"""Structured per-run JSON logs for Kai Co scrapers and importer.

One JSON file per run under <repo>/logs/, plus a rolling runs-index.json
that a frontend / monitor can list from (newest first).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Direct logs directory in the scraper folder
LOGS_DIR = Path(__file__).resolve().parent / "logs"
INDEX_NAME = "runs-index.json"
INDEX_CAP = 500  # keep only the newest N runs in the index


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_index(logs_dir: Path, entry: dict) -> None:
    """Upsert ONE summary entry per run into runs-index.json, newest first."""
    idx_path = logs_dir / INDEX_NAME
    data = []
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []

    # Replace existing or prepend
    new_data = [e for e in data if e.get("run_id") != entry.get("run_id")]
    new_data.insert(0, entry)
    if len(new_data) > INDEX_CAP:
        new_data = new_data[:INDEX_CAP]

    tmp = idx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_data, indent=2), encoding="utf-8")
    tmp.replace(idx_path)


class RunLogger:
    """Context-manager or manual start/finish logger writing a run JSON + updating the index."""

    def __init__(self, scraper_name: str, branch_label: Optional[str] = None):
        self.scraper_name = scraper_name
        self.branch_label = branch_label or "all"
        self.started_at = datetime.now(timezone.utc)
        self.stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{scraper_name}_{self.branch_label}_{self.stamp}"
        self.t0 = time.monotonic()
        self.products_collected = 0
        self.categories_scraped = 0
        self.status = "running"
        self.errors = []
        self.export_path: Optional[str] = None

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.log_file = LOGS_DIR / f"{self.run_id}.json"

    def record_progress(self, products: int = 0, categories: int = 0):
        self.products_collected += products
        self.categories_scraped += categories

    def add_error(self, err: str):
        self.errors.append(err)

    def finish(self, status: str = "success", export_path: Optional[str] = None):
        self.status = status
        self.export_path = export_path
        duration = round(time.monotonic() - self.t0, 2)
        ended_at = datetime.now(timezone.utc)

        data = {
            "run_id": self.run_id,
            "scraper": self.scraper_name,
            "branch_label": self.branch_label,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": duration,
            "products_collected": self.products_collected,
            "categories_scraped": self.categories_scraped,
            "export_file": Path(export_path).name if export_path else None,
            "errors_count": len(self.errors),
            "errors": self.errors[:10],
        }

        # Write run file
        self.log_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Update index
        _write_index(LOGS_DIR, data)
        return data
