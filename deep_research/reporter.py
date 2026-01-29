"""
Módulo Reporter: Genera reportes finales en Markdown.

MEJORA 2026-01: Chunking inteligente de fuentes
- Prioriza fuentes por score de relevancia
- Incluye fuentes completas hasta llenar el límite
- Solo trunca la última fuente si es necesario
"""
import time
from typing import List, Dict, Optional, Tuple, Any
from .config import (
    llm_analyst,
    llm_analyst_fast,
    llm_analyst_precision,
    model_config,
    TOML_CONFIG,
    USE_DEEPSEEK_FOR_TESTING,
    USE_CHEAP_OPENROUTER_MODELS,
    get_model_limits
)
from .prompts import reporter_prompt
from .utils import count_tokens

# Configuración global
REPORT_LANGUAGE = TOML_CONFIG["general"].get("report_language", "Español")
REFERENCES_STYLE = TOML_CONFIG["references"].get("style", "IEEE")


# ==========================================
# CHUNKING INTELIGENTE DE FUENTES
# ==========================================

def _get_source_score(source: Dict) -> float:
    """Obtiene el score de relevancia de una fuente."""
    try:
        # Intentar varios campos donde podría estar el score
        return float(source.get('total_score', source.get('relevance_score', source.get('score', 5.0))))
    except (ValueError, TypeError):
        return 5.0  # Score por defecto


def _chunk_sources_by_relevance(
    sources: List[Dict],
    max_total_tokens: int,
    model_name: str = "gpt-4",
    content_field: str = 'raw_content',
    fallback_field: str = 'snippet'
) -> Tuple[str, int, int]:
    """
    Chunking inteligente: prioriza fuentes por relevancia.
    En lugar de truncar uniformemente todas las fuentes,
    incluye fuentes COMPLETAS ordenadas por score hasta llenar el límite.

    Args:
        sources: Lista de fuentes con score
        max_total_tokens: Límite máximo de tokens para todas las fuentes
        model_name: Nombre del modelo para contar tokens
        content_field: Campo principal de contenido
        fallback_field: Campo de fallback si no hay contenido principal

    Returns:
        Tuple (sources_text, tokens_usados, fuentes_incluidas_completas)
    """
    if not sources:
        return "", 0, 0

    # 1. Ordenar fuentes por score de relevancia (mayor primero)
    sorted_sources = sorted(sources, key=_get_source_score, reverse=True)

    # deduplicate sorted_sources by URL
    unique_sorted = []
    seen = set()
    for s in sorted_sources:
        u = s.get('url', '').rstrip('/').lower()
        if u and u not in seen:
            unique_sorted.append(s)
            seen.add(u)
        elif not u:
            unique_sorted.append(s)

    # 2. Incluir fuentes completas hasta llenar el límite
    sources_text_parts = []
    tokens_used = 0
    sources_included_complete = 0
    max_chars_per_source = 15000  # Límite por fuente individual (para evitar fuentes gigantes)

    for i, source in enumerate(unique_sorted):
        content = source.get(content_field, source.get(fallback_field, 'N/A'))
        if not content or content == 'N/A':
            content = source.get(fallback_field, 'N/A')

        # Limitar contenido individual
        content = content[:max_chars_per_source] if content else 'N/A'

        # Formatear la fuente
        source_text = (
            f"[{i+1}] Título: {source.get('title', 'N/A')}\n"
            f"URL: {source.get('url', 'N/A')}\n"
            f"Score: {_get_source_score(source):.1f}\n"
            f"Contenido: {content}"
        )

        source_tokens = count_tokens(source_text, model_name)

        # Si añadir esta fuente completa no excede el límite, añadirla
        if tokens_used + source_tokens <= max_total_tokens:
            sources_text_parts.append(source_text)
            tokens_used += source_tokens
            sources_included_complete += 1
        else:
            # Si no cabe completa, intentar truncar solo esta fuente
            remaining_tokens = max_total_tokens - tokens_used
            if remaining_tokens > 500:  # Solo si hay espacio significativo
                # Calcular cuántos caracteres podemos incluir
                chars_per_token = len(content) / count_tokens(content, model_name) if count_tokens(content, model_name) > 0 else 4
                available_chars = int(remaining_tokens * chars_per_token * 0.8)  # 80% de margen
                truncated_content = content[:available_chars] + "\n[... contenido truncado ...]"

                truncated_source_text = (
                    f"[{i+1}] Título: {source.get('title', 'N/A')}\n"
                    f"URL: {source.get('url', 'N/A')}\n"
                    f"Score: {_get_source_score(source):.1f}\n"
                    f"Contenido: {truncated_content}"
                )

                sources_text_parts.append(truncated_source_text)
                tokens_used += count_tokens(truncated_source_text, model_name)

            # Parar aquí - las siguientes fuentes ya no caben
            break

    sources_text = "\n\n".join(sources_text_parts)

    return sources_text, tokens_used, sources_included_complete


def _clean_report_metadata(report: str) -> str:
    """
    Limpia metadatos, badges y mensajes de proceso del reporte generado por el LLM.
    El objetivo es obtener SOLO el contenido limpio del reporte.
    """
    import re
    
    # Patrones de metadatos a eliminar
    patterns_to_remove = [
        # Badges de Confidence Score e info de sistema
        r'>\s*[🟢🟡🟠🔴⚫⚪]\s*\*\*Confidence Score:.*?\*\*.*?\n(?:>.*?\n)*',
        r'Confidence Score:\s*\d+/\d+.*?\n',
        # Mensajes de proceso del LLM (comunes en modelos de razonamiento)
        r"Here is the report.*?:",
        r"Here is the drafted report.*?:",
        r"I have analyzed the sources.*?:",
        r"Based on the provided sources.*?:",
        r"Below is the comprehensive report.*?:",
        r"Drafting the report.*?:",
        r"Process:",
        r"Step \d+:",
        r"\*\*Process:\*\*",
        r"\*\*Step \d+:\*\*",
        # Bloques de pensamiento (ocultos o explícitos)
        r'<thinking>.*?</thinking>',
        r'```thinking.*?```',
    ]
    
    cleaned_report = report
    for pattern in patterns_to_remove:
        cleaned_report = re.sub(pattern, '', cleaned_report, flags=re.IGNORECASE | re.DOTALL)
    
    # Eliminar líneas iniciales que no sean encabezados (#) si parecen texto de introducción del LLM
    # Buscar el primer encabezado
    first_header_match = re.search(r'^#\s+', cleaned_report, re.MULTILINE)
    if first_header_match:
        # Si hay texto antes del primer encabezado, verificar si es "basura"
        pre_header = cleaned_report[:first_header_match.start()]
        # Si es corto (< 200 chars) y contiene frases típicas de chat, eliminarlo
        if len(pre_header) < 200 and ("sure" in pre_header.lower() or "here is" in pre_header.lower() or "report" in pre_header.lower()):
            cleaned_report = cleaned_report[first_header_match.start():]
    
    # Limpiar espacios en blanco al inicio y final
    cleaned_report = cleaned_report.strip()
    
    return cleaned_report


def _ensure_references_section(report: str, sources: List[Dict]) -> str:
    """
    Asegura que el reporte tenga una sección ## References al final.
    Si no existe, la crea automáticamente con todas las fuentes proporcionadas.
    Si existe pero está incompleta, agrega las fuentes faltantes.
    """
    import re
    
    # Normalizar URLs para comparación (sin trailing slash, lowercase)
    def normalize_url(url: str) -> str:
        if not url or url == 'N/A':
            return ''
        return url.rstrip('/').lower()
    
    # Extraer URLs de las fuentes
    source_urls = {normalize_url(s.get('url', '')): s for s in sources if normalize_url(s.get('url', ''))}
    
    # Verificar si existe sección ## References (más robusto)
    # Buscamos todas las ocurrencias para consolidarlas
    all_ref_headers = list(re.finditer(r'##\s*References\s*[:\-]*\s*\n?', report, re.IGNORECASE))
    
    if all_ref_headers:
        # Usar la primera ocurrencia como ancla
        first_match = all_ref_headers[0]
        ref_start_pos = first_match.start()
        
        # El "cuerpo" del reporte es todo lo anterior a la primera sección de referencias
        body_text = report[:ref_start_pos]
        # La sección de referencias es todo lo posterior (pero limpiaremos otros headers repetidos)
        ref_section_raw = report[first_match.end():]
        
        # Limpiar cualquier otro header "## References" que el LLM haya repetido dentro de la sección
        ref_section_text = re.sub(r'##\s*References\s*[:\-]*\s*\n?', '', ref_section_raw, flags=re.IGNORECASE)
        ref_section_text = ref_section_text.strip()
        
        # Extraer qué números de referencia se citan realmente en el cuerpo [1], [2], etc.
        # Buscamos patrones del tipo [1], [1, 2], [1-3]
        cited_nums = set()
        # Patrón para [1], [1, 2], [1,2,3]
        citation_matches = re.findall(r'\[([\d\s,\-]+)\]', body_text)
        for group in citation_matches:
            # Separar por comas
            parts = group.split(',')
            for part in parts:
                part = part.strip()
                if '-' in part:
                    # Rango [1-3]
                    try:
                        start, end = map(int, part.split('-'))
                        cited_nums.update(range(start, end + 1))
                    except: pass
                else:
                    try:
                        cited_nums.add(int(part))
                    except: pass
        
        # Extraer URLs y números de las referencias que YA están escritas en la sección de referencias
        ref_url_pattern = r'https?://[^\s\n]+'
        ref_urls_found = set()
        for match in re.finditer(ref_url_pattern, ref_section_text):
            ref_url = normalize_url(match.group(0).rstrip('.,;)]'))
            ref_urls_found.add(ref_url)
            
        # Filtrar la sección de referencias existente para eliminar las NO citadas
        ref_lines = ref_section_text.split('\n')
        filtered_ref_lines = []
        for line in ref_lines:
            line = line.strip()
            if not line: continue
            
            # Intentar detectar si es una línea de referencia [N]
            match = re.match(r'^\s*\[(\d+)\]', line)
            if match:
                ref_num = int(match.group(1))
                if ref_num in cited_nums:
                    filtered_ref_lines.append(line)
            else:
                # Si no empieza por [N], lo mantenemos (podría ser texto adicional)
                filtered_ref_lines.append(line)
        
        ref_section_text = "\n".join(filtered_ref_lines)
        
        # Identificar fuentes que están CITADAS en el texto pero FALTAN en la lista filtrada
        missing_sources_texts = []
        
        # Mapear fuentes por su índice 1-based (el que usa el LLM en el prompt)
        for i, source in enumerate(sources, 1):
            url = normalize_url(source.get('url', ''))
            # Si la fuente está citada y su URL no está en lo que queda de la lista
            if i in cited_nums:
                # Verificar si el URL de la fuente i ya está en el texto filtrado
                found_in_filtered = False
                for line in filtered_ref_lines:
                    if url and url in normalize_url(line):
                        found_in_filtered = True
                        break
                
                if not found_in_filtered:
                    title = source.get('title', 'N/A')
                    title = re.sub(r'^\[(PDF|HTML|DOC)\]\s*', '', title)
                    missing_sources_texts.append(f"[{i}] {title} - {source.get('url', 'N/A')}")
        
        # Reconstruir el reporte consolidando la sección de referencias
        new_report = body_text.rstrip() + "\n\n## References\n\n" + ref_section_text
        if missing_sources_texts:
            print(f"      ⚠️  {len(missing_sources_texts)} fuente(s) citada(s) pero faltantes en la lista, agregándolas...")
            new_report = new_report.rstrip() + "\n" + "\n".join(missing_sources_texts) + "\n"
            
        return new_report
    
    # Si no tiene References, agregarla al final (solo las citadas)
    # Si no hay citas detectadas, por seguridad agregamos todas (modo fallback)
    
    # Si no tiene References, agregarla al final
    print(f"      ⚠️  Sección ## References no detectada, agregándola automáticamente...")
    
    # Limpiar el reporte (eliminar espacios finales)
    report = report.rstrip()
    
    # EXTRAER CITAS del texto para el caso fallback
    cited_nums = set()
    citation_matches = re.findall(r'\[([\d\s,\-]+)\]', report)
    for group in citation_matches:
        parts = group.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    cited_nums.update(range(start, end + 1))
                except: pass
            else:
                try:
                    cited_nums.add(int(part))
                except: pass

    # Agregar separador si no termina con línea vacía
    if not report.endswith('\n\n'):
        if not report.endswith('\n'):
            report += '\n'
        report += '\n'
    
    # Agregar sección References
    report += "## References\n\n"
    
    # Agregar fuentes: si hay citas, solo las citadas. Si no hay citas, todas (fallback total).
    sources_to_add = []
    for i, source in enumerate(sources, 1):
        if not cited_nums or i in cited_nums:
            sources_to_add.append((i, source))
            
    for i, source in sources_to_add:
        title = source.get('title', 'N/A')
        url = source.get('url', 'N/A')
        # Limpiar título
        title = re.sub(r'^\[(PDF|HTML|DOC)\]\s*', '', title)
        report += f"[{i}] {title} - {url}\n"
    
    return report


async def generate_markdown_report(
    topic: str,
    all_sources: List[Dict],
    report_type: str = "General",
    language: str = None,
    reference_style: str = None,
    project_specific_context: Optional[str] = None,
    project_name: Optional[str] = None,
    related_topics: Optional[List[str]] = None,
    hierarchical_context: str = "",
    brief: str = ""
) -> Tuple[str, int]:
    """
    Genera un reporte detallado en Markdown basado en las fuentes.
    Utiliza el LLM Analyst configurado en config.py.
    """
    # Seleccionar el modelo adecuado
    llm = None
    is_test_mode = False
    
    # Deduplicar todas las fuentes por URL al inicio
    unique_sources = []
    seen_urls = set()
    for s in all_sources:
        u = s.get('url', '').rstrip('/').lower()
        if u and u not in seen_urls:
            unique_sources.append(s)
            seen_urls.add(u)
        elif not u:
            unique_sources.append(s)
    all_sources = unique_sources

    if is_test_mode:
        # En modo TEST, usar solo el modelo de TEST (xiaomi/mimo-v2-flash:free)
        llm = llm_analyst
        print(f"      🧪 Modelo: TEST (xiaomi/mimo-v2-flash:free) - Modo TEST activo")
    else:
        # En modo PRODUCTION/ECONOMIC, seleccionar según criticidad
        report_types_critical = ["Strategic", "Financial", "Due_Diligence"]
        if report_type in report_types_critical:
            if llm_analyst_precision is not None:
                llm = llm_analyst_precision
                print(f"      🎯 Modelo: Claude Sonnet 4 (Precision) - Reporte CRÍTICO detectado")
            else:
                llm = llm_analyst
                print(f"      ⚠️  Modelo de precisión no disponible, usando modelo estándar (Fallback)")
        else:
            if llm_analyst_fast is not None:
                llm = llm_analyst_fast
                print(f"      ⚡ Modelo: Gemini 2.5 Pro (Fast) - Reporte exploratorio")
            else:
                llm = llm_analyst
                print(f"      ⚠️  Modelo rápido no disponible, usando modelo estándar (Fallback)")
    
    # Verificar si hay contexto del proyecto
    # Verificar tanto None como string vacío
    has_context = project_specific_context and isinstance(project_specific_context, str) and project_specific_context.strip()
    
    if has_context:
        print(f"      ✅ Project context loaded ({len(project_specific_context)} chars). Context used as reference document.")
    else:
        print(f"      ⚠️  No project-specific context available.")

    if not topic or topic.strip() in ["Sin tema", "N/A", ""]:
        return f"# Error\n\n⚠️ No se puede generar un reporte sin un tema válido.", 0

    # Preparar las fuentes en formato texto para el LLM
    # MEJORA 2026-01: Usar chunking inteligente por relevancia
    # Esto permite incluir fuentes completas priorizadas por score
    # en lugar de truncar uniformemente todas las fuentes

    # Calcular tokens máximos disponibles para fuentes (estimación inicial generosa)
    # Se ajustará después si es necesario
    initial_max_tokens_for_sources = 100000  # ~400K chars, se ajustará después

    sources_text, initial_sources_tokens, sources_complete = _chunk_sources_by_relevance(
        sources=all_sources,
        max_total_tokens=initial_max_tokens_for_sources,
        model_name="gpt-4",
        content_field='raw_content',
        fallback_field='snippet'
    )

    print(f"      📊 [CHUNKING] {sources_complete}/{len(all_sources)} fuentes incluidas completas")
    print(f"      📊 [CHUNKING] {initial_sources_tokens:,} tokens iniciales para fuentes")

    # Fallback al método anterior si el nuevo falla
    if not sources_text:
        content_per_source_limit = 10000
        sources_text = "\n\n".join(
            [
                f"Fuente {i + 1}:\n- Título: {s.get('title', 'N/A')}\n- URL: {s.get('url', 'N/A')}\n- Contenido: {s.get('raw_content', s.get('snippet', 'N/A'))[:content_per_source_limit]}"
                for i, s in enumerate(all_sources)
            ]
        )

    # Usar parámetros pasados o valores por defecto de config
    lang = language or REPORT_LANGUAGE
    ref_style = reference_style or REFERENCES_STYLE

    # Inicializar variables para evitar UnboundLocalError
    context_private_text = ""
    related_topics_text = ""

    # Inyectar instrucciones de estructura al prompt (ya sea custom o fallback)
    base_prompt = (
        reporter_prompt if reporter_prompt else "Actúa como un Consultor de Estrategia Senior."
    )

    system_msg = f"""{base_prompt}

INSTRUCCIONES DE ESTRUCTURA Y FORMATO OBLIGATORIAS:
1. IDIOMA: Escribe el reporte íntegramente en {lang}.
2. ESTRUCTURA DEL REPORTE (CRÍTICO - NO OMITIR):
   - Empieza directamente con el título del tema en texto plano: {topic}
   - Sigue con el contenido redactado de forma profesional y sintetizada.
   - 🚨 OBLIGATORIO: DEBES finalizar el reporte con la sección de referencias: ## References
   - ❌ PROHIBIDO: Finalizar el reporte sin la sección ## References
   - La sección ## References es OBLIGATORIA y debe estar al final del documento
   - ❌ PROHIBIDO: NO generes sección "Executive Summary" ni "Resumen Ejecutivo" - esto se generará en el documento consolidado final
3. CITAS EN EL TEXTO (ESTILO PROFESIONAL OBLIGATORIO):
   - Estilo: {ref_style} (IEEE: [1], [2]...).
   - ORDEN: Las citas deben numerarse consecutivamente en orden de aparición ([1], luego [2], etc.).
   - REGLA CRÍTICA: CADA DATO ESPECÍFICO (números, estadísticas, porcentajes, fechas, nombres propios, cifras) 
     DEBE tener su cita correspondiente al final del párrafo donde aparece.
   - REGLAS DE ESTILO (VER ABAJO SECCIÓN DETALLADA DE EJEMPLOS).
   
4. SECCIÓN DE REFERENCIAS (## References):
   - OBLIGATORIO: Debe incluir TODAS las fuentes que se citaron en el texto.
   - Formato por cada fuente: [Número] Título de la fuente - URL
   - Ejemplo correcto: [1] Market Analysis Report 2024 - https://example.com/report
   - Ejemplo correcto: [2] Industry Trends and Growth Projections - https://example.com/trends
   - Las referencias deben numerarse consecutivamente [1], [2], [3]... según orden de primera aparición en el texto
   - Formato exacto requerido: [N] Título - URL (con guión " - " separando título y URL)
   - ❌ INCORRECTO: [1] URL (falta título)
   - ❌ INCORRECTO: [1] Título URL (falta separador)
   - ❌ INCORRECTO: Título - URL (falta [Número])

5. REGLAS DE ORO:

   **🎯 GUÍA DETALLADA DE ESTILO PROFESIONAL PARA CITAS (OBLIGATORIO):**
   
   ❌ ESTILO INCORRECTO (Excesivo, poco profesional):
   ```
   The company is a leader [1][2][3]. The organization has strong growth [4][5].
   Bank of America recognizes this [1][2]. The pricing power is evident [1][2][6].
   ```
   
   ✅ ESTILO CORRECTO (Profesional, académico):
   ```
   The company is a global leader in its sector, strategically 
   positioned for significant growth by 2026. Market analysts have recognized 
   the company as a top pick, driven by strong pricing power in its regional 
   portfolio, which is expected to achieve significant growth through 2029 [1, 2].
   ```
   
   **PRINCIPIOS NO NEGOCIABLES:**
   
   1. **CITA AL FINAL DEL PÁRRAFO (OBLIGATORIO PARA DATOS ESPECÍFICOS):**
      - Cada dato específico mencionado (porcentajes, cifras, fechas, estadísticas, nombres propios, montos) 
        DEBE tener su cita correspondiente al final del párrafo.
      - Si un párrafo contiene múltiples datos específicos de diferentes fuentes, agrupa las citas: [1, 2, 3] al final.
      - Si todos los datos del párrafo vienen de la misma fuente, usa una sola cita: [1].
      - ❌ NO cites frase por frase, pero SÍ cita cada párrafo que contenga datos específicos.
   
   2. **AGRUPA REFERENCIAS:**
      - Usa [1, 2, 3] con comas al final del párrafo.
      - ❌ NUNCA uses [1][2][3].
      - MÁXIMO 3 referencias por grupo: [1, 2, 3]. Si hay más datos, elige las 3 fuentes más relevantes.
      - Si tienes 4+ fuentes con datos relevantes, prioriza las más confiables y agrupa: [1, 2, 3].
   
   3. **FRECUENCIA OBLIGATORIA:**
      - Cada párrafo que contenga datos específicos DEBE tener al menos 1 cita al final.
      - Si un párrafo tiene solo texto descriptivo sin datos concretos, puede no llevar cita (caso excepcional).
      - Párrafos con datos numéricos, estadísticas o información verificable: SIEMPRE citar.
   
   4. **PRIORIDAD DE FUENTES:**
      - Cita fuentes primarias (informes oficiales) antes que noticias secundarias.
      - Si tienes el mismo dato en múltiples fuentes, cita la más confiable primero.

5. REGLAS FUNDAMENTALES:
   - No resumas fuente por fuente; agrupa por temas.
   - Sé directo y ejecutivo.
   - No te inventes nuevos capítulos, es decir, no crees nuevos títulos con # o ## o del estilo.
   - Usa SOLAMENTE la información de las fuentes proporcionadas.
   - No crees nuevos títulos dentro del reporte con # o ## o del estilo. Todo tiene que estar redactado.
   - Si quieres crear apartados, usa el símbolo * para crearlo en negrita, pero NUNCA crees nuevos títulos.
   - No utilices bullet points a menos que estos sean necesarios para la redacción. La redacción debe ser extensa y detallada.

8. 🚫 PROHIBIDO INCLUIR METADATOS O PROCESO DE GENERACIÓN (CRÍTICO):
   - ❌ PROHIBIDO incluir mensajes sobre tu proceso de trabajo como:
     * "Drafting the Report", "Finalizing the Report", "I'm now drafting", "I'm starting with", "I'm reviewing"
     * "I'm now finalizing", "I'm confident that", "I've completed the draft"
     * Cualquier texto que describa lo que estás haciendo o pensando
   - ❌ PROHIBIDO incluir Confidence Scores, badges, o métricas de confianza en el contenido del reporte
   - ❌ PROHIBIDO incluir mensajes como "🟢 Confidence Score: 100/100" o similares
   - ❌ PROHIBIDO incluir cualquier texto que no sea el contenido real del reporte
   - ✅ SOLO incluye el contenido del reporte: título, texto redactado, y sección de referencias
   - ✅ Empieza directamente con el título del tema y el contenido, sin preámbulos ni metadatos
   - ✅ El reporte debe ser el contenido final, no una descripción del proceso de generación

IMPORTANTE!!:
   - SOLAMENTE tiene que tener HASHTAGS # el título del tema y ## la sección de referencias.
   - No crees nuevos títulos dentro del reporte con HASHTAGS: # o ##. Todo tiene que estar redactado.
   - No incluyas la información privada a menos que el título del reporte se refiera explícitamente a la empresa cliente.
   - NO incluyas metadatos, mensajes de proceso, o cualquier texto que no sea el contenido real del reporte.

6. ALINEACIÓN TOTAL TEMA-PROYECTO DE INVESTIGACIÓN:
   - Todo lo que escribas sobre '{topic}' debe responder a una pregunta: ¿Cómo contribuye esto al objetivo del proyecto '{project_name}'?
   - No escribas genéricamente sobre el tema. Escribe sobre el tema EN EL CONTEXTO del proyecto.
   - Si el proyecto es "Estrategia 2030" y el tema es "IA", no hables de la historia de la IA, habla de "Impacto de la IA en la Estrategia 2030".

7. REGLAS ANTI-ALUCINACIÓN (CRÍTICO - PRIORIDAD ABSOLUTA):
   
   🚨 PROHIBIDO INVENTAR (ZERO TOLERANCE):
   - NUNCA inventes estadísticas, porcentajes, cifras de mercado o proyecciones numéricas
   - NUNCA inventes nombres de empresas, personas, productos o marcas que no aparezcan en las fuentes
   - NUNCA inventes fechas, años, plazos temporales o cronologías
   - NUNCA extrapoles tendencias más allá de lo que dicen explícitamente las fuentes
   - NUNCA hagas inferencias numéricas o comparativas sin datos explícitos
   - NUNCA asumas datos de contexto general si no están en las fuentes proporcionadas
   - NUNCA uses conocimiento previo para "completar" información faltante
   
   ✅ SI NO TIENES DATOS (PROTOCOLO OBLIGATORIO):
   - Usa EXACTAMENTE estos formatos cuando falte información:
     * "Según las fuentes consultadas, no se dispone de información específica sobre..."
     * "Los datos disponibles no permiten cuantificar..."
     * "Las fuentes no especifican..."
     * "La información proporcionada no incluye datos sobre..."
   - Si una fuente menciona algo de forma vaga, repite la vaguedad, NO la conviertas en algo específico
   
   📊 DATOS NUMÉRICOS (VERIFICACIÓN OBLIGATORIA):
   - TODO dato numérico (porcentajes, cifras, años, montos) DEBE tener una cita específica [X] al final del párrafo
   - REGLA DE ORO: Si mencionas un número, porcentaje, fecha o cifra → SIEMPRE cita al final del párrafo [X]
   - Ejemplo correcto: "El mercado creció un 25% en 2024, alcanzando 500 millones de euros [1]."
   - Si una fuente dice "crecimiento significativo" sin cifras, escribe "crecimiento significativo" - NUNCA añadas "del 15%" o similar
   - Reproduce rangos EXACTOS: si la fuente dice "15-20%", escribe "15-20%", NO "aproximadamente 17%" o "alrededor del 18%"
   - Si la fuente dice "millones" sin especificar, escribe "millones", NO inventes "5 millones" o "varios millones"
   - Si hay múltiples fuentes con datos diferentes, cita ambas al final: "Según las fuentes, los datos varían entre X e Y [1, 2]. En caso de duda y si viene de la misma fuente, elige la cifra mas actualizada en base a la fuente"
   
   🔍 VERIFICACIÓN INTERNA OBLIGATORIA (PROCESO PASO A PASO):
   ANTES de escribir CADA párrafo o afirmación:
   1. Pregúntate: "¿En qué fuente específica (número) está esta información?"
   2. Si puedes identificar la fuente: inclúyela con la cita [X] correspondiente
   3. Si NO puedes identificar la fuente exacta: NO la incluyas bajo ningún concepto
   4. Si la información está "implícita" o "sugerida" pero no explícita: NO la incluyas
   5. Si estás "seguro de que es verdad" pero no está en las fuentes: NO la incluyas
   
   ⚠️ CASOS ESPECIALES:
   - Información contradictoria: "Las fuentes presentan información divergente: [1] indica X, mientras que [2] indica Y"
   - Información parcial: "Según [1], se menciona X, aunque no se proporcionan detalles adicionales sobre Y"
   - Inferencias prohibidas: Si las fuentes dicen "A y B", NO escribas "A, B y por lo tanto C" a menos que C esté explícito
   
   ✅ EJEMPLO CORRECTO (CITAS AL FINAL DEL PÁRRAFO):
   "El mercado ha experimentado un crecimiento del 25% en el último año, alcanzando 
   los 500 millones de euros en facturación. Este incremento se debe principalmente 
   a factores tecnológicos identificados en múltiples análisis sectoriales. 
   Según proyecciones recientes, se espera que esta tendencia continúe hasta 2030 
   con un crecimiento anual estimado del 30% [1, 2, 3]."
   
   "La empresa líder del sector reportó ventas de 1.200 millones en 2024, 
   representando un incremento del 18% respecto al año anterior [4]."
   
   ❌ EJEMPLO INCORRECTO (SIN CITAS O ALUCINACIÓN):
   "El mercado ha experimentado un crecimiento del 25% según múltiples analistas. 
   Este incremento se debe principalmente a factores tecnológicos y se espera que 
   continúe hasta 2030 con una proyección del 30% anual."
   
   (Problemas: 
   - No tiene cita [X] al final del párrafo a pesar de mencionar "25%", "2030", "30%"
   - Si estos datos son reales de las fuentes, DEBEN tener cita: [1, 2, 3]
   - Si son inventados, viola reglas anti-alucinación)
   
   ❌ EJEMPLO INCORRECTO (CITA EN LUGAR INCORRECTO):
   "El mercado creció [1] un 25% el año pasado, alcanzando 500 millones [2]."
   
   (Problema: citas intercaladas en el texto, deben ir al final del párrafo: 
   "El mercado creció un 25% el año pasado, alcanzando 500 millones [1, 2].")
"""


    context_text = f"Nombre del Proyecto: {project_name}\n" if project_name else ""

    # NOTA: El contexto de la empresa ahora viene de Airtable (campo Context en Proyectos)
    # No se usa company_context del JSON, se usa project_specific_context de Airtable
    # company_context ya no se usa - toda la información viene en project_specific_context

    # Usar la misma verificación que arriba
    if has_context:
        context_private_text += "--- INFORMACIÓN PRIVADA ---\n"
        context_private_text += f"{project_specific_context}\n"
        context_private_text += f"""
    INSTRUCCIÓN CRÍTICA SOBRE CONTEXTO INTERNO (SEGURIDAD Y PERTINENCIA): 
    
    1. 🛡️ PROHIBICIÓN DE DATOS SENSIBLES:
       - NUNCA reveles cifras financieras internas confidenciales (EBITDA, márgenes detallados, proyecciones no públicas) que aparezcan en los documentos privados.
       - Si el documento privado habla de estrategias futuras confidenciales, úsalo solo para entender el contexto, NO para revelarlas textualmente.

    2. 🎯 USO SELECTIVO SEGÚN EL TEMA DEL CAPÍTULO (Gold Rule):
       - Analiza el TÍTULO del tema actual: "{topic}"
       - SI el tema es sobre Mercado General, Tendencias, Competencia o Tecnología (Outside-In):
         -> ¡IGNORA EL CONTEXTO PRIVADO! 
         -> NO menciones el nombre de la empresa cliente. 
         -> Céntrate 100% en la investigación externa (URLs).
       - SI (y SOLO SI) el tema pide explícitamente "Implicaciones para [Empresa]", "Gap Analysis", "Comparativa" o "Oportunidades para [Empresa]":
         -> Usa el contexto privado para contrastar.
         -> Aterriza los hallazgos externos a la realidad de la empresa.
    
    3. ⚖️ FILOSOFÍA DE REDACCIÓN:
       - Tu "Norte" es el TÍTULO DEL PROYECTO. Todo lo que escribas debe aportar valor a ese objetivo.
       - El contexto privado es tu "conocimiento tácito" para saber qué es relevante, no tu fuente de contenido para "copiar y pegar".
    
    4. 🚫 CERO REFERENCIAS PRIVADAS:
       - PROHIBIDO incluir documentos del "Contexto Privado" en la sección ## References.
       - PROHIBIDO citar con número [X] información que viene de los documentos internos.
       - Las referencias [X] son EXCLUSIVAMENTE para fuentes públicas (URLs).
    \n"""

    if related_topics:
        # El usuario ya incluyó el header en user_msg, solo agregamos los items a la variable
        for rt in related_topics:
            related_topics_text += f"- {rt}\n"

    user_msg = f""" 
Contexto del proyecto: {context_text} 

Tema actual a redactar: {topic}
{"" if not hierarchical_context else chr(10) + hierarchical_context + chr(10)}
{"" if not brief else "BRIEF/OBJETIVO DEL CAPÍTULO:" + chr(10) + brief + chr(10)}
Otros temas relacionados en este mismo proyecto (EVITAR SOLAPAMIENTOS O REPETICIONES):
{related_topics_text}

Lista de Fuentes a utilizar SIEMPRE:
{sources_text}

Información privada (solo si el tema EXPLICITAMENTE lo requiere):
{context_private_text}

🚨 RECORDATORIO FINAL OBLIGATORIO:
- El reporte DEBE terminar con la sección ## References
- DEBES incluir TODAS las fuentes listadas arriba en la sección ## References
- Formato: [Número] Título - URL para cada fuente
- NO omitas la sección ## References bajo ningún concepto

Genera el reporte siguiendo las reglas de formato especificadas."""

    try:
        # Verificar que el LLM esté inicializado
        if llm is None:
            raise ValueError("LLM no está inicializado. Verifica la configuración de los modelos en config.py")
        
        # ============================================
        # TRUNCAMIENTO DE TOKENS ANTES DE ENVIAR
        # ============================================
        from .utils import count_tokens
        
        # Obtener nombre del modelo y determinar límite de tokens
        model_name = ""
        provider = None
        
        try:
            if hasattr(llm, 'model_name'):
                model_name = llm.model_name
            elif hasattr(llm, 'model'):
                model_name = llm.model
            elif hasattr(llm, '_default_params') and 'model' in llm._default_params:
                model_name = llm._default_params['model']
                
            # Detectar proveedor
            if USE_DEEPSEEK_FOR_TESTING:
                roles_key = "roles_test"
            elif USE_CHEAP_OPENROUTER_MODELS:
                roles_key = "roles_cheap"
            else:
                roles_key = "roles"
            
            roles_config = TOML_CONFIG.get(roles_key, {})
            analyst_config = roles_config.get("analyst", {})
            provider = analyst_config.get("provider")
        except Exception:
            pass

        # Usar lógica centralizada
        MAX_TOKENS_MODEL, MAX_TOKENS_AVAILABLE = get_model_limits(model_name, provider)
        
        # Detectar si es DeepInfra (solo para lógica compleja de truncamiento más abajo)
        is_deepinfra = provider == "openrouter" and ("deepseek" in (model_name or "").lower() or "mimo" in (model_name or "").lower())
        
        # Calcular tokens del prompt completo
        system_tokens = count_tokens(system_msg, model_name or "gpt-4")
        user_msg_tokens = count_tokens(user_msg, model_name or "gpt-4")
        total_tokens = system_tokens + user_msg_tokens
        
        print(f"      📊 Tokens calculados: {total_tokens:,} (system: {system_tokens:,}, user: {user_msg_tokens:,})")
        print(f"      📊 Límite del modelo: {MAX_TOKENS_MODEL:,} tokens (disponible para input: {MAX_TOKENS_AVAILABLE:,})")
        
        # Si excede el límite, truncar contenido
        if total_tokens > MAX_TOKENS_AVAILABLE:
            print(f"      ⚠️  El prompt excede el límite. Truncando contenido...")
            print(f"      📊 Tokens estimados: {total_tokens:,} (límite: {MAX_TOKENS_AVAILABLE:,})")
            
            # Calcular tokens disponibles para contenido (después de system message y template)
            # El template incluye: context_text, topic, related_topics_text, y las instrucciones finales
            template_text = f""" 
Contexto del proyecto: {context_text} 

Tema actual a redactar: {topic}
{"" if not hierarchical_context else chr(10) + hierarchical_context + chr(10)}
{"" if not brief else "BRIEF/OBJETIVO DEL CAPÍTULO:" + chr(10) + brief + chr(10)}
Otros temas relacionados en este mismo proyecto (EVITAR SOLAPAMIENTOS O REPETICIONES):
{related_topics_text}

Lista de Fuentes a utilizar SIEMPRE:
{{sources_text}}

Información privada (solo si el tema EXPLICITAMENTE lo requiere):
{{context_private_text}}

🚨 RECORDATORIO FINAL OBLIGATORIO:
- El reporte DEBE terminar con la sección ## References
- DEBES incluir TODAS las fuentes listadas arriba en la sección ## References
- Formato: [Número] Título - URL para cada fuente
- NO omitas la sección ## References bajo ningún concepto

Genera el reporte siguiendo las reglas de formato especificadas."""
            
            template_tokens = count_tokens(template_text, model_name or "gpt-4")
            # Para DeepInfra, usar margen de seguridad más conservador (80% en lugar de 85%)
            safety_margin = 0.80 if is_deepinfra else 0.95
            tokens_for_content = max(5000 if is_deepinfra else 10000, int((MAX_TOKENS_AVAILABLE - system_tokens - template_tokens) * safety_margin))
            
            # Distribuir tokens: ajustar según si es DeepInfra o no
            if is_deepinfra:
                # DeepInfra: 60% para fuentes, 40% para contexto privado (más balanceado)
                tokens_for_sources = int(tokens_for_content * 0.6)
                tokens_for_context = tokens_for_content - tokens_for_sources
            else:
                # Otros: 70% para fuentes, 30% para contexto privado
                tokens_for_sources = int(tokens_for_content * 0.7)
                tokens_for_context = tokens_for_content - tokens_for_sources
            
            # Truncar fuentes usando chunking inteligente
            sources_tokens = count_tokens(sources_text, model_name or "gpt-4")
            if sources_tokens > tokens_for_sources:
                print(f"      🔧 Re-chunking fuentes: {sources_tokens:,} -> {tokens_for_sources:,} tokens")
                # MEJORA: Usar chunking inteligente en lugar de truncamiento uniforme
                sources_text, sources_tokens, sources_complete = _chunk_sources_by_relevance(
                    sources=all_sources,
                    max_total_tokens=tokens_for_sources,
                    model_name=model_name or "gpt-4"
                )
                print(f"      ✅ Fuentes re-chunked: {sources_tokens:,} tokens ({sources_complete}/{len(all_sources)} completas)")
            
            # Truncar contexto privado
            context_tokens = count_tokens(context_private_text, model_name or "gpt-4")
            if context_tokens > tokens_for_context:
                print(f"      🔧 Truncando contexto privado: {context_tokens:,} -> {tokens_for_context:,} tokens")
                chars_per_token = len(context_private_text) / context_tokens if context_tokens > 0 else 4
                max_chars_context = int(tokens_for_context * chars_per_token)
                context_private_text = context_private_text[:max_chars_context] + "\n\n[... contexto truncado por límite de tokens ...]"
                context_tokens = count_tokens(context_private_text, model_name or "gpt-4")
                print(f"      ✅ Contexto truncado: {context_tokens:,} tokens")
            
            # Reconstruir user_msg con contenido truncado
            user_msg = f""" 
Contexto del proyecto: {context_text} 

Tema actual a redactar: {topic}
{"" if not hierarchical_context else chr(10) + hierarchical_context + chr(10)}
{"" if not brief else "BRIEF/OBJETIVO DEL CAPÍTULO:" + chr(10) + brief + chr(10)}
Otros temas relacionados en este mismo proyecto (EVITAR SOLAPAMIENTOS O REPETICIONES):
{related_topics_text}

Lista de Fuentes a utilizar SIEMPRE:
{sources_text}

Información privada (solo si el tema EXPLICITAMENTE lo requiere):
{context_private_text}

🚨 RECORDATORIO FINAL OBLIGATORIO:
- El reporte DEBE terminar con la sección ## References
- DEBES incluir TODAS las fuentes listadas arriba en la sección ## References
- Formato: [Número] Título - URL para cada fuente
- NO omitas la sección ## References bajo ningún concepto

Genera el reporte siguiendo las reglas de formato especificadas."""
            
            # Verificar tokens finales
            final_tokens = system_tokens + count_tokens(user_msg, model_name or "gpt-4")
            
            # CALCULAR PÉRDIDA DE CALIDAD (WARNING)
            original_content_tokens = sources_tokens + context_tokens
            final_content_tokens = count_tokens(sources_text, model_name or "gpt-4") + count_tokens(context_private_text, model_name or "gpt-4")
            
            if original_content_tokens > 0:
                retention_rate = (final_content_tokens / original_content_tokens) * 100
                if retention_rate < 50:
                    print(f"      🚨 ADVERTENCIA DE CALIDAD: Solo se ha retenido el {retention_rate:.1f}% de la información original.")
                    print(f"         Esto puede afectar significativamente la profundidad del reporte.")
                    print(f"         Sugerencia: Cambiar rol 'analyst' a un modelo con mayor contexto (ej: gemini-2.0-flash).")
            
            # Verificación final: asegurar que no exceda el límite
            max_allowed = MAX_TOKENS_MODEL if is_deepinfra else MAX_TOKENS_AVAILABLE
            if final_tokens > max_allowed:
                provider_name = "DeepInfra" if is_deepinfra else "el proveedor"
                print(f"      ⚠️  {provider_name}: prompt aún excede límite ({final_tokens:,} > {max_allowed:,}), aplicando truncamiento más agresivo...")
                # Reducir aún más el contenido
                if is_deepinfra:
                    # DeepInfra: usar solo 60% del límite total para el prompt (muy agresivo)
                    MAX_PROMPT_TOKENS_DEEPINFRA = int(MAX_TOKENS_MODEL * 0.60)
                    tokens_for_content = max(3000, int((MAX_PROMPT_TOKENS_DEEPINFRA - system_tokens - template_tokens) * 0.90))
                else:
                    # Otros: usar 85% del límite disponible
                    tokens_for_content = max(5000, int((MAX_TOKENS_AVAILABLE - system_tokens - template_tokens) * 0.85))
                tokens_for_sources = int(tokens_for_content * 0.6)
                tokens_for_context = tokens_for_content - tokens_for_sources
                
                # Re-truncar con nuevos límites más restrictivos usando chunking inteligente
                if sources_tokens > tokens_for_sources:
                    sources_text, sources_tokens, sources_complete = _chunk_sources_by_relevance(
                        sources=all_sources,
                        max_total_tokens=tokens_for_sources,
                        model_name=model_name or "gpt-4"
                    )
                    print(f"      🔧 Re-chunking agresivo: {sources_complete}/{len(all_sources)} fuentes completas")
                
                if context_tokens > tokens_for_context:
                    chars_per_token = len(context_private_text) / context_tokens if context_tokens > 0 else 4
                    max_chars_context = int(tokens_for_context * chars_per_token)
                    context_private_text = context_private_text[:max_chars_context] + "\n\n[... contexto truncado por límite de tokens ...]"
                    context_tokens = count_tokens(context_private_text, model_name or "gpt-4")
                
                # Reconstruir user_msg
                user_msg = f""" 
Contexto del proyecto: {context_text} 

Tema actual a redactar: {topic}
{"" if not hierarchical_context else chr(10) + hierarchical_context + chr(10)}
{"" if not brief else "BRIEF/OBJETIVO DEL CAPÍTULO:" + chr(10) + brief + chr(10)}
Otros temas relacionados en este mismo proyecto (EVITAR SOLAPAMIENTOS O REPETICIONES):
{related_topics_text}

Lista de Fuentes a utilizar SIEMPRE:
{sources_text}

Información privada (solo si el tema EXPLICITAMENTE lo requiere):
{context_private_text}

🚨 RECORDATORIO FINAL OBLIGATORIO:
- El reporte DEBE terminar con la sección ## References
- DEBES incluir TODAS las fuentes listadas arriba en la sección ## References
- Formato: [Número] Título - URL para cada fuente
- NO omitas la sección ## References bajo ningún concepto

Genera el reporte siguiendo las reglas de formato especificadas."""
                
                final_tokens = system_tokens + count_tokens(user_msg, model_name or "gpt-4")
                print(f"      ⚠️  Re-truncamiento agresivo aplicado: {final_tokens:,} tokens finales")
                
                # Verificación final: si aún excede, aplicar truncamiento extremo
                max_allowed = MAX_TOKENS_MODEL if is_deepinfra else MAX_TOKENS_AVAILABLE
                if final_tokens > max_allowed:
                    provider_name = "DeepInfra" if is_deepinfra else "el proveedor"
                    print(f"      ⚠️  Truncamiento extremo necesario: {final_tokens:,} > {max_allowed:,}")
                    # Truncamiento extremo: reducir fuentes a mínimo absoluto
                    if is_deepinfra:
                        # DeepInfra: usar solo 50% del límite total
                        MAX_PROMPT_TOKENS_EXTREME = int(MAX_TOKENS_MODEL * 0.20)  # Muy agresivo para DeepSeek 32K
                        tokens_for_content = max(2000, int((MAX_PROMPT_TOKENS_EXTREME - system_tokens - template_tokens) * 0.85))
                    else:
                        tokens_for_content = max(3000, int((MAX_TOKENS_AVAILABLE - system_tokens - template_tokens) * 0.75))
                    
                    tokens_for_sources = int(tokens_for_content * 0.6)
                    tokens_for_context = tokens_for_content - tokens_for_sources
                    
                    # Truncar fuentes extremadamente - usar chunking inteligente
                    if sources_tokens > tokens_for_sources:
                        sources_text, sources_tokens, sources_complete = _chunk_sources_by_relevance(
                            sources=all_sources,
                            max_total_tokens=tokens_for_sources,
                            model_name=model_name or "gpt-4"
                        )
                        print(f"      🚨 Truncamiento extremo: solo {sources_complete}/{len(all_sources)} fuentes (priorizadas por relevancia)")
                    
                    # Truncar contexto extremadamente
                    if context_tokens > tokens_for_context:
                        chars_per_token = len(context_private_text) / context_tokens if context_tokens > 0 else 4
                        max_chars_context = int(tokens_for_context * chars_per_token)
                        context_private_text = context_private_text[:max_chars_context] + "\n\n[... contexto truncado por límite de tokens ...]"
                        context_tokens = count_tokens(context_private_text, model_name or "gpt-4")
                    
                    # Reconstruir user_msg
                    user_msg = f""" 
Contexto del proyecto: {context_text} 

Tema actual a redactar: {topic}
{"" if not hierarchical_context else chr(10) + hierarchical_context + chr(10)}
{"" if not brief else "BRIEF/OBJETIVO DEL CAPÍTULO:" + chr(10) + brief + chr(10)}
Otros temas relacionados en este mismo proyecto (EVITAR SOLAPAMIENTOS O REPETICIONES):
{related_topics_text}

Lista de Fuentes a utilizar SIEMPRE:
{sources_text}

Información privada (solo si el tema EXPLICITAMENTE lo requiere):
{context_private_text}

🚨 RECORDATORIO FINAL OBLIGATORIO:
- El reporte DEBE terminar con la sección ## References
- DEBES incluir TODAS las fuentes listadas arriba en la sección ## References
- Formato: [Número] Título - URL para cada fuente
- NO omitas la sección ## References bajo ningún concepto

Genera el reporte siguiendo las reglas de formato especificadas."""
                    
                    final_tokens = system_tokens + count_tokens(user_msg, model_name or "gpt-4")
                    print(f"      ⚠️  Truncamiento extremo aplicado: {final_tokens:,} tokens finales")
            
            # Verificación final antes de enviar
            max_allowed = MAX_TOKENS_MODEL if is_deepinfra else MAX_TOKENS_AVAILABLE
            if final_tokens > max_allowed:
                provider_name = "DeepInfra" if is_deepinfra else "el proveedor"
                print(f"      ❌ ERROR: No se puede reducir el prompt a menos de {max_allowed:,} tokens (actual: {final_tokens:,})")
                print(f"      ⚠️  El contenido es demasiado grande. Se usará el fallback.")
                raise ValueError(f"Prompt demasiado grande para {provider_name}: {final_tokens:,} tokens > {max_allowed:,} tokens")
            
            print(f"      ✅ Truncamiento completado: {final_tokens:,} tokens finales (dentro del límite de {max_allowed:,})")
        else:
            # No necesita truncamiento, calcular tokens finales
            final_tokens = total_tokens
        
        print(f"      📊 Enviando {len(sources_text)} caracteres al modelo...")
        print(f"      🔍 Modelo utilizado: {type(llm).__name__} ({model_name if model_name else 'desconocido'})")
        
        response = await llm.ainvoke(
            [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]
        )

        report = response.content if hasattr(response, "content") else str(response)
        
        # Limpiar metadatos y mensajes de proceso del reporte
        report = _clean_report_metadata(report)
        
        # Verificar que el reporte no esté vacío
        if not report or len(report.strip()) < 100:
            raise ValueError(f"El LLM devolvió un reporte vacío o muy corto ({len(report) if report else 0} caracteres)")
        
        # Auto-corrección: Agregar sección ## References si falta
        report = _ensure_references_section(report, all_sources)

        from .utils import count_tokens
        full_prompt_text = system_msg + "\n" + user_msg
        tokens = count_tokens(full_prompt_text)

        print(f"      ✅ Reporte generado exitosamente ({len(report)} caracteres, ~{tokens} tokens)")
        return report, tokens

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"      ❌ Error al generar reporte con el LLM:")
        print(f"      🔴 Tipo de error: {type(e).__name__}")
        print(f"      🔴 Mensaje: {str(e)}")
        print(f"      🔴 Traceback completo:")
        print(f"      {error_details}")
        
        # Fallback: reporte simple con contenido real basado en fuentes
        print(f"      ⚠️ Generando reporte simple como fallback...")
        report = f"# {topic}\n\n"
        
        # Generar contenido básico basado en las fuentes
        if all_sources:
            report += f"Este reporte analiza {topic} basándose en {len(all_sources)} fuentes de información. "
            report += "A continuación se presenta un resumen de los hallazgos principales.\n\n"
            
            # Agrupar fuentes por tema o extraer información clave
            # Tomar las primeras 5-10 fuentes más relevantes y extraer snippets
            top_sources = sorted(all_sources, key=lambda x: x.get('total_score', x.get('score', 0)), reverse=True)[:10]
            
            report += "## Hallazgos Principales\n\n"
            
            for i, source in enumerate(top_sources, 1):
                title = source.get('title', 'N/A')
                snippet = source.get('snippet', source.get('raw_content', ''))[:500]  # Primeros 500 caracteres
                url = source.get('url', 'N/A')
                
                if snippet and snippet.strip():
                    report += f"Según {title} [{i}], {snippet.strip()}\n\n"
                else:
                    report += f"La fuente {title} [{i}] proporciona información relevante sobre {topic}.\n\n"
            
            # Si hay más fuentes, mencionarlas brevemente
            if len(all_sources) > len(top_sources):
                report += f"\nAdicionalmente, se consultaron {len(all_sources) - len(top_sources)} fuentes adicionales que proporcionan información complementaria sobre {topic}.\n\n"
        else:
            report += f"No se encontraron fuentes suficientes para generar un reporte completo sobre {topic}.\n\n"
        
        # CRÍTICO: Agregar sección ## References al fallback también
        report = _ensure_references_section(report, all_sources)
        
        # Calcular tokens del fallback también
        from .utils import count_tokens
        tokens = count_tokens(report)
        return report, tokens


async def generate_final_report(topic: str, knowledge_base: List[Dict]) -> str:
    """
    Genera un reporte final detallado usando Gemini 2.5 Pro para síntesis masiva.
    NOTE: This synchronous version is kept for compatibility if needed, 
    but for the main pipeline we should probably use an async version or wrap it.
    If this is not used in the main async pipeline, we can leave it as is.
    However, if it IS used, it should be async. Assuming it is NOT used in the graph loop based on graph.py.
    """
    # ... implementation stays sync unless verified it's used in async path ...
    # Actually, let's check graph.py. Only generate_markdown_report is imported and used in reporter_node.
    # So we can leave this one as is or make it async if we want consistency.
    # Let's leave it for now to avoid breaking other scripts unless specified.
    return "Legacy function - use generate_markdown_report"
    print(f"\n   🧠 [GEMINI ANALYST] Generando síntesis final con Gemini 2.5 Pro...")
    print(f"      Procesando {len(knowledge_base)} fuentes validadas...")

    if not knowledge_base:
        return "⚠️ No se encontraron fuentes válidas para este tema."

    # Construir el contenido completo de la base de conocimientos
    # Gemini puede manejar contextos enormes, así que incluimos todo
    knowledge_content = f"TEMA DE INVESTIGACIÓN: {topic}\n\n"
    knowledge_content += "=" * 80 + "\n"
    knowledge_content += "BASE DE CONOCIMIENTOS RECOPILADA\n"
    knowledge_content += "=" * 80 + "\n\n"

    for i, source in enumerate(knowledge_base, 1):
        knowledge_content += f"--- FUENTE {i} ---\n"
        knowledge_content += f"Título: {source.get('title', 'N/A')}\n"
        knowledge_content += f"URL: {source.get('url', 'N/A')}\n"
        knowledge_content += f"Dominio: {source.get('source_domain', 'N/A')}\n"
        # Mostrar scores multidimensionales si están disponibles
        if all(
            key in source
            for key in [
                "authenticity_score",
                "reliability_score",
                "relevance_score",
                "currency_score",
            ]
        ):
            knowledge_content += f"Authenticity: {source.get('authenticity_score', 'N/A')}/10\n"
            knowledge_content += f"Reliability: {source.get('reliability_score', 'N/A')}/10\n"
            knowledge_content += f"Relevance: {source.get('relevance_score', 'N/A')}/10\n"
            knowledge_content += f"Currency: {source.get('currency_score', 'N/A')}/10\n"
            knowledge_content += (
                f"Total Score: {source.get('total_score', source.get('score', 'N/A'))}/10\n"
            )
            if source.get("is_clickbait") is not None:
                knowledge_content += f"Clickbait: {'Sí' if source.get('is_clickbait') else 'No'}\n"
        else:
            knowledge_content += (
                f"Score de Calidad: {source.get('score', source.get('total_score', 'N/A'))}/10\n"
            )
        # Usar 'reasoning' si está disponible, sino 'reason' (compatibilidad)
        reasoning = source.get("reasoning", source.get("reason", "N/A"))
        knowledge_content += f"Razón de Aceptación: {reasoning}\n"
        content = source.get('raw_content', source.get('snippet', 'N/A'))[:2000]
        knowledge_content += f"\nContenido:\n{content}\n"
        knowledge_content += "\n" + "-" * 80 + "\n\n"

    system_msg = """Eres un Analista de Investigación Senior especializado en síntesis estratégica.
Tu misión es analizar TODA la información recopilada y generar un informe estratégico detallado y extenso.

INSTRUCCIONES CRÍTICAS:
1. Lee y analiza TODA la información proporcionada. No dejes nada fuera.
2. Identifica patrones, tendencias y conexiones entre las diferentes fuentes.
3. Usa referencias cruzadas entre fuentes para validar y enriquecer el análisis.
4. Estructura el informe de manera profesional y estratégica.
5. Incluye citas y referencias a las fuentes cuando sea relevante.
6. Proporciona insights accionables y conclusiones estratégicas.
7. El informe debe ser extenso y detallado, aprovechando toda la información disponible.

FORMATO DEL INFORME:
- Resumen Ejecutivo
- Análisis Detallado (con subsecciones según corresponda)
- Tendencias y Patrones Identificados
- Referencias Cruzadas entre Fuentes
- Conclusiones Estratégicas
- Recomendaciones (si aplica)

Escribe en formato Markdown para facilitar la lectura."""

    user_msg = f"""{knowledge_content}

Genera un informe estratégico completo y detallado que sintetice TODA esta información.
Aprovecha la capacidad de contexto para hacer referencias cruzadas y análisis profundo."""

    try:
        # Seleccionar modelo: Gemini 2.5 Pro para síntesis final (reduce)
        # Esta es la síntesis final con evidencia ya filtrada - usar Gemini para máxima calidad
        llm = llm_analyst_fast if llm_analyst_fast is not None else llm_analyst
        print(f"      📊 Enviando {len(knowledge_content)} caracteres de contexto a Gemini 2.5 Pro (síntesis final)...")
        response = await llm.ainvoke(
            [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]
        )

        report = response.content if hasattr(response, "content") else str(response)

        # Agregar metadatos al inicio del reporte
        final_report = f"# Reporte de Investigación: {topic}\n\n"
        final_report += f"**Fecha:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        final_report += f"**Fuentes analizadas:** {len(knowledge_base)}\n\n"
        final_report += "---\n\n"
        final_report += report

        print(f"      ✅ Síntesis generada exitosamente ({len(final_report)} caracteres)")
        return final_report

    except Exception as e:
        print(f"      ❌ Error al generar síntesis con Gemini: {e}")
        # Fallback: usar el reporte Markdown simple
        print(f"      ⚠️ Usando reporte Markdown simple como fallback...")
        return await generate_markdown_report(
            topic=topic, all_sources=knowledge_base, report_type="General"
        )
