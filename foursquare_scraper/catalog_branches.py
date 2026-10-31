"""Branch resolution for Four Square Supermarkets against PICO catalog schema.

This module is strictly READ-ONLY: it resolves *which* store to scrape (id,
name, slug, and external store id). It never writes — the importer owns all catalog writes.

Tables:
  catalog.retailers(id, slug, name)
  catalog.branches(id, retailer_id, slug, name, is_active, ...)
  catalog.external_store_ids(branch_id, source_name, external_id)

The external store id pinned to:
  foursquare -> 'foodstuffs_api_store_id' (POSTed or cookie brands_store_id)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional

from config import BRANCHES_PATH, DEFAULT_STORE_NAME, DEFAULT_STORE_ID, DEFAULT_STORE_GUID

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parent / ".env"

# PICO external store id column key
STORE_ID_SOURCE = {
    "foursquare": "foodstuffs_api_store_id",
    "four-square": "foodstuffs_api_store_id",
}


def load_offline_branches() -> list[dict[str, Any]]:
    """Load authoritative 210-branch registry from branches.json."""
    if BRANCHES_PATH.exists():
        try:
            return json.loads(BRANCHES_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[catalog] Failed to load {BRANCHES_PATH.name}: {e}")
    return []


def _dsn() -> Optional[str]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn and _ENV_PATH.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_ENV_PATH)
            dsn = os.environ.get("DATABASE_URL")
        except Exception:
            pass
    return dsn


def _connect():
    """Short-lived connection to PostgreSQL pooler."""
    dsn = _dsn()
    if not dsn:
        return None
    try:
        import psycopg
        return psycopg.connect(dsn, connect_timeout=15)
    except ImportError:
        try:
            import psycopg2
            return psycopg2.connect(dsn, connect_timeout=15)
        except ImportError:
            return None
    except Exception as e:
        logger.warning(f"[catalog] Postgres connection error ({e})")
        return None


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


_BASE_SELECT = """
    select b.id::text          as id,
           b.name              as name,
           b.slug              as slug,
           b.retailer_id::text as retailer_id,
           b.is_active         as is_active,
           (select e.external_id from catalog.external_store_ids e
             where e.branch_id = b.id and e.source_name = %s
             limit 1)          as api_store_id
      from catalog.branches b
      join catalog.retailers r on r.id = b.retailer_id
     where r.slug = %s
"""


def list_branches(retailer_slug: str = "foursquare", *, active_only: bool = True,
                  require_store_id: bool = False) -> list[dict]:
    """Resolve all branches for Four Square.
    Primary Source: Reads live catalog.branches table over DATABASE_URL.
    Fallback: Uses verified store registry from branches.json.
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

    # Fallback to authentic branches.json registry
    offline = load_offline_branches()
    res = []
    for b in offline:
        api_id = b.get("api_store_id")
        guid = b.get("store_id_guid") or ("{" + api_id.upper() + "}" if api_id else None)
        res.append({
            "id": None,  # Resolved from catalog.branches on live DB import
            "name": b["name"],
            "slug": b["slug"],
            "retailer_id": None,
            "is_active": True,
            "api_store_id": api_id,
            "store_id_guid": guid,
            "url": b.get("url"),
        })
    if require_store_id:
        res = [b for b in res if b.get("api_store_id")]
    return sorted(res, key=lambda x: x["name"])


def get_branch(retailer_slug: str = "foursquare", *, branch_id: Optional[str] = None,
               name: Optional[str] = None, slug: Optional[str] = None) -> Optional[dict]:
    """Resolve ONE branch by id (preferred), name, or slug."""
    source = STORE_ID_SOURCE.get(retailer_slug, "foodstuffs_api_store_id")
    conn = _connect()
    if conn:
        try:
            if branch_id:
                sql = _BASE_SELECT + " and b.id::text = %s"
                params = (source, retailer_slug, branch_id)
            elif slug:
                sql = _BASE_SELECT + " and b.slug = lower(%s)"
                params = (source, retailer_slug, slug)
            elif name:
                sql = _BASE_SELECT + " and (lower(b.name) = lower(%s) or b.slug = lower(%s))"
                clean_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                params = (source, retailer_slug, name, clean_slug)
            else:
                return None
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning(f"[catalog] Query branch failed: {e}")
        finally:
            conn.close()

    # Fallback registry resolution
    candidates = list_branches(retailer_slug, active_only=False)
    target = (name or slug or "").strip().lower()
    target_clean = re.sub(r"[^a-z0-9]+", "-", target).strip("-")

    for b in candidates:
        b_name = b.get("name", "").lower()
        b_slug = b.get("slug", "").lower()
        if b_name == target or b_slug == target or b_slug == target_clean:
            return b

    # Partial substring match
    for b in candidates:
        b_name = b.get("name", "").lower()
        b_slug = b.get("slug", "").lower()
        if target in b_name or target_clean in b_slug:
            return b

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test and inspect Four Square branch resolution")
    parser.add_argument("--retailer", default="foursquare", help="Retailer slug (foursquare, four-square)")
    parser.add_argument("--search", help="Search branch by name or slug")
    args = parser.parse_args()

    dsn_status = "CONFIGURED" if _dsn() else "NOT SET (using verified store registry)"
    print(f"DATABASE_URL Status : {dsn_status}")

    if args.search:
        b = get_branch(args.retailer, name=args.search)
        print(f"Search result for '{args.search}':\n{b}")
    else:
        branches = list_branches(args.retailer, active_only=True)
        print(f"Resolved {len(branches)} authentic {args.retailer} branches:")
        for b in branches[:10]:
            print(f"  {b['name']:<30} slug={b['slug']:<25} store_id={b['api_store_id']}")
