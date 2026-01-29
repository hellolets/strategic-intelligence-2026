#!/usr/bin/env python3
"""
Script de prueba para verificar la carga y parsing del contexto desde Airtable.
Simula exactamente lo que hace el código principal.
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
print("🧪 PRUEBA: CARGA Y PARSING DE CONTEXTO DESDE AIRTABLE")
print("=" * 80)
print()

# Importar módulos necesarios
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from deep_research.config import proyectos_table, CONTEXT_SOURCE
    from deep_research.doc_parser import get_project_context
    from deep_research.context_manager import extract_context_from_document, ProjectContext
    print("✅ Módulos importados correctamente")
    print()
except Exception as e:
    print(f"❌ Error importando módulos: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"📋 Modo de contexto configurado: {CONTEXT_SOURCE}")
print()

# Obtener el primer proyecto
try:
    all_projects = proyectos_table.all()
    if len(all_projects) == 0:
        print("❌ No hay proyectos en la tabla")
        sys.exit(1)
    
    project = all_projects[0]
    project_id = project.get("id", "N/A")
    fields = project.get("fields", {})
    project_name = fields.get("Nombre") or fields.get("Name") or fields.get("Title") or "Sin nombre"
    
    print(f"📋 Proyecto seleccionado: {project_name}")
    print(f"🆔 ID: {project_id}")
    print()
    
    # Intentar múltiples nombres de campo para compatibilidad (igual que en manager.py)
    context_attachments_raw = (
        fields.get("Context") or 
        fields.get("context") or 
        fields.get("Contexto") or 
        fields.get("contexto") or 
        None
    )
    
    print("=" * 80)
    print("PASO 1: VERIFICAR CAMPO 'Context'")
    print("=" * 80)
    print()
    
    if context_attachments_raw is None:
        print("❌ Campo 'Context' no encontrado en ninguna variante")
        print("   Verificando campos disponibles...")
        print(f"   Campos: {list(fields.keys())}")
        sys.exit(1)
    
    print(f"✅ Campo 'Context' encontrado")
    print(f"   Tipo: {type(context_attachments_raw).__name__}")
    
    # Normalizar el formato de attachments (igual que en manager.py)
    context_attachments = []
    if context_attachments_raw:
        if isinstance(context_attachments_raw, list):
            context_attachments = context_attachments_raw
        elif isinstance(context_attachments_raw, dict):
            context_attachments = [context_attachments_raw]
        elif isinstance(context_attachments_raw, str):
            try:
                import json
                parsed = json.loads(context_attachments_raw)
                if isinstance(parsed, list):
                    context_attachments = parsed
                elif isinstance(parsed, dict):
                    context_attachments = [parsed]
            except:
                print(f"   ⚠️ Campo Context es string pero no es JSON válido")
        else:
            print(f"   ⚠️ Campo Context tiene tipo inesperado: {type(context_attachments_raw).__name__}")
    
    print(f"   Adjuntos normalizados: {len(context_attachments)}")
    if len(context_attachments) > 0:
        first_att = context_attachments[0]
        print(f"   📎 Primer adjunto: {first_att.get('filename', 'N/A')}")
        print(f"   🔗 URL: {first_att.get('url', 'N/A')[:80]}...")
    print()
    
    # PASO 2: Cargar contexto usando get_project_context (igual que en manager.py)
    print("=" * 80)
    print("PASO 2: CARGAR CONTEXTO CON get_project_context()")
    print("=" * 80)
    print()
    
    try:
        project_specific_context = get_project_context(
            project_id=project_id,
            attachments=context_attachments
        )
        
        if project_specific_context and project_specific_context.strip():
            print(f"✅ Contexto cargado exitosamente")
            print(f"   Longitud: {len(project_specific_context)} caracteres")
            print()
            print("📄 Preview del contexto (primeros 500 caracteres):")
            print("-" * 80)
            print(project_specific_context[:500])
            print("-" * 80)
            print()
        else:
            print("❌ Contexto cargado pero está vacío")
            print("   Esto indica un problema en el parsing del documento")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error cargando contexto: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # PASO 3: Extraer contexto estructurado con ContextManager
    print("=" * 80)
    print("PASO 3: EXTRAER CONTEXTO ESTRUCTURADO CON ContextManager")
    print("=" * 80)
    print()
    
    try:
        from deep_research.config import llm_planner
        
        # Usar LLM si el contexto es largo (>500 caracteres)
        use_llm = len(project_specific_context) > 500
        llm = llm_planner if use_llm else None
        
        if use_llm:
            print("🤖 Usando LLM para extracción inteligente (contexto >500 caracteres)")
        else:
            print("🔍 Usando extracción por patrones (contexto <=500 caracteres)")
        print()
        
        context = extract_context_from_document(
            document_text=project_specific_context,
            project_name=project_name,
            llm=llm
        )
        
        if context.is_empty():
            print("⚠️ Contexto estructurado está VACÍO")
            print("   El documento no contiene información suficiente para extraer:")
            print("   - Sector (defense, infrastructure, energy, technology)")
            print("   - Competidores (ACS, Acciona, Vinci, etc.)")
            print("   - Geografía (Spain, Europe, USA, etc.)")
            print()
            print("   Esto significa que el ContextManager NO se activará")
            print("   y el sistema funcionará en modo legacy (sin variantes)")
        else:
            print("✅ Contexto estructurado extraído correctamente:")
            print()
            print(f"   📊 Sector: {context.sector or 'No detectado'}")
            print(f"   🌍 Geografía: {context.geography or 'No detectada'}")
            print(f"   🏢 Competidores: {context.competitors or 'No detectados'}")
            print(f"   🏛️  Cliente: {context.client_company or 'No detectado'}")
            print()
            if context.entity_map:
                print("   🔗 Entity Map (desambiguación):")
                for entity, meaning in context.entity_map.items():
                    print(f"      - {entity}: {meaning}")
            print()
            if context.disambiguation_negatives:
                print("   🚫 Exclusiones (disambiguación):")
                for entity, negatives in context.disambiguation_negatives.items():
                    print(f"      - {entity}: excluir {', '.join(negatives[:3])}")
            print()
            if context.query_suffix:
                print(f"   📝 Query Suffix: {context.query_suffix[:100]}...")
            print()
            print("✅ El ContextManager se ACTIVARÁ y generará variantes de queries")
            
    except Exception as e:
        print(f"❌ Error extrayendo contexto estructurado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("=" * 80)
    print("✅ PRUEBA COMPLETADA")
    print("=" * 80)
    print()
    print("RESUMEN:")
    print("   1. ✅ Campo 'Context' encontrado y leído correctamente")
    print("   2. ✅ Documento descargado y parseado correctamente")
    print("   3. ✅ Contexto estructurado extraído correctamente")
    print()
    if not context.is_empty():
        print("✅ El sistema debería funcionar correctamente con ContextManager activo")
    else:
        print("⚠️ El ContextManager NO se activará porque el contexto está vacío")
        print("   Considera mejorar el documento de contexto añadiendo:")
        print("   - Menciones de sector (defense, infrastructure, etc.)")
        print("   - Menciones de competidores (ACS, Acciona, etc.)")
        print("   - Menciones de geografía (Spain, Europe, etc.)")
    print()

except Exception as e:
    print(f"❌ Error general: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
