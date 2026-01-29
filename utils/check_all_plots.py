from deep_research.config import items_table, proyectos_table

project_id = 'recQIhEx25GYThGkQ'
project = proyectos_table.get(project_id)
item_ids = project.get('fields', {}).get('Items_Relacionados', [])

print(f"Checking {len(item_ids)} items for plots...")
found_any = False
for iid in item_ids:
    item = items_table.get(iid)
    report = item.get('fields', {}).get('Final_Report', '')
    if '[[PLOT:' in report:
        print(f"FOUND PLOT in Item {iid}")
        found_any = True

if not found_any:
    print("No plots found in any item.")
