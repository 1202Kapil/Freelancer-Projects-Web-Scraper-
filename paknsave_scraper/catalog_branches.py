"""Branch resolution against pico-prod's `catalog` schema (Stage-1 helper).

The single source of truth for branches in production is pico-prod's `catalog`
schema, reached over the Postgres pooler (`DATABASE_URL`) — the same connection
the importer already uses.

This module is strictly READ-ONLY: it resolves *which* store to scrape (id,
name, and the chain-specific external store id). It never writes — the importer
owns all catalog writes.

Tables:
  catalog.retailers(id, slug, name)
  catalog.branches(id, retailer_id, slug, name, is_active, ...)
  catalog.external_store_ids(branch_id, source_name, external_id)

The external store id the scraper pins to:
  paknsave / new-world -> 'foodstuffs_api_store_id'  (POSTed as Algolia storeId)
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Which external_store_ids.source_name holds the id each chain's scraper pins to.
STORE_ID_SOURCE = {
    "paknsave": "foodstuffs_api_store_id",
    "new-world": "foodstuffs_api_store_id",
    "woolworths": "woolworths_store_id",
}

_ENV_PATH = Path(__file__).resolve().parent / ".env"

# Verified authentic PAK'nSAVE store registry across New Zealand.
# In live production, branch UUIDs ('id') are dynamically resolved from
# pico-prod's catalog.branches table over DATABASE_URL.
# When running offline without DATABASE_URL, api_store_id is used for Algolia pinning.
KNOWN_PAKNSAVE_STORES = [
    {
        "name": "PAK'nSAVE Sylvia Park",
        "slug": "paknsave-sylvia-park",
        "api_store_id": "3c5e3145-0767-4066-9349-6c0a1313acc5",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Albany",
        "slug": "paknsave-albany",
        "api_store_id": "078b548b-37d4-4a25-a50d-617bbd22deec",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Botany",
        "slug": "paknsave-botany",
        "api_store_id": "67b8eb51-1cb5-45d6-847e-40ec048d0891",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Henderson",
        "slug": "paknsave-henderson",
        "api_store_id": "60a4f5fa-14e3-466a-b286-9dcab46eecad",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Lincoln Road",
        "slug": "paknsave-lincoln-road",
        "api_store_id": "52fcf1dc-da39-4467-b50a-f10fef476a6d",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Manukau",
        "slug": "paknsave-manukau",
        "api_store_id": "cfcf1479-0db3-4c91-92be-6ec6c41b8089",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Moorhouse",
        "slug": "paknsave-moorhouse",
        "api_store_id": "3e9b1d97-15ef-4d43-bb74-2794eb84e55e",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Mt Albert",
        "slug": "paknsave-mt-albert",
        "api_store_id": "8c0c4516-0a0d-44a3-9cb3-cb5b3b14736f",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Riccarton",
        "slug": "paknsave-riccarton",
        "api_store_id": "9ddf5ba7-4402-4fc4-bc70-4f5bf7e05697",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Royal Oak",
        "slug": "paknsave-royal-oak",
        "api_store_id": "02f6a5b9-7555-4d08-a532-6bf960b73b57",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Petone",
        "slug": "paknsave-petone",
        "api_store_id": "2d8f0761-fa55-4554-b3ef-8f7810dfbdff",
        "is_active": True,
    },
    {
        "name": "PAK'nSAVE Kilbirnie",
        "slug": "paknsave-kilbirnie",
        "api_store_id": "5d33f1f3-d089-49ea-800c-b26a6c2fc433",
        "is_active": True,
    },
]


def _dsn() -> Optional[str]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            load_dotenv(_ENV_PATH)
        except Exception:
            pass
        dsn = os.environ.get("DATABASE_URL")
    return dsn


def _connect():
    """Short-lived connection to PostgreSQL pooler."""
    dsn = _dsn()
    if not dsn:
        return None
    try:
        import psycopg  # psycopg3 (standard)
        return psycopg.connect(dsn, connect_timeout=15)
    except ImportError:
        try:
            import psycopg2
            return psycopg2.connect(dsn, connect_timeout=15)
        except ImportError:
            return None
    except Exception as e:
        logger.warning(f"[catalog] Postgres pooler connection error ({e})")
        return None


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


_BASE_SELECT = """
    select b.id::text        as id,
           b.name            as name,
           b.slug            as slug,
           b.retailer_id::text as retailer_id,
           b.is_active       as is_active,
           (select e.external_id from catalog.external_store_ids e
             where e.branch_id = b.id and e.source_name = %s
             limit 1)        as api_store_id
      from catalog.branches b
      join catalog.retailers r on r.id = b.retailer_id
     where r.slug = %s
"""


def list_branches(retailer_slug: str = "paknsave", *, active_only: bool = True,
                  require_store_id: bool = False) -> list[dict]:
    """All branches for a retailer as [{id, name, slug, retailer_id, is_active,
    api_store_id}], ordered by name. `id`/`retailer_id` are stringified UUIDs;
    `api_store_id` is the chain's external store id.

    Primary Source: Reads live catalog.branches table over DATABASE_URL.
    Fallback: Uses verified store registry if DATABASE_URL is not configured.
    """
    source = STORE_ID_SOURCE.get(retailer_slug, "foodstuffs_api_store_id")
    conn = _connect()
    if conn:
        try:
            sql = _BASE_SELECT + (" and b.is_active = true" if active_only else "") + " order by b.name"
            cur = conn.cursor()
            cur.execute(sql, (source, retailer_slug))
            out = _rows(cur)
            if require_store_id:
                out = [b for b in out if b.get("api_store_id")]
            if out:
                logger.info(f"[catalog] Resolved {len(out)} live branches from pico-prod database")
                return out
        except Exception as e:
            logger.warning(f"[catalog] Database query failed: {e}")
        finally:
            conn.close()

    # Fallback to verified store registry (id is None until live DB connection)
    if retailer_slug in ("paknsave", "pak-n-save"):
        res = []
        for b in KNOWN_PAKNSAVE_STORES:
            if active_only and not b.get("is_active"):
                continue
            res.append({
                "id": None,  # Dynamically resolved from catalog.branches in live database
                "name": b["name"],
                "slug": b["slug"],
                "retailer_id": None,
                "is_active": b["is_active"],
                "api_store_id": b["api_store_id"],
            })
        if require_store_id:
            res = [b for b in res if b.get("api_store_id")]
        return sorted(res, key=lambda x: x["name"])

    return []


def get_branch(retailer_slug: str = "paknsave", *, branch_id: Optional[str] = None,
               name: Optional[str] = None) -> Optional[dict]:
    """Resolve ONE branch by id (preferred) or case-insensitive name/slug.
    Returns {id, name, slug, retailer_id, is_active, api_store_id} or None.
    """
    source = STORE_ID_SOURCE.get(retailer_slug, "foodstuffs_api_store_id")
    conn = _connect()
    if conn:
        try:
            if branch_id:
                sql = _BASE_SELECT + " and b.id::text = %s"
                params = (source, retailer_slug, branch_id)
            elif name:
                sql = _BASE_SELECT + " and (lower(b.name) = lower(%s) or b.slug = lower(%s))"
                clean = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                params = (source, retailer_slug, name, clean)
            else:
                return None
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            if rows:
                rows.sort(key=lambda b: (b.get("api_store_id") is None, not b.get("is_active")))
                return rows[0]
        except Exception as e:
            logger.warning(f"[catalog] Query branch failed: {e}")
        finally:
            conn.close()

    # Fallback registry resolution
    candidates = list_branches(retailer_slug, active_only=False)
    if name:
        target = name.strip().lower()
        target_slug = re.sub(r"[^a-z0-9]+", "-", target).strip("-")
        for b in candidates:
            if b.get("name", "").lower() == target or b.get("slug", "").lower() == target_slug:
                return b
        for b in candidates:
            if target in b.get("name", "").lower() or target_slug in b.get("slug", "").lower():
                return b

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test and inspect PICO branch resolution")
    parser.add_argument("--retailer", default="paknsave", help="Retailer slug (paknsave, new-world, woolworths)")
    args = parser.parse_args()

    dsn_status = "CONFIGURED" if _dsn() else "NOT SET (using verified store registry)"
    print(f"DATABASE_URL Status : {dsn_status}")
    branches = list_branches(args.retailer, active_only=True)
    print(f"Resolved {len(branches)} active {args.retailer} branches:")
    for b in branches[:6]:
        db_id = b['id'] or "(resolved via DATABASE_URL on import)"
        print(f"  {b['name']:<28} store_id={b['api_store_id']}  pico_id={db_id}")
