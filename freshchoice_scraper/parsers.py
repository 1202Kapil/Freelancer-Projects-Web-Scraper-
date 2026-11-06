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
            # Requirement 10: Do NOT strip "special" or "save" from product names,
            # and require actual offer evidence before setting promotion flag.
            save_m = SAVE_RE.search(line)
            was_m = WAS_PRICE_RE.search(line)
            on_special = bool(save_m or was_m)
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
        sticker_elem = card.find(class_=re.compile(r"talker__sticker|sticker|badge|ribbon", re.I))
        has_promo_badge = bool(sticker_elem and sticker_elem.get_text(strip=True))
        on_special = bool(prev_price_nzd or savings_nzd or has_promo_badge)
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


def normalize_name_for_match(text: str) -> set[str]:
    """Normalize text into distinct significant token set for fuzzy joining."""
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop = {"the", "and", "or", "in", "of", "with", "a", "an", "per", "kg", "g", "ml", "l"}
    return {t for t in tokens if t not in stop and len(t) > 1}


def match_gtm_item(
    card_name: str,
    card_slug: str,
    control_id: Optional[str],
    gtm_items: list[dict[str, Any]],
    card_index: int = -1,
) -> Optional[dict[str, Any]]:
    """Intelligently match a DOM card to its corresponding Google Tag Manager item.
    
    Prevents off-by-one misalignment caused by promo banners or mailer tiles.
    Prioritizes:
    1. Exact ID match (control_id == item_id).
    2. Name token overlap between card name/slug and gtm item_name.
    3. Positional fallback index ONLY IF tokens share significant overlap.
    Returns None if no confident match is found to avoid cross-contaminating brands.
    """
    if not gtm_items:
        return None

    # 1. Exact ID match
    if control_id:
        for it in gtm_items:
            if it.get("item_id") == control_id:
                return it

    # 2. Token overlap matching
    card_tokens = normalize_name_for_match(f"{card_name} {card_slug}")
    if not card_tokens:
        return None

    best_match = None
    best_overlap = 0

    for it in gtm_items:
        it_name = it.get("item_name") or ""
        it_tokens = normalize_name_for_match(it_name)
        overlap = len(card_tokens.intersection(it_tokens))
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = it

    # Require at least 2 matching tokens, or 1 if card_tokens is short
    min_required = 1 if len(card_tokens) <= 2 else 2
    if best_overlap >= min_required:
        return best_match

    # 3. Positional fallback ONLY IF candidate at index shares at least one token
    if 0 <= card_index < len(gtm_items):
        cand = gtm_items[card_index]
        cand_tokens = normalize_name_for_match(cand.get("item_name", ""))
        if card_tokens.intersection(cand_tokens):
            return cand

    return None


def parse_product_card(
    card_elem,
    branch_slug: str,
    category_path: Optional[str] = None,
    gtm_item: Optional[dict[str, Any]] = None,
    gtm_items: Optional[list[dict[str, Any]]] = None,
    card_index: int = -1,
) -> Optional[dict[str, Any]]:
    """Dict-based card extractor with structured pricing, weights, and GTM verification."""
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

    # Detect promotion from card classes only if verified by price or badge
    card_classes = card_elem.get("class", [])
    has_special_class = any("special" in str(c).lower() or "discount" in str(c).lower() for c in card_classes)
    if not promo_badge and has_special_class:
        if comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents:
            promo_badge = f"Save ${(comparison_price_cents - current_price_cents)/100:.2f}"

    promo_type = None
    promo_text = None

    # 1. Multibuy deals (e.g. 3 for $25)
    if mb_qty and mb_price_cents:
        promo_type = "multibuy_fixed_price"
        promo_text = mb_text
        if not promo_badge:
            promo_badge = "MULTIBUY"

    # 2. Was-Price Specials (e.g. was $5.49, now $3.89 -> save $1.60)
    elif comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents:
        promo_type = "special"
        savings_cents = comparison_price_cents - current_price_cents
        savings_str = f"Save ${(savings_cents)/100:.2f}"
        if promo_badge:
            promo_text = f"{promo_badge} | {savings_str}" if promo_badge.lower() not in savings_str.lower() else savings_str
        else:
            promo_badge = savings_str
            promo_text = savings_str

    # 3. Badge-only Specials (e.g. "SPECIAL", "SWEET SAVE")
    elif promo_badge:
        promo_type = "special"
        promo_text = promo_badge

    # Control ID, Weights, Increments, and Selling Price Basis (Requirement 4)
    ctrl_attr = card_elem.get("data-line-control", "")
    control_data = {}
    control_id = None
    unit_type = None
    default_order_weight = None
    quantity_increment = 1.0

    if ctrl_attr:
        try:
            control_data = json.loads(ctrl_attr)
            qty_data = control_data.get("quantity", {}) if isinstance(control_data, dict) else {}
            control_id = qty_data.get("id")
            unit_type = qty_data.get("unit")
            if unit_type == "kg":
                default_order_weight = qty_data.get("default", 0.1)
                quantity_increment = qty_data.get("increments", 0.1)
            else:
                quantity_increment = qty_data.get("increments", 1.0)
        except Exception:
            pass

    # DOM line id fallback
    card_id_attr = str(card_elem.get("id", ""))
    dom_id = card_id_attr.removeprefix("line_") if card_id_attr.startswith("line_") else card_elem.get("data-id")
    line_id = control_id or dom_id or slug

    # Units and Selling Price Basis
    units_elem = card_elem.find(class_=re.compile(r"price__units|units", re.I))
    units_text = units_elem.get_text(strip=True).lower() if units_elem else ""

    if unit_type == "kg" or "per kg" in units_text or "/kg" in units_text or "per kg" in card_text.lower():
        selling_price_basis = "per kg"
        unit_of_measure = "kg"
    elif "pack" in clean_name.lower() or " pk" in clean_name.lower() or "pack" in (size or "").lower():
        selling_price_basis = "per pack"
        unit_of_measure = "pack"
    elif "each" in units_text or "each" in card_text.lower():
        selling_price_basis = "each"
        unit_of_measure = "each"
    else:
        selling_price_basis = "per item"
        unit_of_measure = "item"

    # Comparison Unit Price & Measure
    unit_price_cents = None
    unit_label = None
    up_m = UNIT_PRICE_RE.search(card_text)
    if up_m:
        unit_price_cents = to_cents(up_m.group(1))
        unit_label = f"per {up_m.group(2).strip()}"

    comparison_unit_price = round(unit_price_cents / 100, 2) if unit_price_cents is not None else None
    comparison_unit_measure = unit_label

    stock_status = "in_stock"
    if "out of stock" in card_text.lower():
        stock_status = "out_of_stock"

    # Image URL
    image_url = None
    img_elem = card_elem.find("img")
    if img_elem:
        src = img_elem.get("data-src") or img_elem.get("src")
        branch_base_url = f"https://{branch_slug}.store.freshchoice.co.nz"
        image_url = normalize_image_url(src, branch_base_url)

    # Intelligent GTM Item Matcher (Requirement 1)
    matched_gtm = None
    if gtm_items:
        matched_gtm = match_gtm_item(clean_name, slug, control_id or dom_id, gtm_items, card_index)
    elif gtm_item:
        # Validate that single passed gtm_item is not misaligned
        card_tokens = normalize_name_for_match(f"{clean_name} {slug}")
        gtm_tokens = normalize_name_for_match(gtm_item.get("item_name", ""))
        if card_tokens.intersection(gtm_tokens):
            matched_gtm = gtm_item

    department = matched_gtm.get("item_category") if matched_gtm else None
    category = matched_gtm.get("item_category2") if matched_gtm else None
    sub_category = matched_gtm.get("item_category3") if matched_gtm else None
    brand = matched_gtm.get("item_brand") if matched_gtm else None

    category_hierarchy = [c for c in [department, category, sub_category] if c]
    if category_hierarchy:
        category_path = " > ".join(category_hierarchy)
    elif category_path and category_path != "Specials":
        category_hierarchy = [category_path]
    else:
        category_hierarchy = []

    is_promo = bool(promo_type or promo_badge or (comparison_price_cents and current_price_cents and comparison_price_cents > current_price_cents))
    sale_price_cents = current_price_cents if is_promo else None
    list_price_cents = comparison_price_cents or current_price_cents
    savings_cents = (list_price_cents - current_price_cents) if (list_price_cents and current_price_cents and list_price_cents > current_price_cents) else None
    savings = round(savings_cents / 100, 2) if savings_cents is not None else None
    leaf_category = sub_category or category or department or (category_hierarchy[-1] if category_hierarchy else None)
    lead_category = leaf_category

    # Canonical Retailer & Branch Store URLs (Requirement 7)
    branch_info = get_branch(branch_slug)
    store_base_url = branch_info["url"] if branch_info else f"https://{branch_slug}.store.freshchoice.co.nz"
    is_supervalue = branch_slug == "bellblock" or "supervalue.co.nz" in store_base_url
    retailer = "supervalue" if is_supervalue else "freshchoice"
    retailer_name = "SuperValue" if is_supervalue else "FreshChoice"
    brand_family = "FreshChoice / SuperValue (Woolworths NZ)"

    product_url = f"{store_base_url}/lines/{slug}"

    cat_slug_for_url = None
    if leaf_category:
        cat_slug_for_url = _slug(leaf_category)
    elif category:
        cat_slug_for_url = _slug(category)
    elif department:
        cat_slug_for_url = _slug(department)
    category_url = f"{store_base_url}/category/{cat_slug_for_url}" if cat_slug_for_url else None

    price_per_unit = comparison_unit_price
    price_by_unit = comparison_unit_measure

    mb_total_nzd = f"${mb_price_cents / 100:.2f}" if mb_price_cents else None

    return {
        # Store & Retailer Mapping (Requirement 7)
        "branch_id": branch_slug,
        "branch_name": branch_info["name"] if branch_info else branch_slug.title(),
        "store_id": branch_slug,
        "retailer": retailer,
        "retailer_name": retailer_name,
        "brand_family": brand_family,
        "storefront_url": store_base_url,

        # Product Identifiers (Requirement 3)
        "product_id": line_id,
        "source_product_id": line_id,
        "product_slug": slug,
        "sku": slug,
        "retailer_sku": slug,
        "gtin": None,
        "barcode": None,
        "mpn": None,
        "group_id": None,

        # Titles & Taxonomy (Requirement 1)
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
        "category_path": category_path or (category_hierarchy[0] if category_hierarchy else None),
        "category_tree": category_path or (category_hierarchy[0] if category_hierarchy else None),
        "category_url": category_url,
        "size": size,
        "description": None,

        # Selling Price Basis & Weights (Requirement 4)
        "currency": "NZD",
        "price": round(current_price_cents / 100, 2) if current_price_cents is not None else None,
        "current_price_cents": current_price_cents,
        "current_price_nzd": f"${current_price_cents / 100:.2f}" if current_price_cents is not None else None,
        "selling_price_basis": selling_price_basis,
        "unit_of_measure": unit_of_measure,
        "default_order_weight": default_order_weight,
        "quantity_increment": quantity_increment,
        "comparison_unit_price": comparison_unit_price,
        "comparison_unit_measure": comparison_unit_measure,
        "price_per_unit": price_per_unit,
        "price_by_unit": price_by_unit,
        "unit_price_cents": unit_price_cents,
        "unit_label": unit_label,

        # Structured Promotion Details (Requirement 5 & 10)
        "is_promo": is_promo,
        "promo_type": promo_type,
        "promo_badge": promo_badge,
        "promo_text": promo_text,
        "sale_price": round(sale_price_cents / 100, 2) if sale_price_cents is not None else None,
        "sale_price_cents": sale_price_cents,
        "list_price": round(list_price_cents / 100, 2) if list_price_cents is not None else None,
        "list_price_cents": list_price_cents,
        "comparison_price_cents": comparison_price_cents,
        "savings": savings,
        "savings_cents": savings_cents,
        "multibuy_quantity": mb_qty,
        "multibuy_price_cents": mb_price_cents,
        "multibuy_total_nzd": mb_total_nzd,
        "loyalty_requirement": None,
        "offer_start_date": None,
        "offer_end_date": None,

        # Stock, URLs, Media & Enrichment (Requirement 6 & 8)
        "availability": stock_status,
        "stock_status": stock_status,
        "url": product_url,
        "product_url": product_url,
        "image_url": image_url,
        "source_url": product_url,
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scrape_run_id": None,
        "enriched_at": None,
        "enrichment_source": None,
        "ingredients": None,
        "nutrition": None,
        "allergens": None,
        "recommended_products": [],
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
            "selling_price_basis": selling_price_basis,
            "default_order_weight": default_order_weight,
            "quantity_increment": quantity_increment,
        },
    }


def parse_product_detail_page(html_content: str, base_record: dict) -> dict[str, Any]:
    """Enrich record dictionary from PDP HTML (Requirement 3, 6, 8)."""
    updated = dict(base_record)
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. JSON-LD Breadcrumbs & Product
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    if item.get("brand"):
                        b = item["brand"]
                        updated["brand"] = b.get("name") if isinstance(b, dict) else str(b).strip()
                    if item.get("description") and not updated.get("description"):
                        updated["description"] = item["description"].strip()
                    gtin = item.get("gtin13") or item.get("gtin") or item.get("gtin14") or item.get("gtin8")
                    if gtin and str(gtin).isdigit():
                        gtin_str = str(gtin).strip()
                        if len(gtin_str) in VALID_GTIN_LENGTHS and is_valid_gtin_checksum(gtin_str):
                            updated["gtin"] = gtin_str
                            updated["barcode"] = gtin_str
                    if item.get("sku"):
                        updated["sku"] = str(item["sku"]).strip()
                        updated["retailer_sku"] = str(item["sku"]).strip()
                    if item.get("image") and not updated.get("image_url"):
                        updated["image_url"] = str(item["image"]).strip()
                elif item.get("@type") == "BreadcrumbList":
                    elements = item.get("itemListElement", [])
                    elements = sorted(elements, key=lambda x: x.get("position", 0))
                    names = [el.get("item", {}).get("name") or el.get("name") for el in elements]
                    names = [n.strip() for n in names if n and "home" not in n.lower() and "all products" not in n.lower()]
                    if names:
                        updated["breadcrumbs"] = names
                        updated["category_hierarchy"] = names
                        updated["category_path"] = " > ".join(names)
                        updated["category_tree"] = " > ".join(names)
                        if len(names) >= 1:
                            updated["department"] = names[0]
                        if len(names) >= 2:
                            updated["category"] = names[1]
                        if len(names) >= 3:
                            updated["sub_category"] = names[2]
                        updated["leaf_category"] = names[-1]
                        updated["lead_category"] = names[-1]
        except Exception:
            pass

    # 2. Description section
    desc_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Description|description", re.I))
    if desc_sec and not updated.get("description"):
        d_text = desc_sec.get_text(" ", strip=True)
        d_text = re.sub(r"^Description\s*", "", d_text, flags=re.I).strip()
        if d_text:
            updated["description"] = d_text

    # 3. Ingredients section
    ing_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Ingredients|ingredients?", re.I))
    if ing_sec:
        ing_text = ing_sec.get_text(" ", strip=True)
        ing_text = re.sub(r"^Ingredients?\s*", "", ing_text, flags=re.I).strip()
        updated["ingredients"] = ing_text

    # 4. Nutrition section
    nut_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Nutrition|nutrition", re.I))
    if nut_sec:
        nut_text = nut_sec.get_text(" ", strip=True)
        nut_text = re.sub(r"^Nutritional?\s*(?:Information|Table)?\s*", "", nut_text, flags=re.I).strip()
        updated["nutrition"] = nut_text

    # 5. Allergens section
    all_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Allergens|allergens?", re.I))
    if all_sec:
        all_text = all_sec.get_text(" ", strip=True)
        all_text = re.sub(r"^Allergens?\s*", "", all_text, flags=re.I).strip()
        updated["allergens"] = all_text

    # 6. PDP GTM layer
    gtm_match = re.search(r"window\.gtmDataLayer\s*=\s*(\[.*?\]);\s*//", html_content, re.DOTALL)
    if gtm_match:
        try:
            gtm_payload = json.loads(gtm_match.group(1))
            if gtm_payload and isinstance(gtm_payload, list):
                items = gtm_payload[0].get("ecommerce", {}).get("items", [])
                if items:
                    pdp_item = items[0]
                    if pdp_item.get("item_brand"):
                        updated["brand"] = pdp_item["item_brand"]
                    if pdp_item.get("item_category"):
                        updated["department"] = pdp_item["item_category"]
                    if pdp_item.get("item_category2"):
                        updated["category"] = pdp_item["item_category2"]
                    if pdp_item.get("item_category3"):
                        updated["sub_category"] = pdp_item["item_category3"]
        except Exception:
            pass

    updated["enrichment_source"] = "pdp_html"
    updated["enriched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = dict(updated.get("raw_row") or {})
    for k in ["description", "ingredients", "nutrition", "allergens"]:
        if updated.get(k):
            raw[k] = updated[k]
    updated["raw_row"] = raw

    return updated
