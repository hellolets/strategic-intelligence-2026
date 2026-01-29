"""
Módulo State: Definición del estado para LangGraph.
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator

def deduplicate_sources(current: List[Dict], new: List[Dict]) -> List[Dict]:
    """
    Reductor que combina dos listas de fuentes evitando duplicidades por URL.
    Parsea la URL canónica para asegurar que versiones similares de la misma URL
    no se acumulen repetidamente durante los reintentos del bucle de LangGraph.
    """
    if not new:
        return current
    if not current:
        return new
        
    # Usar set para búsqueda rápida de URLs ya procesadas
    # Nota: No importamos canonicalize_url para evitar dependencias circulares complejas
    # en la definición del estado, usamos una normalización básica aquí.
    def normalize(u):
        if not u: return ""
        return str(u).lower().rstrip('/').replace('https://', 'http://').replace('www.', '')

    seen_urls = {normalize(s.get('url')) for s in current if s.get('url')}
    
    added = []
    for s in new:
        url = s.get('url')
        if not url:
            added.append(s)
            continue
        
        norm_url = normalize(url)
        if norm_url not in seen_urls:
            added.append(s)
            seen_urls.add(norm_url)
            
    return current + added

class ResearchState(TypedDict):
    """
    Estado del proceso de investigación para un item.
    """
    # ==========================================
    # Identificadores y Configuración
    # ==========================================
    record_id: str
    project_id: Optional[str]             # ID del proyecto (para ContextManager cache)
    topic: str
    project_name: Optional[str]           # Contexto del proyecto general
    full_index: List[str]                 # Índice completo del proyecto
    related_topics: List[str]             # Otros temas del mismo proyecto
    company_context: Dict[str, Any]       # Contexto de la empresa del usuario
    project_specific_context: Optional[str]  # Información privada del proyecto
    agent_description: Optional[str]      # Descripción del rol del agente asignado
    brief: Optional[str]                   # Brief/objetivo del capítulo (desde Airtable)
    status: str
    
    # ==========================================
    # Inputs iniciales
    # ==========================================
    system_prompt: Optional[str]
    prompt_type: str
    new_sources_limit: int
    existing_sources_text: str            # Fuentes acumuladas previas
    
    # ==========================================
    # Estado del proceso interno
    # ==========================================
    # (Annotated para acumular en bucles de LangGraph)
    search_strategy: Annotated[List[Dict], operator.add]      # Tareas de búsqueda generadas
    found_sources: Annotated[List[Dict], deduplicate_sources] # Resultados crudos de búsqueda
    validated_sources: Annotated[List[Dict], deduplicate_sources] # Resultados aceptados
    rejected_sources: Annotated[List[Dict], deduplicate_sources]  # Resultados rechazados
    
    # ==========================================
    # Quality Gate y métricas (NUEVO)
    # ==========================================
    quality_gate_passed: bool             # Si pasó el quality gate
    quality_gate_issues: List[str]        # Issues detectados
    quality_gate_recommendation: str      # PROCEED / PROCEED_WITH_WARNINGS / RETRY_SEARCH
    confidence_score: Dict[str, Any]      # Métricas de confianza de las fuentes
    
    # ==========================================
    # Retry y loop control (NUEVO)
    # ==========================================
    failed_queries: List[str]             # Queries que no dieron buenos resultados
    loop_count: int                       # Contador de reintentos
    
    # ==========================================
    # Datos de gráficos (plots)
    # ==========================================
    plot_data: List[Dict[str, Any]]       # Lista de {code, url, path, bookmark}
    
    # ==========================================
    # Outputs finales
    # ==========================================
    final_report: str
    updated_sources_text: str             # Texto final para guardar en Airtable
    tokens_used: int                      # Estimación de tokens usados total
    tokens_by_role: Dict[str, int]       # Tokens usados por rol (planner, judge, analyst, plotter)
    
    # ==========================================
    # Control de flujo / Errores
    # ==========================================
    error: Optional[str]
    logs: Annotated[List[str], operator.add]
