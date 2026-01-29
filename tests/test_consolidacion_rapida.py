#!/usr/bin/env python3
"""
Script de test rápido para generar documento final sin llamadas a API.
Usa datos ya recopilados en Airtable y modo TEST offline.

Uso:
    python test_consolidacion_rapida.py [proyecto_id]
    
Si no se proporciona proyecto_id, busca el primer proyecto con items completados.
"""

import os
import sys

# Configurar modo TEST offline ANTES de importar módulos
os.environ["ENV_PROFILE"] = "TEST"
os.environ["TEST_ONLINE"] = "0"  # Offline mode - usa LocalStubLLM

# Importar después de configurar variables de entorno
from deep_research.processor import consolidate_specific_project
from deep_research.config import proyectos_table, items_table

def find_project_with_completed_items():
    """
    Busca el primer proyecto que tenga items con Final_Report completado.
    """
    print("🔍 Buscando proyecto con items completados...")
    
    # Buscar proyectos con Status='Todo' o 'Done'
    try:
        # Intentar buscar proyectos con diferentes status
        proyectos = []
        for status in ["Todo", "Done", "Processing"]:
            try:
                found = proyectos_table.all(formula=f"{{Status}}='{status}'")
                proyectos.extend(found)
            except Exception:
                continue
        
        # Si no se encontró nada, buscar todos
        if not proyectos:
            proyectos = proyectos_table.all()
        
        for proyecto in proyectos:
            proyecto_id = proyecto["id"]
            fields = proyecto.get("fields", {})
            project_name = fields.get("Project_Name", fields.get("Nombre", "Sin nombre"))
            
            # Buscar items relacionados (probar diferentes nombres de campo)
            related_items = (
                fields.get("Items_Relacionados", []) or 
                fields.get("Items_NEW", []) or 
                fields.get("Items", [])
            )
            
            if not related_items:
                continue
            
            # Verificar que al menos un item tenga Final_Report
            completed_count = 0
            for item_id in related_items:
                try:
                    item = items_table.get(item_id)
                    if item:
                        item_fields = item.get("fields", {})
                        final_report = item_fields.get("Final_Report", "")
                        if final_report and len(final_report) > 100:  # Al menos 100 caracteres
                            completed_count += 1
                except Exception:
                    continue
            
            if completed_count > 0:
                print(f"✅ Encontrado proyecto: {project_name}")
                print(f"   ID: {proyecto_id}")
                print(f"   Items con reportes: {completed_count}/{len(related_items)}")
                return proyecto_id, project_name, fields
            else:
                print(f"   ⏭️  Proyecto '{project_name}' tiene {len(related_items)} items pero ninguno con Final_Report completo")
        
        print("⚠️ No se encontró ningún proyecto con items completados")
        print("💡 Sugerencia: Asegúrate de que haya items con Status='Done' y Final_Report completo")
        return None, None, None
        
    except Exception as e:
        print(f"❌ Error buscando proyecto: {e}")
        return None, None, None

def main():
    print("=" * 100)
    print("🧪 TEST RÁPIDO: Generación de Documento Final (SIN LLAMADAS A API)")
    print("=" * 100)
    print()
    print("Configuración:")
    print("   ✅ ENV_PROFILE=TEST (modo test)")
    print("   ✅ TEST_ONLINE=0 (offline - usa LocalStubLLM)")
    print("   ✅ Sin llamadas a API de búsqueda")
    print("   ✅ Usa datos ya recopilados en Airtable")
    print()
    
    # Obtener proyecto_id de argumentos o buscar uno
    if len(sys.argv) > 1:
        proyecto_id = sys.argv[1]
        try:
            proyecto = proyectos_table.get(proyecto_id)
            if not proyecto:
                print(f"❌ No se encontró proyecto con ID: {proyecto_id}")
                return
            fields = proyecto.get("fields", {})
            project_name = fields.get("Project_Name", fields.get("Nombre", "Sin nombre"))
            print(f"📋 Usando proyecto especificado: {project_name}")
        except Exception as e:
            print(f"❌ Error obteniendo proyecto {proyecto_id}: {e}")
            return
    else:
        proyecto_id, project_name, fields = find_project_with_completed_items()
        if not proyecto_id:
            print("\n💡 Uso: python test_consolidacion_rapida.py [proyecto_id]")
            print("   O asegúrate de que haya proyectos con items completados en Airtable")
            return
    
    print()
    print("=" * 100)
    print(f"🔄 Iniciando consolidación para: {project_name}")
    print("=" * 100)
    print()
    
    try:
        # Ejecutar consolidación
        consolidate_specific_project(proyecto_id, project_name, fields)
        
        print()
        print("=" * 100)
        print("✅ TEST COMPLETADO")
        print("=" * 100)
        print()
        print("📄 El documento Word debería estar en: reports/")
        print("🔍 Busca archivos con el nombre del proyecto")
        print()
        print("💡 Nota: En modo TEST offline, el consolidador usa LocalStubLLM")
        print("   que genera contenido determinístico sin llamadas a API.")
        
    except Exception as e:
        print()
        print("=" * 100)
        print("❌ ERROR EN TEST")
        print("=" * 100)
        print(f"Error: {e}")
        import traceback
        print(f"\nTraceback completo:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
