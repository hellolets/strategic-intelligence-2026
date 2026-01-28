"""
Módulo Doc Parser: Utilidades para parsear documentos (.pdf, .docx, .pptx) usando Docling.
"""
import os
import requests
import aiohttp
import asyncio
import tempfile
from typing import List, Dict, Any, Optional
# from docling.document_converter import DocumentConverter # Movido a get_converter para carga perezosa
from .logger import logger
from .utils import run_async_safely

# Instancia global del convertidor para reutilización (Carga perezosa)
_SHARED_CONVERTER = None

def get_converter():
    """Retorna una instancia compartida de DocumentConverter (Singleton)."""
    global _SHARED_CONVERTER
    if _SHARED_CONVERTER is None:
        logger.log_info("Inicializando motor de Docling (DocumentConverter)... Esta operación puede tardar unos segundos.")
        from docling.document_converter import DocumentConverter
        _SHARED_CONVERTER = DocumentConverter()
    return _SHARED_CONVERTER

def parse_attachment(file_path: str) -> str:
    """
    Parsea un archivo local usando Docling y devuelve su contenido en formato Markdown.
    """
    try:
        converter = get_converter()
        result = converter.convert(file_path)
        return result.document.export_to_markdown()
    except Exception as e:
        logger.log_error(f"Error parseando archivo con Docling ({file_path}): {e}")
        return f"[Error parseando archivo: {os.path.basename(file_path)}]"

async def process_single_attachment(attr: Dict[str, Any], temp_dir: str, index: int) -> Optional[str]:
    """
    Procesa un adjunto individual: descarga y parseo.
    Función helper para paralelización.
    """
    url = attr.get('url')
    filename = attr.get('filename', f'attachment_{index}')
    
    if not url:
        return None
        
    local_path = os.path.join(temp_dir, filename)
    
    try:
        logger.log_info(f"Descargando adjunto: {filename}...")
        # Usar aiohttp para descarga async
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                with open(local_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
        
        logger.log_info(f"Parseando adjunto con Docling: {filename}...")
        # Parseo con Docling (bloqueante, pero paralelizado mediante asyncio)
        # Usar get_running_loop() en lugar de get_event_loop() para evitar warnings
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, parse_attachment, local_path)
        
        return f"\n\n--- CONTENIDO DE ADJUNTO: {filename} ---\n\n{text}"
        
    except Exception as e:
        logger.log_error(f"Error procesando adjunto {filename}: {e}")
        return f"\n\n[Error procesando adjunto: {filename}]\n\n"


def process_airtable_attachments(attachments: List[Dict[str, Any]]) -> str:
    """
    Descarga y procesa una lista de adjuntos de Airtable (paralelizado).
    Compatible con código síncrono existente, pero usa async internamente.
    """
    if not attachments:
        return ""
    
    # Asegurar que el convertidor se inicializa una sola vez antes del bucle si hay adjuntos
    try:
        get_converter()
    except Exception as e:
        logger.log_error(f"Error crítico inicializando Docling: {e}")
        return "[Error inicializando motor de procesamiento de documentos]"

    async def process_all_attachments():
        """Función async interna para procesar todos los adjuntos en paralelo."""
        combined_text = ""
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks = [
                process_single_attachment(attr, temp_dir, i) 
                for i, attr in enumerate(attachments)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.log_error(f"Error en procesamiento paralelo: {result}")
                    combined_text += f"\n\n[Error procesando adjunto]\n\n"
                elif result:
                    combined_text += result
                    
        return combined_text

    # Ejecutar async desde función síncrona usando función compartida para evitar deadlocks
    return run_async_safely(process_all_attachments())

def load_local_context(folder_path: str) -> str:
    """
    Carga todos los archivos .txt y .md desde una carpeta local.
    No requiere Docling, solo lectura directa de archivos.
    
    Args:
        folder_path: Ruta a la carpeta que contiene los archivos de contexto
        
    Returns:
        String con todo el contenido combinado
    """
    import os
    from pathlib import Path
    
    # Resolver ruta absoluta
    if not os.path.isabs(folder_path):
        # Si es relativa, buscar desde la raíz del proyecto
        project_root = Path(__file__).parent.parent
        full_path = project_root / folder_path
    else:
        full_path = Path(folder_path)
    
    if not full_path.exists():
        logger.log_warning(f"Carpeta de contexto no encontrada: {full_path}")
        return ""
    
    if not full_path.is_dir():
        logger.log_error(f"La ruta no es una carpeta: {full_path}")
        return ""
    
    combined_text = ""
    files_loaded = 0
    
    # Buscar todos los archivos .txt y .md
    for file_path in sorted(full_path.glob("*")):
        if file_path.suffix.lower() in [".txt", ".md"]:
            try:
                logger.log_info(f"Cargando contexto local: {file_path.name}")
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                combined_text += f"\n\n--- CONTEXTO: {file_path.name} ---\n\n"
                combined_text += content
                files_loaded += 1
                
            except Exception as e:
                logger.log_error(f"Error leyendo archivo {file_path.name}: {e}")
                combined_text += f"\n\n[Error leyendo archivo: {file_path.name}]\n\n"
    
    if files_loaded > 0:
        logger.log_success(f"✅ Cargados {files_loaded} archivos de contexto local")
    else:
        logger.log_warning(f"⚠️ No se encontraron archivos .txt o .md en {full_path}")
    
    return combined_text

def get_project_context(project_id: Optional[str] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Punto de entrada unificado para obtener contexto del proyecto.
    Decide entre modo Local o Airtable según configuración en config.toml
    
    Args:
        project_id: ID del proyecto (usado en modo Airtable, opcional)
        attachments: Lista de adjuntos de Airtable (modo Airtable directo)
        
    Returns:
        String con el contexto del proyecto
    """
    from .config import CONTEXT_SOURCE, CONTEXT_LOCAL_FOLDER
    
    if CONTEXT_SOURCE == "local":
        logger.log_info("📁 Cargando contexto desde carpeta local...")
        return load_local_context(CONTEXT_LOCAL_FOLDER)
    
    elif CONTEXT_SOURCE == "airtable":
        logger.log_info("☁️ Cargando contexto desde Airtable (con Docling)...")
        if attachments:
            logger.log_info(f"📎 Procesando {len(attachments)} adjunto(s) desde Airtable...")
            result = process_airtable_attachments(attachments)
            if result and result.strip():
                logger.log_success(f"✅ Contexto procesado: {len(result)} caracteres extraídos")
            else:
                logger.log_warning("⚠️ Contexto procesado pero resultado vacío (posible error en procesamiento)")
            return result
        else:
            logger.log_warning("⚠️ Modo Airtable activado pero no se proporcionaron adjuntos (campo Context vacío)")
            return ""
    
    else:
        logger.log_error(f"CONTEXT_SOURCE no reconocido: {CONTEXT_SOURCE}. Usar 'local' o 'airtable'")
        return ""

