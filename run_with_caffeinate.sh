#!/bin/bash
# Script wrapper para ejecutar el sistema sin que el Mac entre en suspensión
# Usa caffeinate para mantener el sistema despierto mientras se ejecuta el script

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔄 Ejecutando con caffeinate (sistema NO se dormirá)${NC}"
echo -e "${YELLOW}💡 Presiona Ctrl+C para detener${NC}"
echo ""

# Ejecutar con caffeinate
# -d: Previene que la pantalla se duerma
# -i: Previene que el sistema entre en idle sleep
# -m: Previene que el disco entre en idle sleep
# -s: Previene que el sistema entre en sleep mientras el proceso está activo
caffeinate -d -i -m -s python3 main.py "$@"
