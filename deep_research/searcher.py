"""deep_research.searcher

Multi-engine search abstraction with practical guardrails:
- Tavily (web research)
- Exa (neural semantic search)

Key goals:
- Iterative search policy (Basic -> Advanced -> Exa)
- Gating for enrichment (Firecrawl)
- Precise metrics and logging per item
- Robust deduplication
"""

import asyncio
import random
import time
import re
from typing import Dict, List, Optional, Set, Any
from urllib.parse import urlparse

import aiohttp

from .config import (
    tavily_client,
    exa_client,
    EXCLUDED_DOMAINS,
    MAX_CHARS_PER_SOURCE,
    EXA_MAX_CHARACTERS,
    MAX_SEARCH_QUERIES,
    TAVILY_ENABLED,
    EXA_ENABLED,
    search_policy, # Instancia de SearchPolicy cargada en config.py
    SMART_SEARCH_ENABLED,
)
from .logger import logger
from .source_quality import get_domain_tier
from .utils import canonicalize_url, truncate_text
from .search_policy import SearchEngine, SearchDepth, Playbook, SearchStep

# ==========================================
# STATE
# ==========================================

_exa_credits_exhausted = False
_tavily_credits_exhausted = False

# ==========================================
# UTILIDADES
# ==========================================

async def validate_url(url: str, session: aiohttp.ClientSession, timeout: int = 10) -> bool:
    """Verifica si un URL es accesible (HEAD) con redirects."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True) as r:
            return r.status == 200
    except asyncio.TimeoutError:
        return False
    except Exception:
        return False

def is_domain_excluded(url: str) -> bool:
    """Verifica si el dominio/URL debe excluirse por baja calidad."""
    if not url:
        return True
    u = url.lower()
    return any(d in u for d in EXCLUDED_DOMAINS)

def extract_domain(url: str) -> str:
    """Extrae dominio sin www."""
    if not url:
        return 'unknown'
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')
    except Exception:
        parts = url.split('/')
        return parts[2] if len(parts) > 2 else 'unknown'

def get_title_with_fallback(result: dict, url: str) -> str:
    """Obtiene el título del resultado, con fallback inteligente si no existe."""
    from urllib.parse import unquote
    
    title = result.get('title', '')
    if title and title.lower().strip() not in ['', 'n/a', 'sin título', 'untitled', 'null', 'none']:
        return title.strip()
    
    if not url:
        return "Fuente web"
    
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if path and path != '/':
            parts = [p for p in path.split('/') if p and len(p) > 2]
            if parts:
                last_part = parts[-1]
                title_from_url = re.sub(r'\.(html|pdf|htm|php|aspx|asp|jsp)$', '', last_part, flags=re.I)
                title_from_url = title_from_url.replace('-', ' ').replace('_', ' ')
                title_from_url = ' '.join(word.capitalize() for word in title_from_url.split())
                if len(title_from_url) > 5:
                    domain = parsed.netloc.replace('www.', '').split('.')[0].capitalize()
                    return f"{title_from_url} ({domain})"
        domain = parsed.netloc.replace('www.', '')
        return f"Documento de {domain}"
    except Exception:
        return "Fuente web"

# ==========================================
# DEDUPLICACIÓN
# ==========================================

def _dedupe_results(results: List[Dict]) -> List[Dict]:
    """Dedupe agresivo por URL canonicalizada."""
    unique: Dict[str, Dict] = {}
    for r in results:
        url = r.get('url') or ''
        if not url: continue
        
        canonical = canonicalize_url(url)
        if canonical not in unique:
            unique[canonical] = r
    
    return list(unique.values())

# ==========================================
# ENGINES
# ==========================================

async def execute_tavily_step(query: str, depth: SearchDepth, max_results: int) -> List[Dict]:
    global _tavily_credits_exhausted
    if not TAVILY_ENABLED or not tavily_client or _tavily_credits_exhausted:
        return []

    try:
        response = await asyncio.to_thread(
            tavily_client.search,
            query=query,
            max_results=max_results,
            search_depth=depth.value,
            include_raw_content=True,
        )
        
        res = []
        if response and 'results' in response:
            for r in response['results']:
                url = r.get('url','')
                if not url or is_domain_excluded(url): continue
                
                res.append({
                    'title': get_title_with_fallback(r, url),
                    'url': url,
                    'snippet': truncate_text(r.get('raw_content') or r.get('content') or '', MAX_CHARS_PER_SOURCE),
                    'raw_content': truncate_text(r.get('raw_content','') or '', MAX_CHARS_PER_SOURCE),
                    'source_domain': extract_domain(url),
                    'search_engine': f'tavily_{depth.value}',
                    'query_used': query
                })
        return res
    except Exception as e:
        logger.log_error(f"Tavily search error for query '{query}': {e}")
        if "credits" in str(e).lower() or "limit" in str(e).lower():
            _tavily_credits_exhausted = True
            logger.log_warning("Tavily credits exhausted.")
        return []

async def execute_exa_step(query: str, max_results: int) -> List[Dict]:
    global _exa_credits_exhausted
    if not EXA_ENABLED or not exa_client or _exa_credits_exhausted:
        return []

    try:
        response = await asyncio.to_thread(
            exa_client.search,
            query=query,
            num_results=max_results,
            type='neural',
            contents={'text': {'max_characters': EXA_MAX_CHARACTERS}}
        )
        
        res = []
        if response and hasattr(response, 'results'):
            for r in response.results:
                url = getattr(r, 'url', '')
                if not url or is_domain_excluded(url): continue
                
                text = getattr(r, 'text', '')
                res.append({
                    'title': get_title_with_fallback({'title': getattr(r, 'title', '')}, url),
                    'url': url,
                    'snippet': truncate_text(text or getattr(r, 'snippet', ''), MAX_CHARS_PER_SOURCE),
                    'raw_content': truncate_text(text, MAX_CHARS_PER_SOURCE),
                    'source_domain': extract_domain(url),
                    'search_engine': 'exa',
                    'query_used': query
                })
        return res
    except Exception as e:
        logger.log_error(f"Exa search error for query '{query}': {e}")
        if "402" in str(e) or "credits" in str(e).lower():
            _exa_credits_exhausted = True
            logger.log_warning("Exa credits exhausted.")
        return []

# ==========================================
# FIRECRAWL GATING
# ==========================================

async def enrich_with_firecrawl(sources: List[Dict], playbook: Playbook) -> List[Dict]:
    """Enriquecimiento inteligente con Firecrawl basado en política."""
    from .firecrawl_client import firecrawl_manager
    
    candidates = search_policy.select_firecrawl_candidates(sources, playbook)
    if not candidates:
        return sources

    logger.log_info(f"🔥 Enriching {len(candidates)} candidates with Firecrawl...")
    
    # Mapeo para actualización rápida
    source_map = {canonicalize_url(s['url']): s for s in sources}
    
    for cand in candidates:
        url = cand['url']
        try:
            # firecrawl_manager ya maneja el cache internamente si está configurado
            md = await firecrawl_manager.scrape_url(url)
            if md:
                canon = canonicalize_url(url)
                if canon in source_map:
                    source_map[canon]['raw_content'] = truncate_text(md, MAX_CHARS_PER_SOURCE)
                    source_map[canon]['snippet'] = truncate_text(md, 2000) # Snippet corto para el analyst
                    source_map[canon]['enriched_by'] = 'firecrawl'
        except Exception as e:
            logger.log_warning(f"Firecrawl failed for {url}: {e}")
            
    return list(source_map.values())

# ==========================================
# MAIN API
# ==========================================

async def execute_search_multi_layer(
    queries: List[str],
    topic: str = '',
    report_type: str = 'General',
    # Los siguientes parámetros se mantienen para compatibilidad pero se ignoran 
    # en favor de la SearchPolicy interna
    max_results: int = 5,
    expand_queries: bool = True,
    validate_urls: bool = True,
    smart_search: Optional[bool] = None,
) -> List[Dict]:
    """
    API Principal implementando la Política Determinista.
    """
    start_time = time.time()
    playbook = search_policy.get_playbook(report_type, topic)
    logger.log_info(f"🚀 Using Playbook: {playbook.name} for topic: {topic[:50]}...")

    all_raw_results = []
    accepted_sources = []
    
    metrics = {
        "queries": queries,
        "steps_executed": 0,
        "tavily_calls": 0,
        "exa_calls": 0,
        "firecrawl_calls": 0,
        "initial_raw_results": 0,
        "final_accepted_sources": 0,
        "latency_sec": 0
    }

    # Bucle por pasos definidos en el playbook
    for i, step in enumerate(playbook.steps):
        metrics["steps_executed"] += 1
        logger.log_info(f"📡 Step {i+1}: {step.engine.value} ({step.depth.value})")
        
        step_results = []
        # Ejecutar queries del step (limitar si el playbook indica menos que el planner)
        step_queries = queries[:step.max_queries]
        logger.log_info(f"🔍 Queries for step {i+1}: {step_queries}")
        
        tasks = []
        for q in step_queries:
            if step.engine == SearchEngine.TAVILY:
                tasks.append(execute_tavily_step(q, step.depth, step.results_per_query))
                metrics["tavily_calls"] += 1
            elif step.engine == SearchEngine.EXA:
                tasks.append(execute_exa_step(q, step.results_per_query))
                metrics["exa_calls"] += 1
        
        new_batch_results = await asyncio.gather(*tasks)
        for batch in new_batch_results:
            step_results.extend(batch)
            
        all_raw_results.extend(step_results)
        
        # Deduplicar y evaluar (Simulación: aquí el Evaluador real se llamará después, 
        # pero para la lógica de escalado necesitamos saber cuántos pasan el filtro)
        # NOTA: En la arquitectura LangGraph, el Searcher no evalúa, pero 
        # para esta política determinista self-contained, necesitamos un feedback loop.
        
        current_deduped = _dedupe_results(all_raw_results)
        # Importante: Aquí el searcher solo busca y de-duplica. 
        # El "escalado" real ocurrirá si esta función es llamada en bucle 
        # o si el searcher decide internamente hacer los retries.
        # Dada la petición "implementa ahora en searcher.py", lo hacemos interno.
        
        # --- Simulación de Evaluación (Evaluator) ---
        # Solo para decidir si escalamos en el mismo call
        # En producción, esto debería integrarse bien con el EvaluatorNode
        from .evaluator import evaluate_source_fast
        
        validated = []
        for src in current_deduped:
            if evaluate_source_fast(src): # Heurística rápida de calidad
                validated.append(src)
        
        accepted_sources = validated
        metrics["initial_raw_results"] = len(current_deduped)
        
        if not search_policy.should_escalate(len(accepted_sources), i, playbook):
            break

    # Exa Booster si es necesario y no estaba en el playbook
    if search_policy.should_call_exa_booster(len(accepted_sources), playbook) and playbook.name != "DEEP_TECH":
        logger.log_info("🚀 Triggering EXA Booster...")
        metrics["steps_executed"] += 1
        exa_res = await execute_exa_step(queries[0], 15)
        metrics["exa_calls"] += 1
        all_raw_results.extend(exa_res)
        
        # Re-evaluar
        current_deduped = _dedupe_results(all_raw_results)
        from .evaluator import evaluate_source_fast
        accepted_sources = [s for s in current_deduped if evaluate_source_fast(s)]

    # Enriquecimiento Firecrawl final para las validadas
    if accepted_sources:
        # Firecrawl solo sobre las que pasaron la evaluación "fast"
        # El pipeline real llamará a Firecrawl después del EvaluatorNode oficial, 
        # pero aquí dejamos la lógica preparada.
        await enrich_with_firecrawl(accepted_sources, playbook)
        metrics["firecrawl_calls"] = len([s for s in accepted_sources if s.get('enriched_by') == 'firecrawl'])

    metrics["final_accepted_sources"] = len(accepted_sources)
    metrics["latency_sec"] = round(time.time() - start_time, 2)
    
    logger.log_info(f"📊 Search Metrics: {metrics}")
    
    # Retornamos todos los deduped para que el EvaluatorNode oficial haga su trabajo
    # pero marcamos las enriquecidas.
    return _dedupe_results(all_raw_results)
# ==========================================
# COMPATIBILITY WRAPPERS
# ==========================================

async def execute_search_smart(
    queries: List[str],
    max_results: int = 5,
    topic: str = '',
    loop_count: int = 0,
    validated_sources_count: int = 0,
    report_type: str = 'General',
    verifier_high_issues_count: int = 0,
) -> List[Dict]:
    """
    Wrapper compatible para execute_search_multi_layer.
    """
    return await execute_search_multi_layer(
        queries=queries,
        topic=topic,
        report_type=report_type,
        max_results=max_results,
        smart_search=True
    )
