"""
Módulo Source Quality: Cache, pre-filtros de élite, métricas de confianza y diversidad.
Optimiza tokens y llamadas al LLM judge.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re

# ==========================================
# CONFIGURACIÓN
# ==========================================

CACHE_FILE = Path(__file__).parent.parent / ".evaluation_cache.json"
CACHE_TTL_DAYS = 7  # Días antes de invalidar cache

# ==========================================
# DOMINIOS DE ÉLITE (Fast-track sin LLM)
# ==========================================

ELITE_DOMAINS: Dict[str, Dict[str, int]] = {
    # Consultoras Tier 1 (reliability 9-10)
    'mckinsey.com': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'bcg.com': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'bain.com': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    
    # Big 4 (reliability 8)
    'deloitte.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'pwc.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'ey.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'kpmg.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    
    # Academia y Research de élite
    'hbr.org': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'mit.edu': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'stanford.edu': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'harvard.edu': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'wharton.upenn.edu': {'reliability': 9, 'authenticity': 9, 'tier': 1},
    'insead.edu': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'lse.ac.uk': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    
    # Instituciones internacionales
    'europa.eu': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'ec.europa.eu': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'worldbank.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'oecd.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'imf.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'iea.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'un.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'wto.org': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    
    # Prensa financiera premium
    'ft.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'bloomberg.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'wsj.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'economist.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'reuters.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'cnbc.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    
    # Research de mercado especializado
    'gartner.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'forrester.com': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'statista.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'ibisworld.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'euromonitor.com': {'reliability': 8, 'authenticity': 8, 'tier': 2},
    
    # Packaging y Sustainability específicos
    'ellenmacarthurfoundation.org': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'packagingeurope.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'packagingdigest.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'plasticstoday.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'recyclingtoday.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'wrap.org.uk': {'reliability': 8, 'authenticity': 9, 'tier': 2},
    'plasticsindustry.org': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    
    # Gobiernos y reguladores
    'epa.gov': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'gov.uk': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'boe.es': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    'miteco.gob.es': {'reliability': 9, 'authenticity': 10, 'tier': 1},
    
    # Venture/Startup Intelligence
    'crunchbase.com': {'reliability': 7, 'authenticity': 8, 'tier': 3},
    'pitchbook.com': {'reliability': 8, 'authenticity': 8, 'tier': 2},
    'cbinsights.com': {'reliability': 8, 'authenticity': 8, 'tier': 2},
    'dealroom.co': {'reliability': 7, 'authenticity': 8, 'tier': 3},
}

# Dominios a rechazar automáticamente (sin evaluar)
# Nota: Los dominios internos de la empresa se filtran dinámicamente en evaluator.py
AUTO_REJECT_DOMAINS = [
    # Dominios internos de la empresa se añaden dinámicamente basándose en COMPANY_CONTEXT
    'facebook.com', 'twitter.com', 'instagram.com', 'tiktok.com',  # Social media
    'pinterest.com', 'linkedin.com/posts',  # Social posts (no articles)
    'youtube.com',  # YouTube generalmente no es fuente confiable para informes académicos (excepto canales oficiales específicos)
    'youtube.com/shorts',  # Shorts no son fuentes
    'medium.com/@',  # Blogs personales en Medium
]


def get_elite_domain_scores(url: str) -> Optional[Dict]:
    """
    Retorna scores pre-asignados si el dominio es de élite.
    Ahorra llamada al LLM judge.
    
    Returns:
        Dict con scores o None si no es élite
    """
    if not url:
        return None
    
    url_lower = url.lower()
    
    # Check auto-reject primero
    for reject_domain in AUTO_REJECT_DOMAINS:
        if reject_domain in url_lower:
            return {
                'reliability': 0,
                'authenticity': 0,
                'domain': reject_domain,
                'auto_reject': True,
                'reason': f'Dominio en lista de rechazo automático: {reject_domain}'
            }
    
    # Check élite
    for domain, scores in ELITE_DOMAINS.items():
        if domain in url_lower:
            return {
                **scores,
                'domain': domain,
                'auto_reject': False
            }
    
    return None


def is_elite_domain(url: str) -> bool:
    """Check rápido si es dominio de élite."""
    result = get_elite_domain_scores(url)
    return result is not None and not result.get('auto_reject', False)


# ==========================================
# CACHE DE EVALUACIONES
# ==========================================

def _load_cache() -> Dict:
    """Carga cache desde archivo JSON."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️ Error cargando cache: {e}")
            return {}
    return {}


def _save_cache(cache: Dict):
    """Guarda cache a archivo JSON."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"   ⚠️ Error guardando cache: {e}")


def _url_hash(url: str) -> str:
    """Genera hash único para URL."""
    normalized = url.lower().rstrip('/').split('?')[0]  # Normalizar y quitar params
    return hashlib.md5(normalized.encode()).hexdigest()


def get_cached_evaluation(url: str) -> Optional[Dict]:
    """
    Obtiene evaluación cacheada si existe y no ha expirado.
    
    Returns:
        Dict con evaluación o None si no hay cache válido
    """
    cache = _load_cache()
    key = _url_hash(url)
    
    if key in cache:
        entry = cache[key]
        try:
            cached_date = datetime.fromisoformat(entry.get('cached_at', '2000-01-01'))
            if datetime.now() - cached_date < timedelta(days=CACHE_TTL_DAYS):
                return entry.get('evaluation')
        except (ValueError, TypeError):
            pass
    return None


def cache_evaluation(url: str, evaluation: Dict):
    """
    Guarda evaluación en cache.
    Solo guarda los campos de scoring, no el contenido completo.
    """
    cache = _load_cache()
    key = _url_hash(url)
    
    # Solo cachear campos de evaluación, no contenido
    eval_fields = {
        'authenticity_score', 'reliability_score', 'relevance_score', 
        'currency_score', 'total_score', 'is_clickbait', 'keep', 'reasoning'
    }
    
    cached_eval = {k: v for k, v in evaluation.items() if k in eval_fields}
    
    cache[key] = {
        'url': url,
        'evaluation': cached_eval,
        'cached_at': datetime.now().isoformat()
    }
    _save_cache(cache)


def clear_cache():
    """Limpia todo el cache de evaluaciones."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        print("   ✅ Cache de evaluaciones limpiado")


def get_cache_stats() -> Dict:
    """Retorna estadísticas del cache."""
    cache = _load_cache()
    if not cache:
        return {'total_entries': 0, 'valid_entries': 0}
    
    now = datetime.now()
    valid = 0
    for entry in cache.values():
        try:
            cached_date = datetime.fromisoformat(entry.get('cached_at', '2000-01-01'))
            if now - cached_date < timedelta(days=CACHE_TTL_DAYS):
                valid += 1
        except:
            pass
    
    return {
        'total_entries': len(cache),
        'valid_entries': valid,
        'expired_entries': len(cache) - valid
    }


# ==========================================
# MÉTRICAS DE CONFIANZA
# ==========================================

def calculate_confidence_score(sources: List[Dict]) -> Dict:
    """
    Calcula métricas de confianza agregadas de las fuentes.
    
    Returns:
        Dict con score (0-100), level, y métricas detalladas
    """
    if not sources:
        return {
            "score": 0,
            "level": "NONE",
            "elite_count": 0,
            "total": 0,
            "avg_reliability": 0,
            "avg_relevance": 0,
            "tier_distribution": {}
        }
    
    total_reliability = sum(s.get('reliability_score', 5) for s in sources)
    total_relevance = sum(s.get('relevance_score', 5) for s in sources)
    avg_reliability = total_reliability / len(sources)
    avg_relevance = total_relevance / len(sources)
    
    # Contar por tier
    tier_distribution = {1: 0, 2: 0, 3: 0, 'other': 0}
    elite_count = 0
    
    for s in sources:
        reliability = s.get('reliability_score', 0)
        if reliability >= 9:
            tier_distribution[1] += 1
            elite_count += 1
        elif reliability >= 8:
            tier_distribution[2] += 1
            elite_count += 1
        elif reliability >= 7:
            tier_distribution[3] += 1
        else:
            tier_distribution['other'] += 1
    
    # Score combinado (0-100)
    # Peso: 60% reliability, 40% relevance
    combined = (avg_reliability * 0.6 + avg_relevance * 0.4) * 10
    
    # Bonus por fuentes de élite (hasta +10 puntos)
    elite_bonus = min(10, (elite_count / len(sources)) * 15)
    combined = min(100, combined + elite_bonus)
    
    # Determinar nivel
    if combined >= 80:
        level = "HIGH"
    elif combined >= 60:
        level = "MEDIUM"
    elif combined >= 40:
        level = "LOW"
    else:
        level = "VERY_LOW"
    
    return {
        "score": round(combined),
        "level": level,
        "elite_count": elite_count,
        "total": len(sources),
        "avg_reliability": round(avg_reliability, 1),
        "avg_relevance": round(avg_relevance, 1),
        "tier_distribution": tier_distribution
    }


def format_confidence_badge(confidence: Dict) -> str:
    """Genera badge de confianza para incluir en reportes."""
    level_emoji = {
        "HIGH": "🟢",
        "MEDIUM": "🟡", 
        "LOW": "🟠",
        "VERY_LOW": "🔴",
        "NONE": "⚫"
    }
    
    emoji = level_emoji.get(confidence['level'], "⚪")
    
    return f"""> {emoji} **Confidence Score: {confidence['score']}/100 ({confidence['level']})**
> *{confidence['elite_count']}/{confidence['total']} fuentes de alta fiabilidad (Tier 1-2) | Avg Reliability: {confidence['avg_reliability']}/10*
"""


# ==========================================
# MÉTRICAS DE DIVERSIDAD
# ==========================================

SOURCE_CATEGORIES = {
    'consulting': ['mckinsey', 'bcg', 'bain', 'deloitte', 'pwc', 'ey', 'kpmg', 'accenture'],
    'academic': ['edu', 'ac.uk', 'university', 'journal', 'research', 'hbr', 'scholar'],
    'news_financial': ['reuters', 'bloomberg', 'ft.com', 'wsj', 'economist', 'cnbc', 'forbes'],
    'news_general': ['news', 'times', 'post', 'guardian', 'bbc'],
    'institutional': ['europa.eu', 'gov', 'worldbank', 'oecd', 'un.org', 'imf', 'iea', 'wto'],
    'industry_specific': ['packaging', 'recycling', 'sustainable', 'plastic', 'circular'],
    'market_research': ['gartner', 'forrester', 'statista', 'ibisworld', 'euromonitor'],
    'startup_vc': ['crunchbase', 'pitchbook', 'cbinsights', 'dealroom', 'techcrunch'],
}


def calculate_source_diversity(sources: List[Dict]) -> Dict:
    """
    Calcula métricas de diversidad de tipos de fuentes.
    
    Returns:
        Dict con diversity_score, distribución y warnings
    """
    if not sources:
        return {
            "diversity_score": 0,
            "category_distribution": {},
            "unique_domains": 0,
            "warnings": ["No hay fuentes para evaluar diversidad"]
        }
    
    category_counts = {cat: 0 for cat in SOURCE_CATEGORIES}
    category_counts['other'] = 0
    domains_seen = set()
    
    for source in sources:
        domain = source.get('source_domain', '').lower()
        url = source.get('url', '').lower()
        
        if domain in domains_seen:
            continue
        domains_seen.add(domain)
        
        categorized = False
        for cat, keywords in SOURCE_CATEGORIES.items():
            if any(kw in domain or kw in url for kw in keywords):
                category_counts[cat] += 1
                categorized = True
                break
        
        if not categorized:
            category_counts['other'] += 1
    
    # Calcular diversidad (0-100)
    non_zero_categories = sum(1 for c in category_counts.values() if c > 0)
    total_categories = len(SOURCE_CATEGORIES) + 1
    diversity_score = (non_zero_categories / total_categories) * 100
    
    # Generar warnings
    warnings = []
    total_sources = len(domains_seen)
    
    # Check concentración excesiva en una categoría
    for cat, count in category_counts.items():
        if count > total_sources * 0.5 and total_sources > 3:
            cat_name = cat.replace('_', ' ').title()
            warnings.append(f"⚠️ >50% de fuentes son de tipo '{cat_name}'. Considerar diversificar.")
    
    # Check poca diversidad
    if non_zero_categories < 3 and total_sources >= 5:
        warnings.append(f"⚠️ Baja diversidad: solo {non_zero_categories} categorías diferentes.")
    
    # Check pocas fuentes
    if total_sources < 5:
        warnings.append(f"⚠️ Solo {total_sources} fuentes únicas. Considerar ampliar búsqueda.")
    
    # Check falta de fuentes institucionales/académicas
    institutional_academic = category_counts.get('institutional', 0) + category_counts.get('academic', 0)
    if institutional_academic == 0 and total_sources >= 5:
        warnings.append("⚠️ Sin fuentes institucionales o académicas. Puede afectar credibilidad.")
    
    return {
        "diversity_score": round(diversity_score),
        "category_distribution": {k: v for k, v in category_counts.items() if v > 0},
        "unique_domains": total_sources,
        "categories_represented": non_zero_categories,
        "warnings": warnings
    }


# ==========================================
# QUALITY GATE
# ==========================================

def check_quality_gate(
    sources: List[Dict], 
    min_sources: int = 3,
    min_avg_reliability: float = 6.0,
    require_elite: bool = True,
    max_consulting_ratio: float = 0.3,  # Actualizado: 30% máximo (25-30% recomendado)
    max_general_media_ratio: float = 0.1,  # Actualizado: 10% máximo
    require_primary_sources: bool = True
) -> Dict:
    """
    Evalúa si las fuentes pasan el quality gate para generar reporte.
    
    Args:
        sources: Lista de fuentes validadas
        min_sources: Mínimo de fuentes requeridas
        min_avg_reliability: Reliability promedio mínima
        require_elite: Si se requiere al menos 1 fuente de alta fiabilidad
        max_consulting_ratio: Ratio máximo de fuentes de consultoras (0.3 = 30%, recomendado 25-30%)
        require_primary_sources: Si se requiere al menos 1 fuente primaria (institucional/académica)
    
    Returns:
        Dict con passed (bool), issues (list), y métricas
    """
    confidence = calculate_confidence_score(sources)
    diversity = calculate_source_diversity(sources)
    
    issues = []
    
    # Check mínimo de fuentes
    if min_sources and min_sources > 0 and len(sources) < min_sources:
        issues.append(f"Fuentes insuficientes: {len(sources)} < {min_sources} requeridas")
    
    # Check reliability promedio
    if confidence['avg_reliability'] < min_avg_reliability:
        issues.append(f"Reliability promedio baja: {confidence['avg_reliability']}/10 < {min_avg_reliability} requerido")
    
    # Check fuentes de élite
    if require_elite and confidence['elite_count'] == 0 and len(sources) > 0:
        issues.append("Sin fuentes de alta fiabilidad (Tier 1-2). Recomendado: McKinsey, HBR, instituciones, etc.")
    
    # Check concentración de consultoras (ERROR si > max_consulting_ratio)
    consulting_count = diversity['category_distribution'].get('consulting', 0)
    total_sources = diversity['unique_domains']
    if total_sources > 0:
        consulting_ratio = consulting_count / total_sources
        if consulting_ratio > max_consulting_ratio and total_sources >= 3:
            max_allowed = int(total_sources * max_consulting_ratio)
            issues.append(f"Demasiadas fuentes de consultoras: {consulting_count}/{total_sources} ({consulting_ratio*100:.0f}%) > {max_consulting_ratio*100:.0f}% máximo permitido. Máximo: {max_allowed} consultoras")
    
    # Check concentración de medios generalistas/confidenciales (ERROR si > max_general_media_ratio)
    # Usar source_category directamente de las fuentes (más preciso que diversity)
    general_media_count = sum(1 for s in sources if s.get('source_category') == 'general_media')
    if total_sources > 0:
        general_media_ratio = general_media_count / total_sources
        if general_media_ratio > max_general_media_ratio and total_sources >= 3:
            max_allowed = int(total_sources * max_general_media_ratio)
            issues.append(f"Demasiadas fuentes de medios generalistas/confidenciales: {general_media_count}/{total_sources} ({general_media_ratio*100:.0f}%) > {max_general_media_ratio*100:.0f}% máximo permitido. Máximo: {max_allowed} medios generalistas | Priorizar fuentes primarias (institucionales/académicas)")
    
    # Check fuentes primarias obligatorias (institucionales o académicas)
    if require_primary_sources and total_sources >= 5:
        institutional_count = diversity['category_distribution'].get('institutional', 0)
        academic_count = diversity['category_distribution'].get('academic', 0)
        primary_count = institutional_count + academic_count
        if primary_count == 0:
            issues.append("Se requiere al menos 1 fuente primaria (institucional o académica) para garantizar diversidad. Buscar fuentes de instituciones oficiales (gov, europa.eu, worldbank) o académicas (edu, journals)")
    
    # Añadir warnings de diversidad adicionales (que no son errores)
    for warning in diversity['warnings']:
        # Solo añadir warnings que no sean sobre concentración de consultoras (ya lo manejamos arriba como error)
        if 'consulting' not in warning.lower() or '>50%' not in warning:
            if not any('institucional' in warning.lower() or 'académica' in warning.lower() for warning in [warning] if 'Sin fuentes' in warning):
                issues.append(warning)
    
    return {
        "passed": len([i for i in issues if not i.startswith("⚠️")]) == 0,  # Solo fallar por errores, no warnings
        "issues": issues,
        "confidence": confidence,
        "diversity": diversity,
        "recommendation": "PROCEED" if len(issues) == 0 else "PROCEED_WITH_WARNINGS" if all(i.startswith("⚠️") for i in issues) else "RETRY_SEARCH"
    }


# ==========================================
# UTILIDADES
# ==========================================

def extract_domain_from_url(url: str) -> str:
    """Extrae dominio limpio de una URL."""
    if not url:
        return 'unknown'
    
    # Limpiar protocolo
    url = re.sub(r'^https?://', '', url.lower())
    # Quitar www
    url = re.sub(r'^www\.', '', url)
    # Tomar solo el dominio
    domain = url.split('/')[0]
    
    return domain


def get_domain_tier(url: str) -> int:
    """
    Retorna el tier del dominio (1=élite, 2=premium, 3=bueno, 4=otros).
    """
    elite_info = get_elite_domain_scores(url)
    if elite_info:
        if elite_info.get('auto_reject'):
            return 5  # Rechazado
        return elite_info.get('tier', 3)
    return 4  # Otros


def prioritize_sources_by_quality(sources: List[Dict]) -> List[Dict]:
    """
    Ordena fuentes por calidad (tier + scores).
    Útil para limitar fuentes manteniendo las mejores.
    """
    def sort_key(source):
        url = source.get('url', '')
        tier = get_domain_tier(url)
        reliability = source.get('reliability_score', 5)
        relevance = source.get('relevance_score', 5)
        combined = reliability * 0.6 + relevance * 0.4
        return (tier, -combined)  # Menor tier primero, mayor score primero
    
    return sorted(sources, key=sort_key)
