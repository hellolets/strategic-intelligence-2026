from deep_research.config import proyectos_table, items_table

project_id = 'recQIhEx25GYThGkQ'
project = proyectos_table.get(project_id)
item_ids = project.get('fields', {}).get('Items_Relacionados', [])

print(f"Project: {project.get('fields', {}).get('Project_Name')}")
print(f"Items: {len(item_ids)}")

all_done = True
for iid in item_ids:
    try:
        item = items_table.get(iid)
        fields = item.get('fields', {})
        topic = fields.get('Topic', 'N/A')
        status = fields.get('Status', 'N/A')
        print(f"{iid} - {topic} - {status}")
        if '[[PLOT:' in fields.get('Final_Report', ''):
            print(f"  -> 📊 HAS PLOTS!")
        if status != 'Done':
            all_done = False

    except Exception as e:
        print(f"Error getting item {iid}: {e}")
        all_done = False

print(f"\nAll items Done: {all_done}")
