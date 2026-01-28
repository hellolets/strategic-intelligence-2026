"""
Módulo Evaluator: Evalúa la calidad de las fuentes con optimizaciones.
- Cache de evaluaciones para evitar re-procesar URLs
- Fast-track para dominios de élite (sin LLM)
- Batch evaluation opcional para reducir llamadas
"""
import json
import asyncio
import re
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from .config import (
    llm_judge, llm_judge_cheap, llm_judge_premium, llm_planner, llm_mimo_cheap, 
    TOTAL_SCORE_THRESHOLD, RELEVANCE_THRESHOLD, 
    AUTHENTICITY_THRESHOLD, RELIABILITY_THRESHOLD, USE_CHEAP_OPENROUTER_MODELS,
    EVAL_ELITE_FAST_TRACK_ENABLED, EVAL_GRAY_ZONE_ENABLED,
    EVAL_GRAY_ZONE_LOW_REJECT, EVAL_GRAY_ZONE_HIGH_ACCEPT,
    EVAL_CONSULTING_MIN_RELEVANCE, EVAL_INSTITUTIONAL_MIN_RELEVANCE,
    EVAL_GENERAL_MEDIA_MIN_RELEVANCE, EVAL_GENERAL_MEDIA_MAX_RATIO,
    JUDGE_ESCALATE_SCORE_LOW, JUDGE_ESCALATE_SCORE_HIGH
)
from .source_quality import (
    get_elite_domain_scores,
    get_cached_evaluation,
    cache_evaluation,
    calculate_confidence_score,
    format_confidence_badge
)

# ==========================================
# MÉTRICAS DE TRACKING: MiMo vs Gemini
# ==========================================
# Contadores globales para tracking de evaluaciones
_mimo_judge_metrics = {
    'mimo_accepted': 0,  # Fuentes aceptadas por MiMo
    'mimo_accepted_then_judge_rejected': 0,  # MiMo aceptó pero Gemini rechazó
    'mimo_accepted_then_judge_accepted': 0,  # MiMo aceptó y Gemini también aceptó
    'mimo_rejected': 0,  # Fuentes rechazadas por MiMo (no van a Judge)
    'judge_only_evaluations': 0,  # Fuentes que van directo a Judge (sin MiMo)
}

def get_mimo_judge_metrics() -> Dict[str, int]:
    """Retorna las métricas actuales de MiMo vs Gemini."""
    return _mimo_judge_metrics.copy()

def reset_mimo_judge_metrics():
    """Resetea las métricas (útil para testing)."""
    global _mimo_judge_metrics
    _mimo_judge_metrics = {
        'mimo_accepted': 0,
        'mimo_accepted_then_judge_rejected': 0,
        'mimo_accepted_then_judge_accepted': 0,
        'mimo_rejected': 0,
        'judge_only_evaluations': 0,
    }

def print_mimo_judge_metrics():
    """Imprime un resumen de las métricas MiMo vs Gemini."""
    metrics = _mimo_judge_metrics
    total_mimo_evaluated = metrics['mimo_accepted'] + metrics['mimo_rejected']
    total_judge_evaluated = metrics['mimo_accepted_then_judge_rejected'] + metrics['mimo_accepted_then_judge_accepted'] + metrics['judge_only_evaluations']
    
    print("\n" + "=" * 80)
    print("📊 MÉTRICAS: MiMo vs Gemini Judge")
    print("=" * 80)
    
    if total_mimo_evaluated > 0:
        print(f"\n🔍 EVALUACIONES CON MIMO:")
        print(f"   Total evaluadas por MiMo: {total_mimo_evaluated}")
        print(f"   ✓ Aceptadas por MiMo: {metrics['mimo_accepted']} ({metrics['mimo_accepted']/total_mimo_evaluated*100:.1f}%)")
        print(f"   ✗ Rechazadas por MiMo: {metrics['mimo_rejected']} ({metrics['mimo_rejected']/total_mimo_evaluated*100:.1f}%)")
    
    if metrics['mimo_accepted'] > 0:
        print(f"\n🎯 FUENTES ACEPTADAS POR MIMO QUE FUERON A GEMINI:")
        print(f"   Total que escalaron a Gemini: {metrics['mimo_accepted_then_judge_rejected'] + metrics['mimo_accepted_then_judge_accepted']}")
        print(f"   ✓ Aceptadas también por Gemini: {metrics['mimo_accepted_then_judge_accepted']}")
        print(f"   ✗ Rechazadas por Gemini: {metrics['mimo_accepted_then_judge_rejected']}")
        
        if metrics['mimo_accepted_then_judge_rejected'] + metrics['mimo_accepted_then_judge_accepted'] > 0:
            rejection_rate = (metrics['mimo_accepted_then_judge_rejected'] / 
                            (metrics['mimo_accepted_then_judge_rejected'] + metrics['mimo_accepted_then_judge_accepted'])) * 100
            print(f"\n   📉 TASA DE RECHAZO DE GEMINI:")
            print(f"      {rejection_rate:.1f}% de las fuentes aceptadas por MiMo fueron rechazadas por Gemini")
    
    if total_judge_evaluated > 0:
        print(f"\n⚖️  EVALUACIONES CON GEMINI (JUDGE):")
        print(f"   Total evaluadas por Gemini: {total_judge_evaluated}")
        print(f"   (Incluye escalamientos desde MiMo + evaluaciones directas)")
    
    print("=" * 80 + "\n")


# ==========================================
# POLICY 2: CHEAP DETERMINISTIC SCORING HELPERS
# ==========================================

def classify_source_category(url: str, domain: str = "") -> str:
    """
    Clasifica la fuente en una categoría determinística.
    
    Returns:
        'consulting' | 'institutional' | 'academic' | 'general_media' | 'other'
    """
    url_lower = url.lower()
    domain_lower = (domain or url_lower).lower()
    
    # Consulting firms
    consulting_keywords = [
        'mckinsey', 'bcg', 'bain', 'oliverwyman', 'accenture', 
        'deloitte', 'pwc', 'kpmg', 'ey', 'ernst', 'arthur', 'andersen',
        'strategy', 'roland', 'berger', 'atkearney', 'booz', 'capgemini'
    ]
    if any(kw in url_lower or kw in domain_lower for kw in consulting_keywords):
        return 'consulting'
    
    # Institutional (.gov, .eu, international orgs)
    institutional_keywords = [
        '.gov', '.gob.es', 'europa.eu', 'ec.europa.eu', 'oecd', 
        'un.org', 'worldbank', 'imf.org', 'iea.org', 'wto.org',
        'ecb.europa.eu', 'eba.europa.eu', 'echa.europa.eu', 'eur-lex',
        'boe.es', 'miteco.gob.es', 'epa.gov', 'fda.gov', 'sec.gov'
    ]
    if any(kw in url_lower or kw in domain_lower for kw in institutional_keywords):
        return 'institutional'
    
    # Academic (.edu, journals, publishers)
    academic_keywords = [
        '.edu', '.ac.uk', 'arxiv', 'nature.com', 'science.org',
        'ieee.org', 'springer.com', 'elsevier.com', 'wiley.com',
        'acm.org', 'jstor.org', 'scholar.google', 'pubmed', 'doi.org'
    ]
    if any(kw in url_lower or kw in domain_lower for kw in academic_keywords):
        return 'academic'
    
    # General media / Confidenciales (medios generalistas y confidenciales)
    # Estos deben tener umbrales más estrictos y priorizarse menos que fuentes primarias
    general_media_keywords = [
        'confidencial', 'confidencialdigital', 'elconfidencial', 'elconfidencialdigital',
        'elmundo', 'elpais', 'abc.es', 'lavanguardia', 'elmundo.es',
        'expansion', 'cinco dias', 'publico', 'elperiodico',
        # Medios digitales generalistas españoles
        'okdiario', 'elespanol', 'libertaddigital', 'vozpopuli',
        'news', 'times', 'post', 'guardian', 'bbc',  # Medios generalistas internacionales
        'cnn', 'msnbc', 'foxnews', 'telegraph', 'independent',
        # Excluir medios financieros premium (se detectan por otros keywords antes)
    ]
    # Solo clasificar como general_media si NO es una fuente primaria (ya clasificada arriba)
    # y coincide con patrones de medios generalistas/confidenciales
    if any(kw in url_lower or kw in domain_lower for kw in general_media_keywords):
        return 'general_media'
    
    return 'other'


def is_methodological_source(url: str, domain: str = "") -> bool:
    """
    Identifica fuentes con metodología robusta (organismos internacionales, think tanks tier-1, 
    agencias gubernamentales con datos oficiales, etc.).
    Estas fuentes deben priorizarse sobre consultoras cuando sea posible.
    Aplicable a TODOS los sectores (defensa, energía, tecnología, salud, infraestructura, etc.).
    
    Returns:
        True si es una fuente metodológica reconocida
    """
    url_lower = url.lower()
    domain_lower = (domain or url_lower).lower()
    
    methodological_keywords = [
        # Organismos internacionales y agencias gubernamentales (datos oficiales)
        'eurostat', 'ec.europa.eu/eurostat',  # Eurostat (estadísticas oficiales EU)
        'worldbank.org', 'world bank',  # World Bank
        'imf.org', 'international monetary fund',  # IMF
        'oecd.org', 'oecd',  # OECD
        'un.org', 'united nations',  # UN
        'wto.org', 'world trade organization',  # WTO
        'iea.org', 'international energy agency',  # IEA (energía)
        'who.int', 'world health organization',  # WHO (salud)
        'itu.int', 'international telecommunication union',  # ITU (tecnología)
        'icao.int', 'international civil aviation organization',  # ICAO (transporte)
        
        # Agencias gubernamentales (datos oficiales)
        'defense.gov', 'dod.gov', 'pentagon',  # US DoD (defensa)
        'eda.europa.eu', 'eda',  # European Defence Agency (defensa)
        'nato.int', 'nato',  # NATO (defensa)
        'epa.gov', 'environmental protection agency',  # EPA (medio ambiente)
        'fda.gov', 'food and drug administration',  # FDA (salud)
        'sec.gov', 'securities and exchange commission',  # SEC (finanzas)
        'ftc.gov', 'federal trade commission',  # FTC (competencia)
        'eia.gov', 'energy information administration',  # EIA (energía)
        'bls.gov', 'bureau of labor statistics',  # BLS (laboral)
        'census.gov', 'us census bureau',  # Census (demografía)
        
        # Think tanks tier-1 (metodología robusta, múltiples sectores)
        'rand.org', 'rand',  # RAND Corporation (defensa, tecnología, salud, etc.)
        'brookings.edu', 'brookings',  # Brookings Institution (política, economía)
        'csis.org', 'csis',  # Center for Strategic and International Studies (geopolítica)
        'chathamhouse.org', 'chatham house',  # Chatham House (internacional)
        'cfr.org', 'council on foreign relations',  # CFR (relaciones internacionales)
        'sipri.org', 'sipri',  # Stockholm International Peace Research Institute (defensa)
        'iiss.org', 'iiss',  # International Institute for Strategic Studies (defensa)
        'petersoninstitute.org', 'peterson institute',  # PIIE (economía)
        'carnegieendowment.org', 'carnegie',  # Carnegie Endowment (internacional)
        
        # Instituciones de investigación con metodología robusta
        'nber.org', 'national bureau of economic research',  # NBER (economía)
        'cepr.org', 'centre for economic policy research',  # CEPR (economía)
        'bruegel.org', 'bruegel',  # Bruegel (economía EU)
        'ecb.europa.eu', 'european central bank',  # ECB (finanzas)
        'bis.org', 'bank for international settlements',  # BIS (finanzas)
    ]
    
    return any(kw in url_lower or kw in domain_lower for kw in methodological_keywords)


def get_consulting_priority(url: str, domain: str = "") -> int:
    """
    Asigna prioridad a consultoras según su especialización.
    Aplicable a TODOS los sectores (defensa, energía, tecnología, salud, infraestructura, etc.).
    
    Returns:
        2: Alta prioridad (Big 4 para industria/operaciones/supply chain; MBB para estrategia/transformación)
        1: Prioridad media (otras consultoras reconocidas)
        0: Baja prioridad (consultoras no reconocidas o genéricas)
    """
    url_lower = url.lower()
    domain_lower = (domain or url_lower).lower()
    
    # Alta prioridad: consultoras especializadas reconocidas
    # Big 4: Deloitte, PwC, KPMG, EY - para industria, operaciones, supply chain, transformación digital
    # MBB: McKinsey, BCG, Bain - para estrategia, implementación, transformación organizacional
    high_priority = [
        'deloitte', 'pwc', 'kpmg', 'ey', 'ernst',  # Big 4 (industria, operaciones, supply chain)
        'mckinsey', 'bcg', 'bain',  # MBB (estrategia, implementación)
    ]
    
    if any(kw in url_lower or kw in domain_lower for kw in high_priority):
        return 2
    
    # Prioridad media: otras consultoras reconocidas
    medium_priority = [
        'accenture', 'oliverwyman', 'roland', 'berger', 'atkearney', 'booz', 'capgemini'
    ]
    
    if any(kw in url_lower or kw in domain_lower for kw in medium_priority):
        return 1
    
    return 0


def quick_relevance_score(context: str, title: str, snippet: str) -> float:
    """
    Calcula un score de relevancia rápido usando Jaccard overlap ponderado.
    
    Returns:
        float 0-10
    """
    if not context or (not title and not snippet):
        return 5.0
    
    # Simple stopwords (minimal set)
    stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can'}
    
    def tokenize(text: str) -> set:
        """Tokeniza y limpia texto."""
        if not text:
            return set()
        # Convertir a minúsculas, tokenizar, filtrar stopwords y tokens muy cortos
        tokens = re.findall(r'\b\w{3,}\b', text.lower())
        return {t for t in tokens if t not in stopwords}
    
    context_tokens = tokenize(context)
    content_tokens = tokenize(f"{title} {snippet}")
    
    if not context_tokens or not content_tokens:
        return 5.0
    
    # Jaccard similarity
    intersection = len(context_tokens & content_tokens)
    union = len(context_tokens | content_tokens)
    
    if union == 0:
        return 5.0
    
    jaccard = intersection / union
    
    # Escalar a 0-10 (mejor ajuste para relevancia)
    # Jaccard típico: 0.1-0.3 para relevante, 0.4+ muy relevante
    score = min(10.0, max(0.0, jaccard * 25))  # Escalar ~0.4 -> 10
    
    return round(score, 1)


def estimate_currency_score(title: str, snippet: str) -> float:
    """
    Estima currency score basándose en años detectados en título/snippet.
    
    Returns:
        float 0-10 (más reciente = más alto)
    """
    text = f"{title} {snippet}".lower()
    
    # Buscar años 2000-2035
    years = re.findall(r'\b(20[0-3][0-9])\b', text)
    
    if not years:
        return 5.0  # Default si no hay año
    
    try:
        max_year = max(int(y) for y in years)
        current_year = datetime.now().year
        
        # Score: más reciente = más alto
        age = current_year - max_year
        if age <= 1:
            return 10.0
        elif age <= 2:
            return 9.0
        elif age <= 3:
            return 8.0
        elif age <= 5:
            return 7.0
        elif age <= 10:
            return 6.0
        else:
            return max(3.0, 10.0 - (age - 10) * 0.3)
    except (ValueError, TypeError):
        return 5.0

def evaluate_source_fast(source: Dict, context: str = "") -> bool:
    """
    Evaluación ultra-rápida y determinista sin LLM.
    Usada por el Searcher para decidir escalado y Firecrawl.
    """
    url = source.get('url', '')
    if not url: return False
    
    # 1. Check elite auto-reject
    elite_info = get_elite_domain_scores(url)
    if elite_info and elite_info.get('auto_reject'):
        return False
        
    # 2. Heurística básica de calidad
    title = source.get('title', '')
    snippet = source.get('snippet', '')
    domain = source.get('source_domain', '')
    
    # Categoría y pre-scores
    category = classify_source_category(url, domain)
    relevance = quick_relevance_score(context or "general research", title, snippet)
    
    # Umbral de éxito rápido (Policy 2):
    # Si es institucional/metodológica/académica + relevancia mínima, aceptamos
    if category in ['institutional', 'academic'] or is_methodological_source(url, domain):
        return relevance >= 4.0
        
    # Si es consultora Tier 1 y relevancia media, aceptamos
    if category == 'consulting':
        from .config import EVAL_CONSULTING_MIN_RELEVANCE
        return relevance >= EVAL_CONSULTING_MIN_RELEVANCE
        
    # Por defecto para 'other', requerimos más relevancia
    return relevance >= 5.0

# ==========================================
# EVALUACIÓN INDIVIDUAL (con optimizaciones)
# ==========================================

async def evaluate_source(source: Dict, context: str) -> Optional[Dict]:
    """
    Evalúa la calidad y relevancia de una fuente usando método multidimensional.
    
    OPTIMIZACIONES:
    1. Cache hit: Retorna evaluación previa si existe
    2. Fast-track élite: Dominios de élite saltan LLM
    3. Auto-reject: Dominios en blacklist se rechazan sin LLM
    
    Args:
        source: Dict con info de la fuente (title, url, snippet, source_domain)
        context: Contexto/tema para evaluar relevancia
    
    Returns:
        Dict con scores multidimensionales, keep y reasoning, o None si error
    """
    if not source.get("url"):
        return None

    url = source.get('url', '')
    domain = source.get('source_domain', '')
    
    # ==========================================
    # PASO 1: CHECK CACHE
    # ==========================================
    cached = get_cached_evaluation(url)
    if cached:
        print(f"   💾 Cache hit: {domain[:30]}")
        # Merge cached evaluation con source data
        result = {**source, **cached}
        result["score"] = cached.get("total_score", 0)
        result["reason"] = cached.get("reasoning", "")
        result["from_cache"] = True
        return result
    
    # ==========================================
    # PASO 2: CHECK DOMINIO ÉLITE / AUTO-REJECT
    # ==========================================
    elite_info = get_elite_domain_scores(url)
    
    if elite_info:
        # Auto-reject
        if elite_info.get('auto_reject'):
            print(f"   🚫 Auto-reject: {elite_info.get('domain', domain)}")
            result = {
                **source,
                "authenticity_score": 0,
                "reliability_score": 0,
                "relevance_score": 0,
                "currency_score": 0,
                "total_score": 0,
                "is_clickbait": False,
                "keep": False,
                "reasoning": elite_info.get('reason', 'Dominio en lista de rechazo automático'),
                "score": 0,
                "reason": elite_info.get('reason', 'Auto-rejected'),
                "fast_track": "auto_reject"
            }
            cache_evaluation(url, result)
            return result
        
        # POLICY 2: Elite pre-score (no auto-keep)
        if EVAL_ELITE_FAST_TRACK_ENABLED:
            print(f"   ⚡ Pre-score élite: {elite_info.get('domain', domain)} (Tier {elite_info.get('tier', '?')})")
            
            # Compute deterministic pre-scores
            title = source.get('title', '')
            snippet = source.get('snippet', '')
            category = classify_source_category(url, domain)
            relevance = quick_relevance_score(context, title, snippet)
            currency = estimate_currency_score(title, snippet)
            authenticity = float(elite_info.get('authenticity', 9))
            reliability = float(elite_info.get('reliability', 8))
            
            # Calculate total_score
            total_score = (authenticity + reliability + relevance + currency) / 4.0
            
            # Apply category adjustments with prioritization
            # PRIORIZACIÓN: Fuentes metodológicas tienen máxima prioridad (aplicable a TODOS los sectores)
            if is_methodological_source(url, domain):
                total_score += 1.0  # Bonus significativo para fuentes metodológicas (organismos internacionales, think tanks tier-1, agencias gubernamentales - multisector)
            elif category == 'consulting':
                # Priorizar consultoras específicas (Deloitte/PwC/KPMG para industria; McKinsey/BCG/Bain para estrategia)
                consulting_priority = get_consulting_priority(url, domain)
                if consulting_priority == 2:  # Alta prioridad
                    if relevance >= EVAL_CONSULTING_MIN_RELEVANCE:
                        total_score += 0.3  # Bonus para consultoras prioritarias con buena relevancia
                    else:
                        total_score -= 0.75  # Penalización si relevancia baja
                elif consulting_priority == 1:  # Prioridad media
                    if relevance < EVAL_CONSULTING_MIN_RELEVANCE:
                        total_score -= 0.75
                else:  # Baja prioridad o no reconocida
                    if relevance < EVAL_CONSULTING_MIN_RELEVANCE:
                        total_score -= 1.0  # Penalización mayor para consultoras no prioritarias
                    else:
                        total_score -= 0.25  # Pequeña penalización incluso si relevancia es buena
            elif category == 'institutional':
                total_score += 0.5  # Bonus para institucionales (fuentes primarias)
            elif category == 'academic':
                total_score += 0.5  # Bonus para académicas (fuentes primarias)
            elif category == 'general_media':
                # Penalizar medios generalistas/confidenciales (priorizar fuentes primarias)
                total_score -= 0.5  # Penalización para priorizar fuentes primarias
                if relevance < EVAL_GENERAL_MEDIA_MIN_RELEVANCE:
                    total_score -= 0.75  # Penalización adicional si relevancia baja
            
            total_score = round(max(0.0, min(10.0, total_score)), 1)
            
            # Gray zone decision
            needs_llm_review = False
            if EVAL_GRAY_ZONE_ENABLED:
                if total_score <= EVAL_GRAY_ZONE_LOW_REJECT:
                    keep_value = False
                    reasoning_pre = f"Pre-score rechazado (total={total_score:.1f} <= {EVAL_GRAY_ZONE_LOW_REJECT})"
                elif total_score >= EVAL_GRAY_ZONE_HIGH_ACCEPT:
                    # Fast accept, but apply hard rules
                    keep_value = True
                    reasoning_pre = f"Pre-score aceptado (total={total_score:.1f} >= {EVAL_GRAY_ZONE_HIGH_ACCEPT})"
                else:
                    # Gray zone: needs LLM review
                    needs_llm_review = True
                    keep_value = None  # Undecided, LLM will decide
                    reasoning_pre = f"Gray zone (total={total_score:.1f}), requiere LLM"
            else:
                # No gray zone: use standard thresholds
                keep_value = (total_score >= TOTAL_SCORE_THRESHOLD and relevance >= RELEVANCE_THRESHOLD)
                reasoning_pre = f"Pre-score evaluado (total={total_score:.1f}, relevance={relevance:.1f})"
            
            # Apply hard rules (even for fast accept)
            if keep_value is not False:  # If not already rejected
                if category == 'consulting' and relevance < EVAL_CONSULTING_MIN_RELEVANCE:
                    keep_value = False
                    reasoning_pre += f" | Regla hard: consulting requiere relevance>={EVAL_CONSULTING_MIN_RELEVANCE}"
                elif category == 'general_media' and relevance < EVAL_GENERAL_MEDIA_MIN_RELEVANCE:
                    keep_value = False
                    reasoning_pre += f" | Regla hard: medios generalistas/confidenciales requieren relevance>={EVAL_GENERAL_MEDIA_MIN_RELEVANCE} | Priorizar fuentes primarias"
                elif category == 'institutional' and relevance >= EVAL_INSTITUTIONAL_MIN_RELEVANCE:
                    # Institutional may pass with lower relevance if other scores are strong
                    if total_score >= TOTAL_SCORE_THRESHOLD - 0.5:
                        keep_value = True
                        reasoning_pre += " | Regla hard: institutional con scores fuertes"
            
            # If not in gray zone or LLM unavailable, return pre-score result
            if not needs_llm_review:
                result = {
                    **source,
                    "authenticity_score": authenticity,
                    "reliability_score": reliability,
                    "relevance_score": relevance,
                    "currency_score": currency,
                    "total_score": total_score,
                    "is_clickbait": False,
                    "keep": keep_value,
                    "reasoning": f"Policy 2 pre-score [{category}]: {reasoning_pre}",
                    "score": total_score,
                    "reason": f"Elite pre-score: {elite_info.get('domain', domain)}",
                    "fast_track": "elite_prescore",
                    "source_category": category
                }
                cache_evaluation(url, result)
                return result
            # Else: continue to LLM evaluation (fall through to MiMo/Judge flow below)
    
    # ==========================================
    # PASO 3: PRE-FILTRO HARD (Fuentes internas de la empresa)
    # ==========================================
    url_lower = url.lower()
    domain_lower = domain.lower()
    title_lower = source.get('title', '').lower()
    
    # NOTA: El filtrado de fuentes internas ahora se hace basándose en el contexto de Airtable
    # No se usa COMPANY_CONTEXT del JSON, se usa project_specific_context de Airtable
    # Por ahora, no filtramos por nombre de empresa (el contexto de Airtable puede contener esta información)
    # Si necesitas filtrar fuentes internas, añade esa lógica basándose en project_specific_context
    company_name = ""  # Ya no se usa COMPANY_CONTEXT del JSON
    
    # Filtrar fuentes internas si el nombre de la empresa está disponible
    # (Esta lógica se puede mejorar para usar el contexto de Airtable)
    if company_name and (company_name in url_lower or company_name in domain_lower or company_name in title_lower):
        print(f"   🚫 Pre-filtro interno: {domain}")
        result = {
            **source,
            "authenticity_score": 10,
            "reliability_score": 10,
            "relevance_score": 0,
            "currency_score": 0,
            "total_score": 4,
            "is_clickbait": False,
            "keep": False,
            "reasoning": f"Rechazada: Fuente interna de la empresa (contexto proporcionado internamente).",
            "score": 4,
            "reason": "Internal source filtered",
            "fast_track": "internal_filter"
        }
        cache_evaluation(url, result)
        return result
    
    # ==========================================
    # PASO 4: EVALUACIÓN PRELIMINAR CON MIMO (Pre-juez barato)
    # ==========================================
    
    # Primera evaluación rápida con MiMo-V2-Flash
    mimo_system_msg = f"""Eres un Pre-Analista de Calidad. Evalúa rápidamente la fuente y determina si necesita evaluación detallada.

EVALUACIÓN RÁPIDA (Cada criterio: 0-10):
- authenticity_score: ¿Es fuente verificable?
- reliability_score: ¿Es institución/autor reconocido?
- relevance_score: ¿Responde al tema?
- currency_score: ¿Información actual?

OUTPUT JSON OBLIGATORIO:
{{
  "authenticity_score": <int 0-10>,
  "reliability_score": <int 0-10>,
  "relevance_score": <int 0-10>,
  "currency_score": <int 0-10>,
  "total_score": <int 0-10>,
  "is_clickbait": <bool>,
  "confidence": "HIGH|PARTIAL|UNCERTAIN",
  "needs_detailed_review": <bool>,
  "reasoning": "<explicación breve>"
}}

REGLA: needs_detailed_review = true si:
- confidence = "PARTIAL" o "UNCERTAIN"
- total_score está entre 5-7 (zona gris)
- reliability_score >= 8 pero relevance_score < 6 (contradicción)
- authenticity_score < 6 pero reliability_score >= 7 (necesita verificación)

REGLA: confidence = "UNCERTAIN" si:
- Información ambigua o contradictoria
- Fuente poco conocida con scores medios
- Contexto insuficiente para decidir claramente"""
    
    mimo_user_msg = f"""TEMA DE INVESTIGACIÓN: {context}
    
FUENTE CANDIDATA:
- URL: {source.get('url', 'N/A')}
- Título: {source.get('title', 'N/A')}
- Dominio: {source.get('source_domain', 'N/A')}
- Snippet: {source.get('snippet', 'N/A')[:300]}...

Evalúa rápidamente esta fuente y responde ÚNICAMENTE en formato JSON."""

    try:
        # ==========================================
        # FASE 1: Evaluación preliminar con MiMo-V2-Flash (barato)
        # ==========================================
        print(f"   🔍 Pre-evaluación con MiMo: {domain[:30]}")
        
        # Manejo de errores con reintentos para errores transitorios (429, 502, etc.)
        mimo_response = None
        mimo_max_retries = 3
        
        # Usar llm_mimo_cheap para pre-evaluación (más económico)
        # Si no está disponible, usar llm_planner como fallback
        llm_pre_eval = llm_mimo_cheap if llm_mimo_cheap else llm_planner
        
        for attempt in range(mimo_max_retries):
            try:
                mimo_response = await llm_pre_eval.ainvoke([
                    {"role": "system", "content": mimo_system_msg},
                    {"role": "user", "content": mimo_user_msg}
                ])
                break  # Éxito, salir del loop
            except Exception as e:
                error_str = str(e).lower()
                error_msg = str(e)
                
                # Detectar errores transitorios (429 rate limit, 502 bad gateway, 503 service unavailable)
                is_transient_error = (
                    "429" in error_msg or "rate limit" in error_str or "rate-limited" in error_str or
                    "502" in error_msg or "bad gateway" in error_str or
                    "503" in error_msg or "service unavailable" in error_str or
                    "provider returned error" in error_str
                )
                
                if is_transient_error and attempt < mimo_max_retries - 1:
                    wait_time = (2 ** attempt) * 2  # 2, 4, 8 segundos
                    print(f"   ⚠️ Error transitorio (intento {attempt + 1}/{mimo_max_retries}): {error_msg[:100]}... Esperando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Último intento fallido o error no transitorio
                    if attempt == mimo_max_retries - 1:
                        # En modo económico, no escalar - rechazar fuente
                        if USE_CHEAP_OPENROUTER_MODELS:
                            print(f"   ⚠️ Error persistente después de {mimo_max_retries} intentos con MiMo, rechazando fuente (modo económico)")
                            mimo_response = None
                            break
                        else:
                            print(f"   ⚠️ Error persistente después de {mimo_max_retries} intentos con MiMo, escalando a Judge")
                            # Si es el último intento y falló, escalar directamente a Judge
                            mimo_response = None
                            break
                    raise  # Re-lanzar el error para que sea manejado por el bloque except exterior
        
        # Si mimo_response es None, decidir qué hacer según modo
        if mimo_response is None:
            # En modo económico, no escalar - rechazar fuente
            if USE_CHEAP_OPENROUTER_MODELS:
                needs_detailed_review = False
            else:
                needs_detailed_review = True
            mimo_evaluation = {}
        else:
            mimo_content = mimo_response.content if hasattr(mimo_response, 'content') else str(mimo_response)
            
            # Limpiar markdown si existe
            if "```" in mimo_content:
                if "```json" in mimo_content:
                    mimo_content = mimo_content.split("```json")[-1].split("```")[0].strip()
                else:
                    mimo_content = mimo_content.split("```")[1].split("```")[0].strip()
            
            try:
                mimo_evaluation = json.loads(mimo_content)
                
                # Validar y completar campos requeridos con valores por defecto razonables
                mimo_required_fields = ["authenticity_score", "reliability_score", "relevance_score", "currency_score", "total_score", "is_clickbait"]
                mimo_missing_fields = [f for f in mimo_required_fields if f not in mimo_evaluation]
                
                # Completar campos faltantes con valores por defecto basados en campos existentes
                if mimo_missing_fields:
                    print(f"   ⚠️ Evaluación preliminar incompleta para {domain}. Faltan: {', '.join(mimo_missing_fields)}")
                    
                    # Calcular valores por defecto basados en campos existentes
                    existing_scores = [mimo_evaluation.get(f, 0) for f in ["authenticity_score", "reliability_score", "relevance_score", "currency_score"] if f in mimo_evaluation]
                    avg_existing = sum(existing_scores) / len(existing_scores) if existing_scores else 5  # Default medio si no hay ninguno
                    
                    # Completar campos faltantes
                    if "relevance_score" not in mimo_evaluation:
                        # Si falta relevance_score, estimar basado en el contexto y otros scores
                        mimo_evaluation["relevance_score"] = int(round(avg_existing)) if existing_scores else 5
                        print(f"      🔧 Completando relevance_score: {mimo_evaluation['relevance_score']}")
                    
                    if "authenticity_score" not in mimo_evaluation:
                        mimo_evaluation["authenticity_score"] = int(round(avg_existing)) if existing_scores else 5
                    
                    if "reliability_score" not in mimo_evaluation:
                        mimo_evaluation["reliability_score"] = int(round(avg_existing)) if existing_scores else 5
                    
                    if "currency_score" not in mimo_evaluation:
                        mimo_evaluation["currency_score"] = int(round(avg_existing)) if existing_scores else 7  # Default más alto para currency
                    
                    if "total_score" not in mimo_evaluation:
                        # Calcular total_score como promedio de los scores individuales
                        scores = [
                            mimo_evaluation.get("authenticity_score", 0),
                            mimo_evaluation.get("reliability_score", 0),
                            mimo_evaluation.get("relevance_score", 0),
                            mimo_evaluation.get("currency_score", 0)
                        ]
                        mimo_evaluation["total_score"] = int(round(sum(scores) / len(scores)))
                    
                    if "is_clickbait" not in mimo_evaluation:
                        # Inferir clickbait basado en scores (baja relevancia pero alta confiabilidad puede ser clickbait)
                        relevance = mimo_evaluation.get("relevance_score", 5)
                        reliability = mimo_evaluation.get("reliability_score", 5)
                        mimo_evaluation["is_clickbait"] = reliability >= 7 and relevance < 4
                    
                    print(f"      ✅ Campos completados. Evaluación ahora completa.")
                    mimo_missing_fields = []  # Ya no faltan campos
                
                # Si aún faltan campos críticos después de completar, decidir según modo
                if mimo_missing_fields:
                    # Si falla MiMo, decidir según modo
                    if USE_CHEAP_OPENROUTER_MODELS:
                        needs_detailed_review = False  # En económico, rechazar fuente incompleta
                    else:
                        needs_detailed_review = True  # En producción, escalar a Judge
                else:
                    # Extraer valores de la evaluación preliminar
                    confidence = mimo_evaluation.get("confidence", "HIGH")
                    needs_detailed_review = mimo_evaluation.get("needs_detailed_review", False)
                    
                    # Determinar si necesita revisión detallada basándose en criterios
                    total_score_pre = float(mimo_evaluation.get("total_score", 0))
                    reliability_score_pre = float(mimo_evaluation.get("reliability_score", 0))
                    relevance_score_pre = float(mimo_evaluation.get("relevance_score", 0))
                    authenticity_score_pre = float(mimo_evaluation.get("authenticity_score", 0))
                    
                    # Criterios para escalamiento (solo en modo producción, no en económico):
                    # En modo económico, MiMo es suficiente para todas las evaluaciones
                    # 1. Confidence es PARTIAL o UNCERTAIN
                    # 2. Scores en zona gris (5-7)
                    # 3. Contradicciones (alta fiabilidad pero baja relevancia)
                    # 4. Baja autenticidad pero alta fiabilidad (necesita verificación)
                    
                    # En modo económico, no escalar - MiMo es suficiente
                    if USE_CHEAP_OPENROUTER_MODELS:
                        # En modo económico, usar evaluación MiMo directamente sin escalamiento
                        needs_detailed_review = False
                    elif confidence in ["PARTIAL", "UNCERTAIN"]:
                        needs_detailed_review = True
                        print(f"      ⚠️ Confianza {confidence} - escalando a Judge (producción)")
                    elif 5 <= total_score_pre <= 7:
                        needs_detailed_review = True
                        print(f"      ⚠️ Score en zona gris ({total_score_pre:.1f}) - escalando a Judge (producción)")
                    elif reliability_score_pre >= 8 and relevance_score_pre < 6:
                        needs_detailed_review = True
                        print(f"      ⚠️ Contradicción detectada (fiabilidad alta, relevancia baja) - escalando a Judge (producción)")
                    elif authenticity_score_pre < 6 and reliability_score_pre >= 7:
                        needs_detailed_review = True
                        print(f"      ⚠️ Baja autenticidad con alta fiabilidad - escalando a Judge (producción)")
            except json.JSONDecodeError:
                # Solo escalar en modo producción, en económico reintentar o rechazar
                if USE_CHEAP_OPENROUTER_MODELS:
                    print(f"   ⚠️ Error parseando JSON de MiMo, rechazando fuente (modo económico)")
                    needs_detailed_review = False
                else:
                    print(f"   ⚠️ Error parseando JSON de MiMo, escalando a Judge")
                    needs_detailed_review = True
                mimo_evaluation = {}
            except Exception as e:
                # Solo escalar en modo producción, en económico reintentar o rechazar
                if USE_CHEAP_OPENROUTER_MODELS:
                    print(f"   ⚠️ Error en evaluación preliminar: {e}, rechazando fuente (modo económico)")
                    needs_detailed_review = False
                else:
                    print(f"   ⚠️ Error en evaluación preliminar: {e}, escalando a Judge")
                    needs_detailed_review = True
                mimo_evaluation = {}
        
        # ==========================================
        # FASE 2: Evaluación detallada con Judge (Cheap vs Premium)
        # ==========================================
        # Judge Cheap (DeepSeek): Por defecto para evaluaciones normales
        # Judge Premium (Claude/Gemini): Solo para casos muy críticos
        if needs_detailed_review:
            # Seleccionar modelo de judge según criticidad
            # Usar judge_cheap (DeepSeek) por defecto, judge_premium solo para casos muy críticos
            use_premium_judge = False  # Por defecto usar cheap
            
            # Criterios para usar judge premium:
            # - Fuentes de élite (Tier 1/2) con scores muy ambiguos
            # - Contradicciones muy marcadas (alta fiabilidad + muy baja relevancia)
            # - Casos donde MiMo tuvo muy baja confianza
            if 'mimo_evaluation' in locals() and mimo_evaluation:
                confidence = mimo_evaluation.get("confidence", "HIGH")
                total_score_pre = float(mimo_evaluation.get("total_score", 0))
                reliability_score_pre = float(mimo_evaluation.get("reliability_score", 0))
                relevance_score_pre = float(mimo_evaluation.get("relevance_score", 0))
                
                # Usar premium si:
                # 1. Confianza muy baja (UNCERTAIN)
                # 2. Score en zona de escalado (entre JUDGE_ESCALATE_SCORE_LOW y JUDGE_ESCALATE_SCORE_HIGH)
                # 3. Contradicción extrema (reliability >= 9 y relevance < 5)
                if confidence == "UNCERTAIN" or (JUDGE_ESCALATE_SCORE_LOW <= total_score_pre <= JUDGE_ESCALATE_SCORE_HIGH) or (reliability_score_pre >= 9 and relevance_score_pre < 5):
                    use_premium_judge = True
            
            # Seleccionar modelo
            # En modo TEST, NO usar Claude Sonnet (llm_judge_premium), solo usar modelos de TEST
            try:
                from .model_routing import get_active_profile, Profile
                active_profile = get_active_profile()
                is_test_mode = (active_profile == Profile.TEST)
            except ImportError:
                is_test_mode = False
            
            if is_test_mode:
                # En modo TEST, NO usar premium judge (Claude Sonnet), usar solo judge de TEST
                if llm_judge:
                    selected_judge = llm_judge
                    judge_model_name = "TEST (xiaomi/mimo-v2-flash:free)"
                elif llm_judge_cheap:
                    selected_judge = llm_judge_cheap
                    judge_model_name = "Cheap (MiMo)"
                else:
                    selected_judge = llm_judge
                    judge_model_name = "Judge (TEST)"
            elif use_premium_judge and llm_judge_premium:
                selected_judge = llm_judge_premium
                judge_model_name = "Premium (Claude Sonnet)"
            elif llm_judge_cheap:
                selected_judge = llm_judge_cheap
                judge_model_name = "Cheap (MiMo)"
            else:
                # Fallback al judge por defecto de config.toml
                selected_judge = llm_judge
                judge_model_name = getattr(llm_judge, 'model_name', 'Judge') if hasattr(llm_judge, 'model_name') else 'Judge'
                try:
                    from .config import CURRENT_JUDGE_MODEL
                    judge_model_name = CURRENT_JUDGE_MODEL
                except:
                    pass
            
            print(f"   🎯 Evaluación detallada con Judge {judge_model_name}: {domain[:30]}")
            
            # TRACKING: Guardar decisión de MiMo si existe para comparar después
            # Recuperar de evaluation dict si existe (se creó arriba con _mimo_keep)
            mimo_keep_for_tracking = None
            if 'evaluation' in locals() and isinstance(locals().get('evaluation'), dict):
                mimo_keep_for_tracking = locals().get('evaluation', {}).get('_mimo_keep')
            elif 'mimo_keep_value' in locals():
                mimo_keep_for_tracking = locals().get('mimo_keep_value')
            
            system_msg = f"""Eres un Analista de Calidad Senior especializado en Due Diligence y Evaluación de Fuentes.
Tu misión es evaluar fuentes de información usando un método multidimensional estricto.

EVALUACIÓN MULTIDIMENSIONAL (Cada criterio: 0-10):

1. AUTHENTICITY (Autenticidad):
   - ¿Es la fuente genuina y verificable?
   - ¿Puede verificarse la autoría y origen?
   - 8-10: Fuentes oficiales verificables, documentos públicos, instituciones reconocidas
   - 5-7: Fuentes con autoría clara pero menos verificables
   - 0-4: Fuentes anónimas, no verificables, o sospechosas

2. RELIABILITY (Fiabilidad):
   - ¿Es una institución/autor reconocido y confiable?
   - 8-10: Organismos oficiales, Think Tanks de élite, Papers académicos peer-reviewed, Consultoras de élite (McKinsey, BCG, Bain)
   - 6-7: Consultoras especializadas, empresas líderes del sector con contenido educativo
   - 5-7: Prensa financiera global, Big 4
   - 0-4: Blogs personales, foros, contenido puramente comercial

3. RELEVANCE (Relevancia):
   - ¿Responde directamente al tema investigado?
   - 8-10: Información altamente relevante y específica
   - 5-7: Información relacionada pero no directamente aplicable
   - 0-4: Información tangencial o no relacionada

4. CURRENCY (Actualidad):
   - ¿Es la información vigente?
   - 8-10: Últimos 1-2 años o información atemporal
   - 5-7: 3-5 años pero aún relevante
   - 0-4: Información obsoleta

DETECCIÓN DE CLICKBAIT:
- Títulos sensacionalistas, exagerados o engañosos = clickbait

OUTPUT JSON OBLIGATORIO:
{{
  "authenticity_score": <int 0-10>,
  "reliability_score": <int 0-10>,
  "relevance_score": <int 0-10>,
  "currency_score": <int 0-10>,
  "total_score": <int 0-10>,
  "is_clickbait": <bool>,
  "keep": <bool>,
  "reasoning": "<explicación breve>"
}}

REGLA CRÍTICA: keep = true SOLO si:
- total_score >= {TOTAL_SCORE_THRESHOLD}
- AND relevance_score >= {RELEVANCE_THRESHOLD}
- AND authenticity_score >= {AUTHENTICITY_THRESHOLD}
- AND reliability_score >= {RELIABILITY_THRESHOLD}
- AND is_clickbait = false

EXCEPCIÓN: Si reliability_score >= 8 y total_score >= {TOTAL_SCORE_THRESHOLD} y relevance_score >= 6:
- keep = true SOLO si authenticity_score >= {AUTHENTICITY_THRESHOLD}"""
            
            user_msg = f"""TEMA DE INVESTIGACIÓN: {context}
    
FUENTE CANDIDATA:
- URL: {source.get('url', 'N/A')}
- Título: {source.get('title', 'N/A')}
- Dominio: {source.get('source_domain', 'N/A')}
- Snippet: {source.get('snippet', 'N/A')[:300]}...

Evalúa esta fuente detalladamente y responde ÚNICAMENTE en formato JSON."""

            response = await selected_judge.ainvoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
        else:
            # Usar evaluación preliminar de MiMo como final, pero calcular "keep" correctamente
            print(f"      ✅ Evaluación MiMo suficiente (confidence: {mimo_evaluation.get('confidence', 'HIGH')})")
            
            # Convertir evaluación preliminar a formato final, calculando "keep"
            total_score_pre = float(mimo_evaluation.get("total_score", 0))
            relevance_score_pre = float(mimo_evaluation.get("relevance_score", 0))
            reliability_score_pre = float(mimo_evaluation.get("reliability_score", 0))
            is_clickbait_pre = mimo_evaluation.get("is_clickbait", False)
            
            # Calcular "keep" con las mismas reglas que Judge (con thresholds mínimos individuales)
            authenticity_score_pre = float(mimo_evaluation.get("authenticity_score", 0))
            
            if is_clickbait_pre:
                keep_value = False
            elif (total_score_pre >= TOTAL_SCORE_THRESHOLD and 
                  relevance_score_pre >= RELEVANCE_THRESHOLD and
                  authenticity_score_pre >= AUTHENTICITY_THRESHOLD and
                  reliability_score_pre >= RELIABILITY_THRESHOLD):
                # Cumple todos los thresholds: total, relevance, authenticity y reliability
                keep_value = True
            elif reliability_score_pre >= 8 and total_score_pre >= TOTAL_SCORE_THRESHOLD and relevance_score_pre >= 6:
                # Excepción para fuentes de alta fiabilidad (reliability >= 8)
                # Aún requiere authenticity mínimo
                if authenticity_score_pre >= AUTHENTICITY_THRESHOLD:
                    keep_value = True
                else:
                    keep_value = False
            else:
                keep_value = False
            
            # TRACKING: Registrar decisión de MiMo
            mimo_keep_value = keep_value  # Guardar para comparar después con Gemini
            if keep_value:
                _mimo_judge_metrics['mimo_accepted'] += 1
            else:
                _mimo_judge_metrics['mimo_rejected'] += 1
            
            # Crear evaluación final con formato estándar
            evaluation = {
                "authenticity_score": float(mimo_evaluation.get("authenticity_score", 0)),
                "reliability_score": float(mimo_evaluation.get("reliability_score", 0)),
                "relevance_score": float(mimo_evaluation.get("relevance_score", 0)),
                "currency_score": float(mimo_evaluation.get("currency_score", 0)),
                "total_score": total_score_pre,
                "is_clickbait": is_clickbait_pre,
                "keep": keep_value,
                "reasoning": mimo_evaluation.get("reasoning", "Evaluación preliminar con MiMo") + " [Pre-juez MiMo]",
                "pre_judge": "mimo",
                "confidence": mimo_evaluation.get("confidence", "HIGH"),
                "_mimo_keep": keep_value  # Guardar decisión de MiMo para tracking después
            }
            # Si viene de MiMo (no escaló), ya tenemos el evaluation parseado
            # Si viene de Gemini, necesitamos parsear el content
            if needs_detailed_review:
                # Viene de Gemini, parsear content
                # Guardar decisión de MiMo para comparar después (ya está en evaluation["_mimo_keep"])
                pass  # Continuar con el parsing de content abajo
            else:
                # Viene de MiMo, ya tenemos evaluation listo
                # Saltar directamente a la validación final
                result = {**source, **evaluation}
                result["score"] = evaluation["total_score"]
                result["reason"] = evaluation["reasoning"]
                result["fast_track"] = None
                cache_evaluation(url, evaluation)
                return result
        
        # Si llegamos aquí, necesitamos parsear content (viene de Gemini)
        # Limpiar markdown si existe
        if "```" in content:
            if "```json" in content:
                content = content.split("```json")[-1].split("```")[0].strip()
            else:
                content = content.split("```")[1].split("```")[0].strip()
        
        try:
            evaluation = json.loads(content)
            
            # Validar campos requeridos
            required_fields = [
                "authenticity_score", "reliability_score", "relevance_score",
                "currency_score", "total_score", "is_clickbait", "keep", "reasoning"
            ]
            missing_fields = [f for f in required_fields if f not in evaluation]
            
            # Tolerancia a fallos
            if "keep" in missing_fields:
                missing_fields.remove("keep")
                evaluation["keep"] = False
            
            if "reasoning" in missing_fields:
                missing_fields.remove("reasoning")
                evaluation["reasoning"] = "Evaluación automática."

            if missing_fields:
                print(f"   ⚠️ Evaluación incompleta para {domain}. Faltan: {', '.join(missing_fields)}")
                return None
            
            # Validar tipos y rangos (aceptar int y float)
            score_fields = ["authenticity_score", "reliability_score", "relevance_score", "currency_score", "total_score"]
            for field in score_fields:
                score = evaluation.get(field)
                # Aceptar tanto int como float, y convertir a float para comparación
                if not isinstance(score, (int, float)) or score < 0 or score > 10:
                    print(f"   ⚠️ Score inválido en {field}: {score}")
                    return None
                # Normalizar a float para consistencia
                evaluation[field] = float(score)
            
            # Validar total_score vs promedio calculado
            llm_total = float(evaluation.get("total_score", 0))
            calculated_total = (
                evaluation["authenticity_score"] + 
                evaluation["reliability_score"] + 
                evaluation["relevance_score"] + 
                evaluation["currency_score"]
            ) / 4.0
            
            # Si el total_score del LLM difiere mucho del calculado, usar el calculado
            if llm_total < 0 or llm_total > 10 or abs(llm_total - calculated_total) > 2:
                evaluation["total_score"] = round(calculated_total, 2)
            
            # Aplicar lógica de filtrado estricta (con thresholds mínimos individuales)
            total_score = evaluation.get("total_score", 0)
            relevance_score = evaluation.get("relevance_score", 0)
            reliability_score = evaluation.get("reliability_score", 0)
            authenticity_score = evaluation.get("authenticity_score", 0)
            is_clickbait = evaluation.get("is_clickbait", False)
            
            # Determinar keep basado en reglas
            if is_clickbait:
                evaluation["keep"] = False
            elif (total_score >= TOTAL_SCORE_THRESHOLD and 
                  relevance_score >= RELEVANCE_THRESHOLD and
                  authenticity_score >= AUTHENTICITY_THRESHOLD and
                  reliability_score >= RELIABILITY_THRESHOLD):
                # Cumple todos los thresholds: total, relevance, authenticity y reliability
                evaluation["keep"] = True
            elif reliability_score >= 8 and total_score >= TOTAL_SCORE_THRESHOLD and relevance_score >= 6:
                # Excepción para fuentes de alta fiabilidad (reliability >= 8)
                # Aún requiere authenticity mínimo
                if authenticity_score >= AUTHENTICITY_THRESHOLD:
                    evaluation["keep"] = True
                else:
                    evaluation["keep"] = False
            else:
                evaluation["keep"] = False
            
            # POLICY 2: Apply category-specific hard rules after LLM evaluation
            category = classify_source_category(url, domain)
            if evaluation.get("keep") and category == 'consulting':
                # Consulting sources require stricter relevance threshold
                if relevance_score < EVAL_CONSULTING_MIN_RELEVANCE:
                    evaluation["keep"] = False
                    evaluation["reasoning"] = evaluation.get("reasoning", "") + f" | Hard rule: consulting requiere relevance>={EVAL_CONSULTING_MIN_RELEVANCE} (tenía {relevance_score:.1f})"
            elif evaluation.get("keep") and category == 'general_media':
                # General media sources require very high relevance (priorizar fuentes primarias)
                if relevance_score < EVAL_GENERAL_MEDIA_MIN_RELEVANCE:
                    evaluation["keep"] = False
                    evaluation["reasoning"] = evaluation.get("reasoning", "") + f" | Hard rule: medios generalistas/confidenciales requieren relevance>={EVAL_GENERAL_MEDIA_MIN_RELEVANCE} (tenía {relevance_score:.1f}) | Priorizar fuentes primarias"
            elif not evaluation.get("keep") and category == 'institutional':
                # Institutional sources may pass with lower relevance if other scores are strong
                if relevance_score >= EVAL_INSTITUTIONAL_MIN_RELEVANCE and total_score >= TOTAL_SCORE_THRESHOLD - 0.5:
                    evaluation["keep"] = True
                    evaluation["reasoning"] = evaluation.get("reasoning", "") + " | Hard rule: institutional con scores fuertes permitido"
            
            # TRACKING: Comparar decisión de Gemini con MiMo (si vino de MiMo)
            judge_keep_value = evaluation.get("keep", False)
            # Recuperar decisión de MiMo guardada antes de llamar a Gemini
            # La variable mimo_keep_for_tracking se guardó arriba antes de llamar a llm_judge
            if 'mimo_keep_for_tracking' in locals():
                mimo_keep = locals().get('mimo_keep_for_tracking')
                if mimo_keep is not None:
                    # Esta fuente vino de MiMo y escaló a Gemini
                    if mimo_keep:
                        # MiMo aceptó esta fuente
                        if judge_keep_value:
                            # Gemini también aceptó
                            _mimo_judge_metrics['mimo_accepted_then_judge_accepted'] += 1
                        else:
                            # Gemini rechazó (MiMo aceptó pero Gemini rechazó)
                            _mimo_judge_metrics['mimo_accepted_then_judge_rejected'] += 1
                else:
                    # Esta fuente fue directo a Gemini (sin pasar por MiMo, ej: elite fast-track)
                    _mimo_judge_metrics['judge_only_evaluations'] += 1
            else:
                # No hay tracking de MiMo (fuente directa a Gemini)
                _mimo_judge_metrics['judge_only_evaluations'] += 1
            
            # Construir resultado final
            result = {**source, **evaluation}
            result["score"] = evaluation["total_score"]
            result["reason"] = evaluation["reasoning"]
            result["fast_track"] = None
            result["pre_judge"] = "gemini"  # Indica que pasó por evaluación detallada de Gemini
            result["source_category"] = category  # Policy 2: category classification
            
            # Cachear para futuras consultas
            cache_evaluation(url, evaluation)
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"   ⚠️ Error parseando JSON: {e}")
            print(f"   Contenido: {content[:200]}...")
            return None
            
    except Exception as e:
        print(f"   ⚠️ Error en evaluate_source: {e}")
        return None


# ==========================================
# BATCH EVALUATION (optimización de tokens)
# ==========================================

async def evaluate_sources_batch(
    sources: List[Dict], 
    context: str, 
    batch_size: int = 5
) -> Tuple[List[Dict], List[Dict]]:
    """
    Evalúa múltiples fuentes en batches para optimizar llamadas LLM.
    
    Flujo:
    1. Primero aplica fast-tracks (cache, élite, auto-reject)
    2. Las que quedan van a evaluación batch con LLM
    
    Args:
        sources: Lista de fuentes a evaluar
        context: Tema de investigación
        batch_size: Tamaño de batch para LLM (default 5)
    
    Returns:
        Tuple (validated_sources, rejected_sources)
    """
    if not sources:
        return [], []
    
    validated = []
    rejected = []
    pending_llm_eval = []
    
    # ==========================================
    # FASE 1: Fast-tracks (sin LLM)
    # ==========================================
    print(f"\n   🔍 [BATCH EVAL] Procesando {len(sources)} fuentes...")
    
    for source in sources:
        url = source.get('url', '')
        
        # Check cache
        cached = get_cached_evaluation(url)
        if cached:
            result = {**source, **cached, "from_cache": True}
            result["score"] = cached.get("total_score", 0)
            if cached.get("keep", False):
                validated.append(result)
            else:
                rejected.append(result)
            continue
        
        # Check élite / auto-reject
        elite_info = get_elite_domain_scores(url)
        if elite_info:
            if elite_info.get('auto_reject'):
                result = {
                    **source,
                    "authenticity_score": 0, "reliability_score": 0,
                    "relevance_score": 0, "currency_score": 0,
                    "total_score": 0, "is_clickbait": False, "keep": False,
                    "reasoning": elite_info.get('reason', 'Auto-rejected'),
                    "fast_track": "auto_reject"
                }
                rejected.append(result)
                cache_evaluation(url, result)
                continue
            
            # POLICY 2: Elite sources should go through evaluate_source() for Policy 2 logic
            # (This ensures consistency and proper gray zone handling)
            # Defer to evaluate_source() which now implements Policy 2
            pending_llm_eval.append(source)
            continue
        
        # Check fuentes internas de la empresa
        # NOTA: Ya no se usa COMPANY_CONTEXT del JSON, se usa el contexto de Airtable
        url_lower = url.lower()
        company_name = ""  # Ya no se usa COMPANY_CONTEXT del JSON
        
        # Si necesitas filtrar fuentes internas, usa el contexto de Airtable (project_specific_context)
        if company_name and (company_name in url_lower or company_name in source.get('source_domain', '').lower()):
            result = {
                **source,
                "authenticity_score": 10, "reliability_score": 10,
                "relevance_score": 0, "currency_score": 0,
                "total_score": 4, "is_clickbait": False, "keep": False,
                "reasoning": "Internal source filtered",
                "fast_track": "internal_filter"
            }
            rejected.append(result)
            cache_evaluation(url, result)
            continue
        
        # No fast-track, necesita LLM
        pending_llm_eval.append(source)
    
    print(f"      Fast-track: {len(sources) - len(pending_llm_eval)} fuentes")
    print(f"      Pendientes LLM: {len(pending_llm_eval)} fuentes")
    
    # ==========================================
    # FASE 2: LLM Evaluation (en paralelo)
    # ==========================================
    if pending_llm_eval:
        print(f"   🤖 Evaluando {len(pending_llm_eval)} fuentes con LLM...")
        
        # Evaluar en paralelo (más rápido que batch en un solo prompt)
        tasks = [evaluate_source(source, context) for source in pending_llm_eval]
        results = await asyncio.gather(*tasks)
        
        for result in results:
            if result:
                if result.get("keep", False):
                    validated.append(result)
                else:
                    rejected.append(result)
    
    print(f"   ✅ Resultado: {len(validated)} validadas, {len(rejected)} rechazadas")
    
    return validated, rejected


# ==========================================
# ESTADÍSTICAS DE EVALUACIÓN
# ==========================================

def get_evaluation_stats(validated: List[Dict], rejected: List[Dict]) -> Dict:
    """
    Genera estadísticas de la evaluación para logging/reporting.
    """
    total = len(validated) + len(rejected)
    
    if total == 0:
        return {"total": 0, "validated": 0, "rejected": 0}
    
    # Contar por tipo de fast-track
    cache_hits = sum(1 for s in validated + rejected if s.get("from_cache"))
    elite_tracks = sum(1 for s in validated + rejected if s.get("fast_track") == "elite")
    auto_rejects = sum(1 for s in validated + rejected if s.get("fast_track") == "auto_reject")
    internal_filters = sum(1 for s in validated + rejected if s.get("fast_track") == "internal_filter")
    llm_evaluated = total - cache_hits - elite_tracks - auto_rejects - internal_filters
    
    # Calcular confidence
    confidence = calculate_confidence_score(validated)
    
    return {
        "total": total,
        "validated": len(validated),
        "rejected": len(rejected),
        "acceptance_rate": round(len(validated) / total * 100, 1) if total > 0 else 0,
        "cache_hits": cache_hits,
        "elite_fast_tracks": elite_tracks,
        "auto_rejects": auto_rejects,
        "internal_filters": internal_filters,
        "llm_evaluated": llm_evaluated,
        "llm_calls_saved": cache_hits + elite_tracks + auto_rejects + internal_filters,
        "confidence": confidence
    }


def print_evaluation_summary(stats: Dict):
    """Imprime resumen de evaluación."""
    print(f"\n   📊 [EVALUATION SUMMARY]")
    print(f"      Total: {stats['total']} fuentes")
    print(f"      ✅ Validadas: {stats['validated']} ({stats['acceptance_rate']}%)")
    print(f"      ❌ Rechazadas: {stats['rejected']}")
    print(f"      ⚡ Fast-tracks: {stats['llm_calls_saved']} (ahorro de LLM calls)")
    print(f"         - Cache hits: {stats['cache_hits']}")
    print(f"         - Élite: {stats['elite_fast_tracks']}")
    print(f"         - Auto-reject: {stats['auto_rejects']}")
    print(f"         - Internal filter: {stats['internal_filters']}")
    print(f"      🤖 LLM evaluadas: {stats['llm_evaluated']}")
    
    conf = stats.get('confidence', {})
    if conf:
        print(f"      📈 Confidence: {conf.get('score', 0)}/100 ({conf.get('level', 'N/A')})")
