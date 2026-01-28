#!/bin/bash
# Script para ejecutar el sistema en una sesión screen persistente

# Crear sesión screen con caffeinate
screen -dmS informes_system bash -c "caffeinate -d -i -m -s python3 main.py $@; exec bash"

echo "✅ Sesión screen creada: informes_system"
echo "💡 Para ver la sesión: screen -r informes_system"
echo "💡 Para listar sesiones: screen -ls"
echo "💡 Para desconectarse: Ctrl+A, luego D"
echo "💡 Para matar la sesión: screen -X -S informes_system quit"

# Esperar un momento y mostrar status
sleep 1
screen -ls
