# Cuándo se Usa Google (Gemini) y sus Costos

## 📊 Uso de Gemini 2.5 Pro

### 1. Consolidación Premium (Automático)

**Cuándo se activa:**
- Cuando el documento consolidado excede **120,000 caracteres** (configurable en `config.toml`: `consolidator_premium_threshold_chars`)

**Roles que usan Gemini:**
- `consolidator_polish_premium`: Gemini 2.5 Pro para pulir narrativa
- `consolidator_summary_premium`: Gemini 2.5 Pro para generar Executive Summary

**Configuración:**
```toml
[roles.consolidator_polish_premium]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 8192

[roles.consolidator_summary_premium]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 4096
```

**Costos:**
- **Polish Premium**: ~30,000 tokens → **$0.0713**
- **Summary Premium**: ~5,000 tokens → **$0.0119**
- **Total Consolidación Premium**: **~$0.0832** (8.3 centavos)

---

### 2. Reportes Exploratorios (llm_analyst_fast)

**Cuándo se activa:**
- Cuando el `report_type` NO es crítico (no es "Strategy", "Financial", "Due_Diligence", etc.)
- Se usa `llm_analyst_fast` en lugar de `llm_analyst` o `llm_analyst_precision`

**Modelo:**
- `google/gemini-2.5-pro` vía OpenRouter

**Costos:**
- ~50,000 tokens por reporte → **~$0.1188** (11.9 centavos)

---

### 3. Síntesis Final (generate_final_report)

**Cuándo se activa:**
- Cuando se llama a `generate_final_report()` para síntesis masiva de conocimiento
- Usa Gemini 2.5 Pro para manejar contextos enormes

**Costos:**
- ~80,000 tokens → **~$0.1900** (19 centavos)

---

## 💰 Precios de Gemini 2.5 Pro

**Precios por 1M tokens (OpenRouter):**
- **Input**: $1.25 por 1M tokens
- **Output**: $5.00 por 1M tokens

**Distribución típica:**
- 70% input tokens
- 30% output tokens

---

## 📈 Costos Estimados por Escenario

### Escenario 1: Proyecto Pequeño (< 120,000 chars)
- **Consolidación**: DeepSeek (no usa Gemini)
- **Costo consolidación**: ~$0.0084 (DeepSeek)
- **Total**: No usa Gemini en consolidación

### Escenario 2: Proyecto Grande (≥ 120,000 chars)
- **Consolidación Premium**: Gemini 2.5 Pro
- **Polish Premium**: ~$0.0713
- **Summary Premium**: ~$0.0119
- **Total Consolidación Premium**: **~$0.0832**

### Escenario 3: Reporte Exploratorio
- **Analyst Fast**: Gemini 2.5 Pro
- **Costo por reporte**: **~$0.1188**

### Escenario 4: Síntesis Final
- **Síntesis masiva**: Gemini 2.5 Pro
- **Costo**: **~$0.1900**

---

## 🎯 Resumen

| Uso | Cuándo | Modelo | Costo Aprox. |
|-----|--------|--------|--------------|
| **Consolidación Premium** | Documento > 120K chars | Gemini 2.5 Pro | $0.0832 |
| **Reportes Exploratorios** | report_type no crítico | Gemini 2.5 Pro | $0.1188 |
| **Síntesis Final** | generate_final_report() | Gemini 2.5 Pro | $0.1900 |

---

## ⚙️ Configuración del Umbral

El umbral para activar consolidación premium se configura en `config.toml`:

```toml
[general]
consolidator_premium_threshold_chars = 120000  # Cambiar este valor para ajustar cuándo se activa
```

**Recomendaciones:**
- **120,000 chars**: Balance calidad/costo (actual)
- **80,000 chars**: Más calidad, más costos
- **200,000 chars**: Menos costos, menos calidad en documentos grandes

---

## 💡 Optimización de Costos

**Para reducir costos de Gemini:**
1. Aumentar `consolidator_premium_threshold_chars` a 200,000 o más
2. Usar DeepSeek para reportes exploratorios en lugar de Gemini
3. Desactivar `llm_analyst_fast` y usar siempre `llm_analyst` (DeepSeek)

**Para aumentar calidad:**
1. Reducir `consolidator_premium_threshold_chars` a 80,000 o menos
2. Usar Gemini para todos los reportes (no solo exploratorios)
3. Activar Gemini en más roles de consolidación
