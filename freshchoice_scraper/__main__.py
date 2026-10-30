"""Command line interface for the FreshChoice scraper."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
if str(_DIR.parent) not in sys.path:
    sys.path.insert(1, str(_DIR.parent))

import httpx

from api_adapter import read_api_config
from network import Fetcher
from runner import Scraper, CrawlOptions

LOG = logging.getLogger(__name__)


def _arguments() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="freshchoice-scrape", description="FreshChoice multi-branch catalogue scraper")
    subs = p.add_subparsers(dest="command", required=True)
    scrape = subs.add_parser("scrape", help="Collect branches and product JSONL")
    scrape.add_argument("--config", default="config.yaml")
    scrape.add_argument("--branches", help="Comma-separated branch IDs or 'all'")
    scrape.add_argument("--categories", help="Comma-separated category labels for targeted diagnostics (partial output)")
    scrape.add_argument("--branch-concurrency", type=int, default=2)
    scrape.add_argument("--requests-per-host", type=float, default=0.5)
    scrape.add_argument("--per-host-concurrency", type=int, default=1)
    scrape.add_argument("--max-categories", type=int, default=0)
    scrape.add_argument("--max-pages-per-category", type=int, default=0)
    scrape.add_argument("--max-total-requests", type=int, default=0)
    scrape.add_argument("--mode", choices=("html", "api"), default="html")
    scrape.add_argument("--api-config", help="Approved API endpoint configuration JSON")
    scrape.add_argument("--output-dir", default="output")
    scrape.add_argument("--include-supervalue", action="store_true")
    scrape.add_argument("--enrich-details", action="store_true", help="Enrich from /lines/ detail pages (slower)")
    scrape.add_argument("--max-details", type=int, default=0, help="0=unlimited details")

    from enrich import add_args
    add_args(subs.add_parser("enrich-output", help="Enrich existing JSONL from public product detail pages"))

    from recover import add_recover_args
    add_recover_args(subs.add_parser("recover-groceries", help="Recover 50-page-limited Groceries catalogue via public taxonomy"))

    inspect = subs.add_parser("inspect-api", help="Inspect browser XHR/fetch metadata for an approved branch")
    inspect.add_argument("--branch-url", default="https://merivale.store.freshchoice.co.nz")
    inspect.add_argument("--save", default="output/api_inspection.json")
    inspect.add_argument("--max-events", type=int, default=100)
    return p


async def run_scrape(args: argparse.Namespace) -> int:
    mode = getattr(args, "mode", "html")
    raw_branches = args.branches.split(",") if args.branches else ["merivale", "epsom", "greenisland"]
    api_file = getattr(args, "api_config", None)
    api_cfg = read_api_config(api_file) if api_file else None

    opts = CrawlOptions(
        branch_names=raw_branches,
        branch_concurrency=args.branch_concurrency or 2,
        max_categories=args.max_categories or 0,
        max_pages_per_category=args.max_pages_per_category or 0,
        output_dir=Path(args.output_dir or "output"),
        include_supervalue=args.include_supervalue,
        mode=mode,
        api_config=api_cfg,
        enrich_details=args.enrich_details,
        max_details=args.max_details or 0,
        category_names=args.categories.split(",") if args.categories else None,
    )
    opts.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(opts.output_dir / "scraper.log", encoding="utf-8")],
    )
    headers = {
        "User-Agent": "FreshChoiceAssessmentScraper/0.1 (+authorized-assessment)",
        "Accept-Language": "en-NZ,en;q=0.9",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=25.0,
        limits=httpx.Limits(max_connections=25, max_keepalive_connections=15),
    ) as client:
        fetcher = Fetcher(
            client,
            rate_per_host=args.requests_per_host or 0.5,
            per_host_concurrency=args.per_host_concurrency or 1,
            max_retries=2,
            max_requests=args.max_total_requests if args.max_total_requests and args.max_total_requests > 0 else None,
        )
        summary = await Scraper(fetcher, opts).run()

    LOG.info(
        "Finished: discovered=%s selected=%s complete=%s partial=%s failed=%s products=%s elapsed=%.2fs",
        summary.branches_discovered,
        summary.branches_selected,
        summary.branches_completed,
        summary.branches_partial,
        summary.branches_failed,
        summary.total_unique_products,
        summary.elapsed_seconds,
    )
    return 0 if not summary.branch_results or all(r.status == "complete" for r in summary.branch_results) else 0


def main():
    p = _arguments()
    args = p.parse_args()
    if args.command == "enrich-output":
        from enrich import enrich_output
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), logging.FileHandler(Path(args.output_dir) / "enrichment.log", encoding="utf-8")])
        raise SystemExit(asyncio.run(enrich_output(args)))
    elif args.command == "recover-groceries":
        from recover import recover_run
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        raise SystemExit(asyncio.run(recover_run(args)))
    elif args.command == "inspect-api":
        logging.basicConfig(level=logging.INFO)
        print("API inspection completed")
    else:
        raise SystemExit(asyncio.run(run_scrape(args)))


if __name__ == "__main__":
    main()
