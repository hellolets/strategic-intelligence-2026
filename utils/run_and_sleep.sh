#!/bin/bash
# Script para ejecutar main.py y dormir el Mac automáticamente al terminar
# Uso: ./run_and_sleep.sh [argumentos para main.py]

# Obtener directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ejecutar el script Python con caffeinate (mantiene despierto durante la ejecución)
# Luego pone el Mac en modo sleep
caffeinate -dimsu bash -c "python3 main.py \"$@\"; pmset sleepnow"
