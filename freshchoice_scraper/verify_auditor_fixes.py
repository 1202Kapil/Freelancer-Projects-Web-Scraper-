import json, random, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('exports/freshchoice_all_branches_merged.jsonl', 'r', encoding='utf-8') as f:
    rows = [json.loads(line) for line in f]

total = len(rows)
print(f"Total merged rows: {total}")

# 1. Auditor Flagged Items
print("\n--- 1. AUDITOR FLAGGED ITEMS AUDIT ---")
for target in [
    'the greater good fries', 'l&p soft drink', 'chesdale cheese slices chives', 
    'chesdale cheese slices colby', 'ploughmans bread', 'hubbards muesli', 
    'meadow fresh yoghurt', 'chelsea sugar', 'tip top moments'
]:
    matches = [r for r in rows if target in (r.get('clean_name') or '').lower().replace('\u200b', '')]
    if matches:
        sample = matches[0]
        print(f"  {sample.get('clean_name')[:35]:<35} -> {sample.get('department')} > {sample.get('category')} > {sample.get('sub_category')}")

# 2. Category Quality
missing_cat = sum(1 for r in rows if not r.get('category'))
dept_eq_cat = sum(1 for r in rows if r.get('category') == r.get('department'))
missing_sub = sum(1 for r in rows if not r.get('sub_category'))
print(f"\n--- 2. TAXONOMY COMPLETENESS ---")
print(f"  Missing Category: {missing_cat}")
print(f"  Category == Department (placeholder): {dept_eq_cat}")
print(f"  Missing Subcategory: {missing_sub} ({missing_sub/total*100:.1f}%) [Was 17,025 / 32%]")

# 3. Enrichment
with_desc = sum(1 for r in rows if r.get('description'))
with_ingr = sum(1 for r in rows if r.get('ingredients'))
with_nutr = sum(1 for r in rows if r.get('nutrition'))
with_alg = sum(1 for r in rows if r.get('allergens'))
print(f"\n--- 3. PDP ENRICHMENT STATUS ---")
print(f"  Rows with Description: {with_desc} ({with_desc/total*100:.1f}%)")
print(f"  Rows with Ingredients: {with_ingr} ({with_ingr/total*100:.1f}%) [Live PDP Source Available]")
print(f"  Rows with Nutrition:   {with_nutr}")
print(f"  Rows with Allergens:   {with_alg}")

# 4. Brand Quality
missing_brand = sum(1 for r in rows if not r.get('brand'))
print(f"\n--- 4. BRAND COVERAGE ---")
print(f"  Missing Brand Rows: {missing_brand} ({missing_brand/total*100:.1f}%)")
unbranded_dept = {}
for r in rows:
    if not r.get('brand'):
        d = r.get('department') or 'Unknown'
        unbranded_dept[d] = unbranded_dept.get(d, 0) + 1
print("  Unbranded breakdown by department (loose produce/butchery/bakery):")
for d, c in sorted(unbranded_dept.items(), key=lambda x: x[1], reverse=True)[:5]:
    print(f"    - {d:<20}: {c} rows ({c/missing_brand*100:.1f}% of unbranded)")

# 5. Meat Weights Verification
meat_kg = [r for r in rows if r.get('department') == 'Meat' and r.get('selling_price_basis') == 'per kg']
print(f"\n--- 5. WEIGHTED MEAT & PRODUCE ACCURACY ---")
print(f"  Total Meat per kg rows: {len(meat_kg)}")
for m in ['Beef Mince Prime', 'Chicken Boneless Breast Fillets', 'Chicken Drumsticks', 'Pork Shoulder Chops']:
    match = [r for r in meat_kg if m.lower() in (r.get('clean_name') or '').lower()]
    if match:
        r = match[0]
        print(f"    - {r.get('clean_name')[:35]:<35} | default_wt: {r.get('default_order_weight')} kg | inc: {r.get('quantity_increment')} kg")

# 6. Random 10 Rows Sample
print(f"\n--- 6. RANDOM 10 ROWS SPOT CHECK ---")
random.seed(42)
sample_rows = random.sample(rows, 10)
for r in sample_rows:
    nm = (r.get('clean_name') or '')[:30]
    b = r.get('brand') or 'None'
    d = r.get('department')
    c = r.get('category')
    s = r.get('sub_category') or 'None'
    basis = r.get('selling_price_basis')
    p = r.get('price')
    print(f"  {nm:<30} | Brand: {b:<15} | {d} > {c} > {s} | {basis} | ${p}")
