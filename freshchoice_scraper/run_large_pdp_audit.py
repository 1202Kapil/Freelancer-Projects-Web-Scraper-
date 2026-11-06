"""Comprehensive Live PDP Audit across 50+ Real New Zealand Supermarket URLs."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sys
import time
import urllib.request
from bs4 import BeautifulSoup

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("pdp_audit")

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"


def collect_real_urls(target_count: int = 55) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    seen = set()

    # Sample from multiple branches
    files = [
        ("Barrington", EXPORTS_DIR / "freshchoice_barrington_20261102T070236Z.jsonl"),
        ("Bell Block", EXPORTS_DIR / "freshchoice_bellblock_20261102T070108Z.jsonl"),
        ("City Market", EXPORTS_DIR / "freshchoice_citymarket_20261102T070305Z.jsonl"),
        ("Cromwell", EXPORTS_DIR / "freshchoice_cromwell_20261102T070256Z.jsonl"),
        ("Merivale", EXPORTS_DIR / "freshchoice_merivale_20261102T070445Z.jsonl"),
    ]

    for store, fpath in files:
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                u = r.get("product_url")
                if u and "/lines/" in u and u not in seen:
                    # Prefer items with good variety
                    seen.add(u)
                    urls.append((store, u))
                    if len(urls) >= target_count:
                        return urls
    return urls


def audit_single_pdp(store: str, url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    result = {
        "store": store,
        "url": url,
        "http_status": None,
        "product_title": None,
        "brand_in_jsonld": None,
        "gtin_in_jsonld": None,
        "sku_in_jsonld": None,
        "jsonld_product_keys": [],
        "has_breadcrumb_list": False,
        "breadcrumbs": [],
        "has_description_text": False,
        "has_ingredients_table": False,
        "has_nutrition_table": False,
        "has_allergen_statement": False,
        "disclaimer_text_found": False,
        "disclaimer_sample": None,
    }

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            result["http_status"] = resp.getcode()
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        result["http_status"] = e.code
        return result
    except Exception as e:
        result["http_status"] = f"Error: {e}"
        return result

    soup = BeautifulSoup(html, "html.parser")

    # Product Title
    if soup.title and soup.title.string:
        result["product_title"] = soup.title.string.strip()

    # JSON-LD Inspection
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            raw_text = s.string or ""
            data = json.loads(raw_text)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                itype = item.get("@type")
                if itype == "Product":
                    result["jsonld_product_keys"] = sorted(list(item.keys()))
                    b = item.get("brand")
                    result["brand_in_jsonld"] = b.get("name") if isinstance(b, dict) else str(b) if b else None
                    result["sku_in_jsonld"] = item.get("sku")
                    gtin = item.get("gtin13") or item.get("gtin") or item.get("gtin14") or item.get("gtin8")
                    result["gtin_in_jsonld"] = gtin
                elif itype == "BreadcrumbList":
                    result["has_breadcrumb_list"] = True
                    elements = item.get("itemListElement", [])
                    elements = sorted(elements, key=lambda x: x.get("position", 0))
                    names = [el.get("item", {}).get("name") or el.get("name") for el in elements]
                    result["breadcrumbs"] = [n.strip() for n in names if n]
        except Exception:
            pass

    # Description check
    desc_el = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Description|description", re.I))
    if desc_el:
        txt = desc_el.get_text(" ", strip=True)
        if len(txt) > 5:
            result["has_description_text"] = True

    # Disclaimer Footnote check
    disc_el = soup.find(class_=re.compile(r"MoreInfo__Disclaimer", re.I))
    if disc_el:
        result["disclaimer_text_found"] = True
        result["disclaimer_sample"] = disc_el.get_text(" ", strip=True)[:160] + "..."

    # Decompose disclaimers before checking for actual ingredient/nutrition sections
    for d in soup.find_all(class_=re.compile(r"MoreInfo__Disclaimer|disclaimer|footer", re.I)):
        d.decompose()

    # Genuine Ingredients
    ing_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Ingredients", re.I))
    if ing_sec and len(ing_sec.get_text(strip=True)) > 10:
        result["has_ingredients_table"] = True

    # Genuine Nutrition table
    nut_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Nutrition|nutrition-table", re.I))
    nut_tbl = soup.find("table", class_=re.compile(r"nutrition", re.I))
    if nut_sec or nut_tbl:
        result["has_nutrition_table"] = True

    # Allergen Statement
    all_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Allergens", re.I))
    if all_sec and len(all_sec.get_text(strip=True)) > 5:
        result["has_allergen_statement"] = True

    return result


def main():
    real_urls = collect_real_urls(52)
    logger.info(f"Auditing {len(real_urls)} real live product URLs across 5 branches...")
    results = []
    success_count = 0
    gtin_count = 0
    ing_count = 0
    nut_count = 0

    for i, (store, url) in enumerate(real_urls, 1):
        res = audit_single_pdp(store, url)
        results.append(res)
        status = res["http_status"]
        if status == 200:
            success_count += 1
            if res["gtin_in_jsonld"]:
                gtin_count += 1
            if res["has_ingredients_table"]:
                ing_count += 1
            if res["has_nutrition_table"]:
                nut_count += 1
            title_prev = (res["product_title"] or "").split("|")[0].strip()
            logger.info(f"[{i:02d}/{len(real_urls)}] 200 OK | {store:<12} | {title_prev[:35]:<35} | GTIN={res['gtin_in_jsonld']} | Nut={res['has_nutrition_table']} | Ing={res['has_ingredients_table']}")
        else:
            logger.warning(f"[{i:02d}/{len(real_urls)}] {status} | {store:<12} | {url}")
        time.sleep(0.1)

    out_file = BASE_DIR / "pdp_audit_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info("=" * 70)
    logger.info(f"COMPREHENSIVE AUDIT COMPLETE ({len(results)} PDPs tested):")
    logger.info(f"  • Pages Returning 200 OK:      {success_count} / {len(results)} ({success_count/len(results)*100:.1f}%)")
    logger.info(f"  • GTIN/Barcode in JSON-LD:     {gtin_count} / {success_count} ({(gtin_count/max(1, success_count))*100:.1f}%)")
    logger.info(f"  • Ingredients Tables in DOM:   {ing_count} / {success_count} ({(ing_count/max(1, success_count))*100:.1f}%)")
    logger.info(f"  • Nutrition Tables in DOM:     {nut_count} / {success_count} ({(nut_count/max(1, success_count))*100:.1f}%)")
    logger.info(f"Results saved to: {out_file}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
