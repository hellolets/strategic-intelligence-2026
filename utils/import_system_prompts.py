"""
Script para importar System Prompts desde CSV a Airtable.

Uso:
    python import_system_prompts.py system_prompts.csv

El CSV debe tener estos campos:
    Prompt_Name, System_Prompt, Description, Type, Active, Keywords, Priority
"""

import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from pyairtable import Api

# Cargar variables de entorno
load_dotenv()

# Validar variables requeridas
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

if not AIRTABLE_API_KEY:
    raise ValueError("❌ AIRTABLE_API_KEY no está configurada en .env")
if not AIRTABLE_BASE_ID:
    raise ValueError("❌ AIRTABLE_BASE_ID no está configurada en .env")

# Obtener nombre de la tabla desde config.toml o usar default
try:
    import tomllib
except ImportError:
    import tomli as tomllib

config_path = Path(__file__).parent.parent / "config.toml"
if config_path.exists():
    with open(config_path, "rb") as f:
        toml_config = tomllib.load(f)
    prompts_table_name = toml_config.get("airtable", {}).get("prompts_table_name", "System_Prompts")
else:
    prompts_table_name = os.environ.get("AIRTABLE_PROMPTS_TABLE_NAME", "System_Prompts")

print(f"📋 Tabla destino: {prompts_table_name}")
print(f"📋 Base ID: {AIRTABLE_BASE_ID}\n")

# Inicializar Airtable
api = Api(AIRTABLE_API_KEY)
base = api.base(AIRTABLE_BASE_ID)
table = base.table(prompts_table_name)


def convert_active(value):
    """Convierte TRUE/FALSE string a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.upper() in ["TRUE", "1", "YES", "Y", "T"]
    return bool(value)


def convert_priority(value):
    """Convierte Priority a número."""
    try:
        return int(value) if value else 5
    except (ValueError, TypeError):
        return 5


def list_table_fields(table):
    """Lista los campos disponibles en la tabla."""
    try:
        # Obtener un registro de ejemplo para ver los campos
        records = table.all(max_records=1)
        if records:
            fields = records[0].get("fields", {})
            print("📋 Campos disponibles en la tabla:")
            for field_name in sorted(fields.keys()):
                print(f"   - {field_name}")
            return set(fields.keys())
        else:
            # Si no hay registros, intentar crear uno temporal para ver los campos requeridos
            print("⚠️ No hay registros en la tabla. No se pueden listar campos automáticamente.")
            return set()
    except Exception as e:
        print(f"⚠️ Error listando campos: {e}")
        return set()


def import_csv_to_airtable(csv_path: str, update_existing: bool = True, skip_confirmation: bool = False):
    """
    Importa registros desde CSV a Airtable.
    
    Args:
        csv_path: Ruta al archivo CSV
        update_existing: Si True, actualiza registros existentes por Prompt_Name
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"❌ Archivo CSV no encontrado: {csv_path}")

    print(f"📂 Leyendo CSV: {csv_path}\n")

    # Obtener campos disponibles en la tabla
    print("🔍 Verificando campos disponibles en la tabla...")
    available_fields = list_table_fields(table)
    print()  # Línea en blanco
    
    # Leer CSV
    records_to_create = []
    records_to_update = []
    
    # Obtener registros existentes si vamos a actualizar
    existing_records = {}
    if update_existing:
        print("🔍 Obteniendo registros existentes...")
        try:
            all_existing = table.all()
            for record in all_existing:
                prompt_name = record.get("fields", {}).get("Prompt_Name", "")
                if prompt_name:
                    existing_records[prompt_name] = record["id"]
            print(f"   ✅ Encontrados {len(existing_records)} registros existentes\n")
        except Exception as e:
            print(f"   ⚠️ Error obteniendo registros existentes: {e}")
            print("   Continuando sin actualización...\n")
            update_existing = False

    # Leer CSV
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        # Validar campos requeridos
        required_fields = ["Prompt_Name", "System_Prompt", "Description", "Type", "Active", "Keywords", "Priority"]
        csv_fields = reader.fieldnames or []
        missing_fields = [f for f in required_fields if f not in csv_fields]
        
        if missing_fields:
            raise ValueError(
                f"❌ Campos faltantes en CSV: {', '.join(missing_fields)}\n"
                f"   Campos encontrados: {', '.join(csv_fields)}"
            )

        for row_num, row in enumerate(reader, start=2):  # Empezar en 2 (header es línea 1)
            prompt_name = row.get("Prompt_Name", "").strip()
            
            if not prompt_name:
                print(f"   ⚠️ Línea {row_num}: Prompt_Name vacío, saltando...")
                continue

            # Preparar campos para Airtable (solo incluir campos que existen en la tabla)
            fields = {}
            
            # Campos requeridos
            if "Prompt_Name" in available_fields or not available_fields:
                fields["Prompt_Name"] = prompt_name
            if "System_Prompt" in available_fields or not available_fields:
                fields["System_Prompt"] = row.get("System_Prompt", "").strip()
            if "Description" in available_fields or not available_fields:
                fields["Description"] = row.get("Description", "").strip()
            
            # Mapeo Type → Category (si Category existe, usar Type del CSV)
            # Nota: Si Category es un Single select, solo se incluirá si el valor es válido
            type_value = row.get("Type", "General").strip()
            if "Category" in available_fields and type_value:
                # Intentar incluir Category, pero si falla por opciones inválidas, se omitirá
                fields["Category"] = type_value
            elif "Type" in available_fields and type_value:
                fields["Type"] = type_value
            
            # Campos opcionales (solo incluir si existen en la tabla)
            if "Active" in available_fields:
                fields["Active"] = convert_active(row.get("Active", "TRUE"))
            if "Keywords" in available_fields:
                keywords = row.get("Keywords", "").strip()
                if keywords:  # Solo incluir si no está vacío
                    fields["Keywords"] = keywords
            if "Priority" in available_fields:
                fields["Priority"] = convert_priority(row.get("Priority", "5"))

            # Verificar si existe
            if update_existing and prompt_name in existing_records:
                records_to_update.append({
                    "id": existing_records[prompt_name],
                    "fields": fields
                })
            else:
                records_to_create.append({"fields": fields})

    # Mostrar resumen
    print(f"📊 Resumen de importación:")
    print(f"   - Nuevos registros: {len(records_to_create)}")
    print(f"   - Registros a actualizar: {len(records_to_update)}")
    print(f"   - Total: {len(records_to_create) + len(records_to_update)}\n")

    if not records_to_create and not records_to_update:
        print("⚠️ No hay registros para importar.")
        return

    # Confirmar
    if update_existing and not skip_confirmation:
        try:
            response = input("¿Continuar con la importación? (s/n): ").strip().lower()
            if response not in ["s", "si", "sí", "y", "yes"]:
                print("❌ Importación cancelada.")
                return
        except EOFError:
            # Si no hay input disponible (ej: ejecución no interactiva), continuar automáticamente
            print("   ⚠️ No hay input disponible, continuando automáticamente...")

    # Crear nuevos registros
    if records_to_create:
        print(f"\n📝 Creando {len(records_to_create)} nuevo(s) registro(s)...")
        try:
            # Crear registros uno por uno para mejor manejo de errores
            created_count = 0
            for i, record in enumerate(records_to_create, 1):
                try:
                    created = table.create(record["fields"])
                    created_count += 1
                    prompt_name = record["fields"].get("Prompt_Name", "Unknown")
                    print(f"   ✅ [{i}/{len(records_to_create)}] Creado: {prompt_name}")
                except Exception as e:
                    prompt_name = record["fields"].get("Prompt_Name", "Unknown")
                    print(f"   ❌ [{i}/{len(records_to_create)}] Error creando '{prompt_name}': {e}")
                    # Continuar con el siguiente registro
            print(f"\n   ✅ Total creados: {created_count}/{len(records_to_create)}")
        except Exception as e:
            print(f"   ❌ Error en proceso de creación: {e}")
            raise

    # Actualizar registros existentes
    if records_to_update:
        print(f"\n🔄 Actualizando {len(records_to_update)} registro(s) existente(s)...")
        try:
            # Actualizar registros uno por uno para mejor manejo de errores
            updated_count = 0
            for i, record in enumerate(records_to_update, 1):
                try:
                    # Si hay error con Category (opciones inválidas), intentar sin ese campo
                    fields_to_update = record["fields"].copy()
                    prompt_name = fields_to_update.get("Prompt_Name", "Unknown")
                    
                    try:
                        updated = table.update(record["id"], fields_to_update)
                        updated_count += 1
                        print(f"   ✅ [{i}/{len(records_to_update)}] Actualizado: {prompt_name}")
                    except Exception as e:
                        error_str = str(e)
                        # Si el error es por opciones inválidas en Category, intentar sin ese campo
                        if "INVALID_MULTIPLE_CHOICE_OPTIONS" in error_str or "Category" in error_str:
                            if "Category" in fields_to_update:
                                category_value = fields_to_update.pop("Category")
                                print(f"   ⚠️ [{i}/{len(records_to_update)}] '{prompt_name}': Category '{category_value}' no válida, actualizando sin Category...")
                                try:
                                    updated = table.update(record["id"], fields_to_update)
                                    updated_count += 1
                                    print(f"   ✅ [{i}/{len(records_to_update)}] Actualizado: {prompt_name} (sin Category)")
                                except Exception as e2:
                                    print(f"   ❌ [{i}/{len(records_to_update)}] Error actualizando '{prompt_name}': {e2}")
                            else:
                                print(f"   ❌ [{i}/{len(records_to_update)}] Error actualizando '{prompt_name}': {e}")
                        else:
                            print(f"   ❌ [{i}/{len(records_to_update)}] Error actualizando '{prompt_name}': {e}")
                except Exception as e:
                    prompt_name = record["fields"].get("Prompt_Name", "Unknown")
                    print(f"   ❌ [{i}/{len(records_to_update)}] Error procesando '{prompt_name}': {e}")
            print(f"\n   ✅ Total actualizados: {updated_count}/{len(records_to_update)}")
        except Exception as e:
            print(f"   ❌ Error en proceso de actualización: {e}")
            raise

    print(f"\n✅ Importación completada exitosamente!")
    print(f"   - {len(records_to_create)} nuevo(s) registro(s) creado(s)")
    print(f"   - {len(records_to_update)} registro(s) actualizado(s)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python import_system_prompts.py <ruta_al_csv> [--yes]")
        print("\nEjemplo:")
        print("  python import_system_prompts.py system_prompts.csv")
        print("  python import_system_prompts.py system_prompts.csv --yes  # Sin confirmación")
        sys.exit(1)

    csv_file = sys.argv[1]
    skip_confirmation = "--yes" in sys.argv or "-y" in sys.argv
    
    try:
        import_csv_to_airtable(csv_file, update_existing=True, skip_confirmation=skip_confirmation)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
