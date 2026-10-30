"""Branch resolution for The Warehouse NZ against branches.json and PICO catalog schema."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional

from config import (
    BRANCHES_FILE,
    DATABASE_URL,
    DEFAULT_BRANCH_ID,
    DEFAULT_BRANCH_SLUG,
    RETAILER_NAME,
    RETAILER_SLUG,
)

logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: Optional[str]) -> str:
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    s = _SLUG_RE.sub("-", cleaned).strip("-")
    return s or "unknown"


def _make_branch_slug(name: str) -> str:
    cleaned = name.lower().replace("the warehouse", "").strip()
    s = _SLUG_RE.sub("-", cleaned).strip("-")
    return f"{RETAILER_SLUG}-{s}"


def load_local_branches() -> list[dict[str, Any]]:
    """Load authentic branches from local branches.json registry."""
    if not BRANCHES_FILE.exists():
        logger.warning(f"Branches file {BRANCHES_FILE} not found")
        return []

    try:
        raw_list = json.loads(BRANCHES_FILE.read_text(encoding="utf-8"))
        branches = []
        for b in raw_list:
            raw_id = str(b.get("ID") or b.get("id") or "").strip()
            raw_name = b.get("name") or b.get("storeName") or f"Store {raw_id}"
            full_name = f"The Warehouse {raw_name}" if not raw_name.lower().startswith("the warehouse") else raw_name
            slug = _make_branch_slug(raw_name)

            branches.append({
                "id": raw_id,
                "store_id": raw_id,
                "name": full_name,
                "branch_name": raw_name,
                "slug": slug,
                "city": b.get("city"),
                "state_code": b.get("stateCode"),
                "postal_code": b.get("postalCode"),
                "address": b.get("fullAddress") or b.get("address1"),
                "latitude": b.get("latitude"),
                "longitude": b.get("longitude"),
                "is_active": True,
            })
        return branches
    except Exception as e:
        logger.error(f"Failed to load branches from {BRANCHES_FILE}: {e}")
        return []


def resolve_branches_from_db() -> Optional[list[dict[str, Any]]]:
    """Attempt reading branch records from live Postgres catalog schema over DATABASE_URL."""
    if not DATABASE_URL:
        return None

    try:
        import psycopg
    except ImportError:
        try:
            import psycopg2 as psycopg
        except ImportError:
            return None

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.id, b.slug, b.name, e.external_id
                    FROM catalog.branches b
                    JOIN catalog.retailers r ON r.id = b.retailer_id
                    LEFT JOIN catalog.external_store_ids e ON e.branch_id = b.id
                    WHERE r.slug = %s AND b.is_active = true
                    ORDER BY b.name
                    """,
                    (RETAILER_SLUG,),
                )
                rows = cur.fetchall()
                if rows:
                    branches = []
                    for row in rows:
                        b_id, slug, name, ext_id = row[0], row[1], row[2], row[3]
                        branches.append({
                            "id": str(b_id),
                            "store_id": ext_id or str(b_id),
                            "name": name,
                            "slug": slug,
                            "is_active": True,
                        })
                    logger.info(f"[branches] Loaded {len(branches)} branches from DB catalog")
                    return branches
    except Exception as e:
        logger.warning(f"[branches] DB catalog lookup failed, using local registry: {e}")

    return None


def list_branches() -> list[dict[str, Any]]:
    """Return all verified branches, using DB if available, else local branches.json."""
    db_branches = resolve_branches_from_db()
    if db_branches:
        return db_branches
    return load_local_branches()


def get_branch(identifier: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Resolve a single branch by ID, slug, or name. Defaults to default branch."""
    branches = list_branches()
    if not branches:
        return None

    if not identifier:
        identifier = DEFAULT_BRANCH_ID

    ident_clean = str(identifier).strip().lower()

    # Match ID
    for b in branches:
        if str(b["store_id"]).strip().lower() == ident_clean or str(b["id"]).strip().lower() == ident_clean:
            return b

    # Match slug
    for b in branches:
        if b["slug"].lower() == ident_clean:
            return b

    # Match name substring
    for b in branches:
        if ident_clean in b["name"].lower() or ident_clean in b.get("branch_name", "").lower():
            return b

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="The Warehouse NZ branch catalog resolver.")
    parser.add_argument("--branch", help="Find specific branch by ID, slug, or name.")
    parser.add_argument("--count", action="store_true", help="Print total branch count.")
    args = parser.parse_args()

    branches = list_branches()
    if args.count:
        print(f"Total branches: {len(branches)}")
        return

    if args.branch:
        b = get_branch(args.branch)
        if b:
            print(json.dumps(b, indent=2))
        else:
            print(f"Branch '{args.branch}' not found.")
            exit(1)
        return

    print(f"Found {len(branches)} active branches for {RETAILER_NAME}:")
    for b in branches:
        print(f"  [{b['store_id']}] {b['name']} ({b['slug']}) - {b.get('city', '')}")


if __name__ == "__main__":
    main()
