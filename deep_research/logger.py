"""
Módulo de Logging profesional usando Rich.
Centraliza el estilo y formato de los logs de la aplicación.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from typing import List, Dict, Any, Optional
import time

# Inicializar consola global
console = Console()

class LogManager:
    """Gestor centralizado de logs con formato enriquecido."""
    
    @staticmethod
    def log_section(title: str, subtitle: str = None, style: str = "bold cyan"):
        """Muestra un panel de sección principal."""
        content = f"[bold]{title}[/bold]"
        if subtitle:
            content += f"\n[dim]{subtitle}[/dim]"
        console.print(Panel(content, border_style=style, expand=False))

    @staticmethod
    def log_phase(phase: str, message: str, color: str = "blue"):
        """Loguea una fase del proceso (ej: PLANNER, SEARCHER)."""
        console.print(f"[{color} bold]➤ [{phase}][/] {message}")

    @staticmethod
    def log_model_usage(role: str, model_name: str):
        """Loguea qué modelo se está usando para una tarea."""
        console.print(f"   🤖 [dim]Model ({role}):[/] [cyan]{model_name}[/]")

    @staticmethod
    def log_success(message: str):
        """Loguea un éxito."""
        console.print(f"   ✅ [green]{message}[/]")

    @staticmethod
    def log_warning(message: str):
        """Loguea una advertencia."""
        console.print(f"   ⚠️  [yellow]{message}[/]")

    @staticmethod
    def log_error(message: str):
        """Loguea un error."""
        console.print(f"   ❌ [bold red]{message}[/]")

    @staticmethod
    def log_info(message: str):
        """Loguea información general."""
        console.print(f"   ℹ️  {message}")

    @staticmethod
    def log_analysis(message: str):
        """Loguea mensajes de análisis (cerebro/pensamiento)."""
        console.print(f"   🧠 [magenta]{message}[/]")
    
    @staticmethod
    def display_search_results(results: List[Dict], provider: str):
        """Muestra una tabla con los resultados de búsqueda."""
        if not results:
            console.print(f"   [dim]No results found from {provider}[/]")
            return

        table = Table(show_header=True, header_style="bold magenta", box=None, title=f"Resultados de {provider}")
        table.add_column("#", style="dim", width=4)
        table.add_column("Domain", style="cyan", width=20)
        table.add_column("Title", style="bold")
        
        for i, res in enumerate(results, 1):
            domain = res.get('source_domain', 'unknown')
            title = res.get('title', 'No Title')[:60]
            table.add_row(str(i), domain, title)
            
        console.print(table)
        console.print(" ") 

    @staticmethod
    def display_evaluation_results(validated: List[Dict], rejected: List[Dict]):
        """Muestra resumen de la evaluación."""
        table = Table(title="Resumen de Evaluación", show_header=True, header_style="bold green")
        table.add_column("Categoría", style="bold")
        table.add_column("Cantidad", justify="right")
        table.add_column("Detalles", style="dim")
        
        table.add_row(
            "[green]Aceptadas[/]", 
            str(len(validated)), 
            "Fuentes de alta relevancia y calidad"
        )
        table.add_row(
            "[red]Rechazadas[/]", 
            str(len(rejected)), 
            "Baja calidad, irrelevantes o duplicadas"
        )
        
        console.print(table)
        
        if validated:
            console.print("   [bold green]Top Sources:[/]")
            for i, v in enumerate(validated[:3], 1):
                score = v.get('total_score', 'N/A')
                domain = v.get('source_domain', 'N/A')
                console.print(f"     {i}. [cyan]{domain}[/] (Score: {score}/10)")
        console.print(" ")

# Instancia global
logger = LogManager()
