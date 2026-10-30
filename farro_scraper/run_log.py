"""Structured per-run JSON logs for Farro Fresh scraper and importer.

One JSON file per run under logs/, plus a rolling runs-index.json
for tracking historical execution metrics.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Optional

from config import LOGS_DIR

logger = logging.getLogger(__name__)
INDEX_NAME = "runs-index.json"
INDEX_CAP = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class RunLogger:
    def __init__(self, command: str, branch_label: Optional[str] = None, retailer: str = "farro"):
        self.retailer = retailer
        self.branch_label = branch_label or "unknown"
        self.command = command
        self.started_at = _now_iso()
        self._t0 = time.monotonic()
        self.run_id = f"{retailer}_{self.branch_label}_{_run_stamp()}"
        self.log_path = LOGS_DIR / f"{self.run_id}.json"

        self.data = {
            "run_id": self.run_id,
            "retailer": self.retailer,
            "branch_label": self.branch_label,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": None,
            "duration_seconds": None,
            "status": "running",
            "stats": {},
            "errors": [],
        }

    def record_stat(self, key: str, value: any) -> None:
        self.data["stats"][key] = value

    def add_error(self, err: str) -> None:
        self.data["errors"].append({"time": _now_iso(), "error": str(err)})

    def finish(self, status: str = "success") -> Path:
        self.data["finished_at"] = _now_iso()
        self.data["duration_seconds"] = round(time.monotonic() - self._t0, 2)
        self.data["status"] = status

        try:
            with self.log_path.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            self._update_index()
        except Exception as e:
            logger.error("Failed to write run log: %s", e)

        return self.log_path

    def _update_index(self) -> None:
        index_path = LOGS_DIR / INDEX_NAME
        entries = []
        if index_path.exists():
            try:
                with index_path.open("r", encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception:
                entries = []

        summary = {
            "run_id": self.run_id,
            "retailer": self.retailer,
            "branch": self.branch_label,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.data["finished_at"],
            "duration_seconds": self.data["duration_seconds"],
            "status": self.data["status"],
            "products_total": self.data["stats"].get("products_scraped", 0),
            "specials_count": self.data["stats"].get("specials_count", 0),
            "errors_count": len(self.data["errors"]),
        }

        entries = [e for e in entries if e.get("run_id") != self.run_id]
        entries.insert(0, summary)
        entries = entries[:INDEX_CAP]

        try:
            with index_path.open("w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception as e:
            logger.error("Failed to update runs-index.json: %s", e)
