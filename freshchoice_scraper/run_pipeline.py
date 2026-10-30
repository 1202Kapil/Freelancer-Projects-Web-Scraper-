"""Run the corrected three-branch pipeline. Stops if any phase reports access restrictions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root', type=Path, default=Path('run-v07'))
    p.add_argument('--branches', default='merivale,epsom,greenisland')
    p.add_argument('--branch-concurrency', type=int, default=2)
    p.add_argument('--enrich-details', action='store_true', help='Fetch every detail URL after recovery; can take hours')
    args = p.parse_args()
    root = args.output_root
    if root.exists():
        raise SystemExit('Use a new --output-root to preserve previous runs.')

    def run(command, report):
        proc = subprocess.run([sys.executable, '-m', 'freshchoice_scraper', *command], check=False)
        if proc.returncode not in (0, 1) or not report.exists():
            raise SystemExit(proc.returncode or 1)
        data = report.read_text(encoding='utf-8')
        if any(s in data for s in ['AccessRestricted', 'HTTP 403', 'HTTP 401', 'HTTP 429', 'Retry-After']):
            raise SystemExit('Access restriction recorded. Stopped; do not bypass the restriction.')
        return json.loads(data)

    pilot = root / 'pilot'
    recovered = root / 'recovered'
    report = run(['scrape', '--branches', args.branches, '--branch-concurrency', str(args.branch_concurrency), '--output-dir', str(pilot)], pilot / 'summary.json')
    if not report.get('total_unique_products'):
        raise SystemExit('No products collected; inspect summary before continuing.')
    selected = ','.join(b['branch_id'] for b in report['branch_results'])
    run(['recover-groceries', '--input-dir', str(pilot), '--output-dir', str(recovered), '--branches', selected, '--branch-concurrency', str(args.branch_concurrency)], recovered / 'recovery_summary.json')
    final = recovered
    if args.enrich_details:
        final = root / 'enriched'
        run(['enrich-output', '--input-dir', str(recovered), '--output-dir', str(final), '--branch-concurrency', str(args.branch_concurrency)], final / 'enrichment_summary.json')
    qa = subprocess.run([sys.executable, '-m', 'quality', '--data-dir', str(final), '--save', str(final / 'quality_report.json')], check=False)
    print(f'Output: {final}. Review summary.json and quality_report.json before claiming completeness.')
    raise SystemExit(qa.returncode)


if __name__ == '__main__':
    main()
