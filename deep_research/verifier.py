"""
Módulo Verifier: Valida que el reporte no contenga alucinaciones.

MEJORA 2026-01: Sistema de verificación exacta de cifras
- Antes de usar LLM, busca cifras con regex en fuentes COMPLETAS
- Reduce falsos positivos significativamente
- Solo usa LLM para cifras que no se encuentran exactamente
"""
import json
import re
from typing import Dict, List, Tuple, Optional, Set
from .config import llm_judge, model_config, TOML_CONFIG, USE_DEEPSEEK_FOR_TESTING, USE_CHEAP_OPENROUTER_MODELS, get_model_limits
from .utils import count_tokens
from .logger import logger


# ==========================================
# VERIFICACIÓN EXACTA DE CIFRAS (Pre-LLM)
# ==========================================

def _extract_numbers_from_report(report: str) -> Set[str]:
    """
    Extrae todos los números/cifras significativos del reporte.
    Incluye porcentajes, cantidades monetarias, años, etc.

    Returns:
        Set de strings con los números encontrados
    """
    patterns = [
        r'\d+(?:[.,]\d+)?%',                    # Porcentajes: 47%, 3.5%, 47,5%
        r'\$\d+(?:[.,]\d+)?(?:\s*)?[BMKbmk]?',  # Dinero USD: $1.5B, $100M, $50K
        r'€\d+(?:[.,]\d+)?(?:\s*)?[BMKbmk]?',   # Dinero EUR: €1.5B
        r'£\d+(?:[.,]\d+)?(?:\s*)?[BMKbmk]?',   # Dinero GBP
        r'\d+(?:[.,]\d+)?\s*(?:billion|million|trillion|mil\s*millones|millones|miles\s*de\s*millones)',  # Cantidades
        r'\d+(?:[.,]\d+)?\s*(?:bn|mn|tn|MM|M)\b',  # Abreviaciones: 1.5bn, 100mn
        r'\b(?:19|20)\d{2}\b',                  # Años: 2024, 1999
        r'\d+(?:[.,]\d+)?x\b',                  # Multiplicadores: 2.5x
        r'\d+(?:[.,]\d+)?\s*CAGR',              # CAGR específico
        r'CAGR\s*(?:of\s*|de\s*)?\d+(?:[.,]\d+)?%?',  # CAGR de X%
    ]

    numbers = set()
    for pattern in patterns:
        matches = re.findall(pattern, report, re.IGNORECASE)
        numbers.update(matches)

    # Filtrar números muy genéricos (años comunes que no aportan información específica)
    # pero mantener años en contexto de datos
    filtered = set()
    for num in numbers:
        # Mantener si es porcentaje, dinero, o número con unidad
        if any(c in num.lower() for c in ['%', '$', '€', '£', 'billion', 'million', 'bn', 'mn', 'cagr', 'x']):
            filtered.add(num)
        # Mantener años recientes (2015-2035) que son relevantes para datos
        elif re.match(r'^20[1-3]\d$', num.strip()):
            filtered.add(num)
        # Mantener números grandes (probablemente cantidades)
        elif re.match(r'^\d{4,}', num.strip()):
            filtered.add(num)

    return filtered


def _normalize_number_for_search(number: str) -> str:
    """
    Normaliza un número para búsqueda flexible.
    Ej: "47.5%" -> "47" (para buscar variaciones)
    """
    # Extraer solo dígitos y punto decimal
    cleaned = re.sub(r'[^\d.,]', '', number)
    # Normalizar separadores
    cleaned = cleaned.replace(',', '.')
    return cleaned


def _verify_number_in_sources(number: str, sources: List[Dict]) -> Tuple[bool, Optional[str]]:
    """
    Verifica si un número existe en alguna fuente usando búsqueda exacta y variaciones.
    NO trunca las fuentes - busca en el contenido COMPLETO.

    Args:
        number: El número a buscar (ej: "47%", "$1.5B")
        sources: Lista de fuentes con 'raw_content' o 'snippet'

    Returns:
        Tuple (encontrado: bool, url_fuente: str o None)
    """
    num_clean = _normalize_number_for_search(number)

    # Construir patrones de variación
    patterns = [
        re.escape(number),                           # Exacto: "47%"
        rf'\b{re.escape(num_clean)}\b',              # Solo dígitos
        rf'{re.escape(num_clean)}\s*%',              # Con espacio antes de %
        rf'~\s*{re.escape(number)}',                 # Aproximado: ~47%
        rf'approximately\s+{re.escape(number)}',     # En inglés
        rf'aproximadamente\s+{re.escape(number)}',   # En español
        rf'around\s+{re.escape(number)}',            # Variación inglés
        rf'cerca\s+de\s+{re.escape(number)}',        # Variación español
        rf'about\s+{re.escape(number)}',             # Otra variación
        rf'nearly\s+{re.escape(number)}',            # Casi
        rf'casi\s+{re.escape(number)}',              # Casi español
        rf'over\s+{re.escape(number)}',              # Más de
        rf'más\s+de\s+{re.escape(number)}',          # Más de español
    ]

    # Patrones adicionales para números con variaciones de formato
    if '.' in num_clean:
        # Variación con coma como decimal
        num_comma = num_clean.replace('.', ',')
        patterns.append(rf'\b{re.escape(num_comma)}\b')

    for source in sources:
        # Usar contenido COMPLETO, no truncado
        content = source.get('raw_content', source.get('snippet', ''))
        if not content:
            continue

        for pattern in patterns:
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    return True, source.get('url', 'Unknown')
            except re.error:
                # Si el patrón es inválido, saltar
                continue

    return False, None


def _pre_verify_numbers_exact(report: str, sources: List[Dict]) -> Tuple[Set[str], Set[str], Dict[str, str]]:
    """
    Verificación PRE-LLM: busca cifras exactas en fuentes completas.

    Args:
        report: El reporte generado
        sources: Lista de fuentes COMPLETAS (sin truncar)

    Returns:
        Tuple de (cifras_verificadas, cifras_no_encontradas, mapa_cifra_a_fuente)
    """
    # 1. Extraer números del reporte
    numbers = _extract_numbers_from_report(report)

    if not numbers:
        return set(), set(), {}

    # 2. Verificar cada número
    verified = set()
    unverified = set()
    number_to_source = {}

    for num in numbers:
        found, source_url = _verify_number_in_sources(num, sources)
        if found:
            verified.add(num)
            number_to_source[num] = source_url
        else:
            unverified.add(num)

    return verified, unverified, number_to_source


# ==========================================
# SELECCIÓN INTELIGENTE DE FUENTES
# ==========================================

def _select_by_thematic_relevance(
    sources: List[Dict],
    topic: str,
    max_count: int = 40
) -> List[Dict]:
    """
    Selección inteligente de fuentes por relevancia temática.

    Prioriza fuentes que el Judge evaluó como más relevantes
    para el tema específico, no solo por score global.

    Estrategia:
    1. Usa relevance_score (específico al tema) como criterio principal
    2. Aplica boost por autenticidad y reliability
    3. Deduplica por URL normalizada
    4. Loguea diversidad de dominios resultante

    Args:
        sources: Lista de fuentes a filtrar
        topic: Tema del reporte (para logging)
        max_count: Número máximo de fuentes a retornar

    Returns:
        Lista filtrada de fuentes ordenadas por relevancia
    """
    from urllib.parse import urlparse

    def get_relevance_score(src: Dict) -> float:
        """
        Calcula score compuesto priorizando relevancia temática.

        Prioridad de scores:
        1. relevance_score (específico al tema) - peso 70%
        2. authenticity_score (credibilidad) - boost 15%
        3. reliability_score (calidad) - boost 15%
        """
        try:
            # Priorizar relevance_score sobre total_score
            relevance = float(src.get('relevance_score', 0))
            if relevance > 0:
                # Normalizar scores secundarios (0-1)
                auth = float(src.get('authenticity_score', 5)) / 10
                rel = float(src.get('reliability_score', 5)) / 10
                # Score compuesto: relevance base + boost por calidad
                return relevance * (0.7 + 0.15 * auth + 0.15 * rel)

            # Fallback a total_score si no hay relevance_score
            return float(src.get('total_score', src.get('score', 0)))
        except (ValueError, TypeError):
            return 0.0

    # 1. Ordenar todas las fuentes por relevancia temática
    sources_sorted = sorted(sources, key=get_relevance_score, reverse=True)

    # 2. Deduplicar por URL normalizada (evitar fuentes repetidas)
    seen_urls = set()
    unique_sources = []
    for src in sources_sorted:
        url = src.get('url', '')
        # Normalizar: lowercase, quitar trailing slash, quitar parámetros de query
        url_normalized = url.lower().rstrip('/').split('?')[0].split('#')[0]
        if url_normalized and url_normalized not in seen_urls:
            seen_urls.add(url_normalized)
            unique_sources.append(src)

    # 3. Tomar las top N más relevantes
    selected = unique_sources[:max_count]

    # 4. Calcular y loguear diversidad de dominios
    domains = set()
    for s in selected:
        try:
            domain = urlparse(s.get('url', '')).netloc.replace('www.', '')
            if domain:
                domains.add(domain)
        except:
            pass

    # Log informativo
    if len(unique_sources) != len(sources):
        print(f"      🔄 Deduplicadas: {len(sources)} → {len(unique_sources)} fuentes únicas")
    print(f"      📊 Selección final: {len(selected)} fuentes de {len(domains)} dominios distintos")

    # Log de top 3 fuentes seleccionadas (para debug)
    if selected:
        top_scores = [f"{get_relevance_score(s):.1f}" for s in selected[:3]]
        print(f"      🏆 Top scores: {', '.join(top_scores)}")

    return selected


def _truncate_content_for_tokens(
    report: str,
    sources: List[Dict],
    system_tokens: int,
    template_tokens: int,
    max_tokens_available: int,
    user_msg_template: str,
    topic: str,
    is_deepinfra: bool = False,
    safety_margin: float = 0.95
) -> Tuple[str, str, int]:
    """
    Trunca reporte y fuentes para que quepan dentro del límite de tokens disponible.
    Calcula tokens considerando el template completo para mayor precisión.
    
    Args:
        report: Texto del reporte a truncar
        sources: Lista de fuentes a truncar
        system_tokens: Tokens usados por el system message
        template_tokens: Tokens usados por el template (sin contenido)
        max_tokens_available: Límite máximo de tokens disponibles
        user_msg_template: Template del mensaje de usuario (para calcular tokens reales)
        topic: Tema del reporte (para el template)
        is_deepinfra: Si es True, aplica límites más conservadores
        safety_margin: Margen de seguridad (0.95 = 95% del límite)
    
    Returns:
        Tuple de (reporte_truncado, fuentes_texto, tokens_finales)
    """
    from .utils import count_tokens
    
    # Calcular tokens disponibles para contenido (reporte + fuentes)
    # Usar margen de seguridad más conservador para asegurar que quepa
    tokens_for_content = max(1000, int((max_tokens_available - system_tokens - template_tokens) * safety_margin))
    
    # Preparar fuentes inicialmente
    content_limit_per_source = 10000
    sources_text = "\n\n".join([
        f"[{i+1}] Título: {s.get('title', 'N/A')}\n"
        f"URL: {s.get('url', 'N/A')}\n"
        f"Contenido: {s.get('raw_content', s.get('snippet', 'N/A'))[:content_limit_per_source]}"
        for i, s in enumerate(sources)
    ])
    
    # Calcular tokens actuales
    sources_tokens = count_tokens(sources_text, "gpt-4")
    report_tokens = count_tokens(report, "gpt-4")
    total_content_tokens = sources_tokens + report_tokens
    
    # Verificar tokens totales con template completo
    user_msg_test = user_msg_template.format(sources_text=sources_text, report=report)
    total_tokens_test = system_tokens + count_tokens(user_msg_test, "gpt-4")
    
    # Si no excede, retornar sin cambios
    if total_tokens_test <= max_tokens_available * safety_margin:
        return report, sources_text, total_tokens_test
    
    # Calcular distribución de tokens (balanceado para DeepInfra, priorizar fuentes para otros)
    if is_deepinfra:
        # DeepInfra: 50% fuentes, 50% reporte (balanceado)
        tokens_for_sources = int(tokens_for_content * 0.5)
        tokens_for_report = tokens_for_content - tokens_for_sources
    else:
        # Otros: 60% fuentes, 40% reporte (priorizar fuentes para verificación)
        tokens_for_sources = int(tokens_for_content * 0.6)
        tokens_for_report = tokens_for_content - tokens_for_sources
    
    # Iterar hasta que los tokens finales quepan en el límite
    max_iterations = 5
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Truncar fuentes si es necesario
        if sources_tokens > tokens_for_sources:
            reduction_factor = tokens_for_sources / sources_tokens
            content_limit_per_source = max(100, int(content_limit_per_source * reduction_factor))
            sources_text = "\n\n".join([
                f"[{i+1}] Título: {s.get('title', 'N/A')}\n"
                f"URL: {s.get('url', 'N/A')}\n"
                f"Contenido: {s.get('raw_content', s.get('snippet', 'N/A'))[:content_limit_per_source]}"
                for i, s in enumerate(sources)
            ])
            sources_tokens = count_tokens(sources_text, "gpt-4")
        
        # Truncar reporte si es necesario
        if report_tokens > tokens_for_report:
            chars_per_token = len(report) / report_tokens if report_tokens > 0 else 4
            max_chars_report = int(tokens_for_report * chars_per_token)
            report = report[:max_chars_report] + "\n\n[... reporte truncado por límite de tokens ...]"
            report_tokens = count_tokens(report, "gpt-4")
        
        # Verificar tokens totales con template completo
        user_msg_test = user_msg_template.format(sources_text=sources_text, report=report)
        total_tokens_test = system_tokens + count_tokens(user_msg_test, "gpt-4")
        
        # Si ya cabe, salir
        if total_tokens_test <= max_tokens_available * safety_margin:
            break
        
        # Si aún excede, reducir más agresivamente
        if iteration < max_iterations:
            # Reducir tokens objetivo en un 10% adicional por iteración
            tokens_for_content = int(tokens_for_content * 0.9)
            tokens_for_sources = int(tokens_for_content * (0.5 if is_deepinfra else 0.6))
            tokens_for_report = tokens_for_content - tokens_for_sources
    
    return report, sources_text, total_tokens_test


def _remove_system_generated_sections(report: str) -> str:
    """
    Elimina secciones generadas por el sistema que no deben aparecer en el consolidado.
    Estas incluyen métricas de confianza, badges, y otras métricas del sistema.
    """
    import re
    
    # Patrones para secciones generadas por el sistema
    patterns_to_remove = [
        # Confidence Score badge (formato markdown blockquote) - puede estar en múltiples líneas
        r'>\s*[🟢🟡🟠🔴⚫⚪]\s*\*\*Confidence Score:.*?\*\*.*?\n(?:>.*?\n)*',
        # Confidence Score en cualquier formato (incluyendo en encabezados)
        r'Confidence Score:\s*\d+/\d+.*?\n',
        r'Confidence Score:\s*\d+/\d+.*?(?=\n|$)',
        # Métricas de fuentes (X/Y fuentes de alta fiabilidad) - puede estar en encabezados
        r'\d+/\d+\s+fuentes de alta fiabilidad.*?\n',
        r'\d+/\d+\s+sources of high reliability.*?\n',
        r'\d+/\d+\s+fuentes de alta fiabilidad.*?(?=\n|$)',
        r'\d+/\d+\s+sources of high reliability.*?(?=\n|$)',
        # Avg Reliability
        r'Avg Reliability:\s*\d+\.?\d*/10.*?\n',
        r'Average Reliability:\s*\d+\.?\d*/10.*?\n',
        r'Avg Reliability:\s*\d+\.?\d*/10.*?(?=\n|$)',
        r'Average Reliability:\s*\d+\.?\d*/10.*?(?=\n|$)',
        # Tier distribution
        r'Tier\s+\d+.*?\n',
        r'Tier\s+\d+.*?(?=\n|$)',
        # Cualquier línea que empiece con > (blockquote) que contenga métricas
        r'>\s*\*\*.*?(?:Score|Reliability|Confidence|Tier|sources|fuentes).*?\*\*.*?\n',
        # Eliminar líneas completas que contengan solo métricas o encabezados de reportes individuales
        r'^.*?(?:Confidence Score|fuentes de alta fiabilidad|sources of high reliability|Avg Reliability|Average Reliability|Tier\s+\d+|Reporte de Investigación|Research Report|Total de fuentes:|Fecha:|Total de fuentes).*?$\n?',
        r'(?i)^#\s+Reporte de Investigación.*?$\n?',
        r'(?i)^#\s+Research Report.*?$\n?',
        r'(?i)^\*\*Reporte de Investigación\*\*.*?$\n?',
        r'(?i)^\*\*Research Report\*\*.*?$\n?',
    ]
    
    cleaned_report = report
    for pattern in patterns_to_remove:
        cleaned_report = re.sub(pattern, '', cleaned_report, flags=re.IGNORECASE | re.MULTILINE)
    
    # Limpiar líneas vacías múltiples que puedan quedar
    cleaned_report = re.sub(r'\n{3,}', '\n\n', cleaned_report)
    
    return cleaned_report


async def verify_report(
    report: str, 
    sources: List[Dict],
    topic: str
) -> Tuple[str, List[Dict], int, str]:
    """
    Verifica el reporte contra las fuentes y detecta posibles alucinaciones.
    
    Args:
        report: Reporte generado a verificar
        sources: Lista de fuentes utilizadas para generar el reporte
        topic: Tema del reporte
    
    Returns:
        Tuple (reporte_original_sin_modificaciones, lista_de_issues_detectados, confidence, summary)
    """
    print(f"\n   🔍 [VERIFIER] Verificando reporte contra {len(sources)} fuente(s)...")

    if not sources:
        print(f"      ⚠️  No hay fuentes para verificar")
        return report, []

    # ==========================================
    # FASE 0: VERIFICACIÓN EXACTA DE CIFRAS (Pre-LLM)
    # ==========================================
    # Buscar cifras en fuentes COMPLETAS antes de usar LLM
    # Esto reduce significativamente los falsos positivos

    print(f"      🔢 [PRE-VERIFY] Verificación exacta de cifras...")
    verified_numbers, unverified_numbers, number_sources = _pre_verify_numbers_exact(report, sources)

    total_numbers = len(verified_numbers) + len(unverified_numbers)
    if total_numbers > 0:
        verification_rate = len(verified_numbers) / total_numbers * 100
        print(f"      ✅ Cifras verificadas exactamente: {len(verified_numbers)}/{total_numbers} ({verification_rate:.1f}%)")
        if unverified_numbers and len(unverified_numbers) <= 5:
            print(f"      ⚠️  Cifras no encontradas exactamente: {', '.join(list(unverified_numbers)[:5])}")
        elif unverified_numbers:
            print(f"      ⚠️  {len(unverified_numbers)} cifras no encontradas exactamente (se verificarán con LLM)")
    else:
        verification_rate = 100
        print(f"      ℹ️  No se detectaron cifras específicas en el reporte")

    # Si todas las cifras están verificadas, aumentar confianza base
    pre_verify_confidence_boost = 0
    if verification_rate >= 95:
        pre_verify_confidence_boost = 15  # Alto boost si casi todo verificado
        print(f"      🎯 Alta tasa de verificación exacta - aumentando confianza base")
    elif verification_rate >= 80:
        pre_verify_confidence_boost = 10
    elif verification_rate >= 60:
        pre_verify_confidence_boost = 5

    # Eliminar secciones generadas por el sistema antes de verificar
    report_for_verification = _remove_system_generated_sections(report)
    
    if report_for_verification != report:
        print(f"      ℹ️  Secciones generadas por el sistema eliminadas antes de verificar")
    
    system_msg = """Eres un Fact-Checker experto especializado en detectar alucinaciones OBVIAS del LLM.

IMPORTANTE: Las fuentes YA fueron validadas por el Judge (calidad, fiabilidad, relevancia). Tu tarea es SOLO detectar si el LLM ANALISTA inventó información que NO está en las fuentes proporcionadas.

SECCIONES GENERADAS POR EL SISTEMA (IGNORAR - NO VERIFICAR):
- Confidence Score y métricas de confianza (ej: "Confidence Score: 98/100", "X/Y fuentes de alta fiabilidad")
- Métricas de fiabilidad promedio (ej: "Avg Reliability: 9.3/10")
- Distribuciones de tier o clasificaciones de fuentes
- Cualquier badge o métrica que indique calidad de fuentes
- Estas secciones son generadas automáticamente por el sistema y NO deben ser verificadas contra las fuentes.

TAREA:
1. Lee el reporte generado cuidadosamente
2. Para CADA afirmación del reporte, BUSCA EXHAUSTIVAMENTE en TODAS las fuentes antes de marcar como problema
3. Identifica SOLO alucinaciones OBVIAS del LLM analista (información completamente inventada)
4. NO verifiques la calidad de las fuentes (ya fue hecho por el Judge)
5. Clasifica SOLO problemas realmente críticos

PROCESO DE VERIFICACIÓN (OBLIGATORIO - SEGUIR ESTOS PASOS):
1. Para cada afirmación del reporte:
   a) Busca la información EXACTA en las fuentes (frase literal)
   b) Si no encuentras la frase exacta, busca el CONCEPTO (sinónimos, términos relacionados)
   c) Si no encuentras el concepto directo, busca información IMPLÍCITA que lo respalde
   d) Si no encuentras nada relacionado, busca en TODAS las fuentes (no solo en una)
   e) SOLO marca como problema si después de buscar exhaustivamente en TODAS las fuentes, NO encuentras NADA relacionado

2. BÚSQUEDA EXHAUSTIVA:
   - Busca sinónimos y términos relacionados (ej: "crecimiento" = "aumento", "expansión", "incremento")
   - Busca variaciones de números (ej: "47%" podría estar como "47 por ciento", "cuarenta y siete por ciento", "~47%", "aproximadamente 47%")
   - Busca información en diferentes partes del contenido de cada fuente (no solo al inicio)
   - Considera que la información puede estar parafraseada o resumida
   - Considera que números pueden estar redondeados (ej: "47%" vs "46.8%" o "alrededor del 47%")

INSTRUCCIONES CRÍTICAS (SER MUY CONSERVADOR - SOLO MARCAR SI ES REALMENTE OBVIO):
- NO marques como problema información que sea una inferencia razonable basada en las fuentes
- NO marques como problema redacción, reformulaciones o resúmenes que conservan el significado original
- NO marques como problema información que podría estar implícita o inferida de las fuentes
- NO marques como problema si no encuentras exactamente la frase, pero el concepto está en las fuentes
- NO marques como problema si encuentras información similar o relacionada en las fuentes
- NO marques como problema si la información está parafraseada o resumida en las fuentes
- NO marques como problema si los números están redondeados o aproximados
- SÍ marca como problema SOLO si después de buscar EXHAUSTIVAMENTE en TODAS las fuentes, es OBVIAMENTE inventado:
  * Datos numéricos específicos que NO aparecen en NINGUNA fuente después de buscar exhaustivamente (ej: "creció un 47%" cuando las fuentes dicen "creció significativamente" y no mencionan ningún porcentaje)
  * Nombres propios de empresas/personas NO mencionadas en NINGUNA fuente después de buscar exhaustivamente
  * Fechas específicas NO mencionadas en NINGUNA fuente después de buscar exhaustivamente
  * Estadísticas exactas NO encontradas en NINGUNA fuente después de buscar exhaustivamente
  * Información completamente contradictoria con las fuentes (ej: las fuentes dicen "A" y el reporte dice "no A")
- Prioriza SOLO alucinaciones de "alta severidad" (datos falsos OBVIOS, información completamente inventada)
- Cuando tengas DUDAS, NO marques como problema - es mejor no marcar que marcar incorrectamente

OUTPUT JSON (OBLIGATORIO):
{
  "issues": [
    {
      "text": "fragmento exacto del reporte problemático (máximo 100 caracteres)",
      "type": "hallucination|unverifiable|misquote|exaggeration",
      "severity": "high|medium|low",
      "suggestion": "cómo corregirlo o qué verificar",
      "source_numbers": [1, 2]  // números de fuentes donde debería estar pero no está (opcional)
    }
  ],
  "confidence": 85,  // 0-100, qué tan seguro estás de tu verificación
  "summary": "resumen breve de la verificación",
  "verified_sections": [
    "secciones o afirmaciones que SÍ pudiste verificar correctamente"
  ]
}

TIPOS DE ISSUES (USAR SOLO PARA ALUCINACIONES OBVIAS):
- "hallucination": Información completamente inventada que OBVIAMENTE no aparece en ninguna fuente (ej: número específico, nombre propio, fecha exacta NO mencionada)
- "misquote": Información que OBVIAMENTE está mal citada o contradice directamente las fuentes (ser muy estricto)
- "exaggeration": Información que OBVIAMENTE exagera o modifica datos específicos de las fuentes (ser muy estricto)

NO USAR "unverifiable" - si no puedes verificar pero es razonable, NO es un problema.

SEVERIDAD (SER MUY ESTRICTO):
- "high": SOLO para datos numéricos específicos inventados, nombres propios completamente inventados, información OBVIAMENTE falsa
- "medium": SOLO para información que OBVIAMENTE contradice las fuentes o exagera significativamente
- "low": EVITAR usar - solo si es realmente crítico

IMPORTANTE: Cuando tengas dudas, NO marques como problema. Solo marca si es OBVIAMENTE una alucinación.
"""
    
    # ============================================
    # TRUNCAMIENTO DE TOKENS INTELIGENTE (Centralizado)
    # ============================================
    
    # 1. Detectar modelo y proveedor
    model_name = None
    provider = None
    
    try:
        # Intentar obtener desde configuración TOML (prioritario)
        if USE_DEEPSEEK_FOR_TESTING:
            roles_key = "roles_test"
        elif USE_CHEAP_OPENROUTER_MODELS:
            roles_key = "roles_cheap"
        else:
            roles_key = "roles"
        
        roles_config = TOML_CONFIG.get(roles_key, {})
        judge_config = roles_config.get("judge", {})
        model_name = judge_config.get("model")
        provider = judge_config.get("provider")
    except Exception:
        pass
    
    # Fallbacks de detección
    if not model_name:
        try:
             # Desde instancia
            if hasattr(llm_judge, 'model_name'):
                model_name = llm_judge.model_name
            elif hasattr(llm_judge, 'model'):
                model_name = llm_judge.model
            elif hasattr(llm_judge, '_default_params') and 'model' in llm_judge._default_params:
                model_name = llm_judge._default_params['model']
        except:
            pass

    # 2. Obtener límites centralizados
    max_tokens_model, max_tokens_available = get_model_limits(model_name, provider)
    
    print(f"      🔍 Modelo detectado: {model_name or 'desconocido'}")
    print(f"      📊 Límite de tokens del modelo: {max_tokens_model:,}")
    print(f"      📊 Tokens disponibles (input): {max_tokens_available:,}")
    
    # Calcular tokens del system message
    system_tokens = count_tokens(system_msg, "gpt-4")
    
    # Usar report_for_verification para el truncamiento (versión sin secciones del sistema)
    report = report_for_verification
    
    # LIMITAR FUENTES: Si hay demasiadas fuentes, seleccionar por relevancia temática
    # Prioriza relevance_score (específico al tema) sobre total_score genérico
    MAX_SOURCES_FOR_VERIFIER = 40
    if len(sources) > MAX_SOURCES_FOR_VERIFIER:
        print(f"      📋 Optimizando {len(sources)} fuentes → {MAX_SOURCES_FOR_VERIFIER} por relevancia temática")
        sources = _select_by_thematic_relevance(sources, topic, MAX_SOURCES_FOR_VERIFIER)
    
    # Preparar las fuentes con raw_content si está disponible
    # Ajustar límite dinámicamente según el tamaño del reporte
    content_limit_per_source = 8000
    sources_text = "\n\n".join([
        f"[{i+1}] Título: {s.get('title', 'N/A')}\n"
        f"URL: {s.get('url', 'N/A')}\n"
        f"Contenido: {s.get('raw_content', s.get('snippet', 'N/A'))[:content_limit_per_source]}"
        for i, s in enumerate(sources)
    ])
    
    # Calcular tokens aproximados del prompt completo
    user_msg_template = f"""TEMA DEL REPORTE: {topic}

FUENTES DISPONIBLES (Total: {len(sources)}):
{{sources_text}}

---
REPORTE A VERIFICAR:
{{report}}
---

INSTRUCCIONES DE VERIFICACIÓN:
1. Para CADA afirmación del reporte, busca EXHAUSTIVAMENTE en TODAS las fuentes antes de decidir si es una alucinación
2. Busca no solo la frase exacta, sino también:
   - Conceptos equivalentes (sinónimos, términos relacionados)
   - Variaciones de números (redondeos, aproximaciones)
   - Información parafraseada o resumida
   - Información implícita que respalde la afirmación
3. SOLO marca como problema si después de buscar en TODAS las fuentes, NO encuentras NADA relacionado
4. Si encuentras información relacionada (aunque no sea exacta), NO marques como problema
5. Cuando tengas dudas, NO marques como problema - es mejor ser conservador

Analiza el reporte línea por línea y verifica cada afirmación importante contra las fuentes.
Responde SOLO con un JSON válido según el formato especificado."""
    
    # Calcular tokens aproximados
    template_tokens = count_tokens(user_msg_template.format(sources_text="", report=""), "gpt-4")
    sources_tokens = count_tokens(sources_text, "gpt-4")
    report_tokens = count_tokens(report, "gpt-4")
    total_tokens_estimated = system_tokens + template_tokens + sources_tokens + report_tokens
    
    print(f"      📊 Estimación de tokens: {total_tokens_estimated:,} (límite: {max_tokens_model:,})")
    
    # Para DeepInfra, usar un límite más restrictivo desde el principio
    # DeepInfra tiene límite de 32,768 tokens (prompt + respuesta), así que ser conservador
    is_deepinfra = provider == "openrouter" and ("deepseek" in (model_name or "").lower() or "mimo" in (model_name or "").lower())
    
    if is_deepinfra:
        # DeepInfra: usar 70% del límite total para el prompt (conservador pero razonable)
        MAX_PROMPT_TOKENS_DEEPINFRA = int(max_tokens_model * 0.70)
        print(f"      ⚠️  DeepInfra detectado: aplicando límite restrictivo de {MAX_PROMPT_TOKENS_DEEPINFRA:,} tokens para el prompt")
        # Ajustar MAX_TOKENS_AVAILABLE para DeepInfra desde el principio
        max_tokens_available = MAX_PROMPT_TOKENS_DEEPINFRA - system_tokens - template_tokens
        if max_tokens_available < 1000:
            max_tokens_available = 1000  # Mínimo absoluto
        print(f"      📊 Tokens disponibles ajustados para DeepInfra: {max_tokens_available:,}")
    
    # Truncar contenido una sola vez usando función consolidada
    if total_tokens_estimated > max_tokens_available:
        print(f"      ⚠️  El prompt excede el límite. Truncando contenido...")
        print(f"      📊 Tokens estimados: {total_tokens_estimated:,} (límite: {max_tokens_available:,})")
        
        # Usar función consolidada para truncar (con margen de seguridad del 95%)
        report, sources_text, final_tokens = _truncate_content_for_tokens(
            report=report,
            sources=sources,
            system_tokens=system_tokens,
            template_tokens=template_tokens,
            max_tokens_available=max_tokens_available,
            user_msg_template=user_msg_template,
            topic=topic,
            is_deepinfra=is_deepinfra,
            safety_margin=0.95
        )
        
        print(f"      ✅ Truncamiento completado: {final_tokens:,} tokens finales")
    else:
        # No necesita truncamiento, calcular tokens finales
        user_msg = user_msg_template.format(sources_text=sources_text, report=report)
        final_tokens = system_tokens + count_tokens(user_msg, "gpt-4")
    
    # Construir user_msg final
    user_msg = user_msg_template.format(sources_text=sources_text, report=report)
    
    # Verificación final: asegurar que no exceda el límite
    if final_tokens > max_tokens_available:
        print(f"      ⚠️  ADVERTENCIA: Tokens finales ({final_tokens:,}) aún exceden el límite disponible ({max_tokens_available:,})")
        print(f"      🔧 Aplicando truncamiento adicional con margen más conservador...")
        
        # Aplicar truncamiento adicional con margen más conservador (85% en lugar de 95%)
        report, sources_text, final_tokens = _truncate_content_for_tokens(
            report=report,
            sources=sources,
            system_tokens=system_tokens,
            template_tokens=template_tokens,
            max_tokens_available=max_tokens_available,
            user_msg_template=user_msg_template,
            topic=topic,
            is_deepinfra=is_deepinfra,
            safety_margin=0.85
        )
        
        # Reconstruir user_msg
        user_msg = user_msg_template.format(sources_text=sources_text, report=report)
        final_tokens = system_tokens + count_tokens(user_msg, "gpt-4")
        print(f"      ✅ Tokens finales después de truncamiento adicional: {final_tokens:,} (límite: {max_tokens_available:,})")
    
    print(f"      ✅ Tokens finales: {final_tokens:,} (límite disponible: {max_tokens_available:,}, límite modelo: {max_tokens_model:,})")
    
    # Verificación final para DeepInfra: asegurar que no exceda el límite absoluto
    if is_deepinfra and final_tokens > max_tokens_model:
        error_msg = f"❌ ERROR CRÍTICO: No se puede reducir el prompt a menos de {max_tokens_model:,} tokens (actual: {final_tokens:,}). El reporte o las fuentes son demasiado grandes para DeepInfra."
        print(f"      {error_msg}")
        raise ValueError(error_msg)
    
    try:
        print(f"      📊 Enviando reporte para verificación ({len(report)} caracteres, {len(sources)} fuentes)...")
        response = await llm_judge.ainvoke(
            [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]
        )
        
        response_text = response.content if hasattr(response, "content") else str(response)
        
        # Intentar parsear JSON (podría estar envuelto en markdown code blocks)
        verification_result = _parse_json_response(response_text)
        
        if not verification_result:
            print(f"      ⚠️  No se pudo parsear la respuesta del verificador")
            return report, []
        
        issues = verification_result.get("issues", [])
        confidence = verification_result.get("confidence", 0)
        summary = verification_result.get("summary", "Verificación completada")

        # Aplicar boost de confianza por verificación exacta de cifras
        if pre_verify_confidence_boost > 0:
            confidence = min(100, confidence + pre_verify_confidence_boost)

        # Filtrar falsos positivos: si una cifra marcada como issue fue verificada exactamente, eliminarla
        if verified_numbers and issues:
            filtered_issues = []
            for issue in issues:
                issue_text = issue.get('text', '')
                # Verificar si alguna cifra verificada aparece en el texto del issue
                is_false_positive = False
                for verified_num in verified_numbers:
                    if verified_num in issue_text:
                        print(f"      🔧 Filtrando falso positivo: '{issue_text[:50]}...' (cifra {verified_num} verificada en fuentes)")
                        is_false_positive = True
                        break
                if not is_false_positive:
                    filtered_issues.append(issue)

            if len(filtered_issues) < len(issues):
                print(f"      ✅ Filtrados {len(issues) - len(filtered_issues)} falsos positivos por verificación exacta")
                issues = filtered_issues

        print(f"      ✅ Verificación completada:")
        print(f"         - Issues detectados: {len(issues)}")
        print(f"         - Confianza: {confidence}%")
        print(f"         - Resumen: {summary}")
        
        if issues:
            print(f"      ⚠️  Issues encontrados:")
            for i, issue in enumerate(issues[:5], 1):  # Mostrar solo los primeros 5
                print(f"         {i}. [{issue.get('severity', 'unknown').upper()}] {issue.get('type', 'unknown')}: {issue.get('text', '')[:60]}...")
            if len(issues) > 5:
                print(f"         ... y {len(issues) - 5} más")

        # Enriquecer summary con información de verificación exacta
        if total_numbers > 0:
            summary = f"{summary} | Verificación exacta de cifras: {len(verified_numbers)}/{total_numbers} ({verification_rate:.0f}%)"

        # NO anotar el reporte con los issues encontrados - el informe final no debe contener información de verificación
        # Retornar el reporte original sin modificaciones, issues, confidence y summary
        return report, issues, confidence, summary
        
    except Exception as e:
        print(f"      ❌ Error durante la verificación: {e}")
        import traceback
        traceback.print_exc()
        return report, [], 0, "Error durante la verificación"


def _parse_json_response(response_text: str) -> Optional[Dict]:
    """
    Intenta extraer JSON de la respuesta, incluso si está envuelto en markdown code blocks.
    Maneja JSON incompleto o truncado de forma más robusta.
    """
    import re
    
    # Intentar extraer JSON de code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Buscar JSON directamente en la respuesta
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response_text.strip()
    
    # Intentar parsear JSON
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Si falla, intentar reparar JSON truncado o mal formado
        try:
            # Intentar encontrar el JSON válido más largo posible
            # Buscar desde el inicio hasta encontrar un objeto JSON válido
            for i in range(len(json_str), 0, -100):
                truncated = json_str[:i]
                # Intentar cerrar objetos/arrays abiertos
                open_braces = truncated.count('{') - truncated.count('}')
                open_brackets = truncated.count('[') - truncated.count(']')
                
                # Cerrar estructuras abiertas
                if open_braces > 0 or open_brackets > 0:
                    truncated += '}' * open_braces + ']' * open_brackets
                
                try:
                    return json.loads(truncated)
                except json.JSONDecodeError:
                    continue
        except:
            pass
        
        # Si todo falla, intentar extraer solo el objeto issues si existe
        try:
            # Buscar el array "issues" dentro del JSON
            issues_match = re.search(r'"issues"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
            if issues_match:
                # Construir un JSON mínimo con solo issues
                issues_content = issues_match.group(1)
                # Intentar extraer objetos individuales del array
                issue_objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', issues_content)
                if issue_objects:
                    # Construir JSON mínimo válido
                    minimal_json = {
                        "issues": [],
                        "confidence": 50,
                        "summary": "Verificación completada (JSON reparado)",
                        "verified_sections": []
                    }
                    # Intentar parsear cada issue individualmente
                    for issue_str in issue_objects:
                        try:
                            issue_obj = json.loads(issue_str)
                            minimal_json["issues"].append(issue_obj)
                        except:
                            pass
                    
                    if minimal_json["issues"]:
                        print(f"      ⚠️  JSON reparado parcialmente: {len(minimal_json['issues'])} issues extraídos")
                        return minimal_json
        except:
            pass
        
        print(f"      ⚠️  Error parseando JSON: {e}")
        print(f"      Posición del error: línea {e.lineno}, columna {e.colno}")
        print(f"      JSON recibido (primeros 1000 chars): {json_str[:1000]}...")
        if len(json_str) > 1000:
            print(f"      JSON recibido (últimos 500 chars): ...{json_str[-500:]}")
        return None


def _annotate_report(report: str, issues: List[Dict]) -> str:
    """
    Anota el reporte con los issues encontrados.
    Si hay issues de alta severidad, los marca en el texto.
    """
    if not issues:
        return report
    
    # Solo anotar issues de alta severidad para no saturar el reporte
    high_severity_issues = [issue for issue in issues if issue.get("severity") == "high"]
    
    if not high_severity_issues:
        return report
    
    annotated = report
    for issue in high_severity_issues:
        text_fragment = issue.get("text", "")
        if text_fragment and len(text_fragment) > 10:
            # Buscar el fragmento en el reporte (búsqueda flexible)
            import re
            # Escapar caracteres especiales para regex
            escaped_fragment = re.escape(text_fragment)
            # Buscar con flexibilidad (puede tener espacios/formatos diferentes)
            pattern = re.escape(text_fragment[:50])  # Usar solo los primeros 50 chars para hacer match más flexible
            
            if re.search(pattern, annotated, re.IGNORECASE):
                # Agregar nota al final del párrafo más cercano
                suggestion = issue.get("suggestion", "")
                annotation = f"\n\n[⚠️ VERIFICACIÓN: {issue.get('type', 'issue').upper()} - {suggestion}]"
                # Insertar después del párrafo (buscar punto final más cercano)
                match = re.search(pattern, annotated, re.IGNORECASE)
                if match:
                    end_pos = match.end()
                    # Buscar el siguiente punto o salto de línea
                    next_period = annotated.find('.', end_pos)
                    next_newline = annotated.find('\n', end_pos)
                    insert_pos = min(
                        next_period + 1 if next_period > 0 else len(annotated),
                        next_newline if next_newline > 0 else len(annotated),
                        len(annotated)
                    )
                    annotated = annotated[:insert_pos] + annotation + annotated[insert_pos:]
    
    return annotated


def format_verification_summary(issues: List[Dict], confidence: int, summary: str) -> str:
    """
    Formatea un resumen legible de la verificación.
    
    Args:
        issues: Lista de issues detectados
        confidence: Nivel de confianza (0-100)
        summary: Resumen textual
    
    Returns:
        Resumen formateado en Markdown
    """
    if not issues:
        return f"## ✅ Verificación Completada\n\n**Confianza:** {confidence}%\n\n{summary}\n\n✅ No se detectaron problemas."
    
    md = f"## ⚠️ Verificación Completada\n\n"
    md += f"**Confianza:** {confidence}%\n\n"
    md += f"**Resumen:** {summary}\n\n"
    md += f"**Total de issues detectados:** {len(issues)}\n\n"
    
    # Agrupar por severidad
    by_severity = {"high": [], "medium": [], "low": []}
    for issue in issues:
        severity = issue.get("severity", "low")
        by_severity[severity].append(issue)
    
    for severity in ["high", "medium", "low"]:
        issues_list = by_severity[severity]
        if issues_list:
            emoji = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🟢"
            md += f"### {emoji} {severity.upper()} ({len(issues_list)})\n\n"
            for i, issue in enumerate(issues_list, 1):
                md += f"{i}. **{issue.get('type', 'unknown').upper()}:** {issue.get('text', '')[:100]}\n"
                md += f"   💡 *Sugerencia:* {issue.get('suggestion', 'N/A')}\n\n"
    
    return md


def generate_verification_report(
    issues: List[Dict],
    confidence: int,
    summary: str,
    topic: str,
    sources_count: int,
    references_validation: Optional[Dict] = None
) -> str:
    """
    Genera un informe completo de verificación en formato Markdown.
    
    Args:
        issues: Lista de issues detectados
        confidence: Nivel de confianza (0-100)
        summary: Resumen textual
        topic: Tema del reporte verificado
        sources_count: Número de fuentes verificadas
        references_validation: Resultados de validación de referencias (opcional)
    
    Returns:
        Informe completo en formato Markdown
    """
    from datetime import datetime
    
    report = f"""# Informe de Verificación

**Tema:** {topic}
**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Fuentes verificadas:** {sources_count}

---

## Resumen Ejecutivo

**Confianza de verificación:** {confidence}%
**Estado general:** {'✅ Verificación exitosa' if not issues else '⚠️ Problemas detectados'}

{summary}

---

## Resultados de Verificación

"""
    
    if not issues:
        report += "### ✅ No se detectaron problemas\n\n"
        report += "El reporte ha sido verificado contra las fuentes y no se encontraron alucinaciones obvias.\n\n"
    else:
        report += f"### ⚠️ Problemas Detectados: {len(issues)}\n\n"
        
        # Agrupar por severidad
        by_severity = {"high": [], "medium": [], "low": []}
        for issue in issues:
            severity = issue.get("severity", "low")
            by_severity[severity].append(issue)
        
        # Contar por severidad
        high_count = len(by_severity["high"])
        medium_count = len(by_severity["medium"])
        low_count = len(by_severity["low"])
        
        report += f"- **Alta severidad:** {high_count}\n"
        report += f"- **Media severidad:** {medium_count}\n"
        report += f"- **Baja severidad:** {low_count}\n\n"
        
        # Detalles por severidad
        for severity in ["high", "medium", "low"]:
            issues_list = by_severity[severity]
            if issues_list:
                emoji = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🟢"
                report += f"### {emoji} Problemas de Severidad {severity.upper()} ({len(issues_list)})\n\n"
                
                for i, issue in enumerate(issues_list, 1):
                    issue_type = issue.get('type', 'unknown').upper()
                    issue_text = issue.get('text', 'N/A')
                    suggestion = issue.get('suggestion', 'N/A')
                    source_numbers = issue.get('source_numbers', [])
                    
                    report += f"#### Problema {i}: {issue_type}\n\n"
                    report += f"**Texto problemático:**\n> {issue_text}\n\n"
                    
                    if source_numbers:
                        report += f"**Fuentes donde debería estar:** {', '.join(map(str, source_numbers))}\n\n"
                    
                    report += f"**Sugerencia:** {suggestion}\n\n"
                    report += "---\n\n"
    
    # Añadir información de validación de referencias si está disponible
    if references_validation:
        report += "## Validación de Referencias\n\n"
        passed = references_validation.get('passed', False)
        report += f"**Estado:** {'✅ Pasada' if passed else '❌ Fallida'}\n\n"
        
        ref_issues = references_validation.get('issues', [])
        if ref_issues:
            report += "**Problemas encontrados:**\n\n"
            for i, issue in enumerate(ref_issues[:10], 1):  # Limitar a 10
                report += f"{i}. {issue}\n"
            if len(ref_issues) > 10:
                report += f"\n... y {len(ref_issues) - 10} más\n"
        report += "\n"
    
    report += f"""
---

## Metadatos

- **Confianza de verificación:** {confidence}%
- **Total de issues:** {len(issues)}
- **Fuentes verificadas:** {sources_count}
- **Fecha de verificación:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
*Este informe fue generado automáticamente por el sistema de verificación de reportes.*
"""
    
    return report


def save_verification_report(
    verification_report: str,
    topic: str,
    record_id: Optional[str] = None
) -> str:
    """
    Guarda el informe de verificación en un archivo separado.
    
    Args:
        verification_report: Contenido del informe en Markdown
        topic: Tema del reporte
        record_id: ID del registro (opcional, para incluir en el nombre del archivo)
    
    Returns:
        Ruta del archivo guardado
    """
    import os
    import re
    from pathlib import Path
    from datetime import datetime
    
    # Crear carpeta reports/ si no existe
    project_root = Path(__file__).parent.parent
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    # Crear nombre de archivo seguro desde el topic
    safe_topic = re.sub(r'[^\w\s-]', '', topic)
    safe_topic = re.sub(r'[-\s]+', '_', safe_topic)
    safe_topic = safe_topic[:50]  # Limitar longitud
    
    if not safe_topic:
        safe_topic = "verificacion"
    
    # Añadir record_id si está disponible
    if record_id:
        safe_topic = f"{safe_topic}_{record_id[:20]}"
    
    # Crear nombre de archivo con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"verificacion_{safe_topic}_{timestamp}.md"
    report_path = reports_dir / filename
    
    # Guardar archivo
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(verification_report)
        
        logger.log_success(f"📋 Informe de verificación guardado en: {report_path}")
        return str(report_path)
    except Exception as e:
        logger.log_error(f"❌ Error guardando informe de verificación: {e}")
        import traceback
        traceback.print_exc()
        return ""
