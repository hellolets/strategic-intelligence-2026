"""
Módulo Graph: Definición del flujo de trabajo con LangGraph.
Incluye Quality Gate y estadísticas de evaluación.
"""
import time
import asyncio
from typing import Dict, List
from langgraph.graph import StateGraph, END

from .state import ResearchState
from .config import CURRENT_PLANNER_MODEL, CURRENT_JUDGE_MODEL, MIN_ACCEPTED_SOURCES, MAX_ACCEPTED_SOURCES, MAX_RETRIES, VERIFIER_ENABLED, QUERY_EXPANSION_ENABLED, URL_VALIDATION_ENABLED, EVAL_GENERAL_MEDIA_MAX_RATIO, CONTEXT_QUERY_VARIANTS_ENABLED, SMART_SEARCH_ENABLED, get_dynamic_config, MAX_RESULTS_PER_QUERY, MAX_SEARCH_QUERIES
from .logger import logger
from .planner import generate_search_strategy
from .searcher import execute_search_multi_layer
from .extractor import extract_evidence_package
from .evaluator import evaluate_source, get_evaluation_stats, print_evaluation_summary
from .reporter import generate_markdown_report
from .verifier import verify_report
from .validate_references import validate_references, format_references_summary
from .utils import extract_urls_from_sources, extract_rejected_urls_from_sources, format_source_for_storage, save_debug_sources, canonicalize_url, truncate_text, build_hierarchical_context
from .source_quality import check_quality_gate, calculate_confidence_score, format_confidence_badge
from .config import (
    FIRECRAWL_ENABLED, FIRECRAWL_API_KEY, FIRECRAWL_ONLY_FOR_VALIDATED_SOURCES,
    FIRECRAWL_MAX_CHARS_PER_SOURCE, FIRECRAWL_TIMEOUT_SECONDS, FIRECRAWL_MIN_EXISTING_CONTENT_CHARS,
    FIRECRAWL_MAX_CALLS_PER_ITEM,
    MAX_CHARS_PER_SOURCE
)

# ==========================================
# NODOS DEL GRAFO
# ==========================================

async def planner_node(state: ResearchState) -> ResearchState:
    # Obtener configuraciones dinámicas según report_type
    report_type = state.get('report_type', state.get('prompt_type', None))
    dynamic_config = get_dynamic_config(report_type)
    max_search_queries = dynamic_config.get('max_search_queries', MAX_SEARCH_QUERIES)
    
    # Logging de configuración dinámica
    is_critical = report_type in ["Strategic", "Financial", "Due_Diligence"] if report_type else False
    config_type = "CRÍTICO" if is_critical else "GENERAL"
    logger.log_info(f"   ⚙️  Configuración dinámica ({config_type}): max_search_queries={max_search_queries}")
    """Genera la estrategia de búsqueda."""
    logger.log_phase("PLANNER", f"Generando estrategia para: {state['topic'][:50]}...")
    logger.log_model_usage("Planner", CURRENT_PLANNER_MODEL)
    
    # Configurar prompts
    prompt_type = state.get('prompt_type', 'General')
    planner_prompt = state.get('system_prompt')
    
    # Obtener queries fallidas para evitar repetir
    failed_queries = state.get('failed_queries', [])
    
    # Inicializar tokens_by_role si no existe
    tokens_by_role = state.get('tokens_by_role', {})
            
    # Generar estrategia
    try:
        # Capturar tokens del planner llamando directamente al LLM
        from .planner import generate_search_strategy
        from .config import llm_planner
        from .utils import count_tokens
        
        # Generar contexto jerárquico automático (padre, hermanos, hijos)
        h_ctx = build_hierarchical_context(state['topic'], state.get('full_index', []))
        if h_ctx:
            print(f"      📐 [PLANNER] Contexto jerárquico inyectado ({len(h_ctx)} chars)")
        else:
            print(f"      📐 [PLANNER] Sin contexto jerárquico (item sin numeración o sin hermanos/hijos)")

        brief = state.get('brief', '')
        if brief:
            print(f"      📋 [PLANNER] Brief inyectado ({len(brief)} chars)")

        # Estimar tokens del planner (se capturarán en la función)
        tasks = await generate_search_strategy(
            topic=state['topic'],
            custom_prompt=planner_prompt,
            existing_sources=state['existing_sources_text'],
            project_title=state.get('project_name'),
            related_topics=state.get('related_topics', []),
            full_index=state.get('full_index', []),
            agent_description=state.get('agent_description', ''),
            company_context=state.get('company_context', {}),
            failed_queries=failed_queries,
            max_search_queries=max_search_queries,
            hierarchical_context=h_ctx,
            brief=brief
        )
        
        if not tasks:
            return {
                "error": "No se pudo generar estrategia de búsqueda.",
                "project_specific_context": state.get('project_specific_context')  # Preservar contexto incluso en error
            }
        
        # Estimar tokens del planner (aproximación basada en queries generadas)
        # Una estimación conservadora: ~500-1000 tokens por query generada
        estimated_planner_tokens = len(tasks) * 800  # Estimación promedio
        tokens_by_role["planner"] = tokens_by_role.get("planner", 0) + estimated_planner_tokens
            
        return {
            "search_strategy": tasks,
            "tokens_by_role": tokens_by_role,
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto
        }
        
    except Exception as e:
        return {
            "error": f"Error en Planner: {e}",
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto incluso en error
        }


async def searcher_node(state: ResearchState) -> ResearchState:
    """Ejecuta las búsquedas definidas en la estrategia."""
    # Obtener configuraciones dinámicas según report_type
    report_type = state.get('report_type', state.get('prompt_type', None))
    dynamic_config = get_dynamic_config(report_type)
    max_results_per_query = dynamic_config.get('max_results_per_query', MAX_RESULTS_PER_QUERY)
    
    # Logging de configuración dinámica
    is_critical = report_type in ["Strategic", "Financial", "Due_Diligence"] if report_type else False
    config_type = "CRÍTICO" if is_critical else "GENERAL"
    logger.log_info(f"   ⚙️  Configuración dinámica ({config_type}): max_results_per_query={max_results_per_query}")
    tasks = state.get('search_strategy', [])
    if not tasks:
        logger.log_warning("No hay tareas de búsqueda.")
        return {
            "error": "No hay tareas de búsqueda.",
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto incluso en error
        }
        
    logger.log_phase("SEARCHER", f"[{state['topic'][:30]}] Ejecutando {len(tasks)} tareas de búsqueda...")
    
    all_raw_results = []
    
    # Preparar filtros de duplicados globales
    existing_urls = extract_urls_from_sources(state.get('existing_sources_text', ''))
    rejected_urls = extract_rejected_urls_from_sources(state.get('existing_sources_text', ''))
    
    # ==========================================
    # CONTEXT MANAGER INTEGRATION (Policy 2)
    # ==========================================
    project_context = None
    query_variants_trace = []  # Para logging/tracing
    
    if CONTEXT_QUERY_VARIANTS_ENABLED:
        try:
            from .context_manager import get_project_context
            from .config import llm_planner  # Para extracción LLM opcional
            
            project_name = state.get('project_name', '')
            project_specific_context = state.get('project_specific_context', '')
            project_id = state.get('project_id', state.get('record_id', ''))  # Fallback a record_id
            
            # Obtener ProjectContext una vez por proyecto (cacheado internamente)
            if project_name or project_specific_context:
                try:
                    project_context = get_project_context(
                        project_id=project_id or '',
                        project_specific_context=project_specific_context or '',
                        project_name=project_name or '',
                        config_override='',  # TODO: Si hay campo Context_Config en Airtable, pasarlo aquí
                        llm=llm_planner if project_specific_context and len(project_specific_context) > 500 else None
                    )
                except Exception as e:
                    logger.log_warning(f"   ⚠️ Error obteniendo ProjectContext: {e}")
                    project_context = None
                
                if project_context and not project_context.is_empty():
                    logger.log_info(f"   📋 ContextManager activo: sector={project_context.sector}, geografía={project_context.geography}, competidores={len(project_context.competitors)}")
                else:
                    # Verificar si hay contexto en el estado pero no se pudo procesar
                    if project_specific_context and project_specific_context.strip():
                        logger.log_warning(f"   ⚠️ Contexto disponible en estado ({len(project_specific_context)} caracteres) pero ContextManager no pudo procesarlo")
                    else:
                        logger.log_info(f"   ℹ️ No hay contexto específico del proyecto en el estado")
        except Exception as e:
            logger.log_warning(f"   ⚠️ Error inicializando ContextManager: {e}. Continuando sin variantes de queries.")
            project_context = None
    
    # ==========================================
    # EJECUTAR BÚSQUEDAS CON/SIN VARIANTS
    # ==========================================
    for task in tasks:
        task_topic = task.get('topic', state['topic'])
        base_queries = task.get('queries', [])
        
        if not base_queries:
            continue
            
        # Construir variantes de queries si ContextManager está activo
        all_queries_to_execute = []
        task_variants_info = []
        
        if CONTEXT_QUERY_VARIANTS_ENABLED and project_context and not project_context.is_empty():
            # Para cada query base, generar variantes
            for base_query in base_queries:
                if not base_query:  # Skip None/empty queries
                    continue
                from .context_manager import build_query_variants
                try:
                    variants = build_query_variants(base_query, project_context)
                except Exception as e:
                    logger.log_warning(f"   ⚠️ Error generando variantes para query '{base_query[:50]}': {e}")
                    variants = [base_query]  # Fallback a query original
                
                if variants:
                    # Usar variantes (máximo 2: precise y broad/disambiguated)
                    all_queries_to_execute.extend(variants[:2])
                    task_variants_info.append({
                        'base_query': base_query,
                        'variants': variants[:2],
                        'count': len(variants[:2])
                    })
                else:
                    # Fallback a query original si no hay variantes
                    all_queries_to_execute.append(base_query)
                    task_variants_info.append({
                        'base_query': base_query,
                        'variants': [base_query],
                        'count': 1
                    })
        else:
            # Modo legacy: usar queries originales sin variantes
            all_queries_to_execute = base_queries
            task_variants_info = [{'base_query': q, 'variants': [q], 'count': 1} for q in base_queries]
        
        # Logging de variantes
        if task_variants_info:
            logger.log_info(f"   🔍 Tarea '{task_topic[:40]}': {len(base_queries)} query(s) base → {len(all_queries_to_execute)} variante(s) total")
            for vinfo in task_variants_info[:2]:  # Log solo primeras 2 para no saturar
                if vinfo['count'] > 1:
                    logger.log_info(f"      '{vinfo['base_query'][:50]}' → {vinfo['count']} variantes")
        
        # Ejecutar búsqueda multi-layer con todas las variantes
        # Capa D: Pasar información de estado para activación condicional de Exa
        try:
            # Obtener información de estado para Exa condicionado
            # report_type ya está obtenido arriba en searcher_node
            loop_count = state.get('loop_count', 0)
            validated_sources_count = len(state.get('validated_sources', []))
            verifier_high_issues_count = state.get('verification_high_severity_count', 0)
            
            # Si smart_search está habilitado, usar execute_search_smart directamente con parámetros condicionales
            if SMART_SEARCH_ENABLED:
                from .searcher import execute_search_smart
                raw_results = await execute_search_smart(
                    all_queries_to_execute,
                    max_results=max_results_per_query,  # Usar configuración dinámica
                    topic=state['topic'],
                    loop_count=loop_count,
                    validated_sources_count=validated_sources_count,
                    report_type=report_type,
                    verifier_high_issues_count=verifier_high_issues_count,
                )
            else:
                # Usar execute_search_multi_layer para modo no-smart
                raw_results = await execute_search_multi_layer(
                    all_queries_to_execute, 
                    max_results=max_results_per_query,  # Usar configuración dinámica
                    topic=state['topic'],
                    expand_queries=False,  # Ya tenemos variantes, no expandir más
                    validate_urls=URL_VALIDATION_ENABLED,
                    smart_search=False
                )
        except Exception as e:
            logger.log_warning(f"   ⚠️ Error en búsqueda para tarea '{task_topic}': {e}. Continuando...")
            raw_results = []
        
        # ==========================================
        # FILTRADO Y RERANKING CON CONTEXT MANAGER
        # ==========================================
        if CONTEXT_QUERY_VARIANTS_ENABLED and project_context and not project_context.is_empty() and raw_results:
            try:
                from .context_manager import filter_results, rerank_results
                
                # Filtrar resultados irrelevantes (ej: ACS -> excluir American Chemical Society)
                valid_results, filtered_out = filter_results(raw_results, project_context)
                
                if filtered_out:
                    logger.log_info(f"      🔍 Filtrados por ContextManager: {len(filtered_out)}/{len(raw_results)} resultados")
                
                # Reranking contextual (priorizar por sector, geografía, competidores)
                ranked_results = rerank_results(valid_results, project_context, top_n=len(valid_results))
                
                raw_results = ranked_results
                
                logger.log_info(f"      📊 Reranking aplicado: top {min(10, len(ranked_results))} resultados priorizados")
            except Exception as e:
                logger.log_warning(f"   ⚠️ Error en filtrado/reranking: {e}. Usando resultados sin filtrar.")
        
        # Filtrar duplicados y fuentes previas (lógica existente)
        for res in raw_results:
            source_url = res.get('url', '')
            if not source_url:
                continue
                
            normalized_url = canonicalize_url(source_url)
            
            # Check contra existentes
            if any(canonicalize_url(u) == normalized_url for u in existing_urls):
                continue
            
            # Check contra rechazadas previas
            if any(canonicalize_url(u) == normalized_url for u in rejected_urls):
                continue
                
            # Agregar task_topic para contexto del evaluador
            res['task_topic'] = task_topic
            all_raw_results.append(res)
            
        # Guardar info de variantes para tracing
        query_variants_trace.append({
            'task_topic': task_topic,
            'base_queries_count': len(base_queries),
            'variants_count': len(all_queries_to_execute),
            'results_before_dedupe': len(raw_results),
            'results_after_dedupe': len([r for r in raw_results if r.get('url')])
        })
        
        # Pausa mínima entre tareas
        await asyncio.sleep(0.1)
    
    # Logging final de variantes
    if query_variants_trace and CONTEXT_QUERY_VARIANTS_ENABLED:
        total_base = sum(t['base_queries_count'] for t in query_variants_trace)
        total_variants = sum(t['variants_count'] for t in query_variants_trace)
        logger.log_info(f"   📊 Resumen variantes: {total_base} queries base → {total_variants} variantes ejecutadas")
            
    if not all_raw_results:
        return {
            "found_sources": [], 
            "query_variants_trace": query_variants_trace,
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto
        }
        
    return {
        "found_sources": all_raw_results, 
        "query_variants_trace": query_variants_trace,
        "project_specific_context": state.get('project_specific_context')  # Preservar contexto
    }


async def extractor_node(state: ResearchState) -> ResearchState:
    """Enriquece las fuentes validadas con evidencia (solo cuando pasamos Quality Gate).

    Motivación: evitar gastar extracción en fuentes que luego serán rechazadas.
    """
    validated_sources = state.get('validated_sources', [])
    if not validated_sources:
        return {"validated_sources": []}

    logger.log_phase("EXTRACTOR", f"[{state['topic'][:30]}] Extrayendo evidencias de {len(validated_sources)} fuente(s) validadas...")

    try:
        enriched_sources = await extract_evidence_package(
            topic=state['topic'],
            search_results=validated_sources
        )

        # Si falla o no devuelve nada, continuar con las fuentes originales
        if not enriched_sources:
            logger.log_warning("      ⚠️  No se pudieron extraer evidencias; continuando sin enriquecer")
            return {
                "validated_sources": validated_sources,
                "project_specific_context": state.get('project_specific_context')  # Preservar contexto
            }

        return {
            "validated_sources": enriched_sources,
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto
        }

    except Exception as e:
        logger.log_error(f"Error durante extracción de evidencias: {e}")
        return {
            "validated_sources": validated_sources,
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto
        }


async def evaluator_node(state: ResearchState) -> ResearchState:
    """Evalúa las fuentes encontradas con optimizaciones (cache, fast-track)."""
    raw_sources = state.get('found_sources', [])
    if not raw_sources:
        return {"validated_sources": [], "rejected_sources": []}
        
    logger.log_phase("JUEZ", f"[{state['topic'][:30]}] Evaluando {len(raw_sources)} candidatos con {CURRENT_JUDGE_MODEL}")
    
    validated = []
    rejected = []
    
    # Deduplicar por URL
    seen_urls = set()
    unique_sources_to_evaluate = []
    
    for source in raw_sources:
        url = source.get('url', '').rstrip('/').lower()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_sources_to_evaluate.append(source)
    
    total_to_evaluate = len(unique_sources_to_evaluate)
    print(f"   📊 {total_to_evaluate} fuentes únicas a evaluar")

    # Inicializar tokens_by_role si no existe
    tokens_by_role = state.get('tokens_by_role', {})

    # Contador de progreso thread-safe
    import threading
    eval_progress_lock = threading.Lock()
    eval_progress = {"completed": 0, "validated": 0, "rejected": 0, "cache_hits": 0, "fast_track": 0}

    async def evaluate_with_progress(source, index: int, total: int, context: str):
        """Wrapper para evaluar con logging de progreso."""
        result = await evaluate_source(source, context)

        with eval_progress_lock:
            eval_progress["completed"] += 1

            if result:
                if result.get("keep") is True:
                    eval_progress["validated"] += 1
                else:
                    eval_progress["rejected"] += 1

                if result.get("from_cache"):
                    eval_progress["cache_hits"] += 1
                elif result.get("fast_track"):
                    eval_progress["fast_track"] += 1

            # Log de progreso cada 5 evaluaciones o al final
            completed = eval_progress["completed"]
            if completed % 5 == 0 or completed == total:
                print(f"      📈 Progreso: {completed}/{total} ({eval_progress['validated']}✅ {eval_progress['rejected']}❌ | cache:{eval_progress['cache_hits']} fast:{eval_progress['fast_track']})", flush=True)

        return result

    # Preparar tareas asíncronas con tracking
    tasks = []
    for i, source in enumerate(unique_sources_to_evaluate):
        task_topic = source.get('task_topic', state['topic'])
        tasks.append(evaluate_with_progress(source, i+1, total_to_evaluate, task_topic))

    # Ejecutar en paralelo
    print(f"      🚀 Iniciando evaluación paralela de {total_to_evaluate} fuentes...", flush=True)
    results = await asyncio.gather(*tasks)

    # Procesar resultados y estimar tokens del judge
    judge_tokens_used = 0
    for evaluation in results:
        if evaluation and evaluation.get("keep") is True:
            validated.append(evaluation)
        elif evaluation:
            if evaluation.get("keep") is None:
                evaluation["keep"] = False
            rejected.append(evaluation)

        # Estimar tokens por evaluación (cada evaluación usa ~300-500 tokens)
        if evaluation and not evaluation.get("from_cache") and not evaluation.get("fast_track"):
            judge_tokens_used += 400  # Estimación promedio por evaluación con LLM

    print(f"      ✅ Evaluación completada: {len(validated)} validadas, {len(rejected)} rechazadas", flush=True)
    
    tokens_by_role["judge"] = tokens_by_role.get("judge", 0) + judge_tokens_used
    
    # Estadísticas de evaluación
    stats = get_evaluation_stats(validated, rejected)
    print_evaluation_summary(stats)
    
    # Mostrar resumen visual
    logger.display_evaluation_results(validated, rejected)
            
    return {
        "validated_sources": validated,
        "rejected_sources": rejected,
        "tokens_by_role": tokens_by_role,
        "project_specific_context": state.get('project_specific_context')  # Preservar contexto
    }


async def quality_gate_node(state: ResearchState) -> ResearchState:
    """
    Quality Gate: Evalúa si las fuentes son suficientes y de calidad.
    Decide si continuar al reporter o reintentar búsqueda.
    """
    validated = state.get('validated_sources', [])
    
    # Obtener configuraciones dinámicas según report_type
    report_type = state.get('report_type', state.get('prompt_type', None))
    dynamic_config = get_dynamic_config(report_type)
    max_accepted_sources = dynamic_config.get('max_accepted_sources', MAX_ACCEPTED_SOURCES)
    min_accepted_sources = dynamic_config.get('min_accepted_sources', MIN_ACCEPTED_SOURCES)

    # Cap de fuentes aceptadas para controlar coste/ruido downstream
    if max_accepted_sources and len(validated) > max_accepted_sources:
        def _score(s: Dict) -> float:
            try:
                return float(s.get('total_score', 0) or 0)
            except Exception:
                return 0.0
        validated_sorted = sorted(validated, key=_score, reverse=True)
        validated = validated_sorted[:max_accepted_sources]
        logger.log_info(f"   ℹ️  Recortando fuentes aceptadas a top {max_accepted_sources} por score (de {len(validated_sorted)})")
    loop_count = state.get('loop_count', 0)
    
    logger.log_phase("QUALITY GATE", f"Evaluando calidad de {len(validated)} fuentes...")
    
    # Ejecutar quality gate
    from .config import EVAL_CONSULTING_MAX_RATIO
    gate_result = check_quality_gate(
        validated,
        min_sources=min_accepted_sources,  # Usar configuración dinámica
        min_avg_reliability=6.0,
        require_elite=True,
        max_consulting_ratio=EVAL_CONSULTING_MAX_RATIO,
        max_general_media_ratio=EVAL_GENERAL_MEDIA_MAX_RATIO
    )
    
    # Log resultados
    if gate_result['passed']:
        print(f"   ✅ Quality Gate PASSED")
    else:
        print(f"   ⚠️ Quality Gate issues:")
        for issue in gate_result['issues']:
            print(f"      - {issue}")
    
    # Guardar resultado en estado
    return {
        "validated_sources": validated,
        "quality_gate_passed": gate_result['passed'],
        "quality_gate_issues": gate_result['issues'],
        "quality_gate_recommendation": gate_result['recommendation'],
        "confidence_score": gate_result['confidence'],
        "project_specific_context": state.get('project_specific_context')  # Preservar contexto
    }


def loop_manager_node(state: ResearchState) -> ResearchState:
    """Incrementa el contador de loops y registra queries fallidas."""
    current_loop = state.get("loop_count", 0)
    
    # Registrar queries que no dieron buenos resultados
    failed_queries = state.get('failed_queries', [])
    
    # Extraer queries usadas en esta ronda
    for task in state.get("search_strategy", []):
        failed_queries.extend(task.get("queries", []))
    
    # Limitar historial de queries fallidas
    failed_queries = failed_queries[-20:]  # Mantener solo últimas 20
    
    logger.log_warning(f"📉 Loop {current_loop + 1}/{MAX_RETRIES}: Reintentando con queries diferentes...")
    
    return {
        "loop_count": current_loop + 1,
        "failed_queries": failed_queries
    }


async def firecrawl_node(state: ResearchState) -> ResearchState:
    """
    Enriquece fuentes validadas con contenido extraído por Firecrawl cuando es necesario.
    Solo se ejecuta si Firecrawl está habilitado y hay API key.
    Se ejecuta SOLO sobre validated_sources (post-evaluator, post-quality-gate).
    """
    # Verificar si Firecrawl está habilitado
    if not FIRECRAWL_ENABLED or not FIRECRAWL_API_KEY:
        return {
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto aunque Firecrawl esté deshabilitado
        }  # No hacer nada si está deshabilitado
    
    validated_sources = state.get('validated_sources', [])
    if not validated_sources:
        return {"validated_sources": []}
    
    logger.log_phase("FIRECRAWL", f"[{state['topic'][:30]}] Enriqueciendo {len(validated_sources)} fuente(s) con Firecrawl...")
    
    from .firecrawl_client import fetch_firecrawl_markdown
    from .utils import canonicalize_url
    
    # DEDUPLICACIÓN: Agrupar fuentes por URL canónica para evitar procesar la misma URL múltiples veces
    url_to_sources = {}
    for source in validated_sources:
        url = source.get('url', '')
        if url:
            canonical_url = canonicalize_url(url)
            if canonical_url not in url_to_sources:
                url_to_sources[canonical_url] = []
            url_to_sources[canonical_url].append(source)
        else:
            # Fuentes sin URL van directamente a "suficiente contenido"
            if 'sources_without_url' not in url_to_sources:
                url_to_sources['sources_without_url'] = []
            url_to_sources['sources_without_url'].append(source)
    
    # Separar fuentes que necesitan Firecrawl de las que no (una por URL única)
    sources_needing_firecrawl = []
    sources_with_sufficient_content = []
    
    for canonical_url, source_list in url_to_sources.items():
        if canonical_url == 'sources_without_url':
            # Fuentes sin URL van directamente a suficiente contenido
            sources_with_sufficient_content.extend(source_list)
            continue
        
        # Tomar solo el primer source de cada URL canónica (evitar duplicados)
        source = source_list[0]
        url = source.get('url', '')
        if not url:
            sources_with_sufficient_content.extend(source_list)
            continue
        
        # Determinar si necesitamos Firecrawl
        existing_raw_content = source.get('raw_content', '')
        existing_content_length = len(existing_raw_content) if existing_raw_content else 0
        
        # Obtener report_type del estado para lógica condicional (Capa C)
        report_type = state.get('report_type', None)
        report_types_critical = ["Strategic", "Financial", "Due_Diligence"]
        is_critical_report = report_type in report_types_critical if report_type else False
        
        # Lógica condicional para Firecrawl (Capa C):
        # - Si raw_content < 4000 chars → Firecrawl scrape
        # - Si raw_content >= 4000 chars → Skip Firecrawl (salvo report crítico)
        # - Si es report crítico y raw_content < 8000 chars → Firecrawl (hasta límite razonable)
        should_use_firecrawl = False
        if not existing_raw_content:
            should_use_firecrawl = True
        elif existing_content_length < FIRECRAWL_MIN_EXISTING_CONTENT_CHARS:
            should_use_firecrawl = True
        elif is_critical_report and existing_content_length < 8000:
            # Report crítico: usar Firecrawl incluso si >= 4000 chars (hasta 8000 chars)
            should_use_firecrawl = True
            logger.log_info(f"      🎯 Report crítico detectado ({report_type}): usando Firecrawl para enriquecer contenido ({existing_content_length} chars)")
        
        if not should_use_firecrawl:
            # Contenido suficiente, mantener el original para todas las instancias
            for s in source_list:
                s["extraction_method"] = s.get("extraction_method", "tavily/exa")
            sources_with_sufficient_content.extend(source_list)
            continue
        
        # Necesita Firecrawl - procesar solo una instancia por URL única, luego replicar resultado a las demás
        # Guardar lista de instancias para replicar resultado después
        source["_source_list"] = source_list
        sources_needing_firecrawl.append(source)
    
    firecrawl_skipped_count = len(sources_with_sufficient_content)
    
    # Procesar fuentes que necesitan Firecrawl en paralelo (con semáforo para evitar rate limiting)


    # Obtener configuraciones dinámicas según report_type
    report_type = state.get('report_type', state.get('prompt_type', None))
    dynamic_config = get_dynamic_config(report_type)
    max_firecrawl_calls = dynamic_config.get('max_firecrawl_calls', FIRECRAWL_MAX_CALLS_PER_ITEM)
    
    # Cap how many Firecrawl calls we do per item to control cost/latency
    if max_firecrawl_calls and len(sources_needing_firecrawl) > max_firecrawl_calls:
        def _score(src):
            return (
                src.get("total_score", src.get("score", 0)) or 0,
                src.get("relevance_score", 0) or 0,
                len(src.get("raw_content", src.get("snippet", "")) or ""),
            )

        sources_needing_firecrawl.sort(key=_score, reverse=True)
        sources_needing_firecrawl = sources_needing_firecrawl[:max_firecrawl_calls]

    if sources_needing_firecrawl:
        unique_urls_count = len(sources_needing_firecrawl)
        logger.log_info(f"   🔍 URLs únicas a procesar con Firecrawl: {unique_urls_count} (de {len(validated_sources)} fuentes totales)")
        semaphore = asyncio.Semaphore(3)  # Concurrencia: 3 paralelas

        # Contador de progreso thread-safe
        import threading
        progress_lock = threading.Lock()
        progress_counter = {"completed": 0, "success": 0, "failed": 0}

        async def process_source_with_firecrawl(source, index: int, total: int):
            async with semaphore:
                url = source.get('url', '')
                domain = source.get('source_domain', url.split('/')[2] if '/' in url else url[:30])

                # Log de inicio
                print(f"      🔗 [{index}/{total}] Firecrawl: {domain[:40]}...", flush=True)

                try:
                    markdown_content, firecrawl_meta = await fetch_firecrawl_markdown(
                        url=url,
                        api_key=FIRECRAWL_API_KEY,
                        timeout_seconds=FIRECRAWL_TIMEOUT_SECONDS
                    )

                    # Actualizar progreso
                    with progress_lock:
                        progress_counter["completed"] += 1

                    if markdown_content and markdown_content.strip():
                        # Usar el mínimo entre FIRECRAWL_MAX_CHARS_PER_SOURCE y MAX_CHARS_PER_SOURCE configurado
                        max_chars = min(FIRECRAWL_MAX_CHARS_PER_SOURCE, MAX_CHARS_PER_SOURCE or FIRECRAWL_MAX_CHARS_PER_SOURCE)

                        # Truncar el contenido si es necesario
                        source["raw_content"] = truncate_text(markdown_content, max_chars)
                        source["extraction_method"] = "firecrawl"
                        source["firecrawl_meta"] = firecrawl_meta

                        with progress_lock:
                            progress_counter["success"] += 1
                            print(f"      ✅ [{progress_counter['completed']}/{total}] OK: {domain[:40]} ({len(markdown_content):,} chars)", flush=True)

                        return source, "success"
                    else:
                        # Firecrawl falló pero mantener fuente con método original
                        source["extraction_method"] = source.get("extraction_method", "tavily/exa")
                        source["firecrawl_meta"] = firecrawl_meta

                        with progress_lock:
                            progress_counter["failed"] += 1
                            print(f"      ⚠️ [{progress_counter['completed']}/{total}] Vacío: {domain[:40]}", flush=True)

                        return source, "failed"

                except Exception as e:
                    # Error inesperado, mantener fuente original
                    with progress_lock:
                        progress_counter["completed"] += 1
                        progress_counter["failed"] += 1
                    print(f"      ❌ [{progress_counter['completed']}/{total}] Error: {domain[:40]} - {str(e)[:50]}", flush=True)
                    source["extraction_method"] = source.get("extraction_method", "tavily/exa")
                    source["firecrawl_meta"] = {"status": "error", "error": str(e)}
                    return source, "failed"

        # Ejecutar en paralelo con índices para tracking
        tasks = [process_source_with_firecrawl(source, i+1, unique_urls_count) for i, source in enumerate(sources_needing_firecrawl)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Procesar resultados
        enriched_sources = list(sources_with_sufficient_content)
        firecrawl_success_count = 0
        firecrawl_failed_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                # Error en la tarea, mantener fuente original
                firecrawl_failed_count += 1
                continue
            
            source, status = result
            
            # Si hay múltiples instancias de la misma URL, replicar el resultado
            source_list = source.pop("_source_list", [source])
            
            # Aplicar el resultado de Firecrawl a todas las instancias
            for s in source_list:
                if status == "success":
                    # Replicar contenido enriquecido a todas las instancias
                    s["raw_content"] = source.get("raw_content", s.get("raw_content", ""))
                    s["extraction_method"] = source.get("extraction_method", "firecrawl")
                    s["firecrawl_meta"] = source.get("firecrawl_meta", {})
                else:
                    # Mantener método original para todas
                    s["extraction_method"] = s.get("extraction_method", "tavily/exa")
                    s["firecrawl_meta"] = source.get("firecrawl_meta", {})
                enriched_sources.append(s)
            
            if status == "success":
                firecrawl_success_count += 1
            else:
                firecrawl_failed_count += 1
    else:
        # No hay fuentes que necesiten Firecrawl
        enriched_sources = sources_with_sufficient_content
        firecrawl_success_count = 0
        firecrawl_failed_count = 0
    
    # Logging resumen
    if firecrawl_success_count > 0:
        logger.log_success(f"✅ Firecrawl: {firecrawl_success_count} extracción(es) exitosa(s)")
    if firecrawl_skipped_count > 0:
        logger.log_info(f"   ℹ️  {firecrawl_skipped_count} fuente(s) con contenido suficiente (omitiendo Firecrawl)")
    if firecrawl_failed_count > 0:
        logger.log_warning(f"   ⚠️  {firecrawl_failed_count} extracción(es) fallida(s) (manteniendo contenido original)")
    
    return {
        "validated_sources": enriched_sources,
        "project_specific_context": state.get('project_specific_context')  # Preservar contexto
    }


async def reporter_node(state: ResearchState) -> ResearchState:
    """Genera el reporte final y prepara los datos para guardar."""
    # DEBUG: Verificar contexto antes de generar reporte
    project_specific_context_in_state = state.get('project_specific_context')
    logger.log_info(f"🔍 [REPORTER] Verificando contexto del proyecto...")
    logger.log_info(f"   - project_specific_context en estado: {project_specific_context_in_state}")
    logger.log_info(f"   - Tipo: {type(project_specific_context_in_state).__name__}")
    logger.log_info(f"   - Es None: {project_specific_context_in_state is None}")
    logger.log_info(f"   - Es False: {project_specific_context_in_state is False}")
    
    # Normalizar: si es False (booleano), convertir a None
    if project_specific_context_in_state is False:
        logger.log_warning("   ⚠️  project_specific_context es False (booleano), normalizando a None")
        project_specific_context_in_state = None
    
    if project_specific_context_in_state is not None:
        if isinstance(project_specific_context_in_state, str):
            logger.log_info(f"   - Tipo: str, Longitud: {len(project_specific_context_in_state)}")
            logger.log_info(f"   - Contenido (primeros 100 chars): {project_specific_context_in_state[:100]}")
        else:
            logger.log_warning(f"   - Tipo inesperado: {type(project_specific_context_in_state).__name__}, valor: {project_specific_context_in_state}")
            # Intentar convertir a string si es posible
            if project_specific_context_in_state:
                try:
                    project_specific_context_in_state = str(project_specific_context_in_state)
                    logger.log_info(f"   - Convertido a string: {len(project_specific_context_in_state)} caracteres")
                except:
                    project_specific_context_in_state = None
                    logger.log_warning("   - No se pudo convertir a string, usando None")
    
    validated_sources = state.get('validated_sources', [])
    rejected_sources = state.get('rejected_sources', [])
    
    # 1. Preparar texto de fuentes nuevas
    if validated_sources:
        new_sources_text = "\n\n".join([format_source_for_storage(s) for s in validated_sources])
    else:
        new_sources_text = "No se encontraron fuentes nuevas en esta ronda."
        
    # 2. Agregar rechazadas al historial
    rejected_text = ""
    if rejected_sources:
        rejected_text_list = [
            f"RECHAZADA: {s.get('url', 'N/A')} - {s.get('source_domain', 'N/A')}"
            for s in rejected_sources
        ]
        rejected_text = "\n\n--- FUENTES RECHAZADAS (para evitar re-evaluación) ---\n\n" + "\n\n".join(rejected_text_list)
        
    # 3. Concatenar todo
    existing = state.get('existing_sources_text', '')
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    if existing:
        updated_sources = f"{existing}\n\n--- NUEVA RONDA ({timestamp}) ---\n\n{new_sources_text}"
    else:
        updated_sources = f"--- PRIMERA RONDA ({timestamp}) ---\n\n{new_sources_text}"
        
    if rejected_text:
        updated_sources += f"\n{rejected_text}"
        
    # 4. Generar Reporte
    if not state.get('topic'):
        logger.log_error("No hay tema definido para generar el reporte.")
        return {"error": "No hay tema definido", "status": "Error"}

    logger.log_phase("REPORTER", f"[{state['topic'][:30]}] Generando reporte (Fuentes: {len(validated_sources)})")

    # El prompt viene del estado
    reporter_prompt = state.get('system_prompt')
    prompt_type = state.get('prompt_type', 'General')
    # Capa C y D: report_type se usa para lógica condicional (Firecrawl y Exa)
    # prompt_type es el mismo que report_type
    report_type = prompt_type

    from .config import REPORT_LANGUAGE, REFERENCES_STYLE

    # Añadir badge de confianza al contexto
    confidence = state.get('confidence_score', calculate_confidence_score(validated_sources))
    confidence_badge = format_confidence_badge(confidence)

    # Inicializar tokens_by_role si no existe
    tokens_by_role = state.get('tokens_by_role', {})
    
    # Generar contexto jerárquico automático (padre, hermanos, hijos)
    h_ctx = build_hierarchical_context(state['topic'], state.get('full_index', []))
    if h_ctx:
        print(f"      📐 [REPORTER] Contexto jerárquico inyectado ({len(h_ctx)} chars)")
    else:
        print(f"      📐 [REPORTER] Sin contexto jerárquico (item sin numeración o sin hermanos/hijos)")

    brief = state.get('brief', '')
    if brief:
        print(f"      📋 [REPORTER] Brief inyectado ({len(brief)} chars)")

    report, tokens = await generate_markdown_report(
        topic=state['topic'],
        all_sources=validated_sources,
        report_type=report_type,
        project_name=state.get('project_name'),
        related_topics=state.get('related_topics', []),
        language=REPORT_LANGUAGE,
        reference_style=REFERENCES_STYLE,
        project_specific_context=project_specific_context_in_state if project_specific_context_in_state else None,
        hierarchical_context=h_ctx,
        brief=brief
    )
    
    # Guardar tokens del analyst
    tokens_by_role["analyst"] = tokens
    
    # Insertar badge de confianza al inicio del reporte
    if report and confidence_badge:
        # Insertar después del título
        lines = report.split('\n')
        if lines:
            # Buscar primera línea no vacía después del título
            insert_idx = 1
            for i, line in enumerate(lines):
                if line.startswith('#') and i == 0:
                    insert_idx = i + 1
                    break
            lines.insert(insert_idx, f"\n{confidence_badge}\n")
            report = '\n'.join(lines)
    
    # Preservar project_specific_context en el return
    # Capa C y D: Guardar report_type en estado para Firecrawl y Exa condicionado
    return {
        "final_report": report,
        "updated_sources_text": updated_sources,
        "tokens_used": tokens,
        "tokens_by_role": tokens_by_role,
        "status": "Done",
        "report_type": report_type,  # Capa C y D: Para lógica condicional de Firecrawl y Exa
        "project_specific_context": state.get('project_specific_context')  # Preservar contexto
    }


async def verifier_node(state: ResearchState) -> ResearchState:
    """
    Verifica el reporte generado contra las fuentes para detectar posibles alucinaciones.
    Se puede deshabilitar desde config.toml con verifier_enabled = false
    """
    # Preservar campos importantes del estado anterior
    updated_sources_text = state.get('updated_sources_text', '')
    final_report = state.get('final_report', '')
    
    # Verificar si el verifier está habilitado
    if not VERIFIER_ENABLED:
        logger.log_info("Verifier deshabilitado (verifier_enabled = false en config.toml)")
        return {
            "final_report": final_report,
            "updated_sources_text": updated_sources_text
        }
    
    report = final_report
    validated_sources = state.get('validated_sources', [])
    topic = state.get('topic', '')
    
    if not report:
        logger.log_warning("No hay reporte para verificar")
        return {
            "final_report": final_report,
            "updated_sources_text": updated_sources_text
        }
    
    if not validated_sources:
        logger.log_warning("No hay fuentes para verificar el reporte")
        return {
            "final_report": final_report,
            "updated_sources_text": updated_sources_text
        }
    
    logger.log_phase("VERIFIER", f"[{topic[:30]}] Verificando reporte contra {len(validated_sources)} fuente(s)...")
    
    try:
        # 1. Validar referencias (verificar que todas las fuentes estén en ## References)
        ref_validation = validate_references(report, validated_sources)
        
        if not ref_validation["passed"]:
            logger.log_warning("⚠️ Validación de referencias fallida:")
            for issue in ref_validation["issues"][:3]:  # Mostrar solo los primeros 3
                print(f"      {issue}")
            if len(ref_validation["issues"]) > 3:
                print(f"      ... y {len(ref_validation['issues']) - 3} más")
        else:
            logger.log_success(f"✅ Validación de referencias: {ref_validation['citation_count']} citas, {ref_validation['reference_count']} referencias")
        
        # 2. Verificar contenido contra fuentes (anti-alucinaciones)
        verified_report, issues, verification_confidence, verification_summary = await verify_report(
            report=report,
            sources=validated_sources,
            topic=topic
        )
        
        # Clasificar issues por severidad
        high_severity_issues = [i for i in issues if i.get('severity') == 'high']
        medium_severity_issues = [i for i in issues if i.get('severity') == 'medium']
        low_severity_issues = [i for i in issues if i.get('severity') == 'low']
        
        # Determinar si pasó la verificación
        verification_passed = len(high_severity_issues) == 0
        
        # Capa D: Trackear verifier issues para activar Exa en siguiente iteración
        verification_high_severity_count = len(high_severity_issues)
        
        # Logging de resultados
        if verification_passed:
            if len(issues) == 0:
                logger.log_success("✅ Verificación completada: Sin issues detectados")
            else:
                logger.log_success(f"✅ Verificación completada: {len(issues)} issues menores (no críticos)")
                if medium_severity_issues:
                    print(f"      ⚠️  {len(medium_severity_issues)} issues de severidad MEDIA")
                if low_severity_issues:
                    print(f"      ℹ️  {len(low_severity_issues)} issues de severidad BAJA")
        else:
            logger.log_warning(f"⚠️  Verificación detectó {len(high_severity_issues)} issue(s) CRÍTICO(S)")
            for i, issue in enumerate(high_severity_issues[:3], 1):  # Mostrar solo los primeros 3
                print(f"      {i}. [{issue.get('type', 'unknown').upper()}] {issue.get('text', '')[:80]}...")
            if len(high_severity_issues) > 3:
                print(f"      ... y {len(high_severity_issues) - 3} más")
        
        # Combinar resultados de validación de referencias y verificación de contenido
        all_verification_passed = verification_passed and ref_validation["passed"]
        
        # Generar y guardar informe de verificación separado
        try:
            from .verifier import generate_verification_report, save_verification_report
            
            # Generar informe completo
            verification_report = generate_verification_report(
                issues=issues,
                confidence=verification_confidence,
                summary=verification_summary,
                topic=topic,
                sources_count=len(validated_sources),
                references_validation=ref_validation
            )
            
            # Guardar informe en archivo separado
            record_id = state.get('record_id', None)
            report_path = save_verification_report(
                verification_report=verification_report,
                topic=topic,
                record_id=record_id
            )
            
            if report_path:
                logger.log_info(f"   📋 Informe de verificación guardado en archivo separado: {report_path}")
        except Exception as e:
            logger.log_warning(f"⚠️ Error generando informe de verificación separado: {e}")
            import traceback
            traceback.print_exc()
        
        # Retornar resultados de verificación (preservar updated_sources_text)
        return {
            "final_report": verified_report,  # Reporte original sin anotaciones (la verificación no modifica el informe final)
            "updated_sources_text": updated_sources_text,  # Preservar fuentes acumuladas
            "verification_issues": issues,
            "verification_passed": verification_passed,
            "verification_high_severity_count": verification_high_severity_count,  # Capa D: Para activar Exa condicionado
            "verification_medium_severity_count": len(medium_severity_issues),
            "verification_low_severity_count": len(low_severity_issues),
            "references_validation": ref_validation,  # Resultados de validación de referencias
            "references_validation_passed": ref_validation["passed"],
            "all_verification_passed": all_verification_passed,  # Verificación completa pasó
            "project_specific_context": state.get('project_specific_context'),  # Preservar contexto
            "verification_result": {  # Guardar resultado para el informe
                "confidence": verification_confidence,
                "summary": verification_summary
            }
        }
        
    except Exception as e:
        logger.log_error(f"Error durante verificación: {e}")
        import traceback
        traceback.print_exc()
        # En caso de error, continuar con el reporte original (preservar campos importantes)
        return {
            "final_report": final_report,  # Preservar reporte original
            "updated_sources_text": updated_sources_text,  # Preservar fuentes acumuladas
            "verification_issues": [],
            "verification_passed": True,  # No fallar el pipeline por error en verificación
            "verification_error": str(e)
        }


async def ploter_node(state: ResearchState) -> ResearchState:
    """Evalúa si se pueden generar gráficos y los inserta en el reporte."""
    # Preservar campos importantes del estado anterior
    updated_sources_text = state.get('updated_sources_text', '')
    final_report = state.get('final_report', '')
    
    from .config import ENABLE_PLOTS
    if not ENABLE_PLOTS:
        return {
            "final_report": final_report,
            "updated_sources_text": updated_sources_text,
            "project_specific_context": state.get('project_specific_context')  # Preservar contexto
        }

    from .ploter import evaluate_and_generate_plot, insert_plots_in_markdown
    
    plots = await evaluate_and_generate_plot(final_report, state.get('topic', ''))
    
    if not plots:
        return {
            "final_report": final_report,
            "updated_sources_text": updated_sources_text
        }
        
    # Actualizar reporte con bookmarks
    updated_report = insert_plots_in_markdown(final_report, plots)
    
    return {
        "final_report": updated_report,
        "updated_sources_text": updated_sources_text,  # Preservar fuentes acumuladas
        "plot_data": plots
    }


# ==========================================
# DEFINICIÓN DEL GRAFO
# ==========================================

def create_research_graph():
    """Crea y compila el grafo de investigación."""
    workflow = StateGraph(ResearchState)
    
    # Agregar nodos
    workflow.add_node("planner", planner_node)
    workflow.add_node("searcher", searcher_node)
    workflow.add_node("extractor", extractor_node)
    workflow.add_node("firecrawl", firecrawl_node)
    workflow.add_node("evaluator", evaluator_node)
    workflow.add_node("quality_gate", quality_gate_node)
    workflow.add_node("loop_manager", loop_manager_node)
    workflow.add_node("reporter", reporter_node)
    workflow.add_node("verifier", verifier_node)
    workflow.add_node("ploter", ploter_node)
    
    # Definir flujo
    workflow.set_entry_point("planner")
    
    # Lógica condicional después de planner
    def check_planner_output(state):
        if state.get("error"):
            return END
        return "searcher"

    workflow.add_conditional_edges(
        "planner", 
        check_planner_output,
        {
            "searcher": "searcher",
            END: END
        }
    )
    
    # Lógica condicional después de searcher
    def check_search_results(state):
        if state.get("error"):
            return END
        return "evaluator"
        
    workflow.add_conditional_edges(
        "searcher",
        check_search_results,
        {
            "evaluator": "evaluator",
            END: END
        }
    )
    
    
    # Después de evaluator -> quality gate
    workflow.add_edge("evaluator", "quality_gate")
    
    # Lógica condicional después de quality gate
    def check_quality_gate_result(state):
        """Decide si ir a reporter o reintentar búsqueda."""
        recommendation = state.get("quality_gate_recommendation", "PROCEED")
        loop_count = state.get("loop_count", 0)
        validated = state.get("validated_sources", [])
        
        # Obtener configuraciones dinámicas según report_type
        report_type = state.get('report_type', state.get('prompt_type', None))
        dynamic_config = get_dynamic_config(report_type)
        max_retries = dynamic_config.get('max_retries', MAX_RETRIES)
        
        # LÍMITE DE SEGURIDAD: Si ya hemos hecho muchos loops, forzar salida al reporter
        if loop_count >= max_retries:
            logger.log_warning(f"⚠️  Límite de loops alcanzado ({loop_count} >= {max_retries}). Forzando salida al reporter.")
            return "extractor"
        
        # Si pasó el gate -> reporter
        if recommendation == "PROCEED":
            return "extractor"
        
        # Si hay warnings pero suficientes fuentes -> reporter con warnings
        if recommendation == "PROCEED_WITH_WARNINGS":
            return "extractor"
        
        # Si falló y no hemos excedido retries -> loop manager
        if recommendation == "RETRY_SEARCH" and loop_count < max_retries:
            logger.log_info(f"🔄 Reintentando búsqueda (loop {loop_count + 1}/{max_retries})...")
            return "loop_manager"
        
        # Si excedimos retries o no hay opción -> reporter (con lo que hay)
        logger.log_info(f"✅ Procediendo al reporter (fuentes disponibles: {len(validated)})")
        return "extractor"

    workflow.add_conditional_edges(
        "quality_gate",
        check_quality_gate_result,
        {
            "extractor": "extractor",
            "loop_manager": "loop_manager"
        }
    )

    # Enriquecer fuentes (post quality gate) -> firecrawl (opcional) -> reporter
    workflow.add_edge("extractor", "firecrawl")
    workflow.add_edge("firecrawl", "reporter")

    # Loop manager vuelve a planner
    workflow.add_edge("loop_manager", "planner")
    
    # Reporter -> verifier -> ploter -> END
    workflow.add_edge("reporter", "verifier")
    workflow.add_edge("verifier", "ploter")
    workflow.add_edge("ploter", END)
    
    # Compilar grafo (recursion_limit se pasa en ainvoke/invoke, no en compile)
    # El límite por defecto es 25, pero con MAX_RETRIES=3 y múltiples nodos, puede necesitarse más
    # Calculamos un límite seguro: (MAX_RETRIES * nodos_en_loop) + nodos_fijos + margen
    # Loop: planner -> searcher -> extractor -> evaluator -> quality_gate -> (loop_manager -> planner)
    # Nodos fijos después del loop: reporter -> verifier -> ploter
    # Total máximo teórico: (MAX_RETRIES * 6) + 3 = (3 * 6) + 3 = 21, más margen = 28
    # Nota: recursion_limit se pasa en ainvoke() en manager.py, no aquí
    
    return workflow.compile()
