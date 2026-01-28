"""
Módulo Cost Calculator: Calcula costos de uso de LLMs basado en tokens y modelos.
"""
from typing import Dict, Optional
from .config import CURRENT_PLANNER_MODEL, CURRENT_JUDGE_MODEL, CURRENT_ANALYST_MODEL, CURRENT_CONSOLIDATOR_MODEL, CURRENT_MATCHER_MODEL, CURRENT_PLOTER_MODEL

# Precios por 1M tokens (input/output) para modelos comunes en OpenRouter
# Fuente: https://openrouter.ai/models (precios aproximados, pueden variar)
MODEL_PRICING = {
    # OpenRouter - Free Models
    "xiaomi/mimo-v2-flash:free": {"input": 0.0, "output": 0.0},
    "google/gemini-2.0-pro-exp:free": {"input": 0.0, "output": 0.0},
    "google/gemini-2.0-flash-exp:free": {"input": 0.0, "output": 0.0},
    
    # OpenRouter - Paid Models
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "openai/gpt-4o": {"input": 2.5, "output": 10.0},
    "anthropic/claude-3.5-sonnet": {"input": 3.0, "output": 15.0},
    "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
    "google/gemini-2.0-flash-001": {"input": 0.1, "output": 0.4},
    "google/gemini-2.0-pro": {"input": 1.25, "output": 5.0},
    "google/gemini-2.5-flash": {"input": 0.3, "output": 2.5},
    "google/gemini-2.5-flash-lite": {"input": 0.1, "output": 0.4},

    # DeepSeek
    "deepseek/deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}

# Mapeo de roles a modelos actuales
ROLE_TO_MODEL = {
    "planner": CURRENT_PLANNER_MODEL,
    "judge": CURRENT_JUDGE_MODEL,
    "analyst": CURRENT_ANALYST_MODEL,
    "consolidator": CURRENT_CONSOLIDATOR_MODEL,
    "matcher": CURRENT_MATCHER_MODEL,
    "ploter": CURRENT_PLOTER_MODEL,
}


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """
    Obtiene el pricing de un modelo.
    
    Args:
        model_name: Nombre del modelo (ej: "openai/gpt-4o-mini")
    
    Returns:
        Dict con "input" y "output" prices por 1M tokens, o precios por defecto si no se encuentra
    """
    # Buscar exacto primero
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]
    
    # Buscar por prefijo (ej: "gpt-4o-mini" en "openai/gpt-4o-mini")
    for key, pricing in MODEL_PRICING.items():
        if key in model_name or model_name in key:
            return pricing
    
    # Precios por defecto conservadores (asumir modelo caro)
    print(f"⚠️ Modelo '{model_name}' no encontrado en pricing, usando precios por defecto")
    return {"input": 2.0, "output": 8.0}  # Precio conservador por defecto


def calculate_cost(input_tokens: int, output_tokens: int, model_name: str) -> float:
    """
    Calcula el costo de una llamada LLM.
    
    Args:
        input_tokens: Número de tokens de entrada
        output_tokens: Número de tokens de salida
        model_name: Nombre del modelo usado
    
    Returns:
        Costo en dólares
    """
    pricing = get_model_pricing(model_name)
    
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    
    return input_cost + output_cost


def estimate_cost_from_total_tokens(total_tokens: int, model_name: str, input_ratio: float = 0.7) -> float:
    """
    Estima el costo cuando solo se conoce el total de tokens.
    Asume una proporción típica de input/output.
    
    Args:
        total_tokens: Total de tokens (input + output)
        model_name: Nombre del modelo
        input_ratio: Proporción de tokens de entrada (default 0.7 = 70% input, 30% output)
    
    Returns:
        Costo estimado en dólares
    """
    input_tokens = int(total_tokens * input_ratio)
    output_tokens = total_tokens - input_tokens
    
    return calculate_cost(input_tokens, output_tokens, model_name)


def calculate_total_cost_from_state(state: Dict) -> float:
    """
    Calcula el costo total de un item basado en el estado.
    Si hay tokens_by_role, usa esos valores. Si no, estima basándose en tokens_used total.
    
    Args:
        state: ResearchState con tokens_used y/o tokens_by_role
    
    Returns:
        Costo total estimado en dólares
    """
    total_cost = 0.0
    
    # Prioridad 1: Usar tokens_by_role si está disponible (más preciso)
    tokens_by_role = state.get("tokens_by_role", {})
    if tokens_by_role:
        for role, tokens in tokens_by_role.items():
            if tokens > 0:
                model_name = ROLE_TO_MODEL.get(role, CURRENT_ANALYST_MODEL)
                role_cost = estimate_cost_from_total_tokens(tokens, model_name)
                total_cost += role_cost
        return round(total_cost, 6)
    
    # Prioridad 2: Estimar desde tokens_used total (fallback)
    tokens_used = state.get("tokens_used", 0)
    if tokens_used == 0:
        return 0.0
    
    # Distribuir tokens estimados por rol (aproximación)
    # Basado en el flujo típico: Planner -> Judge -> Analyst
    role_distribution = {
        "planner": 0.1,      # 10% - Planner genera queries
        "judge": 0.3,        # 30% - Judge evalúa muchas fuentes
        "analyst": 0.5,      # 50% - Analyst genera el reporte (más tokens)
        "matcher": 0.05,     # 5% - Matcher asigna agente
        "ploter": 0.05,      # 5% - Ploter genera gráficos (si aplica)
    }
    
    for role, ratio in role_distribution.items():
        role_tokens = int(tokens_used * ratio)
        if role_tokens > 0:
            model_name = ROLE_TO_MODEL.get(role, CURRENT_ANALYST_MODEL)
            role_cost = estimate_cost_from_total_tokens(role_tokens, model_name)
            total_cost += role_cost
    
    return round(total_cost, 6)


def calculate_costs_by_role_from_state(state: Dict) -> Dict[str, float]:
    """
    Calcula los costos individuales por rol basándose en tokens_by_role.
    
    Args:
        state: ResearchState con tokens_by_role
    
    Returns:
        Dict con costos por rol: {"planner": 0.001, "judge": 0.002, "analyst": 0.005, "plotter": 0.0001}
    """
    costs_by_role = {}
    tokens_by_role = state.get("tokens_by_role", {})
    
    for role, tokens in tokens_by_role.items():
        if tokens > 0:
            model_name = ROLE_TO_MODEL.get(role, CURRENT_ANALYST_MODEL)
            role_cost = estimate_cost_from_total_tokens(tokens, model_name)
            costs_by_role[role] = round(role_cost, 6)
        else:
            costs_by_role[role] = 0.0
    
    return costs_by_role


def calculate_cost_from_tokens_by_role(tokens_by_role: Dict[str, int]) -> float:
    """
    Calcula el costo total cuando se tienen tokens por rol.
    
    Args:
        tokens_by_role: Dict con {role: tokens} (ej: {"planner": 1000, "judge": 5000})
    
    Returns:
        Costo total en dólares
    """
    total_cost = 0.0
    
    for role, tokens in tokens_by_role.items():
        if tokens > 0:
            model_name = ROLE_TO_MODEL.get(role, CURRENT_ANALYST_MODEL)
            role_cost = estimate_cost_from_total_tokens(tokens, model_name)
            total_cost += role_cost
    
    return round(total_cost, 4)
