import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('exports/freshchoice_all_branches_merged.jsonl', 'r', encoding='utf-8') as f:
    rows = [json.loads(line) for line in f]

total = len(rows)

# 1. Weighted products check
kg_rows = [r for r in rows if r.get('selling_price_basis') == 'per kg']
weights = set(r.get('default_order_weight') for r in kg_rows)
increments = set(r.get('quantity_increment') for r in kg_rows)

print('=== 1. WEIGHTED PRODUCTS ===')
print('Total per kg rows:', len(kg_rows))
print('Distinct default_order_weights:', weights)
print('Distinct quantity_increments:', increments)

samples = ['Bananas', 'Ambrosia', 'Mandarins', 'Potatoes Loose Washed White', 'Kumara Red', 'Oranges Imported', 'Carrots Loose']
for name in samples:
    matches = [r for r in kg_rows if name.lower() in r.get('clean_name', '').lower()]
    if matches:
        m = matches[0]
        cname = m.get('clean_name')[:35]
        print(f"{cname:<35} | basis: {m.get('selling_price_basis')} | unit: {m.get('unit_of_measure')} | default: {m.get('default_order_weight')} kg | inc: {m.get('quantity_increment')} kg")

# Check false loose matches
false_tea = [r for r in rows if 'bell loose leaf tea' in r.get('clean_name', '').lower()]
if false_tea:
    print('Bell Loose Leaf Tea:', false_tea[0].get('selling_price_basis'), '| unit:', false_tea[0].get('unit_of_measure'))

false_bun = [r for r in rows if 'pizza bun loose' in r.get('clean_name', '').lower()]
if false_bun:
    print('Small Pizza Bun Loose:', false_bun[0].get('selling_price_basis'), '| unit:', false_bun[0].get('unit_of_measure'))

# 2. Category check
same_cat = sum(1 for r in rows if r.get('department') and r.get('department') == r.get('category'))
print('\n=== 2. CATEGORY CHECKS ===')
print('Rows where department == category:', same_cat, '(Target: 0)')

cromwell_mocha = [r for r in rows if r.get('branch_id') == 'cromwell' and 'mocha' in r.get('clean_name', '').lower() and 'nescafe' in r.get('clean_name', '').lower()]
if cromwell_mocha:
    cm = cromwell_mocha[0]
    print(f"Cromwell Mocha: Dept='{cm.get('department')}', Cat='{cm.get('category')}', Sub='{cm.get('sub_category')}'")

# 3. Enrichment check
desc_cnt = sum(1 for r in rows if r.get('description'))
ing_cnt = sum(1 for r in rows if r.get('ingredients'))
nut_cnt = sum(1 for r in rows if r.get('nutrition'))
print('\n=== 3. ENRICHMENT CHECKS ===')
print('Rows with genuine description:', desc_cnt)
print('Rows with genuine ingredients:', ing_cnt)
print('Rows with genuine nutrition:', nut_cnt)
