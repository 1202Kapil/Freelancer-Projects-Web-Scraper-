"""Parsers and normalization logic for FreshChoice Supermarket HTML & JSON-LD payloads.

Conforms strictly to PICO Scraper Data Contract:
1. Strict separation of unit selling price vs multibuy bundle prices (e.g. '3 for $25').
2. Mathematical GS1 modulo-10 checksum validation for GTIN-8, 12, 13, and 14 barcodes.
3. Produce PLUs (4-5 digits) strictly isolated from barcode space (mapped to plu_code in raw_row).
4. Full name sanitation (rejection of quantity-only names e.g. '250g' or 'each', removal of trailing prices).
5. Legitimate short last pages do not trigger weak text-only fallback.
6. Detail page enrichment and JSON-LD Schema.org parsing.
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
from jsonl_exporter import to_cents, _slug
from catalog_branches import get_branch
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


def _text_stream_products(soup: BeautifulSoup, branch: Branch, category_path: list[str]) -> list[Product]:
    """Weak text stream extraction fallback only used when absolutely 0 real cards exist."""
    prods = []
    entries = soup.find_all(class_=re.compile(r"unlabelled-entry", re.I))
    if entries:
        for entry in entries:
            text = entry.get_text(" ", strip=True)
            spans = entry.find_all("span")
            name = spans[0].get_text(strip=True) if spans else text
            on_special = bool(entry.find("small") and "save" in entry.find("small").get_text(strip=True).lower())
            pm = PRICE_RE.findall(text)
            price_nzd = Decimal(pm[-1]) if pm else None
            was_m = WAS_PRICE_RE.search(text)
            prev_dec = Decimal(was_m.group(1)) if was_m else None
            if prev_dec and len(pm) > 1:
                cand = [Decimal(p) for p in pm if Decimal(p) != prev_dec]
                if cand:
                    price_nzd = cand[0]

            promo = Promotion(on_special=True, previous_price_nzd=prev_dec) if on_special else None
            p = Product(
                branch_id=branch.id,
                branch_name=branch.name,
                product_id=None,
                product_key=f"name:{name}",
                identity_quality="name_fallback",
                name=name,
                category_paths=[category_path],
                price_nzd=price_nzd,
                promotion=promo,
            )
            prods.append(p)
        return prods

    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    for line in lines:
        pm = PRICE_RE.search(line)
        if pm and len(line) < 100 and not QUANTITY_ONLY_RE.match(line):
            name = PRICE_RE.sub("", line).strip()
            on_special = bool(re.search(r"special|save", line, re.I))
            name = re.sub(r"\b(special|save)\b", "", name, flags=re.I).strip()
            if name:
                promo = Promotion(on_special=on_special) if on_special else None
                p = Product(
                    branch_id=branch.id,
                    branch_name=branch.name,
                    product_id=None,
                    product_key=f"name:{name}",
                    identity_quality="name_fallback",
                    name=name,
                    category_paths=[category_path],
                    price_nzd=Decimal(pm.group(1)),
                    promotion=promo,
                )
                prods.append(p)
    return prods


def parse_listing(html: str, branch: Branch, category_path: list[str], request_url: str) -> PageResult:
    """Parse HTML listing page into PageResult."""
    soup = BeautifulSoup(html, "html.parser")
    issues = []

    reported_count = None
    count_match = re.search(r"Refine\s+(\d+)\s+results", html, re.I) or re.search(r"(\d+)\s+products?", html, re.I)
    if count_match:
        reported_count = int(count_match.group(1))

    # Standalone JSON-LD products
    jsonld_scripts = soup.find_all("script", type="application/ld+json")
    jsonld_products = []
    for script in jsonld_scripts:
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            if data.get("@type") == "Product":
                offers = data.get("offers") or {}
                raw_price = offers.get("price")
                price_dec = Decimal(str(raw_price)) if raw_price is not None else None
                avail = "in_stock" if "InStock" in offers.get("availability", "") else "out_of_stock"
                brand_obj = data.get("brand")
                brand_str = brand_obj.get("name") if isinstance(brand_obj, dict) else (str(brand_obj) if brand_obj else None)
                p = Product(
                    branch_id=branch.id,
                    branch_name=branch.name,
                    product_id=None,
                    product_key=f"sku:{data.get('sku')}" if data.get("sku") else f"name:{data.get('name')}",
                    name=data.get("name", ""),
                    sku=data.get("sku"),
                    brand=brand_str,
                    price_nzd=price_dec,
                    availability=avail,
                    category_paths=[category_path],
                    image_url=data.get("image"),
                    product_url=request_url,
                )
                jsonld_products.append(p)
        except Exception:
            pass

    # Discover candidate card containers
    raw_cards = soup.find_all(["div", "article", "li"], class_=re.compile(r"product|line-item|card|talker", re.I))
    # Exclude sort headers or text entries
    raw_cards = [c for c in raw_cards if not any("sort" in cl or "results" in cl or "unlabelled" in cl for cl in c.get("class", []))]

    # Only keep top-level cards (filter out child elements like talker__content or talker__imagery)
    card_set = set(raw_cards)
    cards = [c for c in raw_cards if not any(parent in card_set for parent in c.parents)]

    if not cards:
        line_links = soup.find_all("a", href=re.compile(r"/lines/"))
        if line_links:
            cards = [l.find_parent(["div", "article", "li"]) or l.parent for l in line_links]

    if not cards:
        if jsonld_products:
            return PageResult(products=jsonld_products, reported_count=reported_count or len(jsonld_products))
        if reported_count == 0:
            return PageResult(products=[], reported_count=0)
        fallback_prods = _text_stream_products(soup, branch, category_path)
        if fallback_prods:
            issues.append(f"Parsed {len(fallback_prods)} products via text-only fallback")
            return PageResult(products=fallback_prods, reported_count=reported_count, issues=issues)
        return PageResult(products=[], reported_count=reported_count, issues=["No products parsed; inspect HTML structure / network API"])

    products = []
    seen_urls_count: dict[str, int] = {}

    for card in cards:
        link = card.find("a", href=re.compile(r"/lines/"))
        if not link and card.name == "a" and "/lines/" in card.get("href", ""):
            link = card

        href = link.get("href", "") if link else ""
        slug_match = re.search(r"/lines/([^/?#]+)", href)
        slug = slug_match.group(1).strip() if slug_match else ""

        raw_name = ""
        content_el = card.find(class_=re.compile(r"talker__content|title|name|heading", re.I))
        if content_el:
            first_a = content_el.find("a")
            raw_name = first_a.get_text(separator=" ", strip=True) if first_a else content_el.get_text(separator=" ", strip=True)
        elif link:
            raw_name = link.get_text(separator=" ", strip=True)
        elif card.find("h3"):
            raw_name = card.find("h3").get_text(separator=" ", strip=True)

        if not raw_name or QUANTITY_ONLY_RE.match(raw_name):
            img = card.find("img")
            if img and img.get("alt"):
                alt_txt = img["alt"].strip()
                raw_name = re.sub(r"^Photo\s+of\s+", "", alt_txt, flags=re.I).strip()

        if not raw_name or QUANTITY_ONLY_RE.match(raw_name):
            continue

        clean_name = raw_name.strip()
        clean_name = re.sub(r"\s+\$\s*\d+(?:\.\d{1,2})?$", "", clean_name)
        clean_name = clean_name.replace("’", "'").replace("'", "")

        image_url = None
        img_elem = card.find("img")
        if img_elem:
            src = img_elem.get("data-src") or img_elem.get("src")
            image_url = normalize_image_url(src, branch.url)

        card_text = card.get_text(" ", strip=True)
        price_nzd = None
        prev_price_nzd = None
        savings_nzd = None
        pricing_unit = None
        unit_basis = None
        unit_price_nzd = None

        mb_qty, mb_price_cents, mb_text = parse_multibuy(card_text)

        was_m = WAS_PRICE_RE.search(card_text)
        if was_m:
            prev_price_nzd = Decimal(was_m.group(1))

        save_m = SAVE_RE.search(card_text)
        if save_m:
            if save_m.group(1):
                savings_nzd = Decimal(save_m.group(1))
            elif save_m.group(2):
                savings_nzd = Decimal(save_m.group(2)) / Decimal(100)

        up_m = UNIT_PRICE_RE.search(card_text)
        if up_m:
            unit_price_nzd = Decimal(up_m.group(1))
            unit_basis = f"per {up_m.group(2).strip()}"

        # Regular price
        price_elem = card.find(class_=re.compile(r"price|amount|cost", re.I))
        if price_elem:
            p_text = price_elem.get_text(strip=True)
            pm = PRICE_RE.search(p_text)
            if pm:
                price_nzd = Decimal(pm.group(1))

        if price_nzd is None:
            all_prices = [Decimal(p) for p in PRICE_RE.findall(card_text)]
            candidates = [p for p in all_prices if p != prev_price_nzd and p != unit_price_nzd and p != savings_nzd]
            if mb_price_cents:
                candidates = [p for p in candidates if int(round(float(p) * 100)) != mb_price_cents]
            if prev_price_nzd and savings_nzd and (prev_price_nzd - savings_nzd) in candidates:
                price_nzd = prev_price_nzd - savings_nzd
            elif candidates:
                price_nzd = candidates[0]

        if price_nzd is None:
            issues.append(f"Product {slug or clean_name} has no extractable individual price")

        if prev_price_nzd and price_nzd and not savings_nzd and prev_price_nzd > price_nzd:
            savings_nzd = prev_price_nzd - price_nzd

        if "per kg" in card_text.lower():
            pricing_unit = "per kg"
        elif "each" in card_text.lower():
            pricing_unit = "each"

        stock_status = "in_stock"
        lower_card = card_text.lower()
        if "out of stock" in lower_card or "unavailable" in lower_card:
            stock_status = "out_of_stock"
        add_btn = card.find(["button", "a", "input"], class_=re.compile(r"disabled|out-of-stock", re.I))
        if add_btn and ("disabled" in add_btn.attrs or "out-of-stock" in add_btn.get("class", [])):
            stock_status = "out_of_stock"

        promo = None
        on_special = bool(prev_price_nzd or savings_nzd or "special" in lower_card)
        if on_special or mb_qty:
            mb_dec = Decimal(f"{mb_price_cents/100:.2f}") if mb_price_cents else None
            promo = Promotion(
                on_special=on_special,
                previous_price_nzd=prev_price_nzd,
                savings_nzd=savings_nzd,
                multibuy_quantity=mb_qty,
                multibuy_price_nzd=mb_dec,
                description=mb_text or ("Special" if on_special else None),
            )

        # DOM line id vs Control ID resolution
        card_id_attr = card.get("id", "")
        dom_id = None
        if card_id_attr.startswith("line_"):
            dom_id = card_id_attr.removeprefix("line_")
        elif card.get("data-id"):
            dom_id = card.get("data-id")
        elif card.get("data-product-id"):
            dom_id = card.get("data-product-id")

        control_id = None
        ctrl_attr = card.get("data-line-control", "")
        if ctrl_attr:
            cm = re.search(r'"id":"([a-f0-9]{24})"', ctrl_attr)
            if cm:
                control_id = cm.group(1)

        attrs: dict[str, Any] = {}
        if dom_id and control_id and dom_id != control_id:
            product_id = None
            identity_quality = "url"
            attrs["source_identifier_type"] = "line_dom_id_conflicts_with_control"
        elif dom_id:
            product_id = dom_id
            identity_quality = "source_id"
            attrs["source_identifier_type"] = "storefront_line_id"
        else:
            product_id = None
            identity_quality = "url"

        id_span = card.find(class_=re.compile(r"product-id|item-code|sku", re.I))
        if id_span:
            product_id = id_span.get_text(strip=True)
            identity_quality = "source_id"

        product_url = f"{branch.url.rstrip('/')}/lines/{slug}" if slug else (f"{branch.url.rstrip('/')}/lines/{product_id}" if product_id else None)

        seen_count = seen_urls_count.get(product_url, 0)
        seen_urls_count[product_url] = seen_count + 1
        if product_id:
            pkey = f"id:{product_id}"
        elif product_url:
            pkey = f"url:{slug}" if seen_count == 0 else f"url:{slug}:{seen_count}"
        else:
            pkey = f"name:{clean_name}"

        p = Product(
            branch_id=branch.id,
            branch_name=branch.name,
            product_id=product_id,
            product_key=pkey,
            identity_quality=identity_quality,
            name=clean_name,
            category_paths=[category_path],
            price_nzd=price_nzd,
            pricing_unit=pricing_unit,
            unit_price_nzd=unit_price_nzd,
            unit_price_basis=unit_basis,
            promotion=promo,
            availability=stock_status,
            image_url=image_url,
            product_url=product_url,
            attributes=attrs,
        )
        products.append(p)

    return PageResult(products=products, reported_count=reported_count, issues=issues)


def enrich_from_detail(html_content: str, branch: Branch, item: Product) -> None:
    """Enrich Product from Product Detail Page HTML / OpenGraph."""
    soup = BeautifulSoup(html_content, "html.parser")

    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        item.image_url = normalize_image_url(og_img["content"], branch.url)

    brand_el = soup.find(["div", "span"], itemprop="brand")
    if brand_el:
        item.brand = brand_el.get("content") or brand_el.get_text(strip=True)

    desc_el = soup.find(class_=re.compile(r"description", re.I))
    if desc_el:
        item.description = desc_el.get_text(" ", strip=True)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            if data.get("@type") == "Product":
                if not item.brand:
                    brand_obj = data.get("brand")
                    item.brand = brand_obj.get("name") if isinstance(brand_obj, dict) else str(brand_obj)
                if not item.description and data.get("description"):
                    item.description = data["description"]
                gtin = data.get("gtin13") or data.get("gtin") or data.get("gtin14") or data.get("gtin8")
                if gtin and str(gtin).isdigit():
                    gtin_str = str(gtin).strip()
                    if len(gtin_str) in VALID_GTIN_LENGTHS and is_valid_gtin_checksum(gtin_str):
                        item.gtin = gtin_str
                if data.get("sku"):
                    item.sku = str(data["sku"]).strip()
        except Exception:
            pass


def parse_product_card(
    card_elem,
    branch_slug: str,
    category_path: Optional[str] = None,
    gtm_item: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Legacy dict-based card extractor for compatibility with jsonl exporter."""
    link = card_elem.find("a", href=re.compile(r"/lines/"))
    if not link and card_elem.name == "a" and "/lines/" in card_elem.get("href", ""):
        link = card_elem
    if not link:
        return None

    href = link.get("href", "")
    slug_match = re.search(r"/lines/([^/?#]+)", href)
    if not slug_match:
        return None
    slug = slug_match.group(1).strip()
    product_url = f"https://{branch_slug}.store.freshchoice.co.nz/lines/{slug}"

    title_elem = card_elem.find(class_=re.compile(r"talker__product-name|product-name|title|heading", re.I))
    if not title_elem:
        title_elem = card_elem.find(class_=re.compile(r"name", re.I)) or link
    raw_name = title_elem.get_text(separator=" ", strip=True) if title_elem else ""
    if raw_name.lower().startswith("photo of"):
        raw_name = re.sub(r"^photo of\s+", "", raw_name, flags=re.I).strip()
    if not raw_name or QUANTITY_ONLY_RE.match(raw_name):
        img = card_elem.find("img")
        if img and img.get("alt"):
            raw_name = re.sub(r"^photo of\s+", "", img["alt"].strip(), flags=re.I).strip()

    if not raw_name or QUANTITY_ONLY_RE.match(raw_name):
        return None

    clean_name = clean_product_name(raw_name)
    size_elem = card_elem.find(class_=re.compile(r"talker__name__size|size", re.I))
    size = size_elem.get_text(strip=True) if size_elem else extract_size_from_name(raw_name)

    card_text = card_elem.get_text(" ", strip=True)
    mb_qty, mb_price_cents, mb_text = parse_multibuy(card_text)

    price_elem = card_elem.find(class_=re.compile(r"price__sell|talker__prices__sell", re.I))
    if not price_elem:
        price_elem = card_elem.find("strong", class_=re.compile(r"price", re.I))
    if not price_elem:
        price_elem = card_elem.find(class_=re.compile(r"amount|cost", re.I))
    current_price_cents = None
    if price_elem:
        pm = PRICE_RE.search(price_elem.get_text(strip=True))
        if pm:
            current_price_cents = to_cents(pm.group(1))

    if current_price_cents is None:
        all_prices = PRICE_RE.findall(card_text)
        candidates = [to_cents(p) for p in all_prices if to_cents(p) != mb_price_cents]
        if candidates:
            current_price_cents = candidates[0]

    comparison_price_cents = None
    was_elem = card_elem.find(class_=re.compile(r"talker__prices__was|was", re.I))
    if was_elem:
        wm = PRICE_RE.search(was_elem.get_text(strip=True))
        if wm:
            comparison_price_cents = to_cents(wm.group(1))
    if not comparison_price_cents:
        was_m = WAS_PRICE_RE.search(card_text)
        if was_m:
            comparison_price_cents = to_cents(was_m.group(1))

    # Promotion badge / sticker
    promo_badge = None
    sticker_elem = card_elem.find(class_=re.compile(r"talker__sticker__label|talker__sticker|sticker|badge|ribbon", re.I))
    if sticker_elem:
        promo_badge = re.sub(r"\s+", " ", sticker_elem.get_text(separator=" ", strip=True)).strip()

    promo_type = None
    promo_text = None
    if mb_qty and mb_price_cents:
        promo_type = "multibuy_fixed_price"
        promo_text = mb_text
    elif comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents:
        promo_type = "special"
        savings_cents = comparison_price_cents - current_price_cents
        promo_text = f"Save ${(savings_cents)/100:.2f}"
        if promo_badge and promo_badge not in promo_text:
            promo_text = f"{promo_badge} | {promo_text}"

    unit_price_cents = None
    unit_label = None
    up_m = UNIT_PRICE_RE.search(card_text)
    if up_m:
        unit_price_cents = to_cents(up_m.group(1))
        unit_label = up_m.group(2).strip()

    stock_status = "in_stock"
    if "out of stock" in card_text.lower():
        stock_status = "out_of_stock"

    image_url = None
    img_elem = card_elem.find("img")
    if img_elem:
        src = img_elem.get("data-src") or img_elem.get("src")
        branch_base_url = f"https://{branch_slug}.store.freshchoice.co.nz"
        image_url = normalize_image_url(src, branch_base_url)

    # Department & Category Taxonomy from GTM layer or category_path
    department = gtm_item.get("item_category") if gtm_item else None
    category = gtm_item.get("item_category2") if gtm_item else None
    sub_category = gtm_item.get("item_category3") if gtm_item else None
    brand = gtm_item.get("item_brand") if gtm_item else None

    category_hierarchy = [c for c in [department, category, sub_category] if c]
    if category_hierarchy:
        category_path = " > ".join(category_hierarchy)
    elif category_path:
        category_hierarchy = [category_path]

    is_promo = bool(promo_type or promo_badge or (comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents))
    sale_price_cents = current_price_cents if is_promo else None
    list_price_cents = comparison_price_cents or current_price_cents
    leaf_category = sub_category or category or department or (category_hierarchy[-1] if category_hierarchy else None)
    lead_category = leaf_category

    # Canonical Store & Category URLs
    branch_info = get_branch(branch_slug)
    store_base_url = branch_info["url"] if branch_info else f"https://{branch_slug}.store.freshchoice.co.nz"
    product_url = f"{store_base_url}/lines/{slug}"

    cat_slug_for_url = None
    if leaf_category:
        cat_slug_for_url = _slug(leaf_category)
    elif category:
        cat_slug_for_url = _slug(category)
    elif department:
        cat_slug_for_url = _slug(department)
    category_url = f"{store_base_url}/category/{cat_slug_for_url}" if cat_slug_for_url else None

    price_per_unit = round(unit_price_cents / 100, 2) if unit_price_cents is not None else None
    price_by_unit = unit_label if unit_label else None

    return {
        # Store & Item Identifiers
        "store_id": branch_slug,
        "branch_id": branch_slug,
        "product_id": slug,
        "source_product_id": slug,
        "sku": slug,
        "retailer_sku": slug,
        "gtin": None,
        "barcode": None,
        "mpn": None,
        "group_id": None,

        # Titles & Taxonomy
        "raw_name": raw_name,
        "clean_name": clean_name,
        "brand": brand,
        "department": department or (category_hierarchy[0] if category_hierarchy else None),
        "category": category or (category_hierarchy[1] if len(category_hierarchy) > 1 else None),
        "sub_category": sub_category or (category_hierarchy[2] if len(category_hierarchy) > 2 else None),
        "leaf_category": leaf_category,
        "lead_category": lead_category,
        "breadcrumbs": category_hierarchy,
        "category_hierarchy": category_hierarchy,
        "category_path": category_path,
        "category_tree": category_path,
        "category_url": category_url,
        "size": size,
        "description": None,

        # Pricing & Promotion
        "currency": "NZD",
        "price": round(current_price_cents / 100, 2) if current_price_cents is not None else None,
        "current_price_cents": current_price_cents,
        "sale_price": round(sale_price_cents / 100, 2) if sale_price_cents is not None else None,
        "sale_price_cents": sale_price_cents,
        "list_price": round(list_price_cents / 100, 2) if list_price_cents is not None else None,
        "list_price_cents": list_price_cents,
        "comparison_price_cents": comparison_price_cents,
        "savings": round((comparison_price_cents - current_price_cents) / 100, 2) if (comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents) else None,
        "savings_cents": (comparison_price_cents - current_price_cents) if (comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents) else None,
        "price_per_unit": price_per_unit,
        "price_by_unit": price_by_unit,
        "unit_price_cents": unit_price_cents,
        "unit_label": unit_label,
        "is_promo": is_promo,
        "promo_badge": promo_badge,
        "promo_text": promo_text,
        "promo_type": promo_type,
        "multibuy_quantity": mb_qty,
        "multibuy_price_cents": mb_price_cents,

        # Stock, URLs, Media & Recommendations
        "availability": stock_status,
        "stock_status": stock_status,
        "url": product_url,
        "product_url": product_url,
        "image_url": image_url,
        "recommended_products": [],
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw_row": {
            "branch_id": branch_slug,
            "department": department,
            "category": category,
            "sub_category": sub_category,
            "leaf_category": leaf_category,
            "category_url": category_url,
            "category_tree": category_path,
            "price_per_unit": price_per_unit,
            "price_by_unit": price_by_unit,
        },
    }


def parse_product_detail_page(html_content: str, base_record: dict) -> dict[str, Any]:
    """Enrich record dictionary from PDP HTML."""
    dummy_item = Product(branch_id="", branch_name="", name="")
    dummy_branch = Branch(id="", name="", url="")
    enrich_from_detail(html_content, dummy_branch, dummy_item)

    updated = dict(base_record)
    if dummy_item.brand:
        updated["brand"] = dummy_item.brand
    if dummy_item.gtin:
        updated["gtin"] = dummy_item.gtin
        updated["barcode"] = dummy_item.gtin
    if dummy_item.sku:
        updated["sku"] = dummy_item.sku
        updated["retailer_sku"] = dummy_item.sku
    if dummy_item.description:
        updated["description"] = dummy_item.description
        raw = dict(updated.get("raw_row") or {})
        raw["description"] = dummy_item.description
        updated["raw_row"] = raw
    if dummy_item.image_url and not updated.get("image_url"):
        updated["image_url"] = dummy_item.image_url

    soup = BeautifulSoup(html_content, "html.parser")
    ing = soup.find(class_=re.compile(r"ingredients?", re.I))
    if ing:
        raw = dict(updated.get("raw_row") or {})
        raw["ingredients"] = ing.get_text(" ", strip=True)
        updated["raw_row"] = raw

    return updated
