"""
Funciones de utilidad para el procesamiento de fuentes y textos.
"""
import re
import json
import os
import asyncio
import concurrent.futures
from datetime import datetime
from typing import List, Dict, Set, Any, Tuple
import tiktoken

def count_tokens(text: str, model_name: str = "gpt-4") -> int:
    """
    Cuenta el número aproximado de tokens en un texto usando tiktoken.
    
    Args:
        text: El texto a contar.
        model_name: El nombre del modelo para elegir el encoding (default gpt-4).
    
    Returns:
        Número de tokens.
    """
    if not text:
        return 0
    try:
        # Intentar obtener el encoding para el modelo específico
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # Fallback a cl100k_base (usado por GPT-4) si el modelo no es reconocido
            encoding = tiktoken.get_encoding("cl100k_base")
            
        return len(encoding.encode(text))
    except Exception as e:
        # Fallback heurístico muy básico si tiktoken falla (aprox 4 caracteres por token)
        return len(text) // 4

def extract_urls_from_sources(sources_text: str) -> Set[str]:
    """
    Extrae las URLs principales de las fuentes (aceptadas o rechazadas),
    evitando URLs secundarias encontradas dentro de los snippets.
    
    Args:
        sources_text: Texto con fuentes acumuladas
    
    Returns:
        Set de URLs de fuentes encontradas
    """
    if not sources_text:
        return set()
    
    # Buscamos patrones específicos que indiquen el inicio de una fuente
    # - URL: https://... (Aceptadas)
    # RECHAZADA: https://... (Rechazadas)
    patterns = [
        r'- URL:\s*(https?://[^\s\)]+)',
        r'RECHAZADA:\s*(https?://[^\s\)]+)'
    ]
    
    urls = set()
    for pattern in patterns:
        matches = re.findall(pattern, sources_text)
        for url in matches:
            urls.add(url.rstrip('.,;!?)'))
            
    return urls


def format_source_for_storage(source: Dict) -> str:
    """
    Formatea una fuente para almacenamiento en texto.
    Incluye los scores multidimensionales si están disponibles.
    
    Args:
        source: Diccionario con información de la fuente
    
    Returns:
        String formateado con la información de la fuente
    """
    formatted = f"**{source.get('title', 'Sin título')}**\n"
    formatted += f"- URL: {source.get('url', 'N/A')}\n"
    formatted += f"- Dominio: {source.get('source_domain', 'N/A')}\n"
    
    # Mostrar scores multidimensionales si están disponibles
    if all(key in source for key in ['authenticity_score', 'reliability_score', 'relevance_score', 'currency_score']):
        formatted += f"- Authenticity: {source.get('authenticity_score', 'N/A')}/10\n"
        formatted += f"- Reliability: {source.get('reliability_score', 'N/A')}/10\n"
        formatted += f"- Relevance: {source.get('relevance_score', 'N/A')}/10\n"
        formatted += f"- Currency: {source.get('currency_score', 'N/A')}/10\n"
        formatted += f"- Total Score: {source.get('total_score', source.get('score', 'N/A'))}/10\n"
        if source.get('is_clickbait') is not None:
            formatted += f"- Clickbait: {'Sí' if source.get('is_clickbait') else 'No'}\n"
    else:
        # Fallback para compatibilidad con formato antiguo
        formatted += f"- Score: {source.get('score', source.get('total_score', 'N/A'))}/10\n"
    
    # Usar 'reasoning' si está disponible, sino 'reason' (compatibilidad)
    reasoning = source.get('reasoning', source.get('reason', 'N/A'))
    formatted += f"- Razón: {reasoning}\n"
    formatted += f"- Snippet: {source.get('snippet', 'N/A')[:300]}...\n"
    return formatted


def extract_rejected_urls_from_sources(sources_text: str) -> Set[str]:
    """
    Extrae URLs de fuentes rechazadas del texto de fuentes acumuladas.
    Busca líneas que contengan 'RECHAZADA' o dominios conocidos de baja calidad.
    
    Args:
        sources_text: Texto con fuentes acumuladas
    
    Returns:
        Set de URLs rechazadas
    """
    if not sources_text:
        return set()
    
    rejected_urls = set()
    lines = sources_text.split('\n')
    
    # Buscar líneas que mencionen rechazo
    for line in lines:
        if 'RECHAZADA' in line.upper() or 'RECHAZADO' in line.upper():
            # Extraer URL de la línea
            url_pattern = r'https?://[^\s\)]+'
            urls = re.findall(url_pattern, line)
            rejected_urls.update(url.rstrip('.,;!?)') for url in urls)
    
    # También buscar dominios conocidos de baja calidad que aparecen en el texto
    low_quality_domains = ['zhihu.com', 'quora.com', 'reddit.com', 'blogspot.com']
    for domain in low_quality_domains:
        if domain in sources_text.lower():
            # Buscar todas las URLs de ese dominio
            url_pattern = rf'https?://[^\s\)]*{re.escape(domain)}[^\s\)]*'
            urls = re.findall(url_pattern, sources_text)
            rejected_urls.update(url.rstrip('.,;!?)') for url in urls)
    
    return rejected_urls


def canonicalize_url(url: str) -> str:
    """Canonicaliza URL para comparación/deduplicación.

    - lower
    - strip trailing slash
    - remove fragments
    - remove common tracking query params
    - normalize protocol (http/https)
    - normalize www subdomain
    """
    if not url:
        return ""
    u = url.strip()
    
    # Normalizar protocolo: convertir http a https para comparación
    # (pero mantener el original en la referencia)
    if u.startswith('http://'):
        u = 'https://' + u[7:]
    elif not u.startswith('http'):
        # Si no tiene protocolo, añadir https://
        u = 'https://' + u
    
    # remove fragment
    u = u.split('#', 1)[0]
    
    # split query
    if '?' in u:
        base, query = u.split('?', 1)
        # drop common tracking params
        params = []
        for part in query.split('&'):
            if not part:
                continue
            key = part.split('=', 1)[0].lower()
            if key.startswith('utm_') or key in {'gclid','fbclid','mc_cid','mc_eid','igshid','ref','ref_','cmpid','source','medium','campaign'}:
                continue
            params.append(part)
        u = base + ('?' + '&'.join(params) if params else '')
    
    # Normalizar www: remover www. para comparación
    # (pero mantener el original en la referencia)
    if '://www.' in u:
        u = u.replace('://www.', '://', 1)
    
    u = u.rstrip('/').lower()
    return u


def truncate_text(text: str, limit: int) -> str:
    """Trunca texto de forma segura, preservando integridad básica."""
    if not text or limit <= 0:
        return ''
    if len(text) <= limit:
        return text
    return text[: max(0, limit-1)] + '…'


def filter_duplicate_sources(new_sources: List[Dict], existing_sources_text: str) -> List[Dict]:
    """
    Filtra fuentes duplicadas comparando URLs con las fuentes existentes.
    También filtra fuentes que ya fueron rechazadas anteriormente.
    
    Args:
        new_sources: Lista de nuevas fuentes
        existing_sources_text: Texto con fuentes ya acumuladas
    
    Returns:
        Lista de fuentes sin duplicados ni rechazadas previamente
    """
    # Asegurarse de que existing_sources_text sea string (puede ser lista desde Airtable)
    if existing_sources_text:
        if isinstance(existing_sources_text, list):
            existing_sources_text = '\n'.join(str(s) for s in existing_sources_text) if existing_sources_text else ''
        existing_sources_text = str(existing_sources_text) if existing_sources_text else ''
    
    # Extraer URLs de fuentes aceptadas
    existing_urls = extract_urls_from_sources(existing_sources_text) if existing_sources_text else set()
    
    # Extraer URLs de fuentes rechazadas
    rejected_urls = extract_rejected_urls_from_sources(existing_sources_text) if existing_sources_text else set()
    
    unique_sources = []
    duplicates_count = 0
    
    for source in new_sources:
        url = source.get('url', '')
        if url:
            # Normalizar URL para comparación (remover trailing slash, etc.)
            normalized_url = canonicalize_url(url)
            
            # Verificar si ya fue aceptada
            if any(canonicalize_url(existing_url) == normalized_url for existing_url in existing_urls):
                duplicates_count += 1
                continue
            
            # Verificar si ya fue rechazada
            if any(canonicalize_url(rejected_url) == normalized_url for rejected_url in rejected_urls):
                duplicates_count += 1
                continue
            
            # Verificar si ya está en la lista de únicas actual (para evitar duplicados en el mismo lote)
            if any(canonicalize_url(s.get('url','')) == normalized_url for s in unique_sources):
                duplicates_count += 1
                continue
            
            unique_sources.append(source)
    
    if duplicates_count > 0:
        print(f"      🔍 Filtradas {duplicates_count} fuente(s) duplicada(s) o rechazada(s)")
    
    return unique_sources


def save_debug_sources(state: Dict[str, Any]) -> None:
    """
    Guarda las fuentes (validadas y rechazadas) en un archivo JSON en la carpeta debug_sources/
    para inspección manual de los contenidos (snippets) que recibe el Analyst.
    """
    try:
        # Crear directorio si no existe
        base_dir = "debug_sources"
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
            
        record_id = state.get('record_id', 'unknown_item')
        topic = state.get('topic', 'unknown_topic')
        project_name = state.get('project_name', 'unknown_project')
        
        # Limpiar nombre del tópico para archivo
        safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Filtrar fuentes para que el JSON sea EXACTAMENTE lo que recibe el Analyst
        # El Analyst solo recibe: title, url y snippet. Todo lo demás es ruido para el debug.
        raw_sources = state.get('validated_sources', [])
        filtered_sources = [
            {
                "title": s.get('title', 'N/A'),
                "url": s.get('url', 'N/A'),
                "snippet": s.get('snippet', 'N/A')
            }
            for s in raw_sources
        ]
        
        # Estructurar datos
        debug_data = {
            "metadata": {
                "record_id": record_id,
                "project_name": project_name,
                "topic": topic,
                "timestamp": datetime.now().isoformat(),
                "loop_count": state.get('loop_count', 0)
            },
            "sources_sent_to_analyst": filtered_sources
        }
        
        # Nombre del archivo
        filename = f"{base_dir}/{safe_topic}_{record_id}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(debug_data, f, ensure_ascii=False, indent=2)
            
        print(f"      📁 [DEBUG] Fuentes guardadas en {filename}")
        
    except Exception as e:
        print(f"      ⚠️ No se pudo guardar el archivo de debug de fuentes: {e}")


def is_useless_snippet(snippet: str, title: str = "") -> bool:
    """
    Detecta si un snippet es inútil (menús, índices, navegación).
    
    Args:
        snippet: Texto del snippet a evaluar
        title: Título de la fuente (opcional, para contexto adicional)
    
    Returns:
        True si el snippet es inútil y debe filtrarse
    """
    if not snippet or len(snippet.strip()) < 30:
        return True  # Snippets muy cortos son inútiles
    
    snippet_lower = snippet.lower()
    title_lower = (title or "").lower()
    combined = f"{snippet_lower} {title_lower}"
    
    # Patrones de menús de navegación
    navigation_keywords = [
        'home', 'inicio', 'about', 'sobre', 'contact', 'contacto', 'privacy', 'privacidad',
        'terms', 'términos', 'cookie', 'legal', 'sitemap', 'mapa del sitio',
        'menu', 'menú', 'navigation', 'navegación', 'skip to', 'saltar a',
        'sign in', 'iniciar sesión', 'login', 'register', 'registro',
        'subscribe', 'suscribirse', 'newsletter', 'follow us', 'síguenos'
    ]
    
    # Si el snippet es principalmente palabras de navegación, es inútil
    nav_word_count = sum(1 for kw in navigation_keywords if kw in snippet_lower)
    if nav_word_count >= 3:  # 3+ palabras de navegación = probablemente menú
        return True
    
    # Patrones de índices/TOC
    toc_patterns = [
        r'\b(table of contents|índice|contenido|contents)\b',
        r'\b(chapter \d+|capítulo \d+|section \d+|sección \d+)\b',
        r'^\s*(\d+\.\s*[^\n]+\n?){3,}',  # Lista numerada (3+ items)
        r'^\s*([a-z]\.\s*[^\n]+\n?){3,}',  # Lista alfabética (3+ items)
    ]
    
    for pattern in toc_patterns:
        if re.search(pattern, snippet_lower, re.IGNORECASE | re.MULTILINE):
            return True
    
    # Detectar muchos enlaces sin contexto (probablemente menú)
    url_count = len(re.findall(r'https?://[^\s\)]+', snippet))
    word_count = len(snippet.split())
    if url_count > 0 and word_count > 0:
        url_ratio = url_count / word_count
        if url_ratio > 0.15:  # Más del 15% son URLs = probablemente menú
            return True
    
    # Detectar listas de enlaces sin texto (menús)
    link_patterns = [
        r'^\s*(home|inicio|about|sobre|contact|contacto|services|servicios|products|productos)\s*$',
        r'^\s*[^\n]{1,30}\s*$',  # Líneas muy cortas (probablemente enlaces de menú)
    ]
    
    lines = snippet.split('\n')
    short_lines = sum(1 for line in lines if len(line.strip()) < 30 and line.strip())
    if len(lines) > 0 and short_lines / len(lines) > 0.7:  # 70%+ líneas cortas = probablemente menú
        return True
    
    # Detectar contenido genérico sin información sustancial
    generic_phrases = [
        'click here', 'haz clic aquí', 'read more', 'leer más', 'learn more', 'saber más',
        'view all', 'ver todo', 'see all', 'ver todos', 'browse', 'navegar',
        'select', 'seleccionar', 'choose', 'elegir', 'options', 'opciones'
    ]
    
    generic_count = sum(1 for phrase in generic_phrases if phrase in snippet_lower)
    if generic_count >= 2 and len(snippet.split()) < 50:  # Muchas frases genéricas + poco contenido
        return True
    
    # Detectar patrones de formularios o widgets
    form_patterns = [
        r'\b(email|correo|password|contraseña|submit|enviar|form)\b',
        r'\b(search|buscar|query|consulta)\s*:?\s*$',
    ]
    
    if any(re.search(pattern, snippet_lower) for pattern in form_patterns):
        if len(snippet.split()) < 20:  # Formularios cortos son inútiles
            return True
    
    return False  # El snippet parece útil


def filter_useless_snippets(sources: List[Dict]) -> Tuple[List[Dict], int]:
    """
    Filtra fuentes con snippets inútiles (menús, índices, navegación).
    
    Args:
        sources: Lista de fuentes a filtrar
    
    Returns:
        Tuple (fuentes filtradas, cantidad filtrada)
    """
    filtered = []
    filtered_count = 0
    
    for source in sources:
        snippet = source.get('snippet', '') or source.get('raw_content', '')
        title = source.get('title', '')
        
        # Si no hay snippet, mantenerlo (Firecrawl lo enriquecerá)
        if not snippet or len(snippet.strip()) < 30:
            # Si tiene raw_content suficiente, mantenerlo
            raw_content = source.get('raw_content', '')
            if raw_content and len(raw_content.strip()) >= 200:
                filtered.append(source)
            else:
                filtered_count += 1
            continue
        
        # Verificar si el snippet es inútil
        if is_useless_snippet(snippet, title):
            # Si tiene raw_content suficiente, mantenerlo (Firecrawl ya lo enriqueció)
            raw_content = source.get('raw_content', '')
            if raw_content and len(raw_content.strip()) >= 200:
                # Usar raw_content como snippet si el snippet original es inútil
                source['snippet'] = raw_content[:500]  # Usar primeros 500 chars de raw_content
                filtered.append(source)
            else:
                filtered_count += 1
        else:
            filtered.append(source)
    
    return filtered, filtered_count


def cleanup_temp_plots():
    """
    Elimina el contenido de la carpeta temp_plots si existe para evitar acumulación de archivos.
    """
    import shutil
    folder = "temp_plots"
    if os.path.exists(folder):
        try:
            # Listar archivos y carpetas
            items = os.listdir(folder)
            if not items:
                return
                
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f'❌ Error al eliminar {file_path} en cleanup: {e}')
            
            from .logger import logger
            logger.log_info(f"🧹 Carpeta '{folder}' limpiada correctamente.")
        except Exception as e:
            print(f"❌ Error al limpiar la carpeta '{folder}': {e}")


def run_async_safely(coro):
    """
    Ejecuta una coroutine de forma segura, evitando deadlocks.
    Si hay un loop corriendo, usa thread pool. Si no, usa asyncio.run().
    
    Esta función es útil cuando necesitas ejecutar código async desde código síncrono,
    especialmente en contextos donde puede haber un event loop ya corriendo.
    
    Args:
        coro: Coroutine a ejecutar
    
    Returns:
        Resultado de la coroutine
    
    Example:
        >>> result = run_async_safely(some_async_function())
    """
    try:
        # Intentar obtener el loop actual
        loop = asyncio.get_running_loop()
        # Si hay un loop corriendo, usar thread pool para evitar deadlock
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No hay loop corriendo, usar asyncio.run() directamente
        return asyncio.run(coro)


def _parse_topic_number(topic: str):
    """
    Parsea la numeración jerárquica de un topic.

    Returns:
        tuple: (parts, title_without_number) donde parts es una lista de ints.
        Ej: "7.1 Direct investment" → ([7, 1], "Direct investment")
        Ej: "7. Strategic Options" → ([7], "Strategic Options")
        Ej: "Sin número" → (None, "Sin número")
    """
    match = re.match(r'^(\d+(?:\.\d+)*)\.?\s+(.*)', topic.strip())
    if not match:
        return None, topic.strip()
    number_str = match.group(1)
    title = match.group(2)
    parts = [int(x) for x in number_str.split('.')]
    return parts, title


def build_hierarchical_context(topic: str, full_index: List[str]) -> str:
    """
    Genera contexto jerárquico automático para un item basándose en su numeración
    y la del resto de items del proyecto.

    Detecta padre, hermanos e hijos a partir de la convención de numeración
    (ej: 7 → 7.1, 7.2, 7.3) y genera un bloque de texto que el LLM puede usar
    para entender el alcance exacto de su capítulo.

    Args:
        topic: El tema del item actual (ej: "7.1 Direct investment vs. strategic alliances")
        full_index: Lista completa de topics del proyecto

    Returns:
        String con el contexto jerárquico, o vacío si no hay numeración.
    """
    if not full_index or not topic:
        return ""

    current_parts, current_title = _parse_topic_number(topic)
    if current_parts is None:
        return ""

    # Construir mapa de todos los items numerados
    index_map = {}  # parts_tuple → full topic string
    for item_topic in full_index:
        parts, _ = _parse_topic_number(item_topic)
        if parts is not None:
            index_map[tuple(parts)] = item_topic

    current_key = tuple(current_parts)
    depth = len(current_parts)  # 1 = raíz (ej: "7"), 2 = sub (ej: "7.1"), 3 = subsub (ej: "7.1.1")

    # Encontrar padre: quitar el último nivel
    parent_topic = None
    if depth > 1:
        parent_key = current_key[:-1]
        parent_topic = index_map.get(parent_key)

    # Encontrar hermanos: mismos niveles superiores, diferente último nivel
    siblings = []
    if depth > 1:
        for key, item_topic in sorted(index_map.items()):
            if len(key) == depth and key[:-1] == current_key[:-1] and key != current_key:
                siblings.append(item_topic)

    # Encontrar hijos directos: un nivel más profundo con mismo prefijo
    children = []
    for key, item_topic in sorted(index_map.items()):
        if len(key) == depth + 1 and key[:depth] == current_key:
            children.append(item_topic)

    # Si no hay relaciones jerárquicas, no generar contexto
    if not parent_topic and not siblings and not children:
        return ""

    # Construir bloque de texto
    lines = ["CONTEXTO JERÁRQUICO DE TU CAPÍTULO:"]

    if parent_topic:
        lines.append(f'  Capítulo padre: "{parent_topic}"')

    lines.append(f'  Tu capítulo: "{topic}"')

    if siblings:
        lines.append("  Capítulos hermanos (NO cubras su contenido):")
        for s in siblings:
            lines.append(f"    - {s}")

    if children:
        lines.append("  Subsecciones que se desarrollarán por separado (NO profundices en ellas):")
        for c in children:
            lines.append(f"    - {c}")

    # Generar instrucción de alcance
    lines.append("")
    if children and siblings:
        child_range = f"{children[0].split(' ')[0]}-{children[-1].split(' ')[0]}" if len(children) > 1 else children[0].split(' ')[0]
        lines.append(f"  ALCANCE: Tu investigación debe cubrir EXCLUSIVAMENTE lo que indica tu título: {current_title}.")
        lines.append(f"  Las subsecciones {child_range} profundizarán en cada aspecto, así que NO entres en detalle sobre ellas.")
        lines.append("  Evita solapar con los temas de tus capítulos hermanos listados arriba.")
    elif children:
        child_range = f"{children[0].split(' ')[0]}-{children[-1].split(' ')[0]}" if len(children) > 1 else children[0].split(' ')[0]
        lines.append(f"  ALCANCE: Como capítulo principal, ofrece una visión panorámica de {current_title}.")
        lines.append(f"  Las subsecciones {child_range} profundizarán en cada aspecto, así que NO entres en detalle sobre ellas.")
    elif siblings:
        lines.append(f"  ALCANCE: Tu investigación debe cubrir EXCLUSIVAMENTE lo que indica tu título: {current_title}.")
        lines.append("  Evita solapar con los temas de tus capítulos hermanos listados arriba.")

    return "\n".join(lines)
