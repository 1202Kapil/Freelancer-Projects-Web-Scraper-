"""Detail page enrichment module for FreshChoice products."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any
import httpx

from models import Product
from network import Fetcher, AccessRestricted
from parsers import parse_product_detail_page
from storage import write_json, write_jsonl, read_jsonl

logger = logging.getLogger(__name__)


async def enrich_output(args: argparse.Namespace) -> int:
    """Enrich output product records with detail pages; stops immediately on AccessRestricted."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_file = input_dir / "summary.json"
    branches_file = input_dir / "branches.json"

    branch_list = []
    if branches_file.exists():
        with branches_file.open("r", encoding="utf-8") as f:
            branch_list = json.load(f)

    rate_per_host = getattr(args, "rate_per_host", 1.0)
    max_details = getattr(args, "max_details", None)

    summary_report: dict[str, Any] = {
        "status": "completed",
        "branches_enriched": 0,
        "details_visited": 0,
        "issues": [],
    }

    exit_code = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        fetcher = Fetcher(client, rate_per_host=rate_per_host, max_retries=0)

        for br in branch_list:
            branch_id = br["id"]
            src_file = input_dir / f"{branch_id}.jsonl"
            dst_file = output_dir / f"{branch_id}.jsonl"

            if not src_file.exists():
                continue

            raw_records = read_jsonl(src_file)
            # Baseline preservation: write directly to destination before enrichment
            write_jsonl(dst_file, raw_records)

            count = 0
            for r in raw_records:
                if max_details and count >= max_details:
                    break

                product_url = r.get("product_url")
                if not product_url:
                    continue

                try:
                    resp = await fetcher.get(product_url)
                    if resp.status_code == 200:
                        enriched = parse_product_detail_page(resp.text, r)
                        r.update(enriched)
                    count += 1
                except AccessRestricted as e:
                    logger.error(f"Enrichment halted due to AccessRestricted: {e}")
                    summary_report["status"] = "failed"
                    summary_report["issues"].append(f"AccessRestricted on {product_url}: {e}")
                    exit_code = 1
                    # Ensure current state preserved
                    write_jsonl(dst_file, raw_records)
                    write_json(output_dir / "enrichment_summary.json", summary_report)
                    return exit_code
                except Exception as e:
                    logger.warning(f"Error enriching {product_url}: {e}")

            write_jsonl(dst_file, raw_records)
            summary_report["branches_enriched"] += 1
            summary_report["details_visited"] += count

    write_json(output_dir / "enrichment_summary.json", summary_report)
    return exit_code


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--branch-concurrency", type=int, default=2)
    parser.add_argument("--rate-per-host", type=float, default=0.5)
    parser.add_argument("--max-details", type=int, default=0, help="Per-branch limit; 0 means all product URLs")
