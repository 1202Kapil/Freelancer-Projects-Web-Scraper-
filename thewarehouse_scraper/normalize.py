"""Normalization and parsing utilities for The Warehouse NZ product data."""
from __future__ import annotations

import re
from typing import Any, Optional

VALID_GTIN_LENGTHS = {8, 12, 13, 14}

_SIZE_PATTERNS = [
    re.compile(r"\b(\d+\s*x\s*\d+(?:\.\d+)?\s*(?:kg|g|l|ml|ea|pk|pack|cans|bottles))\b", re.IGNORECASE),
    re.compile(r"\b(\d+(?:\.\d+)?\s*(?:kg|g|l|ml|cl|ltr|litre|litres|m|cm|mm|pk|pack|pcs|piece|pieces|capsules|tablets|bags|slices|ea|can|sheet|sheets))\b", re.IGNORECASE),
    re.compile(r"\b(\d+\s*pack)\b", re.IGNORECASE),
]

_MULTIBUY_BADGE_RE = re.compile(r"badge_(\d+)_for_([\d\.]+)", re.IGNORECASE)
_CLEAN_SPACES_RE = re.compile(r"\s+")
_NON_WORD_EDGES = re.compile(r"^[\s\-_,.:;()&/]+|[\s\-_,.:;()&/]+$")

# Known Demandware category tokens to pretty display names
CATEGORY_TOKEN_NAMES = {
    "foodhouseholdpets": "Food, Pets & Household",
    "fooddrink": "Food & Drink",
    "colddrinks": "Cold Drinks",
    "sportsenergydrinks": "Sports & Energy Drinks",
    "sweetslollies": "Sweets & Lollies",
    "baggedlollies": "Bagged Lollies",
    "chipssnacks": "Chips & Snacks",
    "healthbeauty": "Health & Beauty",
    "homegarden": "Home, Garden & Appliances",
    "electronicsgaming": "Electronics & Gaming",
    "clothingshoesaccessories": "Clothing, Shoes & Accessories",
    "toysbaby": "Toys & Baby",
    "stationerycraftparty": "Craft, Party & Stationery",
    "sportsoutdoors": "Sports & Outdoors",
    "autodiy": "Auto & DIY",
    "specials": "Specials",
    "clearance": "Clearance",
}


def is_valid_gtin_checksum(barcode: Any) -> bool:
    """Verify official GS1 modulo-10 check digit for GTIN-8, 12, 13, 14."""
    if not barcode:
        return False
    s = str(barcode).strip()
    if not (s.isdigit() and len(s) in VALID_GTIN_LENGTHS):
        return False
    digits = [int(c) for c in s]
    payload, check_digit = digits[:-1], digits[-1]
    # Multiply alternately by 3 and 1 from the rightmost payload digit
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    calc_check = (10 - (total % 10)) % 10
    return calc_check == check_digit


def clean_barcode(barcode: Any) -> Optional[str]:
    """Validate and clean GTIN barcode. Returns valid GTIN string or None."""
    if not barcode:
        return None
    s = str(barcode).strip()
    if s.isdigit() and len(s) in VALID_GTIN_LENGTHS and is_valid_gtin_checksum(s):
        return s
    return None


def extract_size(raw_name: str) -> Optional[str]:
    """Extract product volume, weight, dimension, or pack size from name."""
    if not raw_name:
        return None
    for pat in _SIZE_PATTERNS:
        m = pat.search(raw_name)
        if m:
            return m.group(1).strip()
    return None


def clean_product_name(raw_name: str, brand: Optional[str] = None, size: Optional[str] = None) -> str:
    """Produce clean normalized product name."""
    if not raw_name:
        return ""
    name = raw_name
    # Strip leading brand if present and followed by rest of name
    if brand and name.lower().startswith(brand.lower() + " "):
        name = name[len(brand) + 1:].strip()
    # Collapse extra whitespace
    name = _CLEAN_SPACES_RE.sub(" ", name).strip()
    return name or raw_name


def format_category_path(raw_cgid: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """Convert Demandware hyphenated or slashed category strings into clean breadcrumb path.
    Example: 'foodhouseholdpets/foodhouseholdpets-fooddrink/foodhouseholdpets-fooddrink-pantry'
    -> 'Food, Pets & Household > Food & Drink > Pantry'
    """
    if not raw_cgid:
        return fallback

    # If already formatted with ' > '
    if " > " in raw_cgid:
        return raw_cgid

    # If it contains slashes (Demandware full category level hierarchy)
    if "/" in raw_cgid:
        levels = [p.strip() for p in raw_cgid.split("/") if p.strip()]
        unique_tokens = []
        for lvl in levels:
            parts = lvl.split("-")
            token = parts[-1]
            if token and token not in unique_tokens:
                unique_tokens.append(token)
        cleaned = [CATEGORY_TOKEN_NAMES.get(t.lower(), t.replace("-", " ").title()) for t in unique_tokens]
        return " > ".join(cleaned) if cleaned else fallback

    # If it is hyphenated compound cgid (e.g. foodhouseholdpets-fooddrink-colddrinks-sportsenergydrinks)
    parts = [p.strip() for p in raw_cgid.split("-") if p.strip()]
    if parts:
        cleaned_parts = []
        for part in parts:
            pretty = CATEGORY_TOKEN_NAMES.get(part.lower())
            if not pretty:
                s = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).strip()
                pretty = s.replace("-", " ").title()
            if pretty not in cleaned_parts:
                cleaned_parts.append(pretty)
        return " > ".join(cleaned_parts)

    return fallback


def parse_promotions(
    price_cents: Optional[int],
    then_price_cents: Optional[int],
    badges: Optional[str],
    claim: Optional[str],
    promo_msg: Optional[str] = None,
) -> dict[str, Any]:
    """Classify promotions, specials, multibuys, and member pricing.
    Zero orphan promo metadata on regular shelf pricing.
    """
    out: dict[str, Any] = {
        "promo_text": None,
        "promo_type": None,
        "card_required": None,
        "required_loyalty_program_code": None,
        "comparison_price_cents": None,
        "multibuy_quantity": None,
        "multibuy_price_cents": None,
        "promo_metadata": None,
    }

    badges_str = (badges or "").lower()
    promo_msg_str = (promo_msg or "").strip()
    claim_str = (claim or "").strip()

    # 1. Multibuy (e.g. badge_2_for_6.00)
    m = _MULTIBUY_BADGE_RE.search(badges_str)
    if m:
        qty = int(m.group(1))
        mb_price = int(round(float(m.group(2)) * 100))
        out["promo_type"] = "multibuy_fixed_price"
        out["multibuy_quantity"] = qty
        out["multibuy_price_cents"] = mb_price
        out["promo_text"] = f"{qty} for ${float(m.group(2)):.2f}"
        out["promo_metadata"] = {
            "badge": badges,
            "multibuy_quantity": qty,
            "multibuy_price_cents": mb_price,
        }
        return out

    # 2. MarketClub Member Price
    if "marketclub" in badges_str or "marketclub" in claim_str.lower() or "member" in badges_str:
        out["promo_type"] = "member_price"
        out["card_required"] = True
        out["required_loyalty_program_code"] = "marketclub"
        out["promo_text"] = claim_str or "MarketClub Member Price"
        if then_price_cents and price_cents and then_price_cents > price_cents:
            out["comparison_price_cents"] = then_price_cents
        out["promo_metadata"] = {"badge": badges, "program": "marketclub"}
        return out

    # 3. Clearance
    if "clearance" in badges_str or "clearance" in claim_str.lower():
        out["promo_type"] = "clearance"
        out["promo_text"] = claim_str or "Clearance"
        if then_price_cents and price_cents and then_price_cents > price_cents:
            out["comparison_price_cents"] = then_price_cents
        out["promo_metadata"] = {"badge": badges}
        return out

    # 4. Standard Special / Discount
    is_special = (
        "specials" in badges_str
        or "special" in badges_str
        or (then_price_cents and price_cents and then_price_cents > price_cents)
        or bool(claim_str)
    )

    if is_special:
        out["promo_type"] = "special"
        out["promo_text"] = claim_str or "Special"
        if then_price_cents and price_cents and then_price_cents > price_cents:
            out["comparison_price_cents"] = then_price_cents
        elif claim_str:
            # If claim has "Save $X.XX" but then_price wasn't in gtm, compute comparison price
            save_match = re.search(r"save\s*\$?([\d\.]+)", claim_str, re.IGNORECASE)
            if save_match and price_cents:
                save_cents = int(round(float(save_match.group(1)) * 100))
                out["comparison_price_cents"] = price_cents + save_cents

        meta = {}
        if badges and badges != "na":
            meta["badge"] = badges
        if promo_msg_str and promo_msg_str != "na":
            meta["message"] = promo_msg_str
        if meta:
            out["promo_metadata"] = meta
        return out

    return out
