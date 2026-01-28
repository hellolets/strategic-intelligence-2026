#!/usr/bin/env python3
"""
Script de diagnóstico para verificar si el campo 'Context' existe en Airtable
y qué contiene.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

private_context_env = Path(__file__).parent / "private_context" / ".env"
if private_context_env.exists():
    load_dotenv(private_context_env)

print("=" * 80)
print("🔍 DIAGNÓSTICO: DETECTANDO CONTEXTO DESDE AIRTABLE")
print("=" * 80)
print()

# Obtener credenciales directamente desde variables de entorno
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

if not AIRTABLE_API_KEY:
    print("❌ ERROR: AIRTABLE_API_KEY no está configurada")
    sys.exit(1)
if not AIRTABLE_BASE_ID:
    print("❌ ERROR: AIRTABLE_BASE_ID no está configurada")
    sys.exit(1)

print("✅ Credenciales de Airtable encontradas")
print()

# Importar pyairtable
try:
    from pyairtable import Table
except ImportError:
    print("❌ ERROR: pyairtable no está instalado")
    print("   Instala con: pip install pyairtable")
    sys.exit(1)

# Obtener nombre de tabla desde config.toml
try:
    import tomllib
except ImportError:
    import tomli as tomllib

config_path = Path(__file__).parent / "deep_research" / "config.toml"
if config_path.exists():
    with open(config_path, "rb") as f:
        toml_config = tomllib.load(f)
    proyectos_table_name = toml_config.get("airtable", {}).get("proyectos_table_name", "Proyectos")
else:
    proyectos_table_name = "Proyectos"

print(f"📋 Tabla de proyectos: '{proyectos_table_name}'")
print()

# Conectar a Airtable
try:
    proyectos_table = Table(AIRTABLE_API_KEY, AIRTABLE_BASE_ID, proyectos_table_name)
    # Verificar conexión leyendo un registro
    test_records = proyectos_table.all(max_records=1)
    print(f"✅ Conexión exitosa a Airtable")
    print()
except Exception as e:
    print(f"❌ Error conectando a Airtable: {e}")
    sys.exit(1)

# Obtener todos los proyectos
try:
    all_projects = proyectos_table.all()
    print(f"✅ Encontrados {len(all_projects)} proyecto(s)")
    print()
    
    if len(all_projects) == 0:
        print("⚠️ No hay proyectos en la tabla")
        sys.exit(0)
    
    # Buscar proyectos con campo Context
    projects_with_context = []
    for project in all_projects:
        fields = project.get("fields", {})
        project_name = fields.get("Nombre") or fields.get("Name") or fields.get("Title") or "Sin nombre"
        project_id = project.get("id", "N/A")
        
        # Verificar todas las variantes del campo Context
        context_field = None
        context_field_name = None
        for field_name in ["Context", "context", "Contexto", "contexto"]:
            if field_name in fields:
                context_field = fields[field_name]
                context_field_name = field_name
                break
        
        if context_field is not None:
            context_type = type(context_field).__name__
            context_info = {
                "id": project_id,
                "name": project_name,
                "field_name": context_field_name,
                "field_type": context_type,
                "field_value": context_field
            }
            projects_with_context.append(context_info)
    
    if projects_with_context:
        print("=" * 80)
        print(f"✅ ENCONTRADOS {len(projects_with_context)} PROYECTO(S) CON CAMPO 'Context'")
        print("=" * 80)
        print()
        for i, proj in enumerate(projects_with_context, 1):
            print(f"{i}. 📋 Proyecto: {proj['name']}")
            print(f"   🆔 ID: {proj['id']}")
            print(f"   📝 Campo: '{proj['field_name']}'")
            print(f"   🔤 Tipo: {proj['field_type']}")
            print()
            
            # Analizar el contenido
            field_value = proj['field_value']
            if isinstance(field_value, list):
                print(f"   📦 Contenido: Lista con {len(field_value)} elemento(s)")
                if len(field_value) > 0:
                    first_item = field_value[0]
                    print(f"   📦 Primer elemento: tipo={type(first_item).__name__}")
                    if isinstance(first_item, dict):
                        print(f"   🔑 Keys: {list(first_item.keys())}")
                        if 'filename' in first_item:
                            print(f"   📎 Archivo: {first_item.get('filename', 'N/A')}")
                        if 'url' in first_item:
                            url = first_item.get('url', '')
                            print(f"   🔗 URL: {url[:80]}...")
                        if 'size' in first_item:
                            print(f"   📊 Tamaño: {first_item.get('size', 'N/A')} bytes")
                print()
            elif isinstance(field_value, dict):
                print(f"   📦 Contenido: Dict con keys: {list(field_value.keys())}")
                if 'filename' in field_value:
                    print(f"   📎 Archivo: {field_value.get('filename', 'N/A')}")
                if 'url' in field_value:
                    url = field_value.get('url', '')
                    print(f"   🔗 URL: {url[:80]}...")
                print()
            elif isinstance(field_value, str):
                print(f"   📦 Contenido: String ({len(field_value)} caracteres)")
                print(f"   📄 Preview: {field_value[:200]}...")
                print()
            else:
                print(f"   📦 Contenido: {str(field_value)[:200]}...")
                print()
    else:
        print("=" * 80)
        print("❌ NO SE ENCONTRARON PROYECTOS CON CAMPO 'Context'")
        print("=" * 80)
        print()
        print("Verificando campos disponibles en el primer proyecto...")
        if all_projects:
            first_project = all_projects[0]
            fields = first_project.get("fields", {})
            project_name = fields.get("Nombre") or fields.get("Name") or fields.get("Title") or "Sin nombre"
            print(f"📋 Proyecto ejemplo: {project_name}")
            print(f"🔑 Campos disponibles: {list(fields.keys())}")
            print()
            # Buscar campos relacionados
            related_fields = [k for k in fields.keys() if 'context' in k.lower() or 'attach' in k.lower() or 'doc' in k.lower()]
            if related_fields:
                print(f"💡 Campos relacionados encontrados: {related_fields}")
                for field_name in related_fields:
                    field_value = fields[field_name]
                    print(f"   - '{field_name}': tipo={type(field_value).__name__}")
            else:
                print("⚠️ No se encontraron campos relacionados con 'context', 'attach' o 'doc'")
    
except Exception as e:
    print(f"❌ Error leyendo proyectos: {e}")
    import traceback
    traceback.print_exc()

print("=" * 80)
