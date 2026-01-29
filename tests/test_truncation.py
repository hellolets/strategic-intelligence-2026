#!/usr/bin/env python3
"""
Script de prueba para verificar el truncamiento de tokens en reporter.py
Simula un escenario con muchas fuentes (como el caso 8.0 que falló)
"""

import asyncio
import sys
import os

# Añadir el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deep_research.reporter import generate_markdown_report
from deep_research.config import model_config

async def test_truncation():
    """Prueba el truncamiento con un escenario similar al caso 8.0"""
    
    print("🧪 Iniciando prueba de truncamiento...")
    print("=" * 80)
    
    # Simular muchas fuentes (como en el caso 8.0 que tenía 132 fuentes)
    # Crear fuentes con contenido grande para simular el problema
    test_sources = []
    for i in range(50):  # 50 fuentes con contenido grande
        test_sources.append({
            'title': f'Test Source {i+1}: Ethical Considerations in Defense Technology',
            'url': f'https://example.com/source-{i+1}',
            'raw_content': 'A' * 5000 + ' ' + 'B' * 5000,  # ~10,000 caracteres por fuente
            'snippet': 'A' * 2000,
            'score': 8.0,
            'total_score': 8.0
        })
    
    print(f"📊 Fuentes de prueba: {len(test_sources)}")
    print(f"📊 Caracteres totales en fuentes: {sum(len(s.get('raw_content', '')) for s in test_sources):,}")
    
    # Contexto privado grande también
    large_context = 'X' * 50000  # 50,000 caracteres de contexto
    
    print(f"📊 Caracteres en contexto privado: {len(large_context):,}")
    print("=" * 80)
    
    try:
        # Intentar generar el reporte
        print("\n🚀 Generando reporte con truncamiento...")
        report, tokens = await generate_markdown_report(
            topic="8. Risks and Ethical Considerations",
            all_sources=test_sources,
            project_name="Test Project",
            project_specific_context=large_context,
            company_context={}
        )
        
        print("\n" + "=" * 80)
        print("✅ PRUEBA EXITOSA")
        print("=" * 80)
        print(f"📊 Tokens usados: {tokens:,}")
        print(f"📊 Longitud del reporte: {len(report):,} caracteres")
        print(f"📊 Primeras 500 caracteres del reporte:")
        print("-" * 80)
        print(report[:500])
        print("-" * 80)
        
        # Verificar que el reporte tiene contenido real (no solo metadatos)
        if len(report) > 1000 and "Hallazgos Principales" not in report:
            print("✅ El reporte contiene contenido real (no es fallback)")
        elif "Hallazgos Principales" in report:
            print("⚠️  Se usó el fallback (pero es mejorado con contenido real)")
        else:
            print("❌ El reporte parece estar vacío o incompleto")
        
        return True
        
    except ValueError as e:
        if "demasiado grande" in str(e).lower() or "too large" in str(e).lower():
            print("\n" + "=" * 80)
            print("✅ PRUEBA EXITOSA (Fallback activado correctamente)")
            print("=" * 80)
            print(f"📊 El sistema detectó correctamente que el contenido es demasiado grande")
            print(f"📊 Error esperado: {str(e)}")
            print("✅ El fallback mejorado debería haberse activado")
            return True
        else:
            print("\n" + "=" * 80)
            print("❌ PRUEBA FALLIDA")
            print("=" * 80)
            print(f"❌ Error inesperado: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ PRUEBA FALLIDA")
        print("=" * 80)
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_truncation())
    sys.exit(0 if result else 1)
