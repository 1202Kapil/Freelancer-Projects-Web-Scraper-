"""Branch resolution and store registry for Farro Fresh Supermarkets.

Provides authoritative store information for all 8 Farro Fresh branches across Auckland.
Supports dynamic resolution against pico-prod's PostgreSQL `catalog` schema over `DATABASE_URL`,
with an authoritative offline fallback registry.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from config import DATABASE_URL, RETAILER_SLUG

logger = logging.getLogger(__name__)

# Complete authoritative registry of all 8 Farro Fresh branches in Auckland, New Zealand
KNOWN_FARRO_STORES: list[dict[str, Any]] = [
    {
        "name": "Farro Grey Lynn",
        "slug": "farro-grey-lynn",
        "store_id": "stores-p_default_store_ti_1gjtem2",
        "address": "34 Westmoreland Street West, Grey Lynn, Auckland, NZ",
        "suburb": "Grey Lynn",
        "city": "Auckland",
        "phone": "(09) 892 6300",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Newmarket",
        "slug": "farro-newmarket",
        "store_id": "stores-p_default_store_ti_1l84hsi",
        "address": "480 Broadway, Newmarket, Auckland, NZ",
        "suburb": "Newmarket",
        "city": "Auckland",
        "phone": "(09) 892 6364",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Epsom",
        "slug": "farro-epsom",
        "store_id": "stores-p_default_store_ti_1gjtem4",
        "address": "446 Manukau Road, Epsom, Auckland, NZ",
        "suburb": "Epsom",
        "city": "Auckland",
        "phone": "(09) 892 6330",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Mt Eden",
        "slug": "farro-mt-eden",
        "store_id": "stores-p_default_store_ti_1gjtem3",
        "address": "422 Dominion Road, Mount Eden, Auckland, NZ",
        "suburb": "Mount Eden",
        "city": "Auckland",
        "phone": "(09) 892 6377",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Smales Farm",
        "slug": "farro-smales-farm",
        "store_id": "stores-p_default_store_ti_1jfjjpl",
        "address": "Cnr. Taharoto Road & Shakespeare Road, Takapuna, Auckland 0622, NZ",
        "suburb": "Takapuna",
        "city": "Auckland",
        "phone": "(09) 892 6394",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Mairangi Bay",
        "slug": "farro-mairangi-bay",
        "store_id": "stores-p_default_store_ti_1gjtem6",
        "address": "Corner of Constellation Drive & Parkway Drive, Mairangi Bay, Auckland, NZ",
        "suburb": "Mairangi Bay",
        "city": "Auckland",
        "phone": "(09) 892 6307",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Mt Wellington",
        "slug": "farro-mt-wellington",
        "store_id": "stores-p_default_store_ti_1gjtem5",
        "address": "80 Lunn Ave, Mt Wellington, Auckland, NZ",
        "suburb": "Mt Wellington",
        "city": "Auckland",
        "phone": "(09) 892 6347",
        "hours": "Mon - Sun: 7am - 8pm",
        "is_active": True,
    },
    {
        "name": "Farro Orakei Bay Village",
        "slug": "farro-orakei-bay-village",
        "store_id": "stores-p_default_store_ti_1gjtem7",
        "address": "228 Orakei Road, Remuera, Auckland, NZ",
        "suburb": "Remuera",
        "city": "Auckland",
        "phone": "(09) 892 6393",
        "hours": "Mon - Sun: 7am - 7pm",
        "is_active": True,
    },
]

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    cleaned = _SLUG_CLEAN.sub("-", (text or "").lower()).strip("-")
    return cleaned or "unknown"


def get_known_branches() -> list[dict[str, Any]]:
    """Return all known authentic Farro Fresh stores."""
    return list(KNOWN_FARRO_STORES)


def resolve_branch(query: str, db_url: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Resolve a Farro Fresh branch by slug or partial name."""
    db_url = db_url or DATABASE_URL
    target = slugify(query)

    # 1. Attempt PostgreSQL resolution if DATABASE_URL is available
    if db_url:
        try:
            import psycopg
            with psycopg.connect(db_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT b.id, b.slug, b.name, b.is_active
                        FROM catalog.branches b
                        JOIN catalog.retailers r ON r.id = b.retailer_id
                        WHERE r.slug = %s AND (b.slug = %s OR b.slug = %s)
                        LIMIT 1
                        """,
                        (RETAILER_SLUG, target, f"farro-{target}"),
                    )
                    row = cur.fetchone()
                    if row:
                        b_id, b_slug, b_name, b_active = row
                        # Merge with known info
                        match = next((s for s in KNOWN_FARRO_STORES if s["slug"] == b_slug or slugify(s["name"]) == target), {})
                        return {
                            "id": str(b_id),
                            "name": b_name,
                            "slug": b_slug,
                            "is_active": b_active,
                            "store_id": match.get("store_id"),
                            "address": match.get("address"),
                            "phone": match.get("phone"),
                            "hours": match.get("hours"),
                        }
        except Exception as exc:
            logger.debug("Database branch lookup fallback to offline registry: %s", exc)

    # 2. Offline fallback registry matching
    for store in KNOWN_FARRO_STORES:
        if store["slug"] == target or store["slug"] == f"farro-{target}":
            return dict(store)
        if target in store["slug"] or target in slugify(store["name"]):
            return dict(store)

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Farro Fresh branch resolution helper")
    parser.add_argument("--list", action="store_true", help="List all known Farro branches")
    parser.add_argument("--resolve", help="Resolve a branch by slug or name")
    args = parser.parse_args()

    if args.list:
        print(f"Total Known Farro Fresh Branches: {len(KNOWN_FARRO_STORES)}")
        for s in KNOWN_FARRO_STORES:
            print(f"  • {s['slug']:26} : {s['name']} ({s['address']})")
        return 0

    if args.resolve:
        branch = resolve_branch(args.resolve)
        if branch:
            print(f"Resolved branch: {branch['name']} [{branch['slug']}]")
            for k, v in branch.items():
                print(f"  {k}: {v}")
            return 0
        else:
            print(f"Branch not found for query: {args.resolve}")
            return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
