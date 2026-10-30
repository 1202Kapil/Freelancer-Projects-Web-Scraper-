"""JSONL exporter for Farro Fresh Supermarket complying with the Pico contract.

Contract specification:
- One JSON object per product per line (JSONL).
- Top-level keys with null or empty values are omitted on write.
- All prices must be integer cents NZD (not dollar floats).
- Timestamps must be ISO-8601 UTC format (YYYY-MM-DDTHH:MM:SSZ).
- Filename format: {retailer}_{branch-slug}_{UTC timestamp}.jsonl.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional

from config import EXPORTS_DIR, RETAILER_SLUG

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: Optional[str]) -> str:
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    s = _SLUG_RE.sub("-", cleaned).strip("-")
    return s or "unknown"


def export_filename(retailer: str, branch_label: Optional[str],
                    when: Optional[datetime] = None) -> str:
    """Format: {retailer}_{branch-slug}_{UTC timestamp}.jsonl"""
    when = when or datetime.now(timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{_slug(retailer)}_{_slug(branch_label)}_{stamp}.jsonl"


def to_cents(value: Any) -> Optional[int]:
    """Convert dollars (float/int/str) to integer cents. Safe with None/empty."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        val_clean = str(value).replace("$", "").replace(",", "").strip()
        return int(round(float(val_clean) * 100))
    except (TypeError, ValueError):
        return None


def clean_record(rec: dict) -> dict:
    """Drop keys whose value is None or empty at the top level.
    Preserves meaningful nulls inside nested dicts like raw_row.
    """
    out = {}
    for k, v in rec.items():
        if v is None:
            continue
        if v == "" and k != "raw_row":
            continue
        if isinstance(v, dict):
            cleaned_sub = {sk: sv for sk, sv in v.items() if sv is not None and sv != ""}
            if cleaned_sub or k == "raw_row":
                out[k] = v
        else:
            out[k] = v
    return out


def write_jsonl(records: list[dict],
                branch_label: Optional[str],
                retailer: str = RETAILER_SLUG,
                out_dir: Optional[Path] = None,
                when: Optional[datetime] = None) -> Optional[Path]:
    """Write product records to a single JSONL file. Returns written file Path."""
    if not records:
        logger.warning("No records to write for branch '%s'", branch_label)
        return None

    out_dir = out_dir or EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    fname = export_filename(retailer, branch_label, when)
    path = out_dir / fname

    written = 0
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            cleaned = clean_record(r)
            if cleaned:
                f.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
                written += 1

    logger.info("Exported %d products to %s", written, path)
    return path
