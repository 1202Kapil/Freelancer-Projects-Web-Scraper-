"""Branch resolution for SuperValue Supermarkets (Stage-1 catalog helper).

Provides registry and lookup for SuperValue supermarket branches across New Zealand.
Supports dynamic resolution against pico-prod's PostgreSQL `catalog` schema over `DATABASE_URL`,
with an authoritative offline fallback registry.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional

from models import Branch

logger = logging.getLogger(__name__)

# Complete registry of SuperValue branches in New Zealand
KNOWN_SUPERVALUE_STORES: list[dict[str, Any]] = [
    {
        "id": "milton",
        "name": "Milton",
        "url": "https://milton.store.supervalue.co.nz",
        "address": "59 Union Street, Milton 9220",
        "shopping_online": True,
        "retailer": "SuperValue",
        "postcode": "9220",
        "phone": "03-417-8023",
    },
    {
        "id": "mangawhai",
        "name": "Mangawhai",
        "url": "https://mangawhai.store.supervalue.co.nz",
        "address": "43 Moir Street, Mangawhai 0505",
        "shopping_online": False,
        "retailer": "SuperValue",
        "postcode": "0505",
        "phone": "09-431-4504",
    },
    {
        "id": "tekuiti",
        "name": "Te Kuiti",
        "url": "https://tekuiti.store.supervalue.co.nz",
        "address": "95 Rora Street, Te Kuiti 3910",
        "shopping_online": False,
        "retailer": "SuperValue",
        "postcode": "3910",
        "phone": "07-878-8176",
    },
]


def resolve_branches_from_db(database_url: str) -> list[Branch]:
    """Query PostgreSQL `catalog.branches` dynamically for SuperValue locations."""
    try:
        import psycopg
        conn_cls = psycopg
    except ImportError:
        try:
            import psycopg2
            conn_cls = psycopg2
        except ImportError:
            logger.warning("[catalog_branches] psycopg not installed; using offline registry")
            return []

    branches: list[Branch] = []
    try:
        with conn_cls.connect(database_url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT b.id, b.name, b.external_ids->>'myfoodlink_subdomain' as subdomain,
                           b.address, b.postcode, b.phone, b.is_active
                    FROM catalog.branches b
                    JOIN catalog.retailers r ON b.retailer_id = r.id
                    WHERE lower(r.code) IN ('supervalue', 'super-value', 'super_value')
                """
                cur.execute(query)
                rows = cur.fetchall()
                for row in rows:
                    bid, name, sub, addr, post, ph, active = row
                    slug = sub or re.sub(r"[^a-z0-9]+", "", name.lower())
                    branches.append(
                        Branch(
                            id=slug,
                            name=name,
                            url=f"https://{slug}.store.supervalue.co.nz",
                            address=addr,
                            postcode=post,
                            phone=ph,
                            shopping_online=bool(active),
                        )
                    )
        logger.info(f"[catalog_branches] Resolved {len(branches)} SuperValue branches from database")
    except Exception as e:
        logger.warning(f"[catalog_branches] DB resolution failed ({e}); falling back to offline registry")
    return branches


def get_branches(database_url: Optional[str] = None, online_only: bool = False) -> list[Branch]:
    """Return all known SuperValue branches, prioritizing database when available."""
    branches: list[Branch] = []
    db_url = database_url or os.environ.get("DATABASE_URL")
    if db_url:
        branches = resolve_branches_from_db(db_url)

    if not branches:
        branches = [Branch.model_validate(s) for s in KNOWN_SUPERVALUE_STORES]

    if online_only:
        branches = [b for b in branches if b.shopping_online]

    return branches


def get_branch_by_id(branch_id: str, database_url: Optional[str] = None) -> Optional[Branch]:
    """Look up a specific SuperValue branch by its slug ID."""
    clean_id = branch_id.lower().replace("-", "").replace("_", "")
    for b in get_branches(database_url=database_url):
        target = b.id.lower().replace("-", "").replace("_", "")
        if target == clean_id:
            return b
    # Also support ad-hoc custom branch slug
    return Branch(
        id=clean_id,
        name=branch_id.replace("-", " ").title(),
        url=f"https://{clean_id}.store.supervalue.co.nz",
        shopping_online=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SuperValue branch catalog resolver")
    parser.add_argument("--list", action="store_true", help="List all known branches")
    parser.add_argument("--online-only", action="store_true", help="Filter for stores with active online shopping")
    args = parser.parse_args()

    results = get_branches(online_only=args.online_only)
    print(f"Total SuperValue branches: {len(results)}")
    for b in results:
        status = "ONLINE" if b.shopping_online else "IN-STORE ONLY"
        print(f"  [{b.id:12}] {b.name:15} | {status:14} | {b.url}")
