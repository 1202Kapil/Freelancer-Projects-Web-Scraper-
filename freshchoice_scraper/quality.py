"""Read-only dataset checks. Structural validity is not proof of catalogue completeness."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from models import Product

UNIT_ONLY = re.compile(r'(?i)^(?:each|ea|\d+(?:\.\d+)?\s*(?:ml|l|g|kg|oz|pc|pcs|pack|pk)|\d+\s*x\s*\d+(?:\.\d+)?\s*(?:ml|l|g|kg|oz))$')


def record_issues(record: dict) -> list[str]:
    problems = []
    name = re.sub(r'[\u200b-\u200d\ufeff]', '', record.get('name') or '').strip()
    if not name or UNIT_ONLY.fullmatch(name):
        problems.append('invalid_product_name')
    if record.get('identity_quality') == 'name_fallback':
        problems.append('unverified_name_only_identity')
    p = record.get('promotion') or {}
    current, previous, saving = (record.get('price_nzd'), p.get('previous_price_nzd'), p.get('savings_nzd'))
    if current is not None and previous is not None:
        if Decimal(str(previous)) < Decimal(str(current)):
            problems.append('previous_price_below_current_requires_verification')
        if saving is not None and abs(Decimal(str(previous)) - Decimal(str(current)) - Decimal(str(saving))) > Decimal('.02'):
            problems.append('promotion_arithmetic_mismatch')
    return problems


def audit_file(path: Path, branch: str) -> dict:
    rows = []
    errors = []
    with path.open(encoding='utf-8') as stream:
        for n, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                p = Product.model_validate_json(line)
                if p.branch_id != branch:
                    raise ValueError('branch ID differs from filename')
                r = p.model_dump(mode='json')
                rows.append(r)
                for reason in record_issues(r):
                    errors.append({'line': n, 'product_key': p.product_key, 'reason': reason})
            except (ValueError, TypeError) as exc:
                errors.append({'line': n, 'reason': 'invalid_schema', 'detail': str(exc)[:200]})
    keys = Counter(r['product_key'] for r in rows)
    urls = Counter(r['product_url'] for r in rows if r.get('product_url'))
    for label, counter in [('duplicate_product_key', keys), ('duplicate_product_url', urls)]:
        errors.extend({'reason': label, 'value': key, 'count': n} for key, n in counter.items() if n > 1)
    return {
        'branch': branch,
        'records': len(rows),
        'errors': errors,
        'error_count': len(errors),
        'missing_fields': {
            k: sum(r.get(k) is None for r in rows)
            for k in ['product_id', 'product_url', 'image_url', 'price_nzd', 'brand', 'description', 'gtin', 'sku']
        },
        'availability': dict(Counter(r.get('availability') for r in rows)),
        'identity_quality': dict(Counter(r.get('identity_quality') for r in rows)),
    }


def audit_directory(directory: Path) -> dict:
    summary_path = directory / 'summary.json'
    if not summary_path.exists():
        return {'total_records': 0, 'error_count': 0, 'branches': [], 'coverage_status': 'missing_summary'}
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    branches = []
    for b in summary.get('branch_results', []):
        branch_id = b.get('branch_id')
        jsonl_path = directory / f"{branch_id}.jsonl"
        if not jsonl_path.exists():
            continue
        report = audit_file(jsonl_path, branch_id)
        if report['records'] != b.get('products'):
            report['errors'].append({'reason': 'summary_count_mismatch'})
            report['error_count'] += 1
        branches.append(report)
    total = sum(b['records'] for b in branches)
    errors = sum(b['error_count'] for b in branches) + (total != summary.get('total_unique_products', total))
    return {
        'total_records': total,
        'error_count': errors,
        'branches': branches,
        'coverage_status': 'partial' if summary.get('branches_partial') or summary.get('branches_failed') else 'complete',
        'note': 'Zero integrity errors does not verify every source value, field availability, or full catalogue coverage.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('output'))
    parser.add_argument('--save', type=Path)
    args = parser.parse_args()
    report = audit_directory(args.data_dir)
    print(f"Total records: {report['total_records']}, errors: {report['error_count']}")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f"Saved audit report to {args.save}")


if __name__ == '__main__':
    main()
