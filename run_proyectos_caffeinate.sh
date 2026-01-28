#!/bin/bash
# Script para ejecutar solo la consolidación de proyectos con caffeinate
# Previene que el Mac se apague mientras se ejecuta

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔄 Ejecutando consolidación de proyectos con caffeinate${NC}"
echo -e "${YELLOW}💡 El sistema NO se apagará mientras se ejecute${NC}"
echo -e "${YELLOW}💡 Presiona Ctrl+C para detener${NC}"
echo ""

# Ejecutar con caffeinate
# -d: Previene que la pantalla se duerma
# -i: Previene que el sistema entre en idle sleep
# -m: Previene que el disco entre en idle sleep
# -s: Previene que el sistema entre en sleep mientras el proceso está activo
caffeinate -d -i -m -s python3 main.py proyectos
