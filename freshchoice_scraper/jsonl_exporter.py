"""Shared JSONL export for FreshChoice conforming strictly to the PICO Scraper Data Contract.

Contract specification:
- One JSON object per product per line (JSONL).
- Top-level null or empty fields are omitted on export (except meaningful raw_row payloads).
- All prices serialized as integer cents NZD (never floats).
- Timestamps strictly UTC ISO-8601 ('%Y-%m-%dT%H:%M:%SZ').
- One JSONL file per retailer branch per completed run:
  freshchoice_{branch-slug}_{timestamp}.jsonl
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import EXPORTS_DIR

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: Optional[str]) -> str:
    """Canonical slug generator matching branch standards:
    'FreshChoice Green Island' -> 'greenisland' or 'green-island'.
    """
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    s = _SLUG_RE.sub("-", cleaned).strip("-")
    return s or "unknown"


def export_filename(retailer: str = "freshchoice", branch_label: Optional[str] = None,
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


PRESERVED_SCHEMA_KEYS = {
    # Store & Product Identifiers
    "store_id", "branch_id", "product_id", "source_product_id", "sku", "retailer_sku",
    "gtin", "barcode", "mpn", "group_id",
    # Titles & Taxonomy
    "raw_name", "clean_name", "brand", "description",
    "department", "category", "sub_category", "lead_category", "leaf_category",
    "breadcrumbs", "category_hierarchy", "category_path", "category_tree", "category_url",
    "size",
    # Pricing & Promotion
    "currency", "price", "current_price_cents",
    "sale_price", "sale_price_cents",
    "list_price", "list_price_cents", "comparison_price_cents",
    "savings", "savings_cents",
    "price_per_unit", "price_by_unit", "unit_price_cents", "unit_label",
    "is_promo", "promo_badge", "promo_text", "promo_type",
    "multibuy_quantity", "multibuy_price_cents",
    # Stock, Media & Meta
    "availability", "stock_status",
    "url", "product_url", "image_url",
    "recommended_products", "observed_at", "raw_row",
}


def clean_record(rec: dict) -> dict:
    """Ensure consistent schema fields are preserved while dropping unwanted noise."""
    out = {}
    for k, v in rec.items():
        if k in PRESERVED_SCHEMA_KEYS:
            out[k] = v
        elif v is not None and v != "":
            out[k] = v
    return out


def write_jsonl(records: list[dict], branch_label: Optional[str],
                retailer: str = "freshchoice",
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
