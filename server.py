import os
import time
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from deep_research.manager import ResearchManager
from deep_research.logger import logger
from deep_research.pipeline import run_full_pipeline
from deep_research.config import CONCURRENCY_LIMIT

# Modelos de datos
class ItemPayload(BaseModel):
    record_id: str

# Contexto global
manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global manager
    logger.log_section("SERVER STARTUP", "Iniciando ResearchManager para Webhooks")
    manager = ResearchManager(concurrency_limit=CONCURRENCY_LIMIT)
    yield
    # Shutdown
    logger.log_info("Apagando servidor...")

app = FastAPI(lifespan=lifespan)

# Middleware de Logging para depuración
@app.middleware("http")
async def log_requests(request, call_next):
    logger.log_info(f"Incoming Request: {request.method} {request.url}")
    response = await call_next(request)
    logger.log_info(f"Response Status: {response.status_code}")
    return response

# # Configurar CORS para permitir peticiones desde Airtable (browser)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Permitir todo
#     allow_credentials=True,
#     allow_methods=["*"],  # Permitir todos los métodos (POST, OPTIONS, etc.)
#     allow_headers=["*"],
# )

# Solo permitimos los dominios oficiales de Airtable
# Esto es parte de una buena gobernanza de datos [cite: 335]
origins = [
    "https://airtable.com",
    "https://blocks.airtable.com", # Necesario para extensiones/scripts de Airtable
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"], # Solo lo que realmente usas
    allow_headers=["X-API-Key", "Content-Type", "Authorization"], 
)

@app.get("/health")
async def health_check():
    """
    Health check endpoint para Render.com.
    Responde rápidamente para evitar que el servicio se apague por inactividad.
    """
    return {
        "status": "healthy",
        "service": "Deep Research Agent",
        "timestamp": time.time()
    }

@app.api_route("/", methods=["GET", "POST"])
async def root_handler(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Root requests.
    - GET: Health check.
    - POST: Fallback for misconfigured webhooks (triggers pipeline).
    """
    if request.method == "GET":
        return {"status": "ok", "service": "Deep Research Agent"}
    
    if request.method == "POST":
        logger.log_warning("⚠️ POST received at root (/). Triggering Pipeline as fallback.")
        background_tasks.add_task(run_full_pipeline)
        return {"status": "received", "message": "Pipeline triggered via Root Fallback"}

@app.post("/webhook/process-item")
async def process_item_webhook(payload: ItemPayload, background_tasks: BackgroundTasks):
    """
    Recibe un webhook de Airtable con un record_id.
    Responde rápido y procesa en background.
    """
    if not payload.record_id:
        raise HTTPException(status_code=400, detail="Missing record_id")
    
    logger.log_info(f"Webhook recibido para item: {payload.record_id}")
    
    # Añadir a background tasks
    if manager:
        background_tasks.add_task(manager.process_item_by_id, payload.record_id)
    else:
        logger.log_error("Manager no inicializado")
        raise HTTPException(status_code=500, detail="Server not initialized")
        
    return {"status": "received", "message": "Processing started in background"}

@app.post("/webhook/pipeline")
async def process_pipeline_webhook(background_tasks: BackgroundTasks):
    """
    Ejecuta el pipeline completo (Match -> Items -> Consolidated).
    Ideal para llamar cuando se crea un nuevo Proyecto.
    """
    logger.log_info("Webhook de Pipeline recibido.")
    background_tasks.add_task(run_full_pipeline)
    
    return {"status": "received", "message": "Full pipeline started in background"}

def start_server(host="0.0.0.0", port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_server()
