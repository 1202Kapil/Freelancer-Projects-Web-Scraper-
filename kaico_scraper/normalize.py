"""Data normalization, GS1 checksum verification, brand, size, unit price, and category extractors for Kai Co."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional

VALID_GTIN_LENGTHS = {8, 12, 13, 14}

KNOWN_BRANDS = [
    "Couplands", "Coupland's", "Brinks", "Brink's", "Cow & Gate", "Wedderburn",
    "Bluebird", "Cadbury", "Steinlager", "Arnott's", "Harmony", "Griffin's",
    "Whittaker's", "Heineken", "Watties", "Wattie's", "Sanitarium", "Anchor",
    "Meadow Fresh", "Tip Top", "Mainland", "Sealord", "Fresh 'n Fruity", "Primo",
    "Just Juice", "Keri", "Coca-Cola", "Coke", "Pepsi", "Schweppes", "Sprite",
    "Vogel's", "Freya's", "Moltenberg", "Ploughmans", "Quality Bakers", "Nature's Fresh",
    "ETA", "Doritos", "Copper Kettle", "Proper Crisps", "Heartland", "Maggi",
    "Continental", "Campbell's", "MasterFoods", "Leggo's", "Barilla", "San Remo",
    "Diamond", "Ceres Organics", "Chantal Organics", "Uncle Tobys", "Hubbards",
    "Harraways", "Kellogg's", "Nestle", "Milo", "Nescafe", "Jed's", "Avalanche",
    "Robert Harris", "Hummingbird", "L'affare", "Dilmah", "Twinings", "Bell", "Red Seal",
    "Colgate", "Oral-B", "Palmolive", "Dettol", "Dove", "Nivea", "Rexona", "Lynx",
    "Persil", "Surf", "Cold Power", "Dynamo", "Morning Fresh", "Dawn", "Sunlight", "Finish",
    "Kai Co",
]

# Regex patterns
SIZE_REGEX = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:kg|g|gm|gms|litre|litres|l|ml|ea|pk|pack|bunch|pieces|pce|slices|pack\s*bottles|pack\s*cans))\b|"
    r"\b(\d+\s*x\s*\d+(?:\.\d+)?\s*(?:ml|g|gm|kg|l))\b|"
    r"\b(\d+-\d+\s*(?:g|gm|kg))\b",
    re.I,
)

PRICE_IN_TITLE_REGEX = re.compile(
    r"[-–—]?\s*\$(\d+(?:\.\d+)?)\s*(?:/|\s*per\s*)?(kg|ea|100g|g|l|ml)?\b",
    re.I,
)

MULTIBUY_REGEX = re.compile(
    r"\b(\d+)\s+for\s+\$(\d+(?:\.\d+)?)\b",
    re.I,
)


def to_cents(value: Any) -> Optional[int]:
    """Convert dollars (float/int/str) to integer cents NZD. Safe with None/empty."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        val_clean = str(value).replace("$", "").replace(",", "").strip()
        return int(round(float(val_clean) * 100))
    except (TypeError, ValueError):
        return None


def is_valid_gtin_format(code: Any) -> bool:
    """Check if code is numeric and exactly standard GTIN length (8, 12, 13, 14 digits).
    Rejects produce PLUs (4 or 5 digits) and non-numeric codes.
    """
    if not code:
        return False
    s = str(code).strip()
    return s.isdigit() and len(s) in VALID_GTIN_LENGTHS


def is_valid_gtin_checksum(barcode: Any) -> bool:
    """Mathematically verify GS1 Modulo-10 check digit for GTIN-8, 12, 13, 14."""
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


def extract_brand(title: str, vendor: Optional[str] = None) -> Optional[str]:
    """Extract brand name from title or vendor."""
    if not title:
        return vendor or None

    t_lower = title.lower()
    for b in KNOWN_BRANDS:
        b_clean = b.replace("'", "").replace("’", "").lower()
        title_clean = title.replace("'", "").replace("’", "").lower()
        if re.search(r"\b" + re.escape(b_clean) + r"\b", title_clean):
            return b

    # Check vendor if specified
    if vendor and vendor.strip() and vendor.strip().lower() != "default":
        return vendor.strip()

    return "Kai Co"


def extract_size(title: str) -> Optional[str]:
    """Extract pack size / weight from title string."""
    if not title:
        return None

    # Check multibuy or combo pack first
    m_pack = re.search(r"(\d+\s*pk|\d+\s*pack)", title, re.I)
    if m_pack:
        return m_pack.group(1).lower().replace(" ", "")

    m = SIZE_REGEX.search(title)
    if m:
        for g in m.groups():
            if g:
                val = g.strip().lower()
                val = re.sub(r"(?<=\d)gms?\b", "g", val)
                val = re.sub(r"\bgms?\b", "g", val)
                val = re.sub(r"\blitres?\b", "L", val)
                val = re.sub(r"(?<=\d)l\b", "L", val)
                val = val.replace(" ", "")
                return val
    return None


def extract_unit_info(title: str, current_price_cents: int) -> tuple[Optional[int], Optional[str]]:
    """Extract unit_price_cents and unit_label from title or default pricing.
    E.g. '$15.99kg' -> (1599, '1kg')
         '$4.99ea'  -> (499, 'ea')
         'Capsicums Mixed Bag $7.99/kg' -> (799, '1kg')
    """
    if not title:
        return None, None

    # Match '$15.99kg' or '$15.99/kg' or '$4.99ea'
    m = re.search(r"\$(\d+(?:\.\d+)?)\s*(?:/|\s*per\s*)?(kg|ea|100g|g|l|ml)\b", title, re.I)
    if m:
        price_val = to_cents(m.group(1))
        unit_str = m.group(2).lower()
        if unit_str == "kg":
            return price_val, "1kg"
        elif unit_str in ("ea", "each"):
            return price_val, "ea"
        elif unit_str == "100g":
            return price_val, "100g"
        elif unit_str == "l":
            return price_val, "1L"
        return price_val, unit_str

    # Check if title indicates loose produce sold per kg
    if re.search(r"\b(loose|per\s*kg|/kg)\b", title, re.I):
        return current_price_cents, "1kg"

    # Default unit price for count/each
    return current_price_cents, "ea"


def clean_name(title: str, brand: Optional[str] = None, size: Optional[str] = None) -> str:
    """Generate clean, human-readable product title with price, brand, and size stripped."""
    if not title:
        return ""

    text = title

    # Remove price suffixes like '$15.99kg', '- $1.99', '$4.99ea', etc.
    text = re.sub(r"[-–—]?\s*\$\d+(?:\.\d+)?\s*(?:/|\s*per\s*)?(?:kg|ea|100g|g|l|ml)?", "", text, flags=re.I)

    # Remove multibuy prefix/suffix like '5 for $3.99'
    text = re.sub(r"\b\d+\s+for\s+\$\d+(?:\.\d+)?\b", "", text, flags=re.I)

    # Remove explicit brand if found at word boundary
    if brand and brand.lower() != "kai co":
        text = re.sub(r"\b" + re.escape(brand) + r"\b", "", text, flags=re.I)

    # Remove size
    if size:
        text = re.sub(r"\b" + re.escape(size) + r"\b", "", text, flags=re.I)

    # Remove lingering pack/loose tokens if standalone
    text = re.sub(r"\b(range)\b", "", text, flags=re.I)

    # Clean up whitespace and punctuation
    text = re.sub(r"[\s_]+", " ", text).strip(" ,.-–—/")

    # If all uppercase (e.g. 'AVOCADO' or 'CARROTS LOOSE'), convert to title case
    if text.isupper():
        text = text.title()

    return text or title.strip()


def build_category_path(product_type: Optional[str], collection_titles: list[str]) -> Optional[str]:
    """Construct hierarchical category path: Department > Category > Subcategory."""
    pt = (product_type or "").strip().upper()

    meat_types = {
        "PORK", "FRESH PORK", "BEEF", "CHICKEN", "LAMB", "SAUSAGES",
        "SMALL GOODS", "KAI MEAT BOX"
    }
    produce_types = {
        "FRUIT OTHER", "APPLES", "CITRUS", "GRAPES", "TROPICAL",
        "ROOT VEGES", "ROOT VEG OTHER", "VEGETABLES - GREEN", "VEG GREEN",
        "MUSHROOMS", "ONIONS", "CAPSICUM", "BROCCOLI & CAULI",
        "PUMPKINS & SQUASH", "KAI PRODUCE BOX"
    }

    department = ""
    category = ""

    if pt in meat_types:
        department = "Meat"
        category = pt.replace("FRESH ", "").title()
    elif pt in produce_types:
        department = "Produce"
        category = pt.title()
    elif pt == "DAIRY":
        department = "Dairy & Eggs"
        category = "Dairy"
    elif pt == "PANTRY":
        department = "Pantry"
        category = "Groceries"
    elif "KAI BOXES" in [c.upper() for c in collection_titles]:
        department = "Meat & Produce"
        category = "Kai Boxes"
    elif collection_titles:
        c_first = collection_titles[0]
        if any(w in c_first.lower() for w in ["meat", "beef", "pork", "lamb", "chicken"]):
            department = "Meat"
            category = c_first
        elif any(w in c_first.lower() for w in ["produce", "fruit", "veg", "apples", "citrus"]):
            department = "Produce"
            category = c_first
        else:
            department = "Groceries"
            category = c_first
    else:
        department = "Groceries"
        category = pt.title() if pt else "General"

    if category and category.lower() != department.lower():
        return f"{department} > {category}"
    return department or "Groceries"


def extract_promotions(
    title: str,
    body_html: str,
    current_price_cents: int,
    compare_at_price_cents: Optional[int],
    collection_handles: list[str],
) -> dict[str, Any]:
    """Detect specials, multibuys, and promotional discounts."""
    promo: dict[str, Any] = {
        "promo_text": None,
        "promo_type": None,
        "comparison_price_cents": None,
        "multibuy_quantity": None,
        "multibuy_price_cents": None,
    }

    # 1. Multibuy detection (e.g. '5 for $3.99')
    m_multi = MULTIBUY_REGEX.search(title) or MULTIBUY_REGEX.search(body_html or "")
    if m_multi:
        qty = int(m_multi.group(1))
        price = to_cents(m_multi.group(2))
        promo["multibuy_quantity"] = qty
        promo["multibuy_price_cents"] = price
        promo["promo_type"] = "multibuy_fixed_price"
        promo["promo_text"] = f"{qty} for ${float(m_multi.group(2)):.2f}"
        return promo

    # 2. Compare-at price promotion
    if compare_at_price_cents and compare_at_price_cents > current_price_cents:
        promo["comparison_price_cents"] = compare_at_price_cents
        promo["promo_type"] = "special"
        promo["promo_text"] = "Special"
        return promo

    # 3. Collection deals
    if "sizzling-specials" in collection_handles:
        promo["promo_type"] = "special"
        promo["promo_text"] = "Sizzling Special"
    elif "produce-deals" in collection_handles:
        promo["promo_type"] = "special"
        promo["promo_text"] = "Produce Deal"
    elif "everyday-low-deals" in collection_handles:
        promo["promo_type"] = "special"
        promo["promo_text"] = "Everyday Low Deal"

    return promo
