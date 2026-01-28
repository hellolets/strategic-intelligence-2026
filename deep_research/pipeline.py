import asyncio
from .processor import process_agent_matching, check_and_consolidate_completed_projects
from .manager import ResearchManager
from .logger import logger
from .config import CONCURRENCY_LIMIT

async def run_full_pipeline():
    """
    Ejecuta el pipeline completo de forma asíncrona:
    1. Match de Agentes (Sync -> Thread)
    2. Investigación de Items (Async)
    3. Consolidación de Proyectos (Sync -> Thread)
    """
    logger.log_section("PIPELINE", "Iniciando ejecución completa (Push/Webhook)")
    
    loop = asyncio.get_running_loop()
    
    # PASO 1: ASIGNACIÓN (Bloqueante, mover a thread)
    try:
        logger.log_info("1. Ejecutando Asignación de Agentes...")
        await loop.run_in_executor(None, process_agent_matching)
    except Exception as e:
        logger.log_error(f"Error en paso de Asignación: {e}")
        # Continuamos por si hay cosas ya asignadas
        
    # PASO 2: INVESTIGACIÓN (Nativo Async)
    try:
        logger.log_info("2. Ejecutando Investigación de Items...")
        manager = ResearchManager(concurrency_limit=CONCURRENCY_LIMIT)
        # run_once=True para que procese lo pendiente y termine, no se quede en loop infinito
        await manager.run_loop(run_once=True)
    except Exception as e:
        logger.log_error(f"Error en paso de Investigación: {e}")

    # PASO 3: CONSOLIDACIÓN (Bloqueante, mover a thread)
    try:
        logger.log_info("3. Ejecutando Consolidación de Proyectos...")
        await loop.run_in_executor(None, check_and_consolidate_completed_projects)
    except Exception as e:
        logger.log_error(f"Error en paso de Consolidación: {e}")
        
    # Limpieza final de archivos temporales
    try:
        from .utils import cleanup_temp_plots
        await loop.run_in_executor(None, cleanup_temp_plots)
    except Exception as e:
        logger.log_warning(f"Error en limpieza de archivos temporales: {e}")

    logger.log_success("Pipeline finalizado.")
