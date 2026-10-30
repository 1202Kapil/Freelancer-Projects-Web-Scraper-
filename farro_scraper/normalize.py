"""Normalization and parsing utilities for Farro Fresh product data."""
from __future__ import annotations

import re
from typing import Any, Optional

VALID_GTIN_LENGTHS = {8, 12, 13, 14}

_BARCODE_RE = re.compile(r"/(\d{8,14})[_\.]")
_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:kg|g|l|ml|cl|ltr|litre|litres|m|pk|pack|pcs|piece|pieces|capsules|tablets|bags|slices|ea))\b",
    re.IGNORECASE,
)
_MULTI_PACK_RE = re.compile(r"\b(\d+\s*x\s*\d+(?:\.\d+)?\s*(?:kg|g|l|ml|ea|pk|pack))\b", re.IGNORECASE)
_CLEAN_SPACES_RE = re.compile(r"\s+")
_NON_WORD_EDGES = re.compile(r"^[\s\-_,.:;()&/]+|[\s\-_,.:;()&/]+$")

# Product descriptor words that should never be inferred as part of brand
NON_BRAND_WORDS = {
    "organic", "fresh", "premium", "free", "range", "gluten", "plant", "based",
    "pinot", "noir", "gris", "sauvignon", "blanc", "chardonnay", "syrah", "shiraz",
    "merlot", "cabernet", "rose", "rosé", "riesling", "sparkling", "prosecco", "champagne",
    "beer", "cider", "pale", "ale", "lager", "ipa", "pilsner",
    "milk", "cream", "butter", "cheese", "yogurt", "yoghurt", "curd",
    "beef", "chicken", "lamb", "pork", "sausage", "sausages", "bacon", "ham", "steak",
    "bread", "sourdough", "bagel", "bagels", "buns", "roll", "rolls", "loaf",
    "coffee", "beans", "ground", "espresso", "tea",
    "olive", "oil", "extra", "virgin", "vinegar",
    "crackers", "chips", "crisps", "nuts", "seeds", "chocolate",
    "sauce", "pasta", "noodles", "rice", "honey", "jam", "spread",
}

# Authoritative New Zealand and international specialty food brands
KNOWN_BRANDS = [
    "Haha", "Hãhã", "Lewis Road Creamery", "Lewis Road", "Wild Nation", "Kiwi Artisan",
    "Allpress Espresso", "Allpress", "Bostock Brothers", "Bostock", "Fix & Fogg", "Fix and Fogg",
    "Whittaker's", "Whittakers", "Farro Kitchen", "Farro", "Daily Bread", "Little Island",
    "Raglan Food Co", "Raglan", "Proper Crisps", "Kowbucha", "Almighty", "Karma Drinks",
    "Karma", "Phoenix Organics", "Te Mata", "Craggy Range", "Villa Maria", "Rockburn",
    "Kelly Washington", "Man O' War", "Babich", "Ozone Coffee", "Atomic Coffee",
    "Supreme Coffee", "Kokako", "Zany Zeus", "Kapiti", "Whitestone", "Puhoi Valley",
    "Aoraki", "Mt Cook Alpine Salmon", "Bella Vacca", "Harmony", "Freedom Farms",
    "Beak & Sons", "First Light", "The Collective", "Ceres Organics", "Chantal Organics",
    "Anchor", "Meadow Fresh", "Granny Goose", "Foundry Chocolate", "Lucullus",
    "Genoese", "Barker's", "Barkers", "Culley's", "Culleys", "Maison Therese",
    "Delmaine", "Pastarotti", "Rustichella d'Abruzzo", "OMG", "Foundry",
    "OCHO", "Bennettto", "Bennetts", "House of Chocolate", "Molly Woppy",
]


def is_valid_gtin_checksum(barcode: str) -> bool:
    """Verify official GS1 modulo-10 check digit for GTIN-8, 12, 13, 14."""
    if not barcode or not barcode.isdigit():
        return False
    if len(barcode) not in VALID_GTIN_LENGTHS:
        return False
    digits = [int(c) for c in barcode]
    payload, check_digit = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    calc_check = (10 - (total % 10)) % 10
    return calc_check == check_digit


def extract_barcode(image_url: Optional[str], raw_row: Optional[dict] = None) -> Optional[str]:
    """Extract and validate barcode from image URLs or raw product payload."""
    candidates = []

    if image_url:
        m = _BARCODE_RE.search(image_url)
        if m:
            candidates.append(m.group(1))

    if raw_row:
        for img in raw_row.get("additionalImageUrls", []) or []:
            m = _BARCODE_RE.search(img or "")
            if m:
                candidates.append(m.group(1))

    # Strictly return only barcodes with valid mathematical GS1 check digits
    for code in candidates:
        if is_valid_gtin_checksum(code):
            return code

    return None


def extract_size(title: str) -> Optional[str]:
    """Extract pack size/weight text from product title."""
    if not title:
        return None

    multi_m = _MULTI_PACK_RE.search(title)
    if multi_m:
        return multi_m.group(1).strip()

    m = _SIZE_RE.search(title)
    if m:
        return m.group(1).strip()

    return None


def infer_brand(title: str, existing_brand: Optional[str] = None) -> Optional[str]:
    """Infer authentic brand name from explicit field or title prefixes."""
    clean_existing = (existing_brand or "").strip()
    if clean_existing and clean_existing.lower() not in {"null", "none", "unknown", ""}:
        return clean_existing

    if not title:
        return None

    title_clean = title.strip()
    title_lower = title_clean.lower()

    # 1. Match known brands (longest match first)
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        b_lower = brand.lower()
        if title_lower == b_lower or title_lower.startswith(b_lower + " ") or title_lower.startswith(b_lower + "'"):
            return brand

    # 2. Heuristic: inspect leading tokens
    words = title_clean.split()
    if not words:
        return None

    first = words[0]
    if first.lower() in NON_BRAND_WORDS:
        return None

    if len(words) >= 2:
        second = words[1]
        # Check if first 2 words form a brand (e.g. "Wild Nation", "Kiwi Artisan")
        if second[0].isupper() and second.lower() not in NON_BRAND_WORDS and len(second) > 2:
            return f"{first} {second}"

    return first if first[0].isupper() else None


def extract_clean_name(raw_name: str, brand: Optional[str] = None, size: Optional[str] = None) -> str:
    """Derive clean product title by stripping leading brand and trailing size tokens."""
    if not raw_name:
        return ""

    name = raw_name.strip()

    # 1. Strip leading brand if present at the start of name
    if brand:
        brand_clean = brand.strip()
        if name.lower().startswith(brand_clean.lower()):
            name = name[len(brand_clean):].strip()

    # 2. Strip size token if present
    if size:
        pattern = re.compile(r"\b" + re.escape(size) + r"\b", re.IGNORECASE)
        name = pattern.sub("", name).strip()

    # Clean up residual artifacts
    name = _NON_WORD_EDGES.sub("", name)
    name = _CLEAN_SPACES_RE.sub(" ", name).strip()

    return name if len(name) >= 2 else raw_name.strip()


def format_category_path(categories: Any) -> Optional[str]:
    """Format category hierarchy as ' > '-joined string."""
    if not categories:
        return None

    if isinstance(categories, str):
        return categories.replace("/", " > ").strip()

    if isinstance(categories, list) and categories:
        best_path = ""
        for cat in categories:
            if isinstance(cat, dict):
                full = cat.get("FullPath") or ""
                if len(full.split("/")) > len(best_path.split("/")):
                    best_path = full
            elif isinstance(cat, str):
                if len(cat.split("/")) > len(best_path.split("/")):
                    best_path = cat

        if best_path:
            parts = [p.strip() for p in best_path.split("/") if p.strip()]
            return " > ".join(parts)

    return None
