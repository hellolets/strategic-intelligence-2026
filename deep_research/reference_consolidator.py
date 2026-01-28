"""
Módulo de consolidación de referencias.
Resuelve el problema de referencias duplicadas y sin título.
"""

import re
from collections import OrderedDict
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse, unquote
from .utils import canonicalize_url


def extract_title_from_url(url: str) -> str:
    """
    Extrae un título legible de la URL cuando no hay título disponible.
    
    Examples:
        https://mckinsey.com/industries/infrastructure/global-report-2024
        → "Global Report 2024"
        
        https://worldbank.org/en/topic/infrastructure/brief/ppp
        → "Ppp Brief"
    """
    if not url:
        return "Fuente sin identificar"
    
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        
        # Intentar extraer del path
        if path and path != '/':
            parts = [p for p in path.split('/') if p and len(p) > 2]
            if parts:
                # Tomar última parte significativa
                last_part = parts[-1]
                # Limpiar extensiones
                title = re.sub(r'\.(html|pdf|htm|php|aspx|asp)$', '', last_part, flags=re.I)
                # Formatear
                title = title.replace('-', ' ').replace('_', ' ')
                title = ' '.join(word.capitalize() for word in title.split())
                
                if len(title) > 5:
                    # Añadir dominio para contexto
                    domain = parsed.netloc.replace('www.', '').split('.')[0].capitalize()
                    return f"{title} - {domain}"
        
        # Fallback: usar dominio completo
        domain = parsed.netloc.replace('www.', '')
        return f"Documento de {domain}"
        
    except Exception:
        return "Fuente sin identificar"


def extract_references_from_report(report: str) -> Tuple[str, List[Dict]]:
    """
    Separa el contenido del reporte de su sección de referencias.
    
    Args:
        report: Texto completo del reporte (incluye ## References)
    
    Returns:
        (contenido_sin_referencias, lista_de_referencias)
        
    Cada referencia es un dict con:
        - original_num: número original [X]
        - title: título de la fuente
        - url: URL de la fuente
    """
    if not report:
        return "", []
    
    ref_patterns = [
        r'##\s*References\s*(?:[\r\n]+|$)(.*?)(?=\n##|\Z)',
        r'##\s*Referencias\s*(?:[\r\n]+|$)(.*?)(?=\n##|\Z)',
        r'##\s*Fuentes\s*Consultadas\s*(?:[\r\n]+|$)(.*?)(?=\n##|\Z)',
        r'##\s*Fuentes\s*(?:[\r\n]+|$)(.*?)(?=\n##|\Z)',
        r'\*\*References\*\*\s*(?:[\r\n]+|$)(.*?)(?=\n##|\n\*\*|\Z)',
    ]
    
    ref_match = None
    for pattern in ref_patterns:
        ref_match = re.search(pattern, report, re.DOTALL | re.IGNORECASE)
        if ref_match:
            break
    
    if not ref_match:
        return report, []
    
    # Extraer contenido sin referencias
    content = report[:ref_match.start()].rstrip()
    ref_section = ref_match.group(1)
    
    # Parsear referencias individuales
    # Formato esperado: [1] Título - URL o [1] Título URL
    references = []
    
    # Patrones flexibles para capturar referencias (mejorado para más variantes)
    # Acepta: [1] Título - URL, [1] Título URL, [1] URL, etc.
    ref_entry_patterns = [
        r'\[(\d+)\]\s*(.+?)(?:\s*-\s*|\s+)(https?://[^\s\n\)]+)',  # Con título y separador
        r'\[(\d+)\]\s*(https?://[^\s\n\)]+)',  # Solo número y URL (sin título)
    ]
    
    seen_nums = set()  # Para evitar procesar la misma referencia dos veces
    
    for pattern in ref_entry_patterns:
        for match in re.finditer(pattern, ref_section):
            num = int(match.group(1))
            
            # Evitar procesar la misma referencia dos veces
            if num in seen_nums:
                continue
            seen_nums.add(num)
            
            if len(match.groups()) == 3:
                # Patrón con título
                title = match.group(2).strip()
                url = match.group(3).strip().rstrip('.,;)')
            else:
                # Patrón sin título (solo URL)
                title = ""
                url = match.group(2).strip().rstrip('.,;)')
            
            # Limpiar título
            title = re.sub(r'^\[(PDF|HTML|DOC|LINK)\]\s*', '', title, flags=re.I)
            title = title.strip(' -–—')
            
            # Si título es vacío o genérico, extraer de URL
            if not title or title.lower() in ['n/a', 'sin título', 'untitled', '']:
                title = extract_title_from_url(url)
            
            references.append({
                'original_num': num,
                'title': title,
                'url': url
            })
    
    return content, references


def consolidate_references(all_references: List[List[Dict]]) -> Tuple[Dict[str, int], List[Dict]]:
    """
    Consolida referencias de todos los items, eliminando duplicados.
    Usa canonicalize_url para normalización robusta de URLs.
    
    Args:
        all_references: Lista de listas de referencias (una por item)
    
    Returns:
        (url_to_new_num, lista_referencias_unicas)
        
        url_to_new_num: mapeo de URL normalizada -> nuevo número
        lista_referencias_unicas: lista ordenada de referencias únicas
    """
    seen_urls = OrderedDict()  # Mantiene orden de inserción
    url_to_new_num = {}
    duplicates_found = []  # Para logging
    
    new_num = 1
    
    for item_idx, item_refs in enumerate(all_references, 1):
        for ref in item_refs:
            original_url = ref['url']
            # Normalizar URL para comparación usando canonicalize_url (más robusto)
            # Esto maneja trailing slashes, fragments, tracking params, etc.
            url_normalized = canonicalize_url(original_url)
            
            if not url_normalized:
                # URL vacía o inválida, saltar
                continue
            
            if url_normalized not in seen_urls:
                # Nueva referencia única
                seen_urls[url_normalized] = {
                    'num': new_num,
                    'title': ref['title'],
                    'url': original_url  # Mantener URL original (no normalizada)
                }
                url_to_new_num[url_normalized] = new_num
                new_num += 1
            else:
                # Duplicado detectado
                existing = seen_urls[url_normalized]
                duplicates_found.append({
                    'item': item_idx,
                    'original_url': original_url,
                    'normalized_url': url_normalized,
                    'existing_num': existing['num'],
                    'new_title': ref['title'],
                    'existing_title': existing['title']
                })
                
                # Si ya existe, verificar si el nuevo título es mejor
                existing_title_lower = existing['title'].lower().strip()
                new_title_lower = ref['title'].lower().strip()
                
                # Mejorar título si el existente es genérico o vacío
                if existing_title_lower in ['sin título', 'n/a', '', 'untitled', 'fuente sin identificar']:
                    if new_title_lower not in ['sin título', 'n/a', '', 'untitled', 'fuente sin identificar']:
                        existing['title'] = ref['title']
                # Si ambos tienen títulos, preferir el más largo/descriptivo
                elif len(ref['title']) > len(existing['title']) and new_title_lower not in ['sin título', 'n/a', '', 'untitled']:
                    existing['title'] = ref['title']
    
    # Logging de duplicados encontrados
    if duplicates_found:
        print(f"         🔍 Duplicados detectados: {len(duplicates_found)}")
        for dup in duplicates_found[:5]:  # Mostrar solo los primeros 5
            print(f"            Item {dup['item']}: URL duplicada → Ref [{dup['existing_num']}]")
            if dup['normalized_url'] != dup['original_url']:
                print(f"               Normalizada: {dup['normalized_url'][:60]}...")
    
    unique_refs = list(seen_urls.values())
    return url_to_new_num, unique_refs


def renumber_citations_in_text(
    text: str, 
    old_refs: List[Dict], 
    url_to_new_num: Dict[str, int]
) -> str:
    """
    Renumera las citas [X] en el texto según el nuevo mapeo global.
    
    Args:
        text: Contenido del item (sin sección References)
        old_refs: Referencias originales de este item
        url_to_new_num: Mapeo global URL -> nuevo número
    
    Returns:
        Texto con citas renumeradas
    """
    if not old_refs:
        return text
    
    # Crear mapeo old_num -> new_num para este item específico
    old_to_new = {}
    for ref in old_refs:
        # Usar canonicalize_url para normalización consistente
        url_normalized = canonicalize_url(ref['url'])
        if url_normalized in url_to_new_num:
            old_to_new[ref['original_num']] = url_to_new_num[url_normalized]
    
    if not old_to_new:
        return text
    
    # Reemplazar citas [X] con nuevo número
    def replace_citation(match):
        old_num = int(match.group(1))
        new_num = old_to_new.get(old_num, old_num)
        return f'[{new_num}]'
    
    # También manejar citas agrupadas [1, 2, 3]
    def replace_grouped_citations(match):
        nums_str = match.group(1)
        nums = [int(n.strip()) for n in nums_str.split(',')]
        new_nums = [old_to_new.get(n, n) for n in nums]
        return '[' + ', '.join(str(n) for n in sorted(set(new_nums))) + ']'
    
    # Primero reemplazar citas agrupadas
    text = re.sub(r'\[(\d+(?:\s*,\s*\d+)+)\]', replace_grouped_citations, text)
    
    # Luego citas individuales
    text = re.sub(r'\[(\d+)\]', replace_citation, text)
    
    return text


def format_references_section(unique_refs: List[Dict], style: str = "IEEE") -> str:
    """
    Genera la sección de referencias formateada.
    Asegura que no haya duplicados finales usando normalización de URLs.
    
    Args:
        unique_refs: Lista de referencias únicas consolidadas
        style: Estilo de formato (IEEE, APA, etc.)
    
    Returns:
        Sección ## References formateada sin duplicados
    """
    if not unique_refs:
        return "\n\n## References\n\n_No se encontraron referencias._\n"
    
    # Validación final: eliminar cualquier duplicado que pueda haber quedado
    # (por si acaso hay URLs que no se normalizaron correctamente antes)
    # IMPORTANTE: Mantener los números existentes para no romper las citas en el texto
    seen_urls_normalized = {}
    deduplicated_refs = []
    duplicates_removed = 0
    seen_nums = set()  # Para detectar números duplicados
    
    for ref in unique_refs:
        url_normalized = canonicalize_url(ref['url'])
        
        if not url_normalized:
            # URL inválida, saltar
            continue
        
        ref_num = ref.get('num', 0)
        
        if url_normalized not in seen_urls_normalized:
            # Nueva referencia única
            # Verificar que el número no esté duplicado
            if ref_num in seen_nums:
                # Número duplicado, asignar nuevo número
                max_num = max(seen_nums) if seen_nums else 0
                ref_num = max_num + 1
                ref['num'] = ref_num
                print(f"         ⚠️ Número duplicado detectado, renumerado a [{ref_num}]")
            
            seen_urls_normalized[url_normalized] = ref
            seen_nums.add(ref_num)
            deduplicated_refs.append(ref)
        else:
            # Duplicado detectado en la validación final
            duplicates_removed += 1
            existing_ref = seen_urls_normalized[url_normalized]
            # Mejorar título si el existente es genérico
            if existing_ref['title'].lower().strip() in ['sin título', 'n/a', '', 'untitled', 'fuente sin identificar']:
                if ref['title'].lower().strip() not in ['sin título', 'n/a', '', 'untitled', 'fuente sin identificar']:
                    existing_ref['title'] = ref['title']
            # No añadir el duplicado a deduplicated_refs
    
    if duplicates_removed > 0:
        print(f"         ⚠️ Validación final: {duplicates_removed} duplicado(s) adicional(es) eliminado(s)")
    
    # Ordenar por número para mantener orden secuencial
    deduplicated_refs.sort(key=lambda x: x.get('num', 0))
    
    section = "\n\n\\newpage\n\n## References\n\n"
    
    for ref in deduplicated_refs:
        if style.upper() == "IEEE":
            # Formato IEEE: [N] Título, URL
            section += f"[{ref['num']}] {ref['title']} - {ref['url']}\n\n"
        else:
            # Formato genérico
            section += f"[{ref['num']}] {ref['title']}. Disponible en: {ref['url']}\n\n"
    
    return section


def validate_references(report: str) -> Dict:
    """
    Valida la sección de referencias del reporte consolidado.
    
    Returns:
        Dict con issues encontrados:
        - sin_titulo: referencias sin título válido
        - duplicados: URLs o números duplicados
        - huerfanos: referencias no citadas en texto
        - fantasmas: citas sin referencia correspondiente
    """
    issues = {
        'sin_titulo': [],
        'duplicados': [],
        'huerfanos': [],
        'fantasmas': [],
        'total_refs': 0,
        'valid_refs': 0
    }
    
    # Separar contenido de referencias
    parts = report.split('## References')
    if len(parts) < 2:
        return issues
    
    content = parts[0]
    ref_section = parts[1]
    
    # Extraer referencias
    ref_pattern = r'\[(\d+)\]\s*(.+?)(?:\s*-\s*|\s+)(https?://[^\s\n]+)'
    refs = re.findall(ref_pattern, ref_section)
    issues['total_refs'] = len(refs)
    
    seen_urls = set()
    seen_nums = set()
    
    for num, title, url in refs:
        num = int(num)
        
        # Detectar sin título
        if title.lower().strip() in ['sin título', 'n/a', '', 'untitled']:
            issues['sin_titulo'].append(num)
        
        # Detectar URLs duplicadas usando canonicalize_url para normalización consistente
        url_norm = canonicalize_url(url)
        if url_norm in seen_urls:
            issues['duplicados'].append({'num': num, 'url': url, 'type': 'url'})
        seen_urls.add(url_norm)
        
        # Detectar números duplicados
        if num in seen_nums:
            issues['duplicados'].append({'num': num, 'type': 'number'})
        seen_nums.add(num)
    
    # Detectar citas huérfanas y fantasmas
    citas_en_texto = set()
    for match in re.finditer(r'\[(\d+)\]', content):
        citas_en_texto.add(int(match.group(1)))
    
    refs_nums = set(int(num) for num, _, _ in refs)
    
    issues['huerfanos'] = sorted(refs_nums - citas_en_texto)
    issues['fantasmas'] = sorted(citas_en_texto - refs_nums)
    issues['valid_refs'] = len(refs) - len(issues['sin_titulo']) - len([d for d in issues['duplicados'] if d.get('type') == 'url'])
    
    return issues


def print_validation_summary(issues: Dict):
    """
    Imprime resumen de validación de referencias.
    """
    print(f"\n      📊 VALIDACIÓN DE REFERENCIAS:")
    print(f"         Total referencias: {issues['total_refs']}")
    print(f"         Referencias válidas: {issues['valid_refs']}")
    
    if issues['sin_titulo']:
        print(f"         ⚠️  Sin título: {len(issues['sin_titulo'])} ({issues['sin_titulo'][:5]}{'...' if len(issues['sin_titulo']) > 5 else ''})")
    
    if issues['duplicados']:
        print(f"         ⚠️  Duplicados: {len(issues['duplicados'])}")
    
    if issues['huerfanos']:
        print(f"         ⚠️  No citadas: {len(issues['huerfanos'])} ({issues['huerfanos'][:5]}{'...' if len(issues['huerfanos']) > 5 else ''})")
    
    if issues['fantasmas']:
        print(f"         ❌  Citas sin ref: {len(issues['fantasmas'])} ({issues['fantasmas'][:5]}{'...' if len(issues['fantasmas']) > 5 else ''})")
    
    if not any([issues['sin_titulo'], issues['duplicados'], issues['huerfanos'], issues['fantasmas']]):
        print(f"         ✅  Sin problemas detectados")
