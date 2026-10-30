"""Normalization functions for prices, units, and identity keys."""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Optional

from models import Product

PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
WAS_RE = re.compile(r"was\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
SAVE_CENTS_RE = re.compile(r"save\s*(\d+)\s*c\b", re.I)
SAVE_DOLLARS_RE = re.compile(r"save\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
UNIT_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:/|per)\s*(100g|100ml|kg|l|ea)\b", re.I)


def clean(s: object | None) -> str | None:
    if s is None:
        return None
    text = " ".join(re.sub(r"[\u200b-\u200d\ufeff]", "", str(s)).split())
    return text or None


def unit_price_from_text(text: str) -> Optional[Decimal]:
    """Extract unit comparison price (e.g. '$1.12 per 100g' -> Decimal('1.12'))."""
    if not text:
        return None
    m = UNIT_PRICE_RE.search(text)
    if m:
        return Decimal(m.group(1))
    return None


def prices(text: str) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal], Optional[str], Optional[str]]:
    """Parse text into (price, prev_price, savings, pricing_unit, unit_price_basis)."""
    if not text:
        return None, None, None, None, None

    # Savings
    savings = None
    sc_m = SAVE_CENTS_RE.search(text)
    if sc_m:
        savings = Decimal(sc_m.group(1)) / Decimal(100)
    else:
        sd_m = SAVE_DOLLARS_RE.search(text)
        if sd_m:
            savings = Decimal(sd_m.group(1))

    # Was price
    prev_price = None
    was_m = WAS_RE.search(text)
    if was_m:
        prev_price = Decimal(was_m.group(1))

    all_prices = [Decimal(p) for p in PRICE_RE.findall(text)]

    # Unit price & basis
    unit_price = None
    unit_basis = None
    # Only treat as unit price comparison if there are multiple prices or 'per 100g' / 'per 100ml'
    up_m = UNIT_PRICE_RE.search(text)
    if up_m and (len(all_prices) > 1 or up_m.group(2).lower() in ("100g", "100ml")):
        unit_price = Decimal(up_m.group(1))
        unit_basis = f"per {up_m.group(2).strip()}"

    # Selling price: find candidate that is not was_price and not unit_price
    price = None
    candidates = [p for p in all_prices if p != prev_price and p != unit_price]
    if candidates:
        price = candidates[0]
    elif all_prices:
        price = all_prices[0]

    # Calculate savings if was price and price exist
    if savings is None and prev_price and price and prev_price > price:
        savings = prev_price - price

    # Pricing unit
    pricing_unit = None
    if "per kg" in text.lower():
        pricing_unit = "per kg"
    elif "each" in text.lower():
        pricing_unit = "each"

    return price, prev_price, savings, pricing_unit, unit_basis


def identity(branch_id: str, name: str, product_id: Optional[str], product_url: Optional[str]) -> tuple[str, str]:
    """Resolve canonical product_key and identity_quality level."""
    if product_id:
        return f"id:{branch_id}:{product_id}", "source_id"
    elif product_url:
        path = product_url.split(".freshchoice.co.nz")[-1]
        return f"url:{path}", "url"
    else:
        clean = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").lower()).strip("_")
        return f"name:{clean}", "name_fallback"


def merge_product(target: Product, source: Product) -> None:
    """Merge source product information into target product in-place."""
    for cp in source.category_paths:
        if cp not in target.category_paths:
            target.category_paths.append(cp)
    if not target.image_url and source.image_url:
        target.image_url = source.image_url
    if not target.brand and source.brand:
        target.brand = source.brand
    if not target.description and source.description:
        target.description = source.description
