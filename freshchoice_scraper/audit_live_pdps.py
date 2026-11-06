import urllib.request
import json
import re
from bs4 import BeautifulSoup
from pathlib import Path

urls = [
    ("Barrington", "https://barrington.store.freshchoice.co.nz/lines/doritos-party-bag-sup-chse-300g"),
    ("Barrington", "https://barrington.store.freshchoice.co.nz/lines/coca-cola-bottle-2-25l"),
    ("Barrington", "https://barrington.store.freshchoice.co.nz/lines/tip-top-trumpet-choc-4-pack"),
    ("Barrington", "https://barrington.store.freshchoice.co.nz/lines/chelsea-soft-brown-sugar-500g"),
    ("Bellblock", "https://bellblock.store.supervalue.co.nz/lines/kellogg-s-special-k-300g"),
    ("Bellblock", "https://bellblock.store.supervalue.co.nz/lines/watties-baked-beans-in-tomato-sauce-420g"),
    ("Bellblock", "https://bellblock.store.supervalue.co.nz/lines/anchor-blue-milk-standard-2l"),
    ("Cromwell", "https://cromwell.store.freshchoice.co.nz/lines/arnott-shape-orig-pizza-190g"),
    ("Merivale", "https://merivale.store.freshchoice.co.nz/lines/sanitarium-weet-bix-original-cereal-375g"),
    ("Nelson City", "https://nelsoncity.store.freshchoice.co.nz/lines/maggi-2-minute-noodles-chicken-5-pack")
]

results = []

for store, url in urls:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        
        # Check JSON-LD
        jsonld_keys = []
        gtin_val = None
        brand_val = None
        desc_val = None
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                d = json.loads(s.string or "")
                if isinstance(d, dict) and d.get("@type") == "Product":
                    jsonld_keys = list(d.keys())
                    brand_val = d.get("brand")
                    desc_val = d.get("description")
                    gtin_val = d.get("gtin13") or d.get("gtin") or d.get("gtin14") or d.get("gtin8")
            except Exception:
                pass
                
        # Check for HTML ingredients section
        ing_el = soup.find(class_=re.compile(r"ingredient", re.I)) or soup.find(string=re.compile(r"ingredients?:", re.I))
        nut_el = soup.find(class_=re.compile(r"nutrition", re.I)) or soup.find(string=re.compile(r"nutritional\s+information", re.I))
        all_el = soup.find(class_=re.compile(r"allergen", re.I)) or soup.find(string=re.compile(r"allergens?:", re.I))
        
        results.append({
            "store": store,
            "url": url,
            "status": 200,
            "title": soup.title.string.strip() if soup.title else None,
            "brand": brand_val,
            "has_description": bool(desc_val),
            "gtin_in_jsonld": gtin_val,
            "jsonld_keys": jsonld_keys,
            "ingredients_in_html": bool(ing_el),
            "nutrition_in_html": bool(nut_el),
            "allergens_in_html": bool(all_el),
        })
    except Exception as e:
        results.append({"store": store, "url": url, "status": str(e)})

audit_file = Path(r"C:\Users\singh\.gemini\antigravity\scratch\freshchoice_scraper\pdp_audit_results.json")
with open(audit_file, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"Audited {len(results)} live PDPs. Results saved to {audit_file}")
for r in results:
    if r.get("status") == 200:
        print(f"[{r['store']}] {r['title'][:40]} | Brand={r['brand']} | GTIN={r['gtin_in_jsonld']} | Ing={r['ingredients_in_html']} | Nut={r['nutrition_in_html']}")
    else:
        print(f"[{r['store']}] Error: {r['status']}")
