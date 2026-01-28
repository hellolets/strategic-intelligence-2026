# 🚀 Cómo Lanzar el Script

## Ejecución Básica

### 1. **Pipeline Completo (Recomendado)**
Ejecuta todo el flujo automáticamente: asignación de agentes → investigación → consolidación

```bash
python3 main.py pipeline
```

O simplemente (pipeline es el modo por defecto):
```bash
python3 main.py
```

**¿Qué hace?**
1. Asigna agentes a items con `Status='Todo'`
2. Procesa investigación de items con `Status='Pending'`
3. Consolida proyectos completados

---

### 2. **Solo Asignación de Agentes**
Asigna automáticamente el mejor System Prompt a cada item

```bash
python3 main.py match
```

**¿Qué hace?**
- Busca items con `Status='Todo'`
- Analiza el tema y asigna el agente más adecuado
- Cambia `Status` a `'Pending'`

---

### 3. **Solo Procesamiento de Items**
Procesa la investigación de items individuales

```bash
python3 main.py items
```

**¿Qué hace?**
- Busca items con `Status='Pending'`
- Ejecuta: búsqueda → evaluación → síntesis
- Genera reportes individuales
- Cambia `Status` a `'Done'`

---

### 4. **Solo Consolidación de Proyectos**
Consolida proyectos completados en documentos Word

```bash
python3 main.py proyectos
```

**¿Qué hace?**
- Busca proyectos con `Status='Generating items'` o `'Todo'`
- Verifica que todos los items estén `Status='Done'`
- Consolida todos los capítulos en un documento Word
- Sube a R2 (si está habilitado)
- Cambia `Status` a `'Done'`

---

### 5. **Modo Servidor (Webhooks)**
Inicia servidor web para recibir webhooks de Airtable

```bash
python3 main.py server
```

**¿Qué hace?**
- Inicia servidor FastAPI en puerto 8000 (o `$PORT`)
- Expone endpoints para webhooks
- Útil para despliegue en Render.com

---

## 🍎 Ejecución en Mac (Prevenir Suspensión)

Si ejecutas en Mac y quieres evitar que el sistema se duerma:

### Opción 1: Script con caffeinate (Pipeline completo)
```bash
./run_with_caffeinate.sh pipeline
```

### Opción 2: Script con caffeinate (Solo consolidación)
```bash
./run_proyectos_caffeinate.sh
```

### Opción 3: Manual con caffeinate
```bash
caffeinate -d -i -m -s python3 main.py pipeline
```

---

## ⚙️ Configuración Antes de Ejecutar

### 1. Verificar Variables de Entorno

Asegúrate de tener un archivo `.env` con todas las API keys:

```bash
# Verificar que existe
ls -la .env

# O crear desde ejemplo
cp .env.example .env
# Editar .env con tus keys
```

**Variables requeridas:**
- `OPENAI_API_KEY` o `OPENROUTER_API_KEY`
- `GOOGLE_API_KEY`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `TAVILY_API_KEY`
- `EXA_API_KEY` (opcional)

### 2. Verificar Configuración en config.toml

```bash
# Ver configuración actual
cat deep_research/config.toml | grep -A 5 "\[general\]"
```

**Configuraciones importantes:**
- `profile = "PRODUCTION"` o `"ECONOMIC"` o `"TEST"`
- `use_cheap_openrouter_models = false` (cambiar a `true` para modo económico)
- `verifier_enabled = true` (verificación de alucinaciones)

### 3. Activar Modo Económico (Opcional)

Si quieres usar modelos económicos (DeepSeek):

**Opción A: En config.toml**
```toml
[general]
use_cheap_openrouter_models = true
```

**Opción B: Variable de entorno**
```bash
export USE_CHEAP_OPENROUTER_MODELS=true
python3 main.py pipeline
```

---

## 📋 Flujo de Trabajo Recomendado

### Escenario 1: Proyecto Nuevo desde Cero

1. **Crear proyecto en Airtable**
   - Tabla `Proyectos`: Crear registro con `Status='Todo'`
   - Tabla `Items_indice`: Crear items relacionados con `Status='Todo'`

2. **Ejecutar pipeline completo**
   ```bash
   python3 main.py pipeline
   ```

3. **El sistema automáticamente:**
   - Asigna agentes a los items
   - Procesa investigación de cada item
   - Consolida cuando todos los items estén listos

---

### Escenario 2: Solo Quieres Asignar Agentes

```bash
python3 main.py match
```

Luego procesa manualmente cuando quieras:
```bash
python3 main.py items
```

---

### Escenario 3: Ya Tienes Items Procesados, Solo Consolidar

```bash
python3 main.py proyectos
```

---

## 🔍 Verificar que Funciona

### 1. Ver logs en tiempo real
El script muestra logs detallados de cada paso:
```
🚀 [CONFIG] PRODUCCIÓN: Planner=deepseek/deepseek-chat, Judge=...
🔍 [PLANNER] Generando estrategias de búsqueda...
📊 [SEARCHER] Ejecutando 3 búsquedas...
⚖️ [JUDGE] Evaluando 15 fuentes...
✍️ [ANALYST] Generando reporte...
```

### 2. Verificar en Airtable
- Items: `Status` cambia de `Todo` → `Pending` → `Processing` → `Done`
- Proyectos: `Status` cambia a `Processing` → `Done` cuando se consolida

### 3. Ver archivos generados
```bash
# Reportes individuales (Markdown)
ls -la reports/

# Documentos Word consolidados
ls -la reports/*.docx
```

---

## 🐛 Troubleshooting

### Error: "Variables de entorno faltantes"
```bash
# Verificar que .env existe y tiene las keys
cat .env | grep API_KEY
```

### Error: "No se encuentran items para procesar"
- Verifica en Airtable que hay items con `Status='Todo'` o `'Pending'`
- Verifica que el proyecto padre NO tiene `Status='Submitted'` (no se procesa)

### Error: "ModuleNotFoundError"
```bash
# Instalar dependencias
pip install -r requirements.txt
```

### El script se detiene sin error
- Verifica logs en `output_logs/` (se generan automáticamente)
- Revisa que las API keys sean válidas
- Verifica conexión a internet

---

## 📊 Monitoreo de Costos

El script muestra costos estimados al final:
```
💵 Costo Total Estimado: $0.0234
```

Para modo económico, deberías ver costos muy bajos (~$0.02 por reporte).

---

## 🔄 Ejecución Continua (Loop)

Si quieres que el script se ejecute continuamente:

```bash
# Ejecutar cada 60 segundos
while true; do
    python3 main.py pipeline
    echo "Esperando 60 segundos..."
    sleep 60
done
```

O usar un cron job:
```bash
# Ejecutar cada hora
0 * * * * cd /ruta/al/proyecto && python3 main.py pipeline
```

---

## 📝 Resumen de Comandos

| Comando | Descripción | Cuándo Usar |
|---------|-------------|-------------|
| `python3 main.py` o `python3 main.py pipeline` | Pipeline completo | Uso normal, flujo automático |
| `python3 main.py match` | Solo asignar agentes | Quieres controlar cuándo procesar |
| `python3 main.py items` | Solo procesar items | Ya tienes agentes asignados |
| `python3 main.py proyectos` | Solo consolidar | Items ya están listos |
| `python3 main.py server` | Modo servidor | Despliegue con webhooks |
| `./run_with_caffeinate.sh pipeline` | Pipeline en Mac sin suspensión | Ejecución larga en Mac |

---

## ✅ Checklist Antes de Ejecutar

- [ ] Archivo `.env` configurado con todas las API keys
- [ ] `config.toml` revisado (modo económico si quieres ahorrar)
- [ ] Items creados en Airtable con `Status='Todo'`
- [ ] Proyecto en Airtable con `Status='Todo'` (no `'Submitted'`)
- [ ] Dependencias instaladas: `pip install -r requirements.txt`
- [ ] Python 3.10+ instalado: `python3 --version`

---

¡Listo para ejecutar! 🚀
