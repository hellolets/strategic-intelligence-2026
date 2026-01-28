"""
Módulo Validate References: Valida que todas las fuentes estén incluidas en las referencias del reporte.
"""
import re
from typing import Dict, List, Tuple


def normalize_url(url: str) -> str:
    """
    Normaliza una URL para comparación (sin trailing slash, lowercase, sin parámetros de query).
    Igual que en _ensure_references_section para consistencia.
    """
    if not url or url == 'N/A':
        return ''
    # Eliminar trailing slash y convertir a lowercase
    normalized = url.rstrip('/').lower()
    # Eliminar fragmentos (#) y parámetros de query (?) para mejor matching
    normalized = normalized.split('#')[0].split('?')[0]
    return normalized


def validate_references(report: str, sources: List[Dict]) -> Dict:
    """
    Valida que todas las fuentes estén incluidas en la sección ## References del reporte
    y que todas las citas [1], [2]... correspondan a fuentes existentes.
    
    Args:
        report: Reporte en formato Markdown
        sources: Lista de fuentes utilizadas
    
    Returns:
        Dict con:
        - passed: Boolean indicando si pasó la validación
        - issues: Lista de problemas detectados
        - missing_sources: Fuentes que no están en References
        - invalid_citations: Citas que no corresponden a fuentes
        - citation_count: Cantidad de citas encontradas
        - reference_count: Cantidad de referencias en ## References
    """
    issues = []
    missing_sources = []
    invalid_citations = []
    
    if not report:
        return {
            "passed": False,
            "issues": ["Reporte vacío"],
            "missing_sources": [],
            "invalid_citations": [],
            "citation_count": 0,
            "reference_count": 0
        }
    
    # 1. Extraer todas las citas del reporte [1], [2], [1, 2, 3], etc.
    citation_pattern = r'\[(\d+(?:\s*,\s*\d+)*)\]'
    citations_found = []
    
    # Buscar todas las citas individuales
    for match in re.finditer(citation_pattern, report):
        citation_text = match.group(1)
        # Separar números individuales de grupos como "1, 2, 3"
        numbers = [int(n.strip()) for n in citation_text.split(',')]
        citations_found.extend(numbers)
    
    citation_numbers = set(citations_found)
    citation_count = len(citation_numbers)
    
    # 2. Extraer referencias de la sección ## References
    references_section = re.search(r'## References\n(.*?)(?=\n##|$)', report, re.DOTALL | re.IGNORECASE)
    reference_numbers = set()
    referenced_urls = {}
    referenced_titles = {}
    
    if references_section:
        ref_text = references_section.group(1)
        
        # Buscar referencias con formato [Número] Título - URL
        # Aceptar varios formatos: [1] Título - URL, [1] Título, URL, [1] URL
        ref_pattern = r'\[(\d+)\]\s*(.+?)(?=\n\[|\n\n|$)'
        for match in re.finditer(ref_pattern, ref_text, re.MULTILINE):
            ref_num = int(match.group(1))
            ref_content = match.group(2).strip()
            reference_numbers.add(ref_num)
            
            # Intentar extraer URL del contenido
            url_match = re.search(r'(https?://[^\s\n]+)', ref_content)
            if url_match:
                url = url_match.group(1).rstrip('.,;')
                # Normalizar URL para comparación consistente
                referenced_urls[ref_num] = normalize_url(url)
            
            # Extraer título (todo antes de la URL o antes de "-")
            title_match = re.match(r'^(.+?)(?:\s*[-–]\s*|\s*,\s*)(?:https?://|$)', ref_content)
            if title_match:
                title = title_match.group(1).strip()
                referenced_titles[ref_num] = title
            else:
                # Si no hay separador, tomar todo como título (sin URL)
                referenced_titles[ref_num] = ref_content
    
    reference_count = len(reference_numbers)
    
    # 3. Verificar que todas las fuentes están en las referencias
    # Normalizar URLs de fuentes para comparación consistente
    source_urls_normalized = {normalize_url(s.get('url', '')): s for s in sources if normalize_url(s.get('url', ''))}
    
    # Verificar cada fuente
    for i, source in enumerate(sources, 1):
        source_url = source.get('url', '')
        source_title = source.get('title', '')
        
        if not source_url:
            continue
        
        # Normalizar URL de la fuente
        source_url_norm = normalize_url(source_url)
        found = False
        
        # Buscar si esta URL está en alguna referencia (usando normalización)
        for ref_num, ref_url_norm in referenced_urls.items():
            if ref_url_norm == source_url_norm:
                found = True
                break
        
        # También buscar por título si la URL no coincide (fallback para URLs con variaciones)
        if not found and source_title:
            title_lower = source_title.lower()
            for ref_num, ref_title in referenced_titles.items():
                if title_lower in ref_title.lower() or ref_title.lower() in title_lower:
                    # Verificar que la URL también coincida (usando normalización)
                    ref_url_norm = referenced_urls.get(ref_num, '')
                    if ref_url_norm and (source_url_norm in ref_url_norm or ref_url_norm in source_url_norm):
                        found = True
                        break
        
        if not found:
            missing_sources.append({
                "index": i,
                "title": source_title,
                "url": source_url,
                "issue": "Fuente no encontrada en sección ## References"
            })
    
    # 4. Verificar que todas las citas corresponden a referencias existentes
    max_citation = max(citation_numbers) if citation_numbers else 0
    max_reference = max(reference_numbers) if reference_numbers else 0
    
    if citation_numbers and reference_numbers:
        # Citas sin referencia
        missing_refs = citation_numbers - reference_numbers
        if missing_refs:
            invalid_citations.extend([
                {
                    "citation": f"[{num}]",
                    "issue": f"Cita [{num}] sin referencia correspondiente en ## References"
                }
                for num in sorted(missing_refs)
            ])
        
        # Referencias sin citas (advertencia, no error)
        uncited_refs = reference_numbers - citation_numbers
        if uncited_refs:
            issues.append(f"⚠️ {len(uncited_refs)} referencia(s) en ## References no tienen citas en el texto: {sorted(uncited_refs)}")
    
    # 5. Verificar que no haya referencias fuera de rango
    if citation_numbers:
        if max_citation > len(sources):
            issues.append(f"⚠️ Citas hasta [{max_citation}] pero solo hay {len(sources)} fuentes disponibles")
    
    # Compilar issues
    if missing_sources:
        issues.append(f"❌ {len(missing_sources)} fuente(s) no incluida(s) en ## References:")
        for missing in missing_sources[:5]:  # Mostrar solo las primeras 5
            issues.append(f"   - [{missing['index']}] {missing['title'][:60]}... - {missing['url'][:50]}...")
        if len(missing_sources) > 5:
            issues.append(f"   ... y {len(missing_sources) - 5} más")
    
    if invalid_citations:
        issues.append(f"❌ {len(invalid_citations)} cita(s) sin referencia:")
        for invalid in invalid_citations[:5]:
            issues.append(f"   - {invalid['citation']}: {invalid['issue']}")
        if len(invalid_citations) > 5:
            issues.append(f"   ... y {len(invalid_citations) - 5} más")
    
    if not references_section:
        issues.insert(0, "❌ No se encontró sección ## References en el reporte")
    
    # Determinar si pasó
    passed = len(missing_sources) == 0 and len(invalid_citations) == 0 and references_section is not None
    
    return {
        "passed": passed,
        "issues": issues,
        "missing_sources": missing_sources,
        "invalid_citations": invalid_citations,
        "citation_count": citation_count,
        "reference_count": reference_count,
        "unique_citation_numbers": sorted(citation_numbers),
        "unique_reference_numbers": sorted(reference_numbers)
    }


def format_references_summary(validation_result: Dict) -> str:
    """
    Formatea un resumen legible de la validación de referencias.
    """
    if validation_result["passed"]:
        return f"""✅ Validación de Referencias: PASADA

📊 Estadísticas:
- Citas encontradas: {validation_result['citation_count']}
- Referencias en ## References: {validation_result['reference_count']}
- Todas las fuentes están incluidas
- Todas las citas tienen referencias correspondientes
"""
    else:
        md = f"""⚠️ Validación de Referencias: FALLIDA

📊 Estadísticas:
- Citas encontradas: {validation_result['citation_count']}
- Referencias en ## References: {validation_result['reference_count']}
- Fuentes faltantes: {len(validation_result['missing_sources'])}
- Citas inválidas: {len(validation_result['invalid_citations'])}

❌ Problemas detectados:
"""
        for issue in validation_result['issues']:
            md += f"- {issue}\n"
        
        return md
