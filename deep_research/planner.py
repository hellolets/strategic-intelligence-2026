"""
Módulo Planner: Genera estrategias de búsqueda usando GPT-4.
"""
import json
import time
import asyncio
from typing import List, Dict, Optional, Any
from .config import llm_planner, MAX_SEARCH_QUERIES

async def generate_search_strategy(topic: str, custom_prompt: Optional[str] = None, existing_sources: Optional[str] = None, project_title: Optional[str] = None, related_topics: List[str] = [], full_index: List[str] = [], agent_description: Optional[str] = None, company_context: Dict[str, Any] = {}, failed_queries: List[str] = [], max_search_queries: Optional[int] = None, hierarchical_context: str = "", brief: str = "") -> List[Dict]:
    """
    Genera una estrategia de búsqueda basada en un tema.
    Si hay fuentes existentes, hace un gap analysis para buscar solo lo que falta.
    
    Args:
        topic: Tema o índice a investigar
        custom_prompt: Prompt personalizado (opcional)
        existing_sources: Fuentes ya acumuladas para hacer gap analysis (opcional)
        max_search_queries: Máximo de queries a generar (opcional, usa MAX_SEARCH_QUERIES si no se especifica)
    
    Returns:
        Lista de tareas con queries de búsqueda
    """
    # Usar max_search_queries dinámico si se proporciona, sino usar el global
    effective_max_queries = max_search_queries if max_search_queries is not None else MAX_SEARCH_QUERIES
    # Asegurarse de que existing_sources sea string (puede ser lista desde Airtable)
    if existing_sources:
        if isinstance(existing_sources, list):
            existing_sources = '\n'.join(str(s) for s in existing_sources) if existing_sources else None
        existing_sources = str(existing_sources) if existing_sources else None
    
    from .logger import logger
    logger.log_phase("PLANNER", f"[{topic[:30]}] Diseñando estrategia de búsqueda...")
    if project_title:
        logger.log_info(f"Contexto: {project_title}")
    
    # Obtener año actual para incluir en las búsquedas
    current_year = time.strftime('%Y')
    previous_year = str(int(current_year) - 1)
    
    # Prompt por defecto
    default_system_msg = f"""Eres un experto OSINT (Open Source Intelligence). 
    Tu misión es generar queries de búsqueda efectivas para Tavily (API de búsqueda especializada en investigación).
    
    INSTRUCCIONES:
    1. Usa lenguaje natural + keywords relevantes. Tavily entiende queries en lenguaje natural.
    2. Añade "PDF" o "Report" al final si buscas informes oficiales.
    4. PRIORIDAD EXTERNA: Aunque el documento final es para la empresa del cliente, NO busques información interna de la propia empresa (ya contamos con ella). Tu objetivo es maximizar la captura de INFORMACIÓN EXTERNA: mercados globales, tendencias del sector, datos de competidores, informes de consultoras, papers académicos y noticias de mercado.
    5. IMPORTANTE: Prioriza información RECIENTE. Incluye el año actual ({current_year}) o el año anterior ({previous_year}) en las queries cuando sea relevante para datos de mercado, estadísticas, o informes.
    7. Tavily está optimizado para búsquedas de investigación, así que sé específico y descriptivo en tus queries.
    8. RESTRICCIÓN EMPRESARIAL: NO incluyas el nombre de la empresa cliente en tus queries. Queremos una visión "outside-in" del mercado, no noticias corporativas internas. Si el tema es sobre infraestructuras, busca "infrastructure trends", "toll roads market", etc., sin mencionar a la empresa específica.
    9. ALINEACIÓN TOTAL CON EL PROYECTO:
       - TU FOCO ES EXTRACTIVO Y DIFERENCIAL.
       - Debes entender qué pide específicamente el tema del capítulo '{topic}' DENTRO del objetivo general del proyecto '{project_title}'.
       - ¿Qué hace único a este capítulo? ¿Qué información específica necesita el proyecto de este tema? Diférencialo de otros capítulos.
       - Busca EXCLUSIVAMENTE información que responda a este tema específico. No busques información general del proyecto si no aplica a este capítulo concreto.
       - Intenta incluiren las búsquedas la palabra clave del titulo del proyecto.
    
    FORMATO JSON OBLIGATORIO:
    {{
      "tasks": [
        {{
          "topic": "Resumen del tema",
          "queries": ["query 1", "query 2", "query 3"]
        }}
      ]
    }}
    """

    project_context_section = ""
    if project_title:
        project_context_section = f"\n    CONTEXTO DEL PROYECTO: {project_title}\n"
    
    if full_index:
        # Formatear el índice para mostrar contexto
        index_str = "\n    - " + "\n    - ".join(full_index[:50]) # Limitar a 50 items para no saturar
        if len(full_index) > 50:
            index_str += "\n    - ..."
        project_context_section += f"\n    ÍNDICE COMPLETO DEL PROYECTO:{index_str}\n"
        project_context_section += f"\n    TU TAREA ACTUAL ES INVESTIGAR EL PUNTO: '{topic}'\n"

    # Sección de contexto jerárquico (padre, hermanos, hijos)
    hierarchical_section = ""
    if hierarchical_context:
        hierarchical_section = f"\n    {hierarchical_context}\n"

    # Sección de Brief/Objetivo del capítulo
    brief_section = ""
    if brief:
        brief_section = f"\n    BRIEF/OBJETIVO DEL CAPÍTULO:\n    {brief}\n"

    agent_context_section = ""
    if agent_description:
        agent_context_section = f"""
    ROL DEL AGENTE ASIGNADO PARA ESTE TOPIC EN CONCRETO (TÚ ERES ESTE AGENTE):
    {agent_description}

    INSTRUCCIÓN DE ROL: Tu estrategia de búsqueda DEBE estar alineada con este rol. Busca información que permita a este agente escribir un reporte excelente desde su perspectiva única.
    """

    # Sección de queries fallidas (para evitar repetir)
    failed_queries_section = ""
    if failed_queries:
        failed_list = "\n    - ".join(failed_queries[-10:])  # Últimas 10
        failed_queries_section = f"""
    
    ⚠️ QUERIES QUE NO DIERON BUENOS RESULTADOS (EVITAR SIMILARES):
    - {failed_list}
    
    INSTRUCCIÓN: Genera queries DIFERENTES que aborden el tema desde otro ángulo.
    Prueba: sinónimos, términos más específicos, fuentes alternativas, otros idiomas (inglés si el tema es global), site:domain para fuentes específicas.
    """

    # NOTA: El contexto de la empresa ahora viene de Airtable (campo Context en Proyectos)
    # No se usa company_context del JSON, se usa project_specific_context de Airtable
    company_context_section = ""
    # company_context ya no se usa - el contexto viene de Airtable en project_specific_context

    # 1. Caso Default (sin fuentes, sin custom prompt)
    default_system_msg = default_system_msg.replace("INSTRUCCIONES:", f"{project_context_section}{hierarchical_section}{brief_section}{agent_context_section}{company_context_section}{failed_queries_section}\n\n    INSTRUCCIONES:")
    
    # Si hay fuentes existentes, hacer gap analysis
    if existing_sources and existing_sources.strip():
        logger.log_info("Fuentes existentes detectadas. Realizando Gap Analysis...")
        gap_analysis_base = f"""Eres un Analista de Investigación Senior especializado en Gap Analysis.
        
Tu misión es analizar las fuentes ya recopiladas e identificar QUÉ FALTA investigar.
{project_context_section}
{hierarchical_section}
{brief_section}
{agent_context_section}

INSTRUCCIONES:
1. PRIORIDAD EXTERNA: Enfócate en cubrir los gaps con información EXTERNA (mercado, competidores, tendencias globales). No busques información interna de la empresa del cliente ya que esa base ya está cubierta.
2. Genera un MÁXIMO de {effective_max_queries} queries en total.
3. NO generes queries para temas ya bien cubiertos.
4. Enfócate en encontrar información complementaria y nueva del mercado exterior.
5. RESTRICCIÓN EMPRESARIAL: NO incluyas el nombre de la empresa cliente en tus queries. Queremos una visión "outside-in" del mercado, no noticias corporativas internas. Si el tema es sobre infraestructuras, busca "infrastructure trends", "toll roads market", etc., sin mencionar a la empresa específica.
6. ALINEACIÓN TOTAL CON EL PROYECTO: TU FOCO ES EXTRACTIVO Y DIFERENCIAL. Debes entender qué pide específicamente el tema '{topic}' dentro del objetivo del proyecto '{project_title}'. Busca EXCLUSIVAMENTE información que responda a este gap específico.

FORMATO JSON OBLIGATORIO:
{{
  "tasks": [
    {{
      "topic": "Aspecto faltante identificado",
      "queries": ["query específica para gap 1", "query específica para gap 2"]
    }}
  ]
}}"""
        
        # Si hay custom_prompt, combinarlo con gap analysis
        if custom_prompt:
            system_msg = f"""{custom_prompt}

{gap_analysis_base}"""
        else:
            system_msg = gap_analysis_base
            
        user_msg = f"""TEMA PRINCIPAL: {topic}

FUENTES YA RECOPILADAS:
{existing_sources}

TAREA: Analiza las fuentes existentes e identifica qué información falta. 
Genera queries de búsqueda ESPECÍFICAS solo para cubrir esos gaps.
No busques información que ya está bien cubierta.

IMPORTANTE: Responde ÚNICAMENTE en formato JSON con la estructura especificada."""
    else:
        # Si hay custom_prompt, combinarlo con las instrucciones de formato
        if custom_prompt:
            system_msg = f"""{custom_prompt}
{project_context_section}
{hierarchical_section}
{brief_section}
{agent_context_section}

Además, eres un experto OSINT (Open Source Intelligence). 
Tu misión es generar queries de búsqueda efectivas para Tavily (API de búsqueda especializada en investigación).

INSTRUCCIONES:
1. Usa lenguaje natural + keywords relevantes. Tavily entiende queries en lenguaje natural.
2. Añade "PDF" o "Report" al final si buscas informes oficiales.
3. PRIORIDAD EXTERNA: Enfócate en capturar INFORMACIÓN EXTERNA (mercado, competidores, tendencias globales). No busques información interna del cliente ya que esa base ya está cubierta.
4. IMPORTANTE: Prioriza información RECIENTE. Incluye el año actual ({current_year}) o el año anterior ({previous_year}) en las queries cuando sea relevante para datos de mercado, estadísticas, o informes.
5. Para temas que requieren información actualizada (mercados, tendencias, datos económicos), SIEMPRE incluye "{current_year}" o "{previous_year}" en al menos una query.
6. Tavily está optimizado para búsquedas de investigación, así que sé específico y descriptivo en tus queries.
7. RESTRICCIÓN EMPRESARIAL: NO incluyas el nombre de la empresa cliente en tus queries.
8. ALINEACIÓN TOTAL CON EL PROYECTO: 
   - TU FOCO ES EXTRACTIVO Y DIFERENCIAL. 
   - Genera queries que busquen CÓMO el tema '{topic}' impacta o se relaciona con el objetivo del proyecto '{project_title}'.
   - Evita búsquedas genéricas si el proyecto pide un enfoque específico.

FORMATO JSON OBLIGATORIO:
{{
  "tasks": [
    {{
      "topic": "Resumen del tema",
      "queries": ["query 1", "query 2", "query 3"]
    }}
  ]
}}"""
        else:
            system_msg = default_system_msg
        user_msg = f"""TEMA A INVESTIGAR:
{topic}

Genera el plan de búsqueda en formato JSON con la estructura especificada.
IMPORTANTE: Responde ÚNICAMENTE en formato JSON, sin texto adicional antes o después."""

    # Función helper para llamar al LLM con reintentos y manejo de rate limiting
    async def call_llm_with_retry(llm_client, messages, max_retries=3):
        """Llama al LLM con reintentos exponenciales para manejar rate limiting."""
        import time
        from openai import RateLimitError
        
        for attempt in range(max_retries):
            try:
                response = await llm_client.ainvoke(messages)
                return response, None
            except Exception as e:
                error_str = str(e).lower()
                error_code = None
                
                # Detectar error 429 (rate limit)
                if "429" in error_str or "rate limit" in error_str or "rate-limited" in error_str:
                    error_code = 429
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 2  # 2, 4, 8 segundos
                        logger.log_warning(f"   ⚠️  Rate limit detectado (intento {attempt + 1}/{max_retries}). Esperando {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.log_error(f"   ❌ Rate limit persistente después de {max_retries} intentos")
                        return None, e
                else:
                    # Otro tipo de error, no reintentar
                    return None, e
        
        return None, Exception("Error desconocido después de reintentos")
    
    # Intentar con llm_planner primero (MiMo-V2-Flash)
    response = None
    error = None
    
    try:
        response, error = await call_llm_with_retry(llm_planner, [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ])
        
        # Si falló por rate limit, intentar con fallback
        if response is None and error:
            error_str = str(error).lower()
            if "429" in error_str or "rate limit" in error_str or "rate-limited" in error_str:
                logger.log_warning("   ⚠️  MiMo-V2-Flash rate-limited, intentando fallback...")
                # Fallback a otro modelo (opcional, si está configurado)
                # Por ahora, simplemente reintentar después de más tiempo
                await asyncio.sleep(10)  # Esperar 10 segundos antes de reintentar
                try:
                    response = await llm_planner.ainvoke([
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg}
                    ])
                    error = None
                    logger.log_success("   ✅ Fallback exitoso después de espera extendida")
                except Exception as e2:
                    error = e2
                    logger.log_error(f"   ❌ Fallback también falló: {e2}")
    except Exception as e:
        error = e
        response = None
    
    # Si no hay response, retornar vacío
    if response is None:
        logger.log_error(f"❌ Error en Planner: {error}")
        return []
    
    # Capturar tokens usados si están disponibles
    planner_tokens = 0
    if hasattr(response, 'response_metadata') and response.response_metadata:
        token_usage = response.response_metadata.get('token_usage', {})
        planner_tokens = token_usage.get('total_tokens', 0)
    else:
        # Estimación basada en contenido si no hay metadata
        from .utils import count_tokens
        planner_tokens = count_tokens(system_msg + "\n" + user_msg + "\n" + (response.content if hasattr(response, "content") else str(response)))
    
    # Cleaning step: Remove markdown and problematic whitespace
    content = response.content.strip() if hasattr(response, "content") else str(response).strip()
    
    # Remove markdown code blocks
    if "```" in content:
        if "```json" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
        else:
            content = content.split("```")[1].split("```")[0].strip()
    
    # Attempt to extract outermost JSON object if extra text exists
    if not content.startswith("{") or not content.endswith("}"):
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = content[start_idx:end_idx+1]

    # FIX: Clean newlines inside strings that break JSON parsing
    # This regex looks for newlines that are inside double quotes
    import re
    content = re.sub(r'(?<=[^"\\])"(.*?)(?<!\\)"', lambda m: '"' + m.group(1).replace('\n', ' ') + '"', content, flags=re.DOTALL)

    
    # Parsear JSON
    try:
            data = json.loads(content)
            if not isinstance(data, dict):
                logger.log_warning("El Planner no devolvió un objeto JSON válido.")
                return []
            
            tasks = data.get("tasks", [])
            if not isinstance(tasks, list):
                logger.log_warning("El campo 'tasks' no es una lista.")
                return []
            
            # --- CORRECCIÓN: IMPONER LÍMITE TOTAL ESTRICTO ---
            # Para evitar "búsquedas de más", limitamos el total de queries globales.
            total_allowed = effective_max_queries  # Límite estricto según configuración (dinámico o global)
            current_total = 0
            final_tasks = []
            
            for task in tasks:
                if not isinstance(task, dict) or "queries" not in task:
                    continue
                
                queries = task.get("queries", [])
                if not isinstance(queries, list):
                    continue
                
                # Cuántas podemos aceptar de esta tarea?
                remaining_quota = total_allowed - current_total
                if remaining_quota <= 0:
                    break
                
                # Tomar el mínimo entre las que tiene la tarea, el límite por tarea y la cuota restante
                queries_to_take = queries[:min(len(queries), effective_max_queries, remaining_quota)]
                
                if queries_to_take:
                    task["queries"] = queries_to_take
                    final_tasks.append(task)
                    current_total += len(queries_to_take)
            
            tasks = final_tasks
            # -------------------------------------------

            logger.log_success(f"Estrategia generada: {len(tasks)} tarea(s), {current_total} queries totales")
            # Retornar tasks y tokens (para compatibilidad, retornamos solo tasks, tokens se capturan en el nodo)
            return tasks
            
    except json.JSONDecodeError as e:
        logger.log_error(f"Error al parsear JSON del Planner: {e}")
        logger.log_info(f"Contenido recibido (primeros 200 chars): {content[:200]}...")
        return []
