#!/bin/bash
# Test rápido para verificar que caffeinate funciona

echo "🧪 Test de caffeinate..."
echo ""
echo "1️⃣ Ejecutando caffeinate en background por 5 segundos..."
echo "2️⃣ Deberías ver un proceso 'caffeinate' cuando ejecutes: ps aux | grep caffeinate"
echo ""

# Ejecutar caffeinate por 5 segundos
caffeinate -d -i -m -s sleep 5 &

CAFFEINATE_PID=$!
echo "✅ caffeinate iniciado (PID: $CAFFEINATE_PID)"
echo ""
echo "🔍 Verifica ahora con: ps aux | grep caffeinate"
echo "⏱️  Esperando 5 segundos..."

sleep 5

echo ""
echo "✅ Test completado. El proceso caffeinate debería haber terminado."
