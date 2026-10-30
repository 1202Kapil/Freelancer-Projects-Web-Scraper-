"""Offline QA of the existing pilot and recovered FreshChoice JSONL files.

Does not fetch pages, change product data, or assume a catalogue count is
infallible. Separate source-backed products from weak name-only fallbacks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

UNIT_ONLY = re.compile(
    r"(?ix)^(?:each|ea|\d+(?:\.\d+)?\s*(?:ml|l|g|kg|oz|pc|pcs|pack|pk)"
    r"|\d+\s*x\s*\d+(?:\.\d+)?\s*(?:ml|l|g|kg|oz))$"
)


def load_records(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Required catalogue missing: {path}")
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
    return records


def summarize(records):
    qualities = Counter(r.get("identity_quality") or "missing" for r in records)
    provenance = Counter((r.get("attributes") or {}).get("source_identifier_type") or "unmarked"
                         for r in records if r.get("product_id"))
    missing = {field: sum(not r.get(field) for r in records)
               for field in ("product_id", "product_url", "image_url", "price_nzd")}
    product_paths = Counter()
    raw_groceries_parent = 0
    grocery_in_subcategory = 0
    weak = []
    unit_only = []
    for r in records:
        categories = r.get("category_paths") or []
        roots = {p[0] for p in categories if isinstance(p, list) and p}
        for root in roots:
            product_paths[root] += 1
        if any(isinstance(p, list) and p == ["Groceries"] for p in categories):
            raw_groceries_parent += 1
        if any(isinstance(p, list) and len(p) > 1 and p[0] == "Groceries" for p in categories):
            grocery_in_subcategory += 1
        if r.get("identity_quality") == "name_fallback":
            weak.append({"name": r.get("name"), "price_nzd": r.get("price_nzd"),
                         "category_paths": categories[:2]})
        if UNIT_ONLY.fullmatch(str(r.get("name") or "").replace("\u200b", "").strip()):
            unit_only.append({"name": r.get("name"), "identity_quality": r.get("identity_quality"),
                              "category_paths": categories[:2]})
    product_keys = [r.get("product_key") for r in records if r.get("product_key")]
    product_urls = [r["product_url"] for r in records if r.get("product_url")]
    return {
        "records": len(records),
        "identity_quality": dict(qualities),
        "source_identifier_provenance": dict(provenance),
        "missing_fields": missing,
        "grocery_product_records": product_paths.get("Groceries", 0),
        "grocery_parent_records": raw_groceries_parent,
        "grocery_nested_records": grocery_in_subcategory,
        "duplicate_product_keys": len(product_keys) - len(set(product_keys)),
        "duplicate_product_urls": len(product_urls) - len(set(product_urls)),
        "weak_name_only_samples": weak[:12],
        "unit_only_name_count": len(unit_only),
        "unit_only_name_samples": unit_only[:12],
        "category_roots": dict(product_paths),
    }


def run(baseline: Path, recovered: Path, branches: list[str]):
    result = {"description": "Offline, read-only integrity audit of v0.5 recovery",
              "baseline_dir": str(baseline), "recovered_dir": str(recovered), "branches": []}
    recovery_summary_path = recovered / "recovery_summary.json"
    previous = {}
    if recovery_summary_path.is_file():
        summary = json.loads(recovery_summary_path.read_text(encoding="utf-8"))
        previous = {b["branch"]: b for b in summary.get("branches", [])}
    for branch in branches:
        original = load_records(baseline / f"{branch}.jsonl")
        restored = load_records(recovered / f"{branch}.jsonl")
        original_summary = summarize(original)
        restored_summary = summarize(restored)
        base_keys = {p.get("product_key") for p in original}
        new = [p for p in restored if p.get("product_key") not in base_keys]
        recovery = previous.get(branch, {})
        notes = []
        if (recovery.get("previous_groceries_count") is not None
                and recovery["previous_groceries_count"] != original_summary["grocery_product_records"]):
            notes.append("Recovery report's previous_groceries_count differs from actual baseline JSONL")
        if original_summary["grocery_product_records"] == 0 and recovery.get("previous_reported_groceries_total"):
            notes.append("Baseline has no Groceries category paths despite prior website Groceries total; inspect original JSONL")
        if any(r.get("identity_quality") == "name_fallback" for r in new):
            notes.append("New name-only records need independent validation; do not treat as verified product identities")
        if restored_summary["duplicate_product_urls"]:
            notes.append("Duplicate product URLs remain in saved output")
        result["branches"].append({
            "branch": branch, "original": original_summary, "recovered": restored_summary,
            "added_by_product_key": len(new),
            "added_weak_name_only": sum(p.get("identity_quality") == "name_fallback" for p in new),
            "added_missing_product_url": sum(not p.get("product_url") for p in new),
            "expected_groceries_prior": recovery.get("previous_reported_groceries_total"),
            "recovery_reported_groceries": recovery.get("grocery_union_count"),
            "notes": notes,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=Path("output-pilot"))
    parser.add_argument("--recovered-dir", type=Path, default=Path("output-recovered"))
    parser.add_argument("--branches", default="merivale,epsom,greenisland")
    parser.add_argument("--save", type=Path, default=Path("output-integrity/audit.json"))
    args = parser.parse_args()
    report = run(args.baseline_dir, args.recovered_dir,
                 [x.strip() for x in args.branches.split(",") if x.strip()])
    args.save.parent.mkdir(parents=True, exist_ok=True)
    args.save.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved read-only audit to {args.save}")
    for b in report["branches"]:
        before, after = b["original"], b["recovered"]
        print(f"{b['branch']}: {before['records']} -> {after['records']}"
              f" | weak names {before['identity_quality'].get('name_fallback', 0)} ->"
              f" {after['identity_quality'].get('name_fallback', 0)}"
              f" | new weak {b['added_weak_name_only']}"
              f" | Groceries {before['grocery_product_records']} -> {after['grocery_product_records']}")
        for note in b["notes"]:
            print("  CHECK:", note)


if __name__ == "__main__":
    main()
