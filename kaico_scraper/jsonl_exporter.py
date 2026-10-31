"""Shared JSONL export for Kai Co according to PICO client data contract.

Contract specification:
- One JSON object per product per line (JSONL).
- Null / empty fields are omitted on write at the top level.
- Prices in integer cents NZD.
- Timestamps in ISO-8601 UTC format (YYYY-MM-DDTHH:MM:SSZ).
- Filename format: {retailer}_{branch-slug}_{UTC timestamp}.jsonl
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import EXPORTS_DIR, RETAILER_SLUG

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: Optional[str]) -> str:
    """Canonical slug generator matching branch slug standards:
    'Kai Co Northwood' -> 'kai-co-northwood'.
    """
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    s = _SLUG_RE.sub("-", cleaned).strip("-")
    return s or "unknown"


def export_filename(retailer: str, branch_slug: Optional[str],
                    when: Optional[datetime] = None) -> str:
    """Format: {retailer}_{branch-slug}_{UTC timestamp}.jsonl"""
    when = when or datetime.now(timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{slugify(retailer)}_{slugify(branch_slug)}_{stamp}.jsonl"


def clean_record(rec: dict) -> dict:
    """Drop keys whose value is None or empty string at the top level.
    Preserves raw_row dictionary structure.
    """
    out = {}
    for k, v in rec.items():
        if v is None:
            continue
        if v == "" and k != "raw_row":
            continue
        if isinstance(v, dict):
            # If a nested object is empty (e.g. {}), drop it unless it's raw_row
            cleaned_sub = {sk: sv for sk, sv in v.items() if sv is not None and sv != ""}
            if cleaned_sub or k == "raw_row":
                out[k] = v
        else:
            out[k] = v
    return out


def write_jsonl(
    records: list[dict],
    branch_slug: Optional[str] = "northwood",
    retailer: str = RETAILER_SLUG,
    out_dir: Optional[Path] = None,
    when: Optional[datetime] = None,
) -> Optional[Path]:
    """Write product records to a single JSONL file atomically."""
    if not records:
        logger.warning("[jsonl] No records to export — skipping write")
        return None

    out_dir = out_dir or EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = export_filename(retailer, branch_slug, when)
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
