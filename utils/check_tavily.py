
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from tavily import TavilyClient

# Cargar .env
env_paths = [
    Path(__file__).parent.parent / "private_context" / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent / "deep_research" / ".env",
]

for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"✅ Cargado .env desde {env_path}")
        break

def check_tavily():
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("❌ TAVILY_API_KEY no encontrada en el entorno después de cargar .env.")
        return

    client = TavilyClient(api_key=api_key)
    print(f"Probando Tavily con API Key: {api_key[:5]}...{api_key[-4:]}")
    
    try:
        # Intento de búsqueda básica
        print("📡 Realizando búsqueda de prueba (basic)...")
        response = client.search(query="Ferrovial news 2026", search_depth="basic", max_results=1)
        if response and 'results' in response:
            print(f"✅ Éxito: Se encontró {len(response['results'])} resultado.")
            print(f"🔗 URL: {response['results'][0].get('url')}")
        else:
            print("⚠️ Respuesta recibida pero sin resultados.")
            print(f"DEBUG: {response}")
            
    except Exception as e:
        error_str = str(e).lower()
        if "402" in error_str or "credits" in error_str or "payment" in error_str:
            print("❌ ERROR DE CRÉDITOS: No hay créditos suficientes en Tavily.")
        elif "401" in error_str or "unauthorized" in error_str:
            print("❌ ERROR DE AUTORIZACIÓN: API Key inválida.")
        elif "rate limit" in error_str or "429" in error_str:
            print("❌ ERROR DE RATE LIMIT: Demasiadas peticiones.")
        else:
            print(f"❌ ERROR INESPERADO: {e}")

if __name__ == "__main__":
    check_tavily()
