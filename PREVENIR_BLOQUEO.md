# 🔋 Prevenir Bloqueo/Suspensión del Sistema

Guía para evitar que el ordenador se bloquee o entre en suspensión durante la ejecución de los scripts largos.

## 🍎 macOS - Opción 1: Caffeinate (Recomendado)

### Uso Simple con Script Wrapper

```bash
# Ejecutar cualquier modo con caffeinate (automático)
./run_with_caffeinate.sh pipeline
./run_with_caffeinate.sh items
./run_with_caffeinate.sh proyectos
./run_with_caffeinate.sh server
```

### Uso Manual con Caffeinate

```bash
# Mantener despierto mientras se ejecuta el script
caffeinate -d -i -m -s python3 main.py pipeline

# O para el servidor
caffeinate -d -i -m -s python3 main.py server
```

**Opciones de caffeinate:**
- `-d`: Previene que la pantalla se duerma
- `-i`: Previene que el sistema entre en idle sleep
- `-m`: Previene que el disco entre en idle sleep
- `-s`: Previene que el sistema entre en sleep mientras el proceso esté activo

### Caffeinate en Background (Recomendado para ejecuciones largas)

```bash
# Ejecutar en background con output redirigido
nohup caffeinate -d -i -m -s python3 main.py pipeline > output.log 2>&1 &

# Ver el proceso
ps aux | grep caffeinate

# Ver logs en tiempo real
tail -f output.log

# Detener (encuentra el PID primero)
kill <PID>
```

## 🖥️ Usar Screen o TMUX (Para Conexiones SSH)

### Screen (Sesiones Persistentes)

```bash
# Instalar screen (si no está instalado)
brew install screen

# Crear sesión
screen -S informes_system

# Dentro de screen, ejecutar el script
python3 main.py pipeline

# Desconectarse de screen (Ctrl+A, luego D)
# Reconectar después: screen -r informes_system
# Listar sesiones: screen -ls
# Matar sesión: screen -X -S informes_system quit
```

### TMUX (Alternativa Moderna)

```bash
# Instalar tmux (si no está instalado)
brew install tmux

# Crear sesión
tmux new -s informes_system

# Dentro de tmux, ejecutar el script
python3 main.py pipeline

# Desconectarse de tmux (Ctrl+B, luego D)
# Reconectar después: tmux attach -t informes_system
# Listar sesiones: tmux ls
# Matar sesión: tmux kill-session -t informes_system
```

## ⚙️ Configuración del Sistema (macOS)

### Prevenir Suspensión Globalmente

```bash
# Desactivar sleep automático (hasta reinicio)
sudo pmset -a sleep 0

# Restaurar valores por defecto después
sudo pmset -a sleep 10  # 10 minutos (valor común)
```

### Solo para el Usuario Actual

```bash
# Ver configuración actual
pmset -g

# Configurar para no dormir cuando está conectado a corriente
pmset -c sleep 0 displaysleep 10

# Restaurar después
pmset -c sleep 10 displaysleep 10
```

**⚠️ ADVERTENCIA:** Cambiar `sleep 0` desactiva la suspensión completamente. Úsalo solo durante ejecuciones largas.

## 📋 Resumen de Recomendaciones

### Para Ejecuciones Cortas (< 1 hora):
```bash
./run_with_caffeinate.sh pipeline
```

### Para Ejecuciones Largas (> 1 hora):
```bash
# Opción 1: Screen/Tmux + Caffeinate
screen -S informes
caffeinate -d -i -m -s python3 main.py pipeline

# Opción 2: NoHup + Caffeinate (background)
nohup caffeinate -d -i -m -s python3 main.py pipeline > output.log 2>&1 &
```

### Para Servidor Web (Servidor de Producción):
```bash
# Usar screen/tmux para mantener sesión persistente
screen -S server
caffeinate -d -i -m -s python3 main.py server
```

## 🔧 Verificar Estado

```bash
# Ver si caffeinate está activo
ps aux | grep caffeinate

# Ver procesos de Python
ps aux | grep "main.py"

# Ver logs del sistema
tail -f logs/execution_*.log
```

## ❓ Solución de Problemas

### Problema: El sistema se duerme igual
**Solución:** Verifica que caffeinate esté ejecutándose:
```bash
ps aux | grep caffeinate
```

### Problema: Pierdo la conexión SSH
**Solución:** Usa screen o tmux ANTES de ejecutar:
```bash
screen -S informes
# Luego ejecuta tu comando normalmente
```

### Problema: Quiero ejecutar en background sin terminal
**Solución:** Usa nohup:
```bash
nohup ./run_with_caffeinate.sh pipeline > output.log 2>&1 &
```
