"""Validate and package code plus the selected output directory. No network access."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from quality import audit_directory

ROOT = 'freshchoice-scraper'
ROOT_FILES = {'.gitignore', 'README.md', 'API_ANALYSIS.md', 'pyproject.toml', 'config.yaml', 'api.example.json', 'TEST_RESULTS.txt'}


def source_files(project: Path):
    for path in sorted(project.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(project)
        if any(x in {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'} or x.endswith('.egg-info') for x in rel.parts):
            continue
        if rel.suffix in {'.pyc', '.zip'}:
            continue
        if (len(rel.parts) == 1 and rel.name in ROOT_FILES) or rel.parts[0] in {'src', 'tests', 'examples'}:
            yield path, (Path(ROOT) / rel).as_posix()


def build(project: Path, data_dir: Path, archive: Path) -> dict:
    report = audit_directory(data_dir)
    if report['error_count']:
        raise ValueError(f"Integrity audit found {report['error_count']} errors")
    manifest = {
        'schema_version': '0.7.0',
        'branches': {},
        'total_branch_product_records': report['total_records'],
        'coverage_status': report['coverage_status'],
        'caveat': 'Integrity checks do not prove complete catalogues or verify every source value.',
    }
    for branch in report['branches']:
        path = data_dir / f"{branch['branch']}.jsonl"
        manifest['branches'][branch['branch']] = {
            'records': branch['records'],
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    branches_path = data_dir / 'branches.json'
    if branches_path.exists():
        branches = json.loads(branches_path.read_text(encoding='utf-8'))
        if len({b['id'] for b in branches}) != len(branches):
            raise ValueError('Duplicate branch IDs')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.resolve().is_relative_to(project.resolve()):
        raise ValueError('Write ZIP outside the project directory')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path, name in source_files(project):
            z.write(path, name)
        for path in sorted(data_dir.rglob('*')):
            if not path.is_file() or path == data_dir / 'submission_manifest.json':
                continue
            if path.suffix == '.tmp':
                continue
            rel = path.relative_to(data_dir)
            z.write(path, (Path(ROOT) / 'output' / rel).as_posix())
        z.writestr(f'{ROOT}/output/submission_manifest.json', json.dumps(manifest, indent=2) + '\n')
    # Check exactly what was packaged, not just the source directory.
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('ZIP CRC validation failed')
        for bid, stats in manifest['branches'].items():
            content = z.read(f'{ROOT}/output/{bid}.jsonl')
            if hashlib.sha256(content).hexdigest() != stats['sha256']:
                raise ValueError('Packaged checksum mismatch')
            if len(content.splitlines()) != stats['records']:
                raise ValueError('Packaged row count mismatch')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', type=Path, default=Path('output'))
    p.add_argument('--archive', type=Path, default=Path('../FreshChoice_Updated_Submission_v0.7.zip'))
    args = p.parse_args()
    manifest = build(Path(__file__).resolve().parent, args.data_dir, args.archive)
    print(f"Created {args.archive.resolve()}: {manifest['total_branch_product_records']:,} records; {manifest['coverage_status']}")


if __name__ == '__main__':
    main()
