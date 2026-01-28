"""
Módulo Extractor: Procesa resultados de búsqueda para extraer hechos y citas literales.
Reduce el ruido antes de la evaluación y redacción final.
"""
import json
import re
import asyncio
from typing import List, Dict, Any, Optional
from .config import llm_planner, llm_mimo_cheap  # Usa MiMo para extracción económica
from .logger import logger

# Flag global para deshabilitar extractor si hay demasiados rate limits
_extractor_rate_limited = False

# Semáforo se crea dinámicamente dentro de la función para evitar problemas de event loop
_extractor_semaphore = None


def _get_extractor_semaphore():
    """
    Obtiene o crea el semáforo del extractor en el event loop actual.
    Evita problemas de "attached to a different loop" creando el semáforo cuando se necesita.
    """
    global _extractor_semaphore
    try:
        loop = asyncio.get_running_loop()
        # Si el semáforo existe y está en el loop correcto, usarlo
        if _extractor_semaphore is not None:
            return _extractor_semaphore
        # Crear nuevo semáforo en el loop actual (concurrencia: 3 para más velocidad)
        _extractor_semaphore = asyncio.Semaphore(3)
        return _extractor_semaphore
    except RuntimeError:
        # No hay loop corriendo, crear uno nuevo (no debería pasar en uso normal)
        _extractor_semaphore = asyncio.Semaphore(3)
        return _extractor_semaphore


async def extract_evidence_package(topic: str, search_results: List[Dict]) -> List[Dict]:
    """
    Procesa resultados de búsqueda para extraer hechos y citas literales.
    Reduce el ruido antes de la evaluación y redacción final.

    Args:
        topic: Tema del reporte
        search_results: Lista de resultados de búsqueda brutos

    Returns:
        Lista de fuentes enriquecidas con evidence_points
    """
    global _extractor_rate_limited
    
    # Si el extractor está deshabilitado por rate limiting, saltar completamente
    if _extractor_rate_limited:
        logger.log_warning("⚠️  Extractor deshabilitado por rate limiting persistente. Saltando extracción.")
        return search_results  # Devolver fuentes originales sin procesar
    
    if not search_results:
        return []

    logger.log_phase("EXTRACTOR", f"Extrayendo evidencias de {len(search_results)} fuente(s)...")

    # Agrupamos por fuente para procesar con concurrencia limitada
    # Usar semáforo para evitar rate limiting masivo (máximo 3 simultáneas)
    tasks = []
    for source in search_results:
        tasks.append(_process_single_source_with_semaphore(topic, source))

    # Ejecución concurrente limitada para evitar rate limiting
    try:
        evidence_packs = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtrar errores y None, mantener fuentes originales si falla la extracción
        enriched_sources = []
        for i, pack in enumerate(evidence_packs):
            if isinstance(pack, Exception):
                logger.log_warning(f"      ⚠️  Error extrayendo evidencias de fuente {i+1}: {pack}")
                # Mantener la fuente original sin evidencias
                enriched_sources.append(search_results[i])
            elif pack:
                enriched_sources.append(pack)
            else:
                # Si no hay evidencias pero no hay error, mantener la fuente original
                enriched_sources.append(search_results[i])

        extracted_count = sum(1 for s in enriched_sources if s.get('extracted', False))
        logger.log_info(f"      ✅ Evidencias extraídas de {extracted_count}/{len(enriched_sources)} fuente(s)")

        return enriched_sources

    except Exception as e:
        logger.log_error(f"Error durante extracción de evidencias: {e}")
        # Si falla completamente, devolver fuentes originales
        return search_results


async def _process_single_source_with_semaphore(topic: str, source: Dict) -> Optional[Dict]:
    """
    Wrapper que usa semáforo para limitar concurrencia y agrega delay entre llamadas.
    """
    global _extractor_rate_limited
    
    # Si está deshabilitado, retornar None inmediatamente
    if _extractor_rate_limited:
        return None
    
    # Obtener semáforo del event loop actual
    semaphore = _get_extractor_semaphore()
    
    async with semaphore:
        # Delay reducido entre llamadas (0.3s es suficiente para evitar rate limiting con concurrencia 3)
        await asyncio.sleep(0.3)  # 0.3 segundos entre cada extracción (reducido de 1.0s)
        result = await _process_single_source(topic, source)
        return result


async def _process_single_source(topic: str, source: Dict) -> Optional[Dict]:
    """
    Procesa una fuente individual usando LLM para extraer evidencias.

    Args:
        topic: Tema del reporte
        source: Diccionario con información de la fuente (url, snippet, raw_content, etc.)

    Returns:
        Fuente enriquecida con evidence_points o None si no hay información útil
    """
    # Obtener contenido priorizando raw_content
    content = source.get('raw_content') or source.get('snippet', '')
    if not content or len(content.strip()) < 50:  # Muy poco contenido, saltar
        return None

    url = source.get('url', 'N/A')
    title = source.get('title', 'Sin título')

    system_msg = f"""Eres un Analista de Extracción de Datos de Precisión. 
Tu misión es transformar texto bruto en un 'Evidence Pack' libre de ruido.
TEMA: {topic}

REGLAS:
1. Extrae solo hechos atómicos y citas textuales exactas relacionadas con el tema.
2. Ignora publicidad, menús de navegación, avisos legales y contenido irrelevante.
3. Si no hay información útil sobre el tema, devuelve un JSON vacío con "evidence_points": [].
4. Cada evidencia debe ser verificable y citable directamente.
5. Las citas deben ser textuales (exactas) o parafraseadas con precisión.

CATEGORÍAS sugeridas (puedes usar otras si es apropiado):
- "data": Datos numéricos, estadísticas, métricas
- "quote": Citas directas de personas o documentos
- "fact": Hechos objetivos verificables
- "claim": Afirmaciones o declaraciones de organizaciones
- "date": Información temporal relevante

OUTPUT JSON (OBLIGATORIO):
{{
  "evidence_points": [
    {{
      "fact": "descripción breve del hecho o información clave",
      "exact_quote": "cita textual exacta o parafraseo preciso",
      "category": "data|quote|fact|claim|date"
    }}
  ]
}}

Si no encuentras información útil, responde con:
{{
  "evidence_points": []
}}"""

    # Aumentar límite de contenido para extraer más evidencias de calidad
    # Usar hasta 10,000 caracteres para documentos largos (mejora calidad de insights)
    content_limit = 10000
    content_truncated = content[:content_limit] if len(content) > content_limit else content
    
    user_msg = f"""FUENTE: {url}
TÍTULO: {title}

CONTENIDO:
{content_truncated}

Extrae las evidencias en el formato JSON especificado. Si no hay información útil sobre "{topic}", devuelve un JSON con "evidence_points": []."""

    try:
        # Usamos llm_mimo_cheap (MiMo free/regular) para extracción de claims (tarea económica)
        # Si no está disponible, usar llm_planner como fallback
        llm_extractor = llm_mimo_cheap if llm_mimo_cheap else llm_planner
        
        # Manejo de rate limiting con reintentos
        max_retries = 3
        response = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await llm_extractor.ainvoke([
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ])
                break  # Éxito, salir del loop
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                
                # Detectar error 429 (rate limit) y reintentar
                is_rate_limit = "429" in error_str or "rate limit" in error_str or "rate-limited" in error_str
                
                if is_rate_limit and attempt < max_retries - 1:
                    # Reintentar con backoff exponencial
                    wait_time = (2 ** attempt) * 2  # 2, 4, 8 segundos
                    logger.log_warning(f"      ⚠️  Rate limit en extractor (intento {attempt + 1}/{max_retries}). Esperando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                elif attempt == max_retries - 1:
                    # Último intento fallido - no reintentar más, retornar None
                    global _extractor_rate_limited
                    
                    if is_rate_limit:
                        logger.log_warning(f"      ⚠️  Rate limit persistente después de {max_retries} intentos. Saltando extracción para esta fuente.")
                        # Si hay múltiples rate limits, deshabilitar extractor completamente
                        _extractor_rate_limited = True
                        logger.log_warning(f"      ⚠️  DESHABILITANDO extractor para el resto de la ejecución por rate limiting persistente.")
                    else:
                        logger.log_warning(f"      ⚠️  Error en extractor después de {max_retries} intentos: {error_str[:100]}...")
                    # No hacer raise, simplemente retornar None para continuar con el resto de las fuentes
                    response = None
                    break
                else:
                    # Otro tipo de error en intentos intermedios - reintentar
                    logger.log_warning(f"      ⚠️  Error en extractor (intento {attempt + 1}/{max_retries}): {error_str[:100]}...")
                    wait_time = (2 ** attempt) * 2
                    await asyncio.sleep(wait_time)
                    continue
        
        if response is None:
            return None

        content_text = response.content.strip() if hasattr(response, "content") else str(response).strip()

        # Limpieza de markdown si el modelo lo incluye
        if "```json" in content_text:
            content_text = content_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in content_text:
            # Buscar cualquier bloque de código
            parts = content_text.split("```")
            if len(parts) >= 3:
                content_text = parts[1].strip()
                if content_text.startswith("json"):
                    content_text = content_text[4:].strip()

        # Intentar parsear JSON con manejo robusto de errores
        data = None
        try:
            data = json.loads(content_text)
        except json.JSONDecodeError as json_err:
            # Intentar reparar JSON mal formado o extraer parte válida
            try:
                # Estrategia 1: Buscar el primer objeto JSON completo (entre {})
                json_start = content_text.find('{')
                if json_start != -1:
                    # Intentar encontrar el cierre correspondiente
                    brace_count = 0
                    json_end = -1
                    for i in range(json_start, len(content_text)):
                        if content_text[i] == '{':
                            brace_count += 1
                        elif content_text[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = i + 1
                                break
                    
                    if json_end > json_start:
                        # Extraer el JSON completo
                        json_substring = content_text[json_start:json_end]
                        
                        # Intentar reparar problemas comunes de JSON
                        # 1. Comillas simples en lugar de dobles
                        json_substring = json_substring.replace("'", '"')
                        # 2. Comas finales antes de }
                        json_substring = re.sub(r',\s*}', '}', json_substring)
                        json_substring = re.sub(r',\s*]', ']', json_substring)
                        # 3. Strings sin cerrar (heurística simple)
                        # Contar comillas dobles - si es impar, añadir una al final del último string
                        
                        try:
                            data = json.loads(json_substring)
                        except json.JSONDecodeError as inner_err:
                            # Estrategia 2: Intentar extraer evidence_points parcialmente usando regex
                            evidence_pattern = r'"evidence_points"\s*:\s*\[(.*?)\]'
                            match = re.search(evidence_pattern, json_substring, re.DOTALL)
                            if match:
                                evidence_content = match.group(1).strip()
                                if evidence_content:
                                    # Intentar parsear items individuales
                                    evidence_items = []
                                    # Buscar objetos individuales dentro del array
                                    item_pattern = r'\{[^{}]*\}'
                                    for item_match in re.finditer(item_pattern, evidence_content):
                                        try:
                                            item_json = item_match.group(0)
                                            # Reparar comillas simples
                                            item_json = item_json.replace("'", '"')
                                            item = json.loads(item_json)
                                            evidence_items.append(item)
                                        except:
                                            continue
                                    
                                    if evidence_items:
                                        data = {"evidence_points": evidence_items}
                                        logger.log_info(f"      ✅ Extraídos {len(evidence_items)} evidence_points parcialmente del JSON corrupto")
                                    else:
                                        # No se pudieron extraer items, usar vacío
                                        logger.log_warning(f"      ⚠️  JSON corrupto: se encontró 'evidence_points' pero no se pudieron extraer items. Usando fallback vacío.")
                                        data = {"evidence_points": []}
                                else:
                                    # Array vacío encontrado
                                    data = {"evidence_points": []}
                            else:
                                # No se encontró evidence_points, usar fallback
                                if '"evidence_points"' in content_text or "'evidence_points'" in content_text:
                                    logger.log_warning(f"      ⚠️  JSON corrupto, usando fallback: evidence_points vacío")
                                    data = {"evidence_points": []}
                                else:
                                    raise inner_err
                    else:
                        # No se pudo encontrar el cierre, intentar extraer parcialmente
                        if '"evidence_points"' in content_text or "'evidence_points'" in content_text:
                            logger.log_warning(f"      ⚠️  JSON corrupto (sin cierre), usando fallback: evidence_points vacío")
                            data = {"evidence_points": []}
                        else:
                            raise
                else:
                    # No hay {, usar fallback
                    if '"evidence_points"' in content_text or "'evidence_points'" in content_text:
                        logger.log_warning(f"      ⚠️  JSON corrupto (sin objeto), usando fallback: evidence_points vacío")
                        data = {"evidence_points": []}
                    else:
                        raise
            except Exception as repair_err:
                # Si todo falla, usar JSON vacío como fallback
                logger.log_warning(f"      ⚠️  No se pudo reparar JSON mal formado de fuente {url[:50]}. Error original: {json_err}. Error de reparación: {repair_err}")
                logger.log_warning(f"      📋 Primeros 200 caracteres de la respuesta: {content_text[:200]}")
                data = {"evidence_points": []}

        if data.get("evidence_points") and len(data["evidence_points"]) > 0:
            # Combinamos la info original de la fuente con las evidencias extraídas
            return {
                **source,  # Preservar todos los campos originales
                "evidence_points": data["evidence_points"],
                "extracted": True
            }
        else:
            # No hay evidencias útiles, devolver None para que se mantenga la fuente original
            return None

    except json.JSONDecodeError as e:
        logger.log_warning(f"      ⚠️  Error parseando JSON de fuente {url[:50]}: {e}")
        return None
    except Exception as e:
        logger.log_warning(f"      ⚠️  Error procesando fuente {url[:50]}: {e}")
        return None
