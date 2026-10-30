"""Audit recovered FreshChoice dataset against pilot baseline and quality rules."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from storage import read_jsonl, read_json

UNIT_ONLY_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|pk|pack|ea|sachets)|each|per\s+kg)$", re.I)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize list of product observation dicts."""
    records = len(rows)
    grocery_records = 0
    id_quality: dict[str, int] = {}
    missing_fields: dict[str, int] = {"product_url": 0, "image_url": 0, "product_id": 0}
    unit_only_count = 0
    provenance: dict[str, int] = {}

    for r in rows:
        name = r.get("name") or r.get("raw_name") or ""
        if UNIT_ONLY_RE.match(name):
            unit_only_count += 1

        cats = r.get("category_paths") or []
        cat_str = " ".join(" ".join(c) if isinstance(c, list) else str(c) for c in cats)
        if "Groceries" in cat_str or "groceries" in cat_str:
            grocery_records += 1

        iq = r.get("identity_quality", "source_id")
        id_quality[iq] = id_quality.get(iq, 0) + 1

        for f in ("product_url", "image_url", "product_id"):
            if not r.get(f):
                missing_fields[f] = missing_fields.get(f, 0) + 1

        attrs = r.get("attributes") or {}
        prov = attrs.get("source_identifier_type")
        if prov:
            provenance[prov] = provenance.get(prov, 0) + 1

    return {
        "records": records,
        "grocery_product_records": grocery_records,
        "identity_quality": id_quality,
        "missing_fields": missing_fields,
        "unit_only_name_count": unit_only_count,
        "source_identifier_provenance": provenance,
    }


def run(base_dir: Path | str, recovered_dir: Path | str, branches: list[str]) -> dict[str, Any]:
    """Run audit comparing pilot baseline and recovered output."""
    base_p = Path(base_dir)
    rec_p = Path(recovered_dir)

    rec_summary = {}
    rec_sum_file = rec_p / "recovery_summary.json"
    if rec_sum_file.exists():
        rec_summary = read_json(rec_sum_file)

    branch_results = []
    for branch in branches:
        base_rows = read_jsonl(base_p / f"{branch}.jsonl")
        rec_rows = read_jsonl(rec_p / f"{branch}.jsonl")

        base_summary = summarize(base_rows)
        rec_summary_branch = summarize(rec_rows)

        base_weak = base_summary["identity_quality"].get("name_fallback", 0)
        rec_weak = rec_summary_branch["identity_quality"].get("name_fallback", 0)
        added_weak = max(0, rec_weak - base_weak)

        notes = []
        if added_weak > 0:
            notes.append(f"Added {added_weak} weak name-only fallback records")

        # Check recovery union against reported total
        b_sum_data = next((b for b in rec_summary.get("branches", []) if b.get("branch") == branch), None)
        if b_sum_data:
            rep_tot = b_sum_data.get("previous_reported_groceries_total", 0)
            rec_union = b_sum_data.get("grocery_union_count", 0)
            if rec_union < rep_tot:
                notes.append(f"Groceries union count ({rec_union}) below reported total ({rep_tot})")

        branch_results.append({
            "branch": branch,
            "added_weak_name_only": added_weak,
            "notes": notes,
            "baseline_records": len(base_rows),
            "recovered_records": len(rec_rows),
        })

    return {"branches": branch_results}
