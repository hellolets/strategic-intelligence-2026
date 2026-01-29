"""
Deep Research Agent - Sistema de investigación autónomo integrado con Airtable
Arquitectura Híbrida: GPT-4 (lógica y búsqueda) + Gemini 2.5 Pro (síntesis masiva)

- GPT-4 Turbo: Planner (generación de estrategias de búsqueda)
- GPT-4o: Judge (evaluación y filtrado de fuentes)
- Gemini 2.5 Pro: Analyst (síntesis masiva de información con contexto grande)
- Tavily API: Motor de búsqueda especializado en investigación
- Airtable: Gestión de tareas y resultados
"""

# ==========================================
# PATCHES & WARNING FILTERS (MUST BE FIRST)
# ==========================================
import sys
import warnings

# Suppress FutureWarning from google.api_core (Python 3.9 deprecation)
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")
warnings.filterwarnings("ignore", message=".*non-supported Python version.*")

# Patch importlib.metadata for Python 3.9 compatibility
def _patch_importlib_metadata():
    try:
        import importlib.metadata as std_metadata
    except (ImportError, AttributeError):
        std_metadata = None
    try:
        import importlib_metadata as ext_metadata
    except ImportError:
        ext_metadata = None

    def packages_distributions():
        return {}

    for mod in [std_metadata, ext_metadata]:
        if mod and not hasattr(mod, "packages_distributions"):
            try:
                mod.packages_distributions = packages_distributions
            except (AttributeError, TypeError):
                pass

_patch_importlib_metadata()

# ==========================================
# STANDARD IMPORTS
# ==========================================
import atexit
import time
from datetime import datetime

from deep_research.processor import (
    process_items_queue, 
    process_project_consolidation, 
    process_agent_matching,
    process_pipeline
)
from deep_research.logger import logger
from deep_research.output_logger import setup_output_logging, restore_output

# Variable global para el logger de salida
output_tee = None
start_time = None

if __name__ == "__main__":
    # Capturar tiempo de inicio
    start_time = time.time()
    
    # Configurar logging de salida (captura todo en archivo)
    try:
        output_tee = setup_output_logging()
        # NO registrar función atexit, la llamaremos manualmente con los datos
    except Exception as e:
        print(f"⚠️ Error configurando logging de salida: {e}")
        output_tee = None
    
    # Permitir elegir qué proceso ejecutar (default: pipeline)
    mode = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else "pipeline"
    
    # Variable para almacenar costo total
    total_cost = 0.0
    
    try:
        if mode == "pipeline":
            # logger.log_info("Modo: Pipeline Automático (Match + Items + Proyectos)")
            total_cost = process_pipeline() or 0.0
        elif mode == "items":
            logger.log_info("Modo: Procesamiento de Items (Investigación Individual)")
            total_cost = process_items_queue() or 0.0
        elif mode == "proyectos":
            logger.log_info("Modo: Consolidación de Proyectos")
            process_project_consolidation()
        elif mode == "match":
            logger.log_info("Modo: Asignación Inteligente de Agentes")
            process_agent_matching()
        elif mode == 'server':
            # Modo Servidor Web (Webhooks)
            try:
                from .server import start_server
                print("\n🚀 INICIANDO MODO SERVIDOR (PUSH)...")
                start_server()
            except ImportError:
                print("❌ Error: Faltan dependencias. Ejecuta: pip install fastapi uvicorn")
        else:
            logger.log_error(f"Modo desconocido: {mode}")
            print("💡 Uso: python main.py [pipeline|items|proyectos|match|server]")
            print("   - pipeline: (DEFAULT) Ejecuta match + items + consolida proyectos completados")
            print("   - items: Procesa investigación individual (ITEMS_INDICE)")
            print("   - proyectos: Consolida reportes (PROYECTOS)")
            print("   - match: Asigna automáticamente el mejor agente a cada item")
            print("   - server: Inicia el servidor web para webhooks")
    except KeyboardInterrupt:
        logger.log_warning("Procesador detenido por el usuario.")
    except Exception as e:
        logger.log_error(f"Error fatal: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Calcular tiempo transcurrido
        elapsed_time = time.time() - start_time if start_time else 0
        
        # Asegurar que el log se cierre correctamente con resumen final
        if output_tee:
            restore_output(output_tee, elapsed_time=elapsed_time, total_cost=total_cost)