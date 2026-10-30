"""Shared JSONL export for The Warehouse according to the PICO Scraper Data Contract.

Contract specification:
- One JSON object per product per line (JSONL).
- Top-level absent / None keys are omitted on write; never invent data.
- Prices in integer cents NZD.
- Timestamps in ISO-8601 UTC format.
- Format: {retailer}_{branch-slug}_{UTC timestamp}.jsonl
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
    """Canonical slug generator matching branch slug standards:
    'The Warehouse Auckland Central' -> 'thewarehouse-auckland-central'.
    """
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
    try:
        val_clean = str(value).replace("$", "").replace(",", "").strip()
        return int(round(float(val_clean) * 100))
    except (TypeError, ValueError):
        return None


def clean_record(rec: dict) -> dict:
    """Drop keys whose value is None or empty at the top level so the file
    uses nulls only where specifically meaningful inside raw_row; top-level
    absent keys are omitted as required by the client contract.
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


def write_jsonl(records: list[dict], branch_label: Optional[str],
                retailer: str = RETAILER_SLUG,
                out_dir: Optional[Path] = None,
                when: Optional[datetime] = None) -> Optional[Path]:
    """Write product records to a single JSONL file atomically. Returns written file Path."""
    if not records:
        logger.warning("[jsonl] No records to export — skipping write")
        return None

    out_dir = out_dir or EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = export_filename(retailer, branch_label, when)
    path = out_dir / filename
    temp_path = path.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        for rec in records:
            clean = clean_record(rec)
            f.write(json.dumps(clean, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")

    # Atomic rename
    temp_path.replace(path)
    logger.info(f"[jsonl] Wrote {len(records)} observations to {path}")
    return path
