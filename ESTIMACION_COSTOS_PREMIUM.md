# Estimación de Costos - Modo Premium

## 📊 Configuración Premium

### Modelos Premium Recomendados

Para un modo premium completo, se recomienda usar modelos de alta calidad:

| Rol | Modelo Premium | Provider | Precio Input | Precio Output |
|-----|----------------|----------|--------------|---------------|
| Matcher | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Planner | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Judge | `anthropic/claude-sonnet-4.5` | openrouter | $3.00/1M | $15.00/1M |
| Analyst | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Ploter | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Consolidator | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Consolidator Polish | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Consolidator Summary | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Consolidator Polish Premium | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |
| Consolidator Summary Premium | `google/gemini-2.5-pro` | openrouter | $1.25/1M | $5.00/1M |

**Nota**: Los roles premium de consolidator ya están configurados para usar `google/gemini-2.5-pro` cuando el documento excede 120,000 caracteres.

---

## 💰 Estimación de Costos por Reporte Individual

Basado en el uso típico de tokens por rol (70% input, 30% output):

### Escenario 1: Reporte Estándar (1 item)

| Rol | Tokens Estimados | Input Tokens | Output Tokens | Costo Input | Costo Output | **Costo Total** |
|-----|------------------|--------------|---------------|-------------|--------------|-----------------|
| Matcher | ~500 | 350 | 150 | $0.0004 | $0.0008 | **$0.0012** |
| Planner | ~2,000 | 1,400 | 600 | $0.0018 | $0.0030 | **$0.0048** |
| Judge | ~15,000 | 10,500 | 4,500 | $0.0315 | $0.0675 | **$0.0990** |
| Analyst | ~50,000 | 35,000 | 15,000 | $0.0438 | $0.0750 | **$0.1188** |
| Verifier | ~8,000 | 5,600 | 2,400 | $0.0070 | $0.0120 | **$0.0190** |
| Ploter | ~3,000 | 2,100 | 900 | $0.0026 | $0.0045 | **$0.0071** |

**Total por reporte individual**: **~$0.2499** (aproximadamente **25 centavos**)

---

### Escenario 2: Reporte con Consolidación (proyecto completo)

#### Fase 1: Reportes Individuales
- 5 items × $0.25 = **$1.25**

#### Fase 2: Consolidación Premium (documento > 120,000 chars)
- **Consolidator Polish Premium**: ~30,000 tokens (21,000 input + 9,000 output)
  - Input: $0.0263
  - Output: $0.0450
  - **Total**: **$0.0713**

- **Consolidator Summary Premium**: ~5,000 tokens (3,500 input + 1,500 output)
  - Input: $0.0044
  - Output: $0.0075
  - **Total**: **$0.0119**

**Total por proyecto consolidado premium**: **~$1.33** (aproximadamente **$1.33**)

---

## 📈 Comparación de Costos

| Modo | Costo por Reporte | Costo por Proyecto (5 items) | Ahorro vs Premium |
|------|-------------------|------------------------------|-------------------|
| **Premium** (Gemini 2.5 Pro + Claude Sonnet) | **~$0.25** | **~$1.33** | - |
| Producción Actual (DeepSeek) | ~$0.022 | ~$0.12 | **~91% más barato** |
| Económico (DeepSeek) | ~$0.022 | ~$0.12 | **~91% más barato** |

---

## 💵 Estimación Mensual - Modo Premium

### Escenario Conservador (100 reportes/mes)
- 100 reportes individuales: 100 × $0.25 = **$25.00**
- 20 proyectos consolidados: 20 × $1.33 = **$26.60**
- **Total mensual**: **~$51.60**

### Escenario Moderado (500 reportes/mes)
- 500 reportes individuales: 500 × $0.25 = **$125.00**
- 100 proyectos consolidados: 100 × $1.33 = **$133.00**
- **Total mensual**: **~$258.00**

### Escenario Alto (2000 reportes/mes)
- 2000 reportes individuales: 2000 × $0.25 = **$500.00**
- 400 proyectos consolidados: 400 × $1.33 = **$532.00**
- **Total mensual**: **~$1,032.00**

---

## 🎯 Desglose de Costos por Rol (Modo Premium)

| Rol | Tokens Estimados | % del Total | Costo Estimado | Modelo |
|-----|------------------|-------------|----------------|--------|
| Planner | 2,000 | 2.5% | $0.0048 | Gemini 2.5 Pro |
| Judge | 15,000 | 18.8% | $0.0990 | Claude Sonnet 4.5 |
| Analyst | 50,000 | 62.5% | $0.1188 | Gemini 2.5 Pro |
| Verifier | 8,000 | 10.0% | $0.0190 | Gemini 2.5 Pro |
| Ploter | 3,000 | 3.8% | $0.0071 | Gemini 2.5 Pro |
| Matcher | 500 | 0.6% | $0.0012 | Gemini 2.5 Pro |
| **Total** | **~78,500** | **100%** | **~$0.2499** | - |

*Nota: Los tokens de input/output se distribuyen aproximadamente 70% input / 30% output*

---

## ⚙️ Configuración para Modo Premium

Para activar el modo premium, edita `config.toml`:

```toml
[roles.matcher]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0

[roles.planner]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0

[roles.judge]
provider = "openrouter"
model = "anthropic/claude-sonnet-4.5"
temperature = 0.0
max_tokens = 1200

[roles.analyst]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.3
max_tokens = 16384

[roles.ploter]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 4096

[roles.consolidator]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 8192

[roles.consolidator_polish]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 8192

[roles.consolidator_summary]
provider = "openrouter"
model = "google/gemini-2.5-pro"
temperature = 0.0
max_tokens = 4096
```

**Nota**: Los roles `consolidator_polish_premium` y `consolidator_summary_premium` ya están configurados para usar `google/gemini-2.5-pro` y se activan automáticamente cuando el documento excede 120,000 caracteres.

---

## 📊 Resumen Ejecutivo

### Costo por Reporte Individual
- **Modo Premium**: ~$0.25 (25 centavos)
- **Modo Producción Actual**: ~$0.022 (2.2 centavos)
- **Diferencia**: ~11x más caro

### Costo por Proyecto Consolidado
- **Modo Premium**: ~$1.33
- **Modo Producción Actual**: ~$0.12
- **Diferencia**: ~11x más caro

### Costo Mensual Estimado (500 reportes)
- **Modo Premium**: ~$258
- **Modo Producción Actual**: ~$23
- **Diferencia**: ~11x más caro

---

## ✅ Ventajas del Modo Premium

1. **Mayor Calidad**: Gemini 2.5 Pro y Claude Sonnet ofrecen mejor calidad de análisis
2. **Mejor Comprensión**: Modelos más avanzados para tareas complejas
3. **Mayor Contexto**: Modelos premium tienen límites de contexto más altos
4. **Mejor Coherencia**: Generación más coherente y contextualizada

## ⚠️ Consideraciones

1. **Costo 11x Mayor**: El modo premium es significativamente más caro
2. **Ideal para**: Reportes críticos, clientes externos, máxima calidad
3. **Recomendación**: Usar premium selectivamente para proyectos importantes

---

## 🔄 Modo Híbrido Recomendado

**Estrategia Óptima**:
- **Modo Producción (DeepSeek)**: Para la mayoría de reportes y proyectos internos
- **Modo Premium (Gemini/Claude)**: Solo para proyectos críticos o clientes externos
- **Consolidación Premium Automática**: Se activa automáticamente cuando el documento excede 120,000 caracteres

Esto permite mantener costos bajos mientras se garantiza máxima calidad cuando es necesario.
