"""
Script de prueba para verificar que el matcher funciona correctamente
con la nueva estructura de la tabla System_Prompts.
"""

import os
from dotenv import load_dotenv
from pyairtable import Api

load_dotenv()

# Inicializar Airtable
api = Api(os.environ.get('AIRTABLE_API_KEY'))
base = api.base(os.environ.get('AIRTABLE_BASE_ID'))
prompts_table = base.table('System_Prompts')

print("=" * 70)
print("🔍 VERIFICACIÓN DEL MATCHER CON SYSTEM_PROMPTS")
print("=" * 70)
print()

# 1. Cargar todos los agentes
print("1️⃣ Cargando agentes desde System_Prompts...")
all_agents = prompts_table.all()

if not all_agents:
    print("   ❌ No se encontraron agentes")
    exit(1)

print(f"   ✅ Encontrados {len(all_agents)} agente(s)\n")

# 2. Verificar qué campos se están usando
print("2️⃣ Verificando campos usados por el matcher...")
print()

agents_info = []
campos_faltantes = []
campos_activos = set()

for agent_record in all_agents:
    agent_id = agent_record["id"]
    fields = agent_record.get("fields", {})
    
    # Campos que el matcher usa
    prompt_name = fields.get("Prompt_Name", "Sin nombre")
    description = fields.get("Description", "Sin descripción")
    
    # Campos adicionales que podrían mejorar el matching
    active = fields.get("Active", True)
    agent_type = fields.get("Type") or fields.get("Category", "General")
    keywords = fields.get("Keywords", "")
    
    # Verificar campos obligatorios
    if not prompt_name or prompt_name == "Sin nombre":
        campos_faltantes.append(f"❌ {agent_id}: Prompt_Name vacío")
    if not description or description == "Sin descripción":
        campos_faltantes.append(f"❌ {agent_id}: Description vacía")
    
    # Acumular campos encontrados
    campos_activos.update(fields.keys())
    
    agents_info.append({
        "id": agent_id,
        "name": prompt_name,
        "description": description,
        "active": active,
        "type": agent_type,
        "keywords": keywords
    })

print("   📋 Campos encontrados en la tabla:")
for campo in sorted(campos_activos):
    print(f"      - {campo}")

print()
print("   📊 Campos usados por el matcher:")
print("      ✅ Prompt_Name (obligatorio)")
print("      ✅ Description (obligatorio)")
print()

if campos_faltantes:
    print("   ⚠️ PROBLEMAS ENCONTRADOS:")
    for problema in campos_faltantes:
        print(f"      {problema}")
    print()
else:
    print("   ✅ Todos los campos obligatorios están presentes\n")

# 3. Mostrar agentes cargados (como los vería el matcher)
print("3️⃣ Agentes que verá el matcher:")
print()

for i, agent in enumerate(agents_info, 1):
    status = "✅ Activo" if agent["active"] else "❌ Inactivo"
    print(f"   {i}. {agent['name']} ({status})")
    print(f"      Tipo: {agent['type']}")
    print(f"      Descripción: {agent['description'][:80]}...")
    if agent['keywords']:
        print(f"      Keywords: {agent['keywords'][:60]}...")
    print()

# 4. Verificar si hay agentes inactivos
inactivos = [a for a in agents_info if not a["active"]]
if inactivos:
    print(f"   ⚠️ ADVERTENCIA: {len(inactivos)} agente(s) inactivo(s) encontrado(s)")
    print("      El matcher los incluirá, pero el manager mostrará advertencia al usarlos")
    print()

# 5. Simular el prompt que se envía al LLM
print("4️⃣ Simulando prompt que se envía al matcher:")
print()
print("   Tema de ejemplo: 'Análisis del mercado de inteligencia artificial en Europa'")
print()
print("   Agentes disponibles (formato que ve el LLM):")
agents_description = "\n".join([
    f"   {i + 1}. **{agent['name']}**: {agent['description']}"
    for i, agent in enumerate(agents_info)
])
print(agents_description)
print()

# 6. Verificar que el formato es correcto
print("5️⃣ Verificación de formato:")
print()

problemas_formato = []
for i, agent in enumerate(agents_info, 1):
    if len(agent['description']) < 10:
        problemas_formato.append(f"   ⚠️ {agent['name']}: Descripción muy corta ({len(agent['description'])} chars)")
    if not agent['description'].strip():
        problemas_formato.append(f"   ❌ {agent['name']}: Descripción vacía")

if problemas_formato:
    print("   PROBLEMAS DE FORMATO:")
    for problema in problemas_formato:
        print(problema)
    print()
else:
    print("   ✅ Todas las descripciones tienen formato correcto\n")

# 7. Recomendaciones
print("6️⃣ Recomendaciones:")
print()

recomendaciones = []

# Verificar si se está usando Active para filtrar
if not any(not a["active"] for a in agents_info):
    recomendaciones.append("   ℹ️  Todos los agentes están activos (campo Active no se usa)")

# Verificar si hay agentes con descripciones muy similares
descripciones = [a['description'].lower() for a in agents_info]
if len(descripciones) != len(set(descripciones)):
    recomendaciones.append("   ⚠️  Hay descripciones duplicadas o muy similares")

# Verificar si se podría mejorar con Keywords
agentes_sin_keywords = [a for a in agents_info if not a['keywords']]
if agentes_sin_keywords:
    recomendaciones.append(f"   💡 {len(agentes_sin_keywords)} agente(s) sin Keywords (podrían mejorar matching)")

# Verificar si Type/Category se está usando
tipos_unicos = set(a['type'] for a in agents_info)
if len(tipos_unicos) > 1:
    recomendaciones.append(f"   ✅ Hay {len(tipos_unicos)} tipos diferentes de agentes (buena diversidad)")

if recomendaciones:
    for rec in recomendaciones:
        print(rec)
else:
    print("   ✅ Todo parece estar bien configurado")

print()
print("=" * 70)
print("✅ VERIFICACIÓN COMPLETADA")
print("=" * 70)
print()
print("📝 Resumen:")
print(f"   - Total agentes: {len(agents_info)}")
print(f"   - Agentes activos: {len([a for a in agents_info if a['active']])}")
print(f"   - Agentes inactivos: {len([a for a in agents_info if not a['active']])}")
print(f"   - Tipos únicos: {len(tipos_unicos)}")
print(f"   - Campos en tabla: {len(campos_activos)}")
print()
