"""Reproducible offline repair of the supplied v0.6 dataset, preserving provenance.

Unverifiable records are quarantined, not guessed. Targeted factual updates come
only from the reviewed public-source evidence JSON files beside this script.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import time

from models import Product
from normalize import clean
from quality import record_issues, audit_directory
from storage import write_json, write_jsonl


def repair(source: Path, output: Path, evidence: Path) -> dict:
    if source.resolve() == output.resolve():
        raise ValueError('Use a distinct output directory to preserve source data')
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    history = output / 'history'
    history.mkdir(exist_ok=True)
    for filename in ['summary.json', 'recovery_summary.json', 'pilot_summary.json', 'branches.json', 'submission_manifest.json', 'pilot_scraper.log']:
        if (source / filename).exists():
            shutil.copy2(source / filename, history / filename)
    directory = json.loads((evidence / 'directory_patch.json').read_text(encoding='utf-8')) if (evidence / 'directory_patch.json').exists() else {'branches': [], 'source_url': '', 'method': ''}
    updates = {b['id']: b for b in directory.get('branches', [])}
    branches_file = source / 'branches.json'
    branches = json.loads(branches_file.read_text(encoding='utf-8')) if branches_file.exists() else []
    for b in branches:
        if b['id'] in updates:
            b.update(updates[b['id']])
    write_json(output / 'branches.json', branches)
    write_json(output / 'directory_only_stores.json', directory.get('directory_only_stores', []))
    names = {b['id']: b['name'] for b in branches}
    product_evidence_file = evidence / 'product_patch.json'
    product_evidence = json.loads(product_evidence_file.read_text(encoding='utf-8')) if product_evidence_file.exists() else {'products': [], 'retrieved_date': '', 'method': ''}
    patches = {(p['branch_id'], p['product_id']): p for p in product_evidence.get('products', [])}
    summary_file = source / 'summary.json'
    summary = json.loads(summary_file.read_text(encoding='utf-8')) if summary_file.exists() else {'branch_results': [], 'elapsed_seconds': 0}
    report = {
        'repair_version': '0.7.0',
        'input_archive_version': '0.6.0',
        'repaired_at': datetime.now(timezone.utc).isoformat(),
        'full_live_rerun': False,
        'direct_http_probe': {'url': 'https://store.freshchoice.co.nz/', 'status': 403, 'action': 'stopped; no authentication, proxy rotation or access bypass'},
        'branch_metadata_source': directory.get('source_url', ''),
        'branch_metadata_method': directory.get('method', ''),
        'branch_metadata_updated': len(updates),
        'branches': [],
        'targeted_changes': [],
    }
    quarantine = output / 'quarantine'
    quarantine.mkdir(exist_ok=True)
    manifest = {'schema_version': '0.7.0', 'branches': {}, 'caveat': 'Cleaned historical data with one public-source price correction; catalogue coverage and optional fields remain partial.'}
    log = []
    for b in summary.get('branch_results', []):
        bid = b['branch_id']
        source_file = source / f'{bid}.jsonl'
        if not source_file.exists():
            continue
        original = [json.loads(l) for l in source_file.read_text(encoding='utf-8').splitlines() if l.strip()]
        accepted = []
        rejected = []
        normalizations = 0
        for raw in original:
            r = copy.deepcopy(raw)
            patch = patches.get((bid, r.get('product_id')))
            if patch:
                before = {k: r.get(k) for k in ['price_nzd', 'pricing_unit', 'unit_price_nzd', 'unit_price_basis', 'promotion']}
                for k in before:
                    r[k] = patch[k]
                r.setdefault('attributes', {})['price_verification'] = {
                    'source_url': patch['source_url'],
                    'retrieved_date': product_evidence['retrieved_date'],
                    'method': product_evidence['method'],
                    'original_scraped_at': raw.get('scraped_at'),
                }
                report['targeted_changes'].append({'branch_id': bid, 'product_id': r['product_id'], 'source_url': patch['source_url'], 'before': before, 'after': {k: r[k] for k in before}})
            reasons = record_issues(r)
            if reasons:
                rejected.append({'reasons': reasons, 'original_record': raw})
                continue
            r['name'] = clean(r.get('name'))
            r['branch_name'] = names.get(bid, bid.title())
            paths = []
            for path in r.get('category_paths', []):
                values = []
                for label in path:
                    label = clean(label)
                    if not label or re.sub('[^a-z0-9]', '', label.lower()) in {bid.replace('-', ''), re.sub('[^a-z0-9]', '', names.get(bid, '').lower())}:
                        continue
                    if label not in values:
                        values.append(label)
                if values and values not in paths:
                    paths.append(values)
            r['category_paths'] = paths
            if any(raw.get(k) != r.get(k) for k in ['name', 'branch_name', 'category_paths']):
                normalizations += 1
            accepted.append(Product.model_validate(r))
        write_jsonl(output / f'{bid}.jsonl', accepted)
        (quarantine / f'{bid}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rejected), encoding='utf-8')
        b['original_products'] = b.get('products', len(original))
        b['products'] = len(accepted)
        b['branch_name'] = names.get(bid, bid.title())
        b['status'] = 'partial'
        b['output_file'] = f'output/{bid}.jsonl'
        b['quarantined_records'] = len(rejected)
        b['historical_collection_issues'] = b.pop('issues', [])
        b['issues'] = [
            'Historical catalogue coverage remains partial; see output/history/summary.json.',
            'Brand and availability have not been verified across all products; run detail enrichment when permitted.',
            f'{len(rejected)} unverifiable records quarantined; no replacement identities or prices inferred.',
        ]
        if bid == 'greenisland':
            b['issues'].append('Household originally stopped at 191/1079; requires a fresh permitted crawl.')
        if bid == 'merivale':
            b['issues'].append('Groceries remained below its historical reported total; rerun taxonomy recovery.')
        for field, key in [('product_id', 'missing_product_ids'), ('price_nzd', 'missing_prices'), ('image_url', 'missing_images')]:
            b[key] = sum(getattr(r, field) is None for r in accepted)
        digest = hashlib.sha256((output / f'{bid}.jsonl').read_bytes()).hexdigest()
        manifest['branches'][bid] = {'records': len(accepted), 'sha256': digest}
        stat = {'branch': bid, 'original_records': len(original), 'retained_records': len(accepted), 'quarantined_records': len(rejected), 'normalized_records': normalizations}
        report['branches'].append(stat)
        log.append(json.dumps(stat))
    summary['dataset_version'] = '0.7.0'
    summary['total_unique_products'] = sum(b['products'] for b in summary.get('branch_results', []))
    summary['branches_completed'] = 0
    summary['branches_partial'] = len(summary.get('branch_results', []))
    summary['branches_failed'] = 0
    summary['collection_elapsed_seconds'] = summary.get('elapsed_seconds', 0)
    summary['elapsed_seconds_scope'] = 'Historical pilot plus recovery collection only; excludes idle gap, source lookup and offline repair. Not one uninterrupted crawl.'
    summary['repair_elapsed_seconds'] = round(time.perf_counter() - started, 3)
    summary['data_repaired_at'] = report['repaired_at']
    summary['total_quarantined_records'] = sum(b['quarantined_records'] for b in report['branches'])
    summary['issues'] = ['Full live refresh was not possible: direct public-directory HTTP request returned 403; no bypass attempted.']
    write_json(output / 'summary.json', summary)
    report['elapsed_seconds'] = summary['repair_elapsed_seconds']
    write_json(output / 'repair_report.json', report)
    manifest['total_branch_product_records'] = summary['total_unique_products']
    manifest['quarantined_records'] = summary['total_quarantined_records']
    write_json(output / 'submission_manifest.json', manifest)
    qa = audit_directory(output)
    write_json(output / 'quality_report.json', qa)
    (output / 'repair.log').write_text('\n'.join(log) + f"\nintegrity_errors={qa['error_count']}\n", encoding='utf-8')
    if qa['error_count']:
        raise ValueError('Repaired output failed integrity checks')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, default=Path(__file__).parent / 'evidence')
    args = parser.parse_args()
    report = repair(args.input_dir, args.output_dir, args.evidence_dir)
    for b in report['branches']:
        print(b)


if __name__ == '__main__':
    main()
