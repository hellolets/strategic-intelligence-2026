"""
Módulo Firecrawl Client: Extrae contenido limpio en Markdown desde URLs usando Firecrawl API.
"""
import aiohttp
import asyncio
from typing import Dict, Optional, Tuple
from .logger import logger


async def fetch_firecrawl_markdown(url: str, api_key: str, timeout_seconds: int = 30) -> Tuple[Optional[str], Dict]:
    """
    Extrae contenido en formato Markdown desde una URL usando Firecrawl API.
    
    Args:
        url: URL a extraer
        api_key: API key de Firecrawl
        timeout_seconds: Tiempo máximo de espera en segundos
    
    Returns:
        Tuple (markdown_text, metadata):
        - markdown_text: Contenido extraído en Markdown o None si falla
        - metadata: Diccionario con información de la extracción (status, error, etc.)
    """
    if not url or not api_key:
        return None, {"status": "error", "error": "Missing URL or API key"}
    
    base_url = "https://api.firecrawl.dev/v1/scrape"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "formats": ["markdown"]
    }
    
    metadata = {"url": url, "status": "unknown"}
    
    try:
        logger.log_info(f"🕷️  [Firecrawl] Extrayendo contenido de {url[:50]}...")
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(base_url, json=payload, headers=headers) as response:
                status_code = response.status
                
                # Verificar código de estado
                if status_code == 200:
                    try:
                        data = await response.json()
                        
                        # Firecrawl devuelve el contenido en diferentes estructuras según la versión de API
                        # v1: {"success": true, "data": {"markdown": "..."}}
                        # v0: {"markdown": "..."} o {"data": {"markdown": "..."}}
                        markdown_content = None
                        if isinstance(data, dict):
                            # Intentar diferentes posibles estructuras de respuesta
                            if "data" in data and isinstance(data["data"], dict):
                                markdown_content = data["data"].get("markdown")
                            elif "markdown" in data:
                                markdown_content = data["markdown"]
                            elif "content" in data:
                                markdown_content = data["content"]
                            
                            # Actualizar metadata con información de la respuesta
                            metadata.update({
                                "status": "success",
                                "status_code": status_code,
                                "response_keys": list(data.keys()) if isinstance(data, dict) else []
                            })
                        
                        if markdown_content:
                            logger.log_success(f"✅ [Firecrawl] Contenido extraído: {len(markdown_content)} caracteres")
                            return markdown_content, metadata
                        else:
                            logger.log_warning(f"⚠️  [Firecrawl] Respuesta sin contenido markdown para {url[:50]}")
                            metadata["status"] = "no_content"
                            metadata["error"] = "Response missing markdown content"
                            return None, metadata
                            
                    except ValueError as e:
                        # Error parseando JSON
                        logger.log_warning(f"⚠️  [Firecrawl] Error parseando JSON: {e}")
                        response_text = await response.text()
                        metadata.update({
                            "status": "json_error",
                            "error": str(e),
                            "status_code": status_code,
                            "response_preview": response_text[:200] if response_text else None
                        })
                        return None, metadata
                
                elif status_code == 429:
                    # Rate limit
                    logger.log_warning(f"⚠️  [Firecrawl] Rate limit (429) para {url[:50]}")
                    metadata.update({
                        "status": "rate_limited",
                        "status_code": 429,
                        "error": "Rate limit exceeded"
                    })
                    return None, metadata
                
                elif status_code == 402:
                    # Payment required / credits exhausted
                    logger.log_warning(f"⚠️  [Firecrawl] Créditos agotados (402) para {url[:50]}")
                    metadata.update({
                        "status": "credits_exhausted",
                        "status_code": 402,
                        "error": "Credits exhausted"
                    })
                    return None, metadata
                
                else:
                    # Otro error HTTP
                    error_msg = f"HTTP {status_code}"
                    try:
                        error_data = await response.json()
                        if isinstance(error_data, dict) and "error" in error_data:
                            error_msg = error_data["error"]
                    except:
                        pass
                    
                    logger.log_warning(f"⚠️  [Firecrawl] Error HTTP {status_code}: {error_msg}")
                    metadata.update({
                        "status": "http_error",
                        "status_code": status_code,
                        "error": error_msg
                    })
                    return None, metadata
            
    except asyncio.TimeoutError:
        logger.log_warning(f"⚠️  [Firecrawl] Timeout después de {timeout_seconds}s para {url[:50]}")
        metadata.update({
            "status": "timeout",
            "error": f"Request timeout after {timeout_seconds}s"
        })
        return None, metadata
        
    except aiohttp.ClientError as e:
        logger.log_warning(f"⚠️  [Firecrawl] Error de conexión: {str(e)[:100]}")
        metadata.update({
            "status": "connection_error",
            "error": str(e)
        })
        return None, metadata
        
    except Exception as e:
        logger.log_error(f"❌ [Firecrawl] Error inesperado: {e}")
        metadata.update({
            "status": "unknown_error",
            "error": str(e)
        })
        return None, metadata
