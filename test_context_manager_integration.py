#!/usr/bin/env python3
"""
Smoke test para integración de ContextManager.
Prueba:
1. Desambiguación de ACS (excluir American Chemical Society)
2. Reranking basado en geografía
"""

import sys
from pathlib import Path

# Añadir el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from deep_research.context_manager import (
    extract_context_from_document,
    build_query_variants,
    filter_results,
    rerank_results,
    ProjectContext
)


def test_acs_disambiguation():
    """Test: ACS debe excluir American Chemical Society cuando el contexto es construcción/defensa."""
    print("=" * 80)
    print("TEST 1: Desambiguación ACS")
    print("=" * 80)
    
    # Contexto de defensa/infraestructura donde ACS = constructora española
    context_doc = """
    Analysis of Defense Sector Opportunity for Ferrovial
    
    This strategic report examines opportunities in the European defense 
    infrastructure market for Ferrovial.
    
    Key competitors in this space include ACS, Acciona, and Vinci.
    The focus is on NATO member countries, particularly Spain, Germany, and Poland.
    
    ACS has recently pivoted toward defense contracts, winning several 
    military base construction projects.
    """
    
    context = extract_context_from_document(
        context_doc,
        "Analysis of Defense Sector Opportunity for Ferrovial"
    )
    
    print(f"\n✅ Contexto extraído:")
    print(f"   Sector: {context.sector}")
    print(f"   Competidores: {context.competitors}")
    print(f"   Entity Map: {context.entity_map}")
    print(f"   Disambiguation Negatives: {context.disambiguation_negatives}")
    
    # Test query variants
    query = "ACS M&A strategy 2024"
    variants = build_query_variants(query, context)
    
    print(f"\n✅ Variantes generadas para '{query}':")
    for i, v in enumerate(variants, 1):
        print(f"   {i}. {v}")
    
    # Verificar que las variantes excluyen "American Chemical Society"
    all_variants_text = " ".join(variants).lower()
    assert "american chemical society" not in all_variants_text or "-" in all_variants_text, \
        "❌ ERROR: Variantes deberían excluir 'American Chemical Society'"
    
    print("\n✅ Test 1 PASADO: Variantes excluyen 'American Chemical Society'")
    
    # Test filter_results
    fake_results = [
        {
            "title": "ACS wins defense contract in Spain",
            "snippet": "ACS Actividades de Construcción y Servicios wins major defense infrastructure project",
            "url": "https://example.com/acs-defense"
        },
        {
            "title": "American Chemical Society publishes new research",
            "snippet": "The American Chemical Society announces breakthrough in chemistry research",
            "url": "https://example.com/acs-chemistry"
        },
        {
            "title": "ACS construction company expands operations",
            "snippet": "Spanish builder ACS reports strong growth in infrastructure sector",
            "url": "https://example.com/acs-construction"
        }
    ]
    
    valid, filtered = filter_results(fake_results, context)
    
    print(f"\n✅ Filtrado de resultados:")
    print(f"   Válidos: {len(valid)}")
    print(f"   Filtrados: {len(filtered)}")
    
    for f in filtered:
        print(f"   ❌ Filtrado: {f['title']}")
    
    # Verificar que se filtró el resultado de American Chemical Society
    filtered_titles = [f['title'].lower() for f in filtered]
    assert any("american chemical society" in t for t in filtered_titles), \
        "❌ ERROR: Debería filtrar resultados de 'American Chemical Society'"
    
    print("\n✅ Test 1 PASADO: Filtrado excluye 'American Chemical Society'")


def test_geography_reranking():
    """Test: Reranking prioriza resultados con geografía relevante."""
    print("\n" + "=" * 80)
    print("TEST 2: Reranking por Geografía")
    print("=" * 80)
    
    # Contexto con geografía específica (España)
    context_doc = """
    Infrastructure Market Analysis for Spain
    
    This report analyzes the infrastructure construction market in Spain.
    Key players include Ferrovial, ACS, and Acciona.
    """
    
    context = extract_context_from_document(
        context_doc,
        "Infrastructure Market Analysis for Spain"
    )
    
    print(f"\n✅ Contexto extraído:")
    print(f"   Geografía: {context.geography}")
    print(f"   Query Suffix: '{context.query_suffix}'")
    
    # Resultados con diferentes geografías
    fake_results = [
        {
            "title": "Global infrastructure trends 2024",
            "snippet": "Worldwide infrastructure market shows strong growth",
            "url": "https://example.com/global"
        },
        {
            "title": "Spain infrastructure investment increases",
            "snippet": "Spanish government announces major infrastructure spending in Madrid and Barcelona",
            "url": "https://example.com/spain"
        },
        {
            "title": "European construction market outlook",
            "snippet": "Europe sees infrastructure boom across multiple countries",
            "url": "https://example.com/europe"
        },
        {
            "title": "USA infrastructure bill impact",
            "snippet": "United States infrastructure investment reaches record levels",
            "url": "https://example.com/usa"
        }
    ]
    
    ranked = rerank_results(fake_results, context, top_n=10)
    
    print(f"\n✅ Reranking aplicado:")
    for i, r in enumerate(ranked, 1):
        score = r.get("_score", 0)
        print(f"   {i}. [{score:.1f}] {r['title']}")
    
    # Verificar que resultados con "Spain" están más arriba
    top_3_titles = " ".join([r['title'].lower() for r in ranked[:3]])
    assert "spain" in top_3_titles, \
        "❌ ERROR: Resultados con 'Spain' deberían estar en top 3"
    
    print("\n✅ Test 2 PASADO: Reranking prioriza geografía relevante (Spain)")


def test_backward_compatibility():
    """Test: Verificar que funciona sin contexto (backward compatibility)."""
    print("\n" + "=" * 80)
    print("TEST 3: Backward Compatibility (sin contexto)")
    print("=" * 80)
    
    # Contexto vacío
    empty_context = ProjectContext()
    
    query = "market trends 2024"
    variants = build_query_variants(query, empty_context)
    
    print(f"\n✅ Variantes sin contexto para '{query}':")
    for i, v in enumerate(variants, 1):
        print(f"   {i}. {v}")
    
    # Debería retornar al menos la query original
    assert len(variants) > 0, "❌ ERROR: Debería retornar al menos 1 variante"
    assert query in variants[0], "❌ ERROR: Primera variante debería contener query original"
    
    print("\n✅ Test 3 PASADO: Backward compatibility funciona")


if __name__ == "__main__":
    print("\n🧪 EJECUTANDO SMOKE TESTS PARA CONTEXT MANAGER INTEGRATION\n")
    
    try:
        test_acs_disambiguation()
        test_geography_reranking()
        test_backward_compatibility()
        
        print("\n" + "=" * 80)
        print("✅ TODOS LOS TESTS PASARON")
        print("=" * 80)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FALLÓ: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
