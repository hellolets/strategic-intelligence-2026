"""
Módulo Output Logger: Captura toda la salida del terminal y la guarda en un archivo.
"""
import sys
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TextIO


# Patrón para eliminar códigos ANSI de escape (colores, estilos, etc.)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi_codes(text: str) -> str:
    """Elimina códigos ANSI de escape de un texto."""
    return ANSI_ESCAPE_PATTERN.sub('', text)


class TeeOutput:
    """
    Clase que permite escribir simultáneamente a stdout/stderr y a un archivo.
    Los códigos ANSI se mantienen en stdout pero se eliminan del archivo.
    """
    def __init__(self, file_path: str, mode: str = 'a'):
        self.file = open(file_path, mode, encoding='utf-8')
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text: str):
        """Escribe tanto en stdout (con colores) como en el archivo (sin colores)."""
        # Escribir con colores a stdout
        self.stdout.write(text)
        # Escribir SIN códigos ANSI al archivo para legibilidad
        if self.file and not self.file.closed:
            clean_text = strip_ansi_codes(text)
            self.file.write(clean_text)
            self.file.flush()  # Asegurar que se escribe inmediatamente
        
    def flush(self):
        """Flush tanto stdout como el archivo."""
        self.stdout.flush()
        if self.file and not self.file.closed:
            self.file.flush()
        
    def close(self):
        """Cierra el archivo y restaura stdout/stderr originales."""
        if self.file:
            self.file.close()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


def setup_output_logging(log_dir: str = "logs") -> TeeOutput:
    """
    Configura el logging de salida para capturar todo en un archivo.
    
    Args:
        log_dir: Directorio donde guardar los logs
        
    Returns:
        Instancia de TeeOutput para poder cerrarla después
    """
    # Crear directorio de logs si no existe
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Crear nombre de archivo con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"execution_{timestamp}.log"
    
    # Crear instancia de TeeOutput
    tee = TeeOutput(str(log_file), mode='w')
    
    # Redirigir stdout y stderr
    sys.stdout = tee
    sys.stderr = tee
    
    # Escribir header al inicio del log
    header = f"""
{'=' * 80}
EJECUCIÓN INICIADA: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
{'=' * 80}
Log file: {log_file}
{'=' * 80}

"""
    tee.write(header)
    
    print(f"📝 Logging activado: Toda la salida se guardará en {log_file}")
    
    return tee


def restore_output(tee: TeeOutput, elapsed_time: float = None, total_cost: float = None):
    """
    Restaura stdout/stderr originales y cierra el archivo de log.
    
    Args:
        tee: Instancia de TeeOutput a cerrar
        elapsed_time: Tiempo transcurrido en segundos (opcional)
        total_cost: Costo total de la ejecución en dólares (opcional)
    """
    if tee:
        # Solo escribir footer si el archivo no está cerrado
        if tee.file and not tee.file.closed:
            end_time = datetime.now()
            
            # Construir footer con información de resumen
            footer_lines = [
                "",
                "=" * 80,
                f"EJECUCIÓN FINALIZADA: {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 80,
            ]
            
            # Añadir tiempo transcurrido si está disponible
            if elapsed_time is not None:
                hours = int(elapsed_time // 3600)
                minutes = int((elapsed_time % 3600) // 60)
                seconds = int(elapsed_time % 60)
                if hours > 0:
                    elapsed_str = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    elapsed_str = f"{minutes}m {seconds}s"
                else:
                    elapsed_str = f"{seconds}s"
                footer_lines.append(f"⏱️  Tiempo total transcurrido: {elapsed_str}")
            
            # Añadir costo total si está disponible
            if total_cost is not None and total_cost > 0:
                footer_lines.append(f"💰 Costo total: ${total_cost:.6f}")
            
            footer_lines.append("=" * 80)
            footer_lines.append("")
            
            footer = "\n".join(footer_lines)
            
            try:
                tee.write(footer)
            except (ValueError, OSError):
                # El archivo podría estar cerrado, ignorar el error
                pass
        tee.close()
        # Solo imprimir si stdout está disponible
        try:
            print(f"✅ Log guardado correctamente")
        except (ValueError, OSError):
            pass
