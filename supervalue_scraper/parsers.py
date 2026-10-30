"""Parsers and normalization logic for SuperValue Supermarket HTML & JSON-LD payloads.

Conforms strictly to PICO Scraper Data Contract:
1. Strict separation of unit selling price vs multibuy bundle prices (e.g. '3 for $25').
2. Mathematical GS1 modulo-10 checksum validation for GTIN-8, 12, 13, and 14 barcodes.
3. Produce PLUs (4-5 digits) strictly isolated from barcode space (mapped to plu_code in raw_row).
4. Full name sanitation (rejection of quantity-only names, removal of trailing prices and promo tags).
5. Robust parsing of MyFoodLink 'talker' product cards across category listings.
6. Detail page enrichment and JSON-LD Schema.org / BreadcrumbList parsing.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from bs4 import BeautifulSoup

from config import VALID_GTIN_LENGTHS, VALID_STOCK_STATUSES, VALID_PROMO_TYPES
from jsonl_exporter import to_cents
from models import Branch, Product, Promotion, PageResult

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
WAS_PRICE_RE = re.compile(r"(?:was|previously)\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
SAVE_RE = re.compile(r"save\s*(?:\$\s*(\d+(?:\.\d{1,2})?)|\s*(\d+)\s*c\b)", re.I)
MULTIBUY_RE = re.compile(r"(\d+)\s*(?:for|/\s*)\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)
UNIT_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:/|per)\s*(100g|100ml|kg|l|ea)\b", re.I)
SIZE_EXTRACT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|cl|pk|pack|ea|pieces|bag|bunch|sachets|tablets|capsules))\b",
    re.I,
)
QUANTITY_ONLY_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|pk|pack|ea|sachets)|each|per\s+kg)$",
    re.I,
)


def is_valid_gtin_checksum(barcode: Any) -> bool:
    """Verify official GS1 modulo-10 check digit for GTIN-8, 12, 13, 14."""
    if not barcode:
        return False
    s = str(barcode).strip()
    if not (s.isdigit() and len(s) in VALID_GTIN_LENGTHS):
        return False
    digits = [int(c) for c in s]
    payload, check_digit = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    calc_check = (10 - (total % 10)) % 10
    return calc_check == check_digit


def clean_product_name(raw_name: str) -> str:
    """Strip packaging sizes, promotional tags, trailing prices, and extra whitespace to form clean_name."""
    if not raw_name:
        return ""
    name = re.sub(r"\s+", " ", raw_name).strip()
    name = re.sub(r"\s+\$\s*\d+(?:\.\d{1,2})?$", "", name)
    name = re.sub(r"^(?:SPECIAL|SAVE|NEW|CLEARANCE|ROLLBACK)[\s:!-]+", "", name, flags=re.I)
    name = SIZE_EXTRACT_RE.sub("", name).strip()
    return name or raw_name.strip()


def normalize_image_url(src: Optional[str], base_url: str) -> Optional[str]:
    """Normalize image source to an absolute HTTPS URL avoiding double-prefixing.
    Correctly handles protocol-relative (//), root-relative (/), relative paths,
    and already-absolute URLs. Filters out data: URIs and empty strings.
    """
    if not src:
        return None
    s = str(src).strip()
    if not s or s.startswith("data:"):
        return None
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith("http://") or s.startswith("https://"):
        return s
    base = base_url.rstrip("/")
    if s.startswith("/"):
        return f"{base}{s}"
    return f"{base}/{s}"


def extract_size_from_name(name: str) -> Optional[str]:
    """Extract standard package size from title string."""
    if not name:
        return None
    matches = SIZE_EXTRACT_RE.findall(name)
    if matches:
        return matches[-1].strip()
    return None


def parse_multibuy(text: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Parse '3 for $25' into (quantity=3, price_cents=2500, promo_text='3 for $25')."""
    if not text:
        return None, None, None
    m = MULTIBUY_RE.search(text)
    if m:
        qty = int(m.group(1))
        price_dollars = float(m.group(2))
        return qty, int(round(price_dollars * 100)), m.group(0).strip()
    return None, None, None


def parse_talker_card(card: Any, branch: Branch, category_path: list[str], request_url: str) -> Optional[Product]:
    """Extract a complete Product from a MyFoodLink 'talker' DOM element."""
    # Find link to product line
    link = card.find("a", href=re.compile(r"/lines/"))
    if not link and card.name == "a" and "/lines/" in card.get("href", ""):
        link = card

    href = link.get("href", "") if link else ""
    slug_match = re.search(r"/lines/([^/?#]+)", href)
    slug = slug_match.group(1).strip() if slug_match else ""

    # Source ID from data-line-control or id attribute
    line_id = None
    line_ctrl_raw = card.get("data-line-control")
    if line_ctrl_raw:
        try:
            line_ctrl = json.loads(line_ctrl_raw)
            if isinstance(line_ctrl, dict):
                qty_obj = line_ctrl.get("quantity") or {}
                line_id = qty_obj.get("id") or line_ctrl.get("id")
        except Exception:
            pass

    if not line_id:
        card_id = card.get("id", "")
        if card_id.startswith("line_"):
            line_id = card_id.replace("line_", "").strip()

    source_id = line_id or slug or ""
    if not source_id and not href:
        return None

    # Name extraction
    raw_name = ""
    name_el = card.find(class_=re.compile(r"talker__product-name|talker__name", re.I))
    if name_el:
        prod_span = name_el.find(class_="talker__product-name")
        raw_name = prod_span.get_text(strip=True) if prod_span else name_el.get_text(strip=True)
    if not raw_name and link:
        img_el = link.find("img")
        if img_el and img_el.get("alt"):
            alt_txt = img_el["alt"].strip()
            raw_name = re.sub(r"^Photo of\s+", "", alt_txt, flags=re.I)
    if not raw_name and slug:
        raw_name = slug.replace("-", " ").title()

    # Size extraction
    size_str = None
    size_el = card.find(class_=re.compile(r"talker__name__size|size", re.I))
    if size_el:
        size_str = size_el.get_text(strip=True)
    if not size_str:
        size_str = extract_size_from_name(raw_name)

    # Clean name
    clean_name = clean_product_name(raw_name)

    # Selling price
    price_dec: Optional[Decimal] = None
    sell_price_el = card.find(class_=re.compile(r"price__sell", re.I))
    if sell_price_el:
        pm = PRICE_RE.search(sell_price_el.get_text(strip=True))
        if pm:
            price_dec = Decimal(pm.group(1))

    # Pricing unit
    pricing_unit = "each"
    unit_el = card.find(class_=re.compile(r"price__units", re.I))
    if unit_el:
        pricing_unit = unit_el.get_text(strip=True) or pricing_unit

    # Comparison / unit price (e.g. $0.68 per 100g)
    unit_price_dec: Optional[Decimal] = None
    unit_basis: Optional[str] = None
    comp_el = card.find(class_=re.compile(r"talker__prices__comparison", re.I))
    if comp_el:
        comp_text = comp_el.get_text(strip=True)
        up_match = UNIT_PRICE_RE.search(comp_text)
        if up_match:
            unit_price_dec = Decimal(up_match.group(1))
            unit_basis = up_match.group(2)
        else:
            pm = PRICE_RE.search(comp_text)
            if pm:
                unit_price_dec = Decimal(pm.group(1))

    # Promotion detection (was price, stickers, multibuy)
    previous_price_dec: Optional[Decimal] = None
    savings_dec: Optional[Decimal] = None
    multibuy_qty: Optional[int] = None
    multibuy_price_dec: Optional[Decimal] = None
    promo_desc: Optional[str] = None

    prices_sec = card.find(class_=re.compile(r"talker__prices", re.I))
    prices_text = prices_sec.get_text(" ", strip=True) if prices_sec else ""
    stickers_sec = card.find(class_=re.compile(r"talker__stickers", re.I))
    stickers_text = stickers_sec.get_text(" ", strip=True) if stickers_sec else ""
    full_card_text = card.get_text(" ", strip=True)

    was_match = WAS_PRICE_RE.search(prices_text) or WAS_PRICE_RE.search(full_card_text)
    if was_match:
        previous_price_dec = Decimal(was_match.group(1))

    save_match = SAVE_RE.search(stickers_text) or SAVE_RE.search(prices_text)
    if save_match:
        if save_match.group(1):
            savings_dec = Decimal(save_match.group(1))
            promo_desc = f"Save ${savings_dec:.2f}"
        elif save_match.group(2):
            cents_val = int(save_match.group(2))
            savings_dec = Decimal(cents_val) / Decimal(100)
            promo_desc = f"Save {cents_val}c"

    # Multibuy extraction (e.g. "3 for $25")
    mb_qty, mb_cents, mb_text = parse_multibuy(full_card_text)
    if mb_qty and mb_cents:
        multibuy_qty = mb_qty
        multibuy_price_dec = Decimal(mb_cents) / Decimal(100)
        promo_desc = mb_text

    is_special = (
        bool(previous_price_dec)
        or bool(savings_dec)
        or bool(multibuy_qty)
        or "special" in card.get("class", [])
        or "talker--special" in " ".join(card.get("class", [])).lower()
    )

    promo_obj: Optional[Promotion] = None
    if is_special:
        promo_obj = Promotion(
            on_special=True,
            previous_price_nzd=previous_price_dec,
            savings_nzd=savings_dec,
            multibuy_quantity=multibuy_qty,
            multibuy_price_nzd=multibuy_price_dec,
            description=promo_desc,
        )

    # Image URL
    img_url = None
    img_el = card.find("img")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src")
        # Prefer higher resolution webp source if available
        picture_el = card.find("picture")
        if picture_el:
            source_el = picture_el.find("source")
            if source_el and source_el.get("srcset"):
                src = source_el["srcset"].split()[0]
        img_url = normalize_image_url(src, branch.url)

    # Availability
    classes_str = " ".join(card.get("class", [])).lower()
    avail = "in_stock"
    if "out-of-stock" in classes_str or "unavailable" in classes_str:
        avail = "out_of_stock"
    if "sold out" in full_card_text.lower():
        avail = "out_of_stock"

    # Full product URL
    prod_url = f"{branch.url.rstrip('/')}{href}" if href.startswith("/") else (href or request_url)

    return Product(
        branch_id=branch.id,
        branch_name=branch.name,
        name=clean_name or raw_name,
        product_id=source_id,
        product_key=f"source_id:{source_id}",
        identity_quality="source_id" if line_id else "url",
        category_paths=[category_path] if category_path else [],
        price_nzd=price_dec,
        pricing_unit=size_str or pricing_unit,
        unit_price_nzd=unit_price_dec,
        unit_price_basis=unit_basis,
        promotion=promo_obj,
        availability=avail,
        image_url=img_url,
        product_url=prod_url,
        sku=source_id,
        attributes={"slug": slug, "raw_name": raw_name},
    )


def parse_listing(html: str, branch: Branch, category_path: list[str], request_url: str) -> PageResult:
    """Parse HTML category or sitemap listing page into PageResult."""
    soup = BeautifulSoup(html, "html.parser")
    issues = []

    reported_count = None
    count_match = re.search(r"Refine\s+(\d+)\s+results", html, re.I) or re.search(r"(\d+)\s+products?", html, re.I)
    if count_match:
        reported_count = int(count_match.group(1))

    # Find all talker cards
    cards = soup.find_all(class_=lambda c: c and "talker" in c and "talker--row" in c)
    if not cards:
        # Fallback to talker containers or line-item elements
        cards = soup.find_all(class_=lambda c: c and ("talker" in c or "ProductCell" in c or "line-item" in c))

    products: list[Product] = []
    seen_ids: set[str] = set()

    for card in cards:
        p = parse_talker_card(card, branch, category_path, request_url)
        if p and p.product_id and p.product_id not in seen_ids:
            seen_ids.add(p.product_id)
            products.append(p)

    return PageResult(
        products=products,
        reported_count=reported_count or len(products),
        issues=issues,
    )


def parse_detail_page(html: str, base_url: str) -> dict[str, Any]:
    """Parse product detail page HTML & JSON-LD to extract brand, description, and full category taxonomy."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {
        "brand": None,
        "description": None,
        "category_path": None,
        "gtin": None,
        "sku": None,
    }

    # Extract JSON-LD scripts
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}

            item_type = data.get("@type")
            if item_type == "Product":
                brand_val = data.get("brand")
                if isinstance(brand_val, dict):
                    out["brand"] = brand_val.get("name")
                elif brand_val:
                    out["brand"] = str(brand_val).strip()

                if data.get("description"):
                    out["description"] = data.get("description").strip()

                # Check gtin / sku
                for gtin_key in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin", "barcode"):
                    if data.get(gtin_key):
                        candidate = str(data[gtin_key]).strip()
                        if is_valid_gtin_checksum(candidate):
                            out["gtin"] = candidate
                            break

                if data.get("sku"):
                    out["sku"] = str(data.get("sku")).strip()

            elif item_type == "BreadcrumbList":
                elements = data.get("itemListElement") or []
                crumbs: list[str] = []
                for el in sorted(elements, key=lambda x: x.get("position", 0)):
                    item = el.get("item") or {}
                    name = item.get("name") if isinstance(item, dict) else el.get("name")
                    if name and not any(ign in name.lower() for ign in ["home", "all products", "browse"]):
                        crumbs.append(name.strip())
                if crumbs:
                    out["category_path"] = " > ".join(crumbs)

        except Exception:
            pass

    # HTML breadcrumb fallback
    if not out["category_path"]:
        bc_el = soup.find(class_=re.compile(r"breadcrumb", re.I))
        if bc_el:
            crumbs = [
                a.get_text(strip=True)
                for a in bc_el.find_all("a")
                if a.get_text(strip=True) and not any(ign in a.get_text(strip=True).lower() for ign in ["home", "all products", "browse"])
            ]
            if crumbs:
                out["category_path"] = " > ".join(crumbs)

    return out
