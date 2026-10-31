"""Branch resolution for Kai Co against PICO catalog schema.

This module is strictly READ-ONLY: it resolves which store to scrape (id,
name, slug, and external store id). It never writes — the importer owns all catalog writes.

Authoritative offline fallback is loaded from branches.json.
When DATABASE_URL is available, it queries the live PostgreSQL `catalog` schema.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional

from config import BRANCHES_PATH, DEFAULT_STORE_NAME, DEFAULT_STORE_ID, DEFAULT_STORE_SLUG, DATABASE_URL, RETAILER_SLUG

logger = logging.getLogger(__name__)

# Fallback store registry
KNOWN_KAICO_STORES: list[dict[str, Any]] = [
    {
        "name": "Kai Co Northwood",
        "slug": "northwood",
        "store_id": "kaico-northwood",
        "external_id": "kaico-northwood",
        "address": "Northwood Supa Centa, Main North Road, Christchurch 8051, New Zealand",
        "suburb": "Northwood",
        "city": "Christchurch",
        "phone": "03 323 4555",
        "email": "online@kaico.co.nz",
        "is_active": True,
    }
]


def load_offline_branches() -> list[dict[str, Any]]:
    """Load authoritative branch registry from branches.json."""
    if BRANCHES_PATH.exists():
        try:
            data = json.loads(BRANCHES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            logger.warning(f"[catalog] Failed to load {BRANCHES_PATH.name}: {e}")
    return KNOWN_KAICO_STORES


def _connect():
    """Short-lived connection to PostgreSQL pooler if DATABASE_URL configured."""
    if not DATABASE_URL:
        return None
    try:
        import psycopg
        return psycopg.connect(DATABASE_URL, connect_timeout=5)
    except Exception as exc:
        logger.debug(f"[catalog] DB connection skipped/failed: {exc}")
        return None


def resolve_branch(query: Optional[str] = None) -> dict[str, Any]:
    """Resolve a single branch by slug, external store id, or name.
    If no query provided, returns the default branch.
    """
    branches = list_branches()
    if not query:
        return branches[0]

    q_lower = query.strip().lower()
    for b in branches:
        if (
            b.get("slug", "").lower() == q_lower
            or b.get("store_id", "").lower() == q_lower
            or b.get("external_id", "").lower() == q_lower
            or q_lower in b.get("name", "").lower()
        ):
            return b

    # Fallback default if not matched
    logger.warning(f"[catalog] Branch query '{query}' not found; falling back to default.")
    return branches[0]


def list_branches(active_only: bool = True) -> list[dict[str, Any]]:
    """Fetch all known branches, trying PostgreSQL first, then falling back to offline registry."""
    conn = _connect()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.id, b.slug, b.name, b.is_active, e.external_id
                    FROM catalog.branches b
                    JOIN catalog.retailers r ON r.id = b.retailer_id
                    LEFT JOIN catalog.external_store_ids e ON e.branch_id = b.id
                    WHERE r.slug = %s
                    ORDER BY b.name
                    """,
                    (RETAILER_SLUG,),
                )
                rows = cur.fetchall()
                if rows:
                    results = []
                    for r in rows:
                        b_id, slug, name, is_active, ext_id = r
                        if active_only and not is_active:
                            continue
                        results.append({
                            "id": str(b_id),
                            "name": name,
                            "slug": slug,
                            "store_id": ext_id or slug,
                            "external_id": ext_id or slug,
                            "is_active": is_active,
                        })
                    if results:
                        return results
        except Exception as exc:
            logger.warning(f"[catalog] Failed to query catalog schema: {exc}")
        finally:
            conn.close()

    # Offline fallback
    branches = load_offline_branches()
    if active_only:
        branches = [b for b in branches if b.get("is_active", True)]
    return branches


def main():
    parser = argparse.ArgumentParser(description="Kai Co branch resolution utility")
    parser.add_argument("--list", action="store_true", help="List all available branches")
    parser.add_argument("--resolve", type=str, help="Resolve a specific branch slug or name")
    args = parser.parse_args()

    if args.list:
        branches = list_branches(active_only=False)
        print(f"Total branches: {len(branches)}")
        for b in branches:
            print(f"- {b['name']} (slug: {b['slug']}, id: {b.get('external_id') or b.get('store_id')}) [active={b.get('is_active')}]")
    elif args.resolve:
        branch = resolve_branch(args.resolve)
        print(json.dumps(branch, indent=2))
    else:
        branch = resolve_branch()
        print(f"Default branch: {branch['name']} ({branch['slug']})")


if __name__ == "__main__":
    main()
