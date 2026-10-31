"""Data normalization, GS1 checksum verification, brand, and size extractors."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

VALID_GTIN_LENGTHS = {8, 12, 13, 14}

# Known supermarket brands for clean parsing
KNOWN_BRANDS = [
    "Bluebird", "Cadbury", "Pams", "Steinlager", "Arnott's", "Harmony", "Griffin's",
    "Whittaker's", "Heineken", "Watties", "Wattie's", "Sanitarium", "Anchor", "Meadow Fresh",
    "Tip Top", "Mainland", "Sealord", "Fresh 'n Fruity", "Primo", "Just Juice", "Keri",
    "Coca-Cola", "Coke", "Pepsi", "Schweppes", "Sprite", "Fanta", "V", "Red Bull", "Monster",
    "Mother", "Powerade", "Gatorade", "Mizone", "Pump", "H2Go", "Kiwi Blue", "Pure Dew",
    "Vogel's", "Freya's", "Moltenberg", "Ploughmans", "Quality Bakers", "Nature's Fresh",
    "ETA", "Doritos", "Copper Kettle", "Proper Crisps", "Heartland", "Snak Logs",
    "Maggi", "Continental", "Campbell's", "MasterFoods", "Leggo's", "Barilla", "San Remo",
    "Diamond", "Ceres Organics", "Chantal Organics", "Macro", "Woolworths", "Uncle Tobys",
    "Hubbards", "Harraways", "Kellogg's", "Nestle", "Milo", "Nescafe", "Jed's", "Avalanche",
    "Robert Harris", "Hummingbird", "L'affare", "Dilmah", "Twinings", "Bell", "Red Seal",
    "Colgate", "Oral-B", "Palmolive", "Dettol", "Dove", "Nivea", "Rexona", "Lynx",
    "Pantene", "Head & Shoulders", "Sunsilk", "Schwarzkopf", "Garnier", "L'Oreal",
    "Persil", "Surf", "Cold Power", "Dynamo", "Attack", "Fab", "Comfort", "Fluffy",
    "Morning Fresh", "Dawn", "Sunlight", "Finish", "Somat", "Kleenex", "Cottonelle",
    "Purex", "Handee", "Tork", "Glad", "Cast Away", "Multiix", "Huggies", "Treasures",
    "Pampers", "Wattie's Baby", "Only Organic", "Farex", "Whiskas", "Purina", "Friskies",
    "Fancy Feast", "Chef", "Tux", "Pedigree", "My Dog", "Champ", "VIP Petfoods",
    "Corona", "Stella Artois", "Peroni", "Asahi", "Mac's", "Speight's", "Lion Red",
    "Waikato", "DB Draught", "Export Gold", "Tui", "Boundary Road", "Monteith's",
    "Montana", "Brancott Estate", "Oyster Bay", "Villa Maria", "Stoneleigh", "Giesen",
    "Church Road", "Babich", "Wither Hills", "Mud House", "Selaks", "Lindauer", "Jacob's Creek"
]

SIZE_REGEX = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:kg|g|litre|litres|l|ml|ea|pk|pack|bunch|pieces|pce|slices|pack\s*bottles|pack\s*cans|varieties))\b|"
    r"\b(\d+\s*x\s*\d+(?:\.\d+)?\s*(?:ml|g|kg|l))\b|"
    r"\b(\d+-\d+\s*g)\b",
    re.I,
)


def is_valid_gtin_format(code: Any) -> bool:
    """Check if code is numeric and exactly standard GTIN length (8, 12, 13, 14 digits).
    Strictly isolates produce PLUs (4 or 5 digits) and arbitrary SKUs.
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


def extract_brand(heading: str) -> Optional[str]:
    """Extract recognized brand name from product title."""
    if not heading:
        return None
    h_lower = heading.lower()
    for brand in KNOWN_BRANDS:
        # Check boundary match
        b_lower = brand.lower()
        if re.search(r"\b" + re.escape(b_lower) + r"\b", h_lower):
            return brand
    # Fallback: first word if title starts with capitalized word
    first_word = heading.strip().split()[0] if heading.strip() else None
    if first_word and first_word.isalpha() and first_word[0].isupper() and len(first_word) > 2:
        return first_word
    return None


def extract_size(heading: str) -> Optional[str]:
    """Extract pack size/weight from title string (e.g. '140-150g', '500g', '330ml 12 Pack')."""
    if not heading:
        return None
    # Special compound match: '330ml 12 Pack Bottles' or '330ml 12 Pack'
    m_pack = re.search(r"(\d+(?:\.\d+)?\s*(?:ml|g|kg|l)\s+\d+\s+Pack(?:\s+\w+)?)", heading, re.I)
    if m_pack:
        return m_pack.group(1).strip()

    m_range = re.search(r"(\d+-\d+\s*[a-zA-Z]+)", heading)
    if m_range:
        return m_range.group(1).strip()

    m = SIZE_REGEX.search(heading)
    if m:
        for g in m.groups():
            if g:
                return g.strip()
    return None


def clean_name(heading: str, brand: Optional[str] = None, size: Optional[str] = None) -> str:
    """Generate clean product title with brand and size stripped."""
    if not heading:
        return ""
    text = heading
    if brand:
        text = re.sub(r"\b" + re.escape(brand) + r"\b", "", text, flags=re.I)
    if size:
        text = re.sub(r"\b" + re.escape(size) + r"\b", "", text, flags=re.I)
    # Strip lingering 'Varieties', trailing punctuation, extra spaces
    text = re.sub(r"\bVarieties\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.-/")
    return text or heading.strip()


def parse_promo_date(date_str: Optional[str]) -> Optional[str]:
    """Convert '01 Nov 2026' into ISO '2026-11-01'."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_foodstuffs_pid(image_url: Optional[str]) -> Optional[str]:
    """Extract numeric Foodstuffs product ID from fsimg URL:
    'https://a.fsimg.co.nz/product/retail/fan/image/400x400/5010717.png?w=320' -> '5010717-EA-000'
    """
    if not image_url:
        return None
    m = re.search(r"/image/\d+x\d+/(\d+)\.(?:png|jpg|webp)", image_url)
    if m:
        return f"{m.group(1)}-EA-000"
    return None
