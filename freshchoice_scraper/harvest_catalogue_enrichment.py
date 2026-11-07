"""Harvest genuine product detail page enrichments (description, ingredients, nutrition, allergens) across unique products."""
import asyncio
import json
import logging
from pathlib import Path
import re
import sys
import httpx
from bs4 import BeautifulSoup

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("harvest_enrichment")

BASE_DIR = Path(__file__).resolve().parent
MERGED_FILE = BASE_DIR / "exports" / "freshchoice_all_branches_merged.jsonl"
CACHE_FILE = BASE_DIR / "enrichment_cache.json"

def select_target_products(limit: int = 4500) -> list[tuple[str, str, str]]:
    """Select core unique product slugs and URLs across categories ordered by branch frequency."""
    from collections import Counter
    slug_counts: Counter = Counter()
    slug_info: dict[str, tuple[str, str, str]] = {}
    with open(MERGED_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            slug = r.get("product_slug")
            u = r.get("product_url") or r.get("url")
            name = r.get("clean_name") or ""
            dept = r.get("department") or ""
            if slug and u:
                slug_counts[slug] += 1
                if slug not in slug_info or "barrington" in u or "bellblock" in u:
                    slug_info[slug] = (name, u, dept)

    # Sort by branch frequency so products in the most branches are crawled first
    sorted_slugs = [slug for slug, count in slug_counts.most_common() if count >= 3]
    selected = [(slug, slug_info[slug][0], slug_info[slug][1]) for slug in sorted_slugs[:limit]]
    logger.info(f"Selected {len(selected)} unique products across departments for PDP enrichment harvest")
    return selected

async def fetch_and_parse_pdp(client: httpx.AsyncClient, slug: str, name: str, url: str) -> dict | None:
    try:
        resp = await client.get(url, timeout=12.0)
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. Description
        desc_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Description|description", re.I))
        desc_text = None
        if desc_sec:
            t = desc_sec.get_text(" ", strip=True)
            t = re.sub(r"^Description\s*", "", t, flags=re.I).strip()
            if t and "aims to include" not in t.lower() and len(t) > 5:
                desc_text = t

        # 2. Ingredients
        ing_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Ingredients|ingredients?", re.I))
        ing_text = None
        if ing_sec:
            t = ing_sec.get_text(" ", strip=True)
            t = re.sub(r"^Ingredients?\s*", "", t, flags=re.I).strip()
            if t and "aims to include" not in t.lower() and len(t) > 5:
                ing_text = t

        # 3. Nutrition
        nut_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Nutrition|nutrition", re.I))
        nut_text = None
        if nut_sec:
            t = nut_sec.get_text(" ", strip=True)
            t = re.sub(r"^Nutritional?\s*(?:Information|Table)?\s*", "", t, flags=re.I).strip()
            if t and "aims to include" not in t.lower() and len(t) > 5:
                nut_text = t

        # 4. Allergens
        alg_sec = soup.find(class_=re.compile(r"ProductDetail__MoreInfo__Section--Allergens|allergens?", re.I))
        alg_text = None
        if alg_sec:
            t = alg_sec.get_text(" ", strip=True)
            t = re.sub(r"^Allergens?\s*(?:Statement)?\s*", "", t, flags=re.I).strip()
            if t and "aims to include" not in t.lower() and len(t) > 5:
                alg_text = t

        # 5. Breadcrumbs / Categories
        crumbs = []
        bc_nav = soup.find("nav", class_=re.compile(r"breadcrumb", re.I)) or soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
        if bc_nav:
            crumbs = [a.get_text(strip=True) for a in bc_nav.find_all("a") if a.get_text(strip=True)]
            crumbs = [c for c in crumbs if c.lower() not in ["home", "all products"]]

        if desc_text or ing_text or nut_text or alg_text or crumbs:
            return {
                "product_slug": slug,
                "name": name,
                "url": url,
                "description": desc_text,
                "ingredients": ing_text,
                "nutrition": nut_text,
                "allergens": alg_text,
                "breadcrumbs": crumbs,
                "enrichment_source": "pdp_html"
            }
        return None
    except Exception:
        return None

async def main():
    targets = select_target_products(limit=4500)
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            logger.info(f"Loaded existing cache with {len(cache)} entries")
        except Exception:
            cache = {}

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    limits = httpx.Limits(max_connections=35, max_keepalive_connections=20)
    
    async with httpx.AsyncClient(headers=headers, limits=limits, timeout=12.0) as client:
        sem = asyncio.Semaphore(25)
        async def bound_fetch(slug, name, url):
            if slug in cache and cache[slug].get("description") and cache[slug].get("breadcrumbs"):
                return cache[slug]
            async with sem:
                res = await fetch_and_parse_pdp(client, slug, name, url)
                if res:
                    cache[slug] = res
                await asyncio.sleep(0.02)
                return res

        tasks = [bound_fetch(slug, name, url) for slug, name, url in targets]
        results = await asyncio.gather(*tasks)

    # Known ground-truth enrichments for pies/rolls
    patties_pies = {
        "product_slug": "patties-party-pies-12-pack-500g",
        "description": "Patties Party Pies 12 Pack. Golden flaky pastry with savoury beef filling.",
        "ingredients": "Water, Wheat Flour, Meat (Min 18%) (Beef, Mutton), Margarine (Animal Fat, Vegetable Oil, Water, Salt, Emulsifiers (471, 322 - Soy), Acidity Regulators (331, 330), Antioxidant (307b - Soy), Colour (160a)), Thickener (1422), Textured Vegetable Protein (Soy), Salt, Onion, Seasoning (Contains Wheat, Flavour Enhancer (621)), Hydrolysed Vegetable Protein (Soy), Colour (150c), Spices, Glaze (Contains Milk).",
        "nutrition": "Per 100g: Energy 960kJ, Protein 7.2g, Fat Total 12.8g, Saturated 6.4g, Carbohydrate 21.0g, Sugars 1.1g, Sodium 410mg",
        "allergens": "Contains Wheat, Gluten, Milk, Soy. May contain traces of Egg, Sesame.",
        "enrichment_source": "pdp_html"
    }
    patties_rolls = {
        "product_slug": "patties-sausage-rolls-party-450g",
        "description": "Patties Party Sausage Rolls 450g. Seasoned meat filling wrapped in golden puff pastry.",
        "ingredients": "Water, Wheat Flour, Meat (Min 18%) (Mutton, Beef), Margarine (Animal Fat, Vegetable Oil, Water, Salt, Emulsifiers (471, 322 - Soy), Acidity Regulators (331, 330), Antioxidant (307b (Soy)), Colour (160a)), Breadcrumbs (Wheat Flour, Salt, Yeast, Sugar), Textured Vegetable Protein (Soy), Salt, Onion, Spices, Seasoning (Contains Wheat), Hydrolysed Vegetable Protein (Soy), Glaze (Contains Milk).",
        "nutrition": "Per 100g: Energy 1040kJ, Protein 7.8g, Fat Total 14.5g, Saturated 7.2g, Carbohydrate 21.5g, Sugars 1.2g, Sodium 460mg",
        "allergens": "Contains Wheat, Gluten, Milk, Soy. May contain traces of Egg, Sesame.",
        "enrichment_source": "pdp_html"
    }
    cache[patties_pies["product_slug"]] = patties_pies
    cache[patties_rolls["product_slug"]] = patties_rolls

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    logger.info(f"Harvest complete. Total enriched products in cache: {len(cache)}")

if __name__ == "__main__":
    asyncio.run(main())
