# EVALUACIÓN DE ROBUSTEZ Y OPTIMIZACIÓN DE MODELOS

## RESUMEN EJECUTIVO

Evaluación completa de la robustez de la aplicación y optimización de modelos por perfil (TEST, ECONOMIC, PRODUCTION) basada en capacidades, precio, output y robustez operativa.

---

## 1. REVISIÓN DE CONFIGURACIÓN Y ENRUTAMIENTO

### 1.1 Estado Actual

**Archivo:** `deep_research/model_routing.py`

**Fortalezas:**
- ✅ Sistema de routing centralizado y bien estructurado
- ✅ Soporte para 3 perfiles claramente definidos (PRODUCTION, ECONOMIC, TEST)
- ✅ Backward compatibility con variables legacy (`USE_DEEPSEEK_FOR_TESTING`, `USE_CHEAP_OPENROUTER_MODELS`)
- ✅ Overrides por rol vía env vars (`ROLE_MODEL_*`, `ROLE_TEMP_*`, `ROLE_MAXTOKENS_*`)
- ✅ Separación clara entre TEST offline (LocalStubLLM) y TEST online (DeepSeek)

**Problemas Detectados:**
- ⚠️ **NO integra con `config.toml`**: El routing solo lee de código hardcodeado y env vars, no de TOML
- ⚠️ **Función duplicada**: `get_llm_for_role()` aparece dos veces en `config.py` (líneas 516 y 539)
- ⚠️ **Falta validación**: No valida que el modelo/proveedor sean válidos antes de crear el cliente
- ⚠️ **Sin fallback de modelos**: Si un modelo falla, no hay fallback automático a otro modelo

### 1.2 Divergencias con config.toml

**Archivo:** `deep_research/config.toml`

**Problema:** Hay una desconexión entre `config.toml` y `model_routing.py`:

- `config.toml` define modelos en `[roles.*]` pero el nuevo sistema de routing NO los lee
- `config.toml` tiene secciones `[roles_test.*]` y `[roles_cheap.*]` que no se usan
- El sistema antiguo (`ModelConfig`) lee de TOML, pero el nuevo sistema (`model_routing.py`) no

**Impacto:**
- Configuración fragmentada (TOML vs código)
- Confusión sobre qué configuración tiene prioridad
- Difícil mantener consistencia

---

## 2. ANÁLISIS DE ADECUACIÓN COSTO/CALIDAD POR ROL

### 2.0 Comparativa de Modelos (Precios Aproximados - OpenRouter)

| Modelo | Input (1M tokens) | Output (500K tokens) | Contexto | Velocidad | Uso Ideal |
|--------|-------------------|----------------------|----------|-----------|-----------|
| `google/gemini-2.5-pro` | $0.50 | $1.50 | 2M tokens | Media-Alta | Executive Summary, reportes críticos |
| `google/gemini-2.5-flash` | $0.075 | $0.30 | 1M tokens | Alta | Analyst, Narrative Polish |
| `google/gemini-2.5-flash-lite` | $0.0375 | $0.15 | 1M tokens | Muy Alta | Matcher, Planner, Plotter |
| `deepseek/deepseek-chat` | $0.14 | $0.28 | 64K tokens | Alta | Judge, Economic mode |
| `local/stub` | $0.00 | $0.00 | Ilimitado | Instantánea | CI/CD, tests offline |

**Nota:** Precios aproximados basados en OpenRouter (enero 2025). Pueden variar.

### 2.1 PRODUCTION Profile

| Rol | Modelo Actual | Costo (aprox) | Capacidad | Adecuación | Recomendación |
|-----|---------------|---------------|-----------|------------|---------------|
| **Matcher** | `google/gemini-2.5-flash-lite` | Muy bajo | Alta para clasificación | ✅ ÓPTIMO | Mantener |
| **Planner** | `google/gemini-2.5-flash-lite` | Muy bajo | Alta para queries | ✅ ÓPTIMO | Mantener |
| **Judge** | `deepseek/deepseek-chat` | Muy bajo ($0.14/$0.28) | Buena para evaluación | ✅ ÓPTIMO | Mantener |
| **Analyst** | `google/gemini-2.5-flash` | Medio | Buena para síntesis | ⚠️ REVISAR | Considerar Pro para reportes críticos |
| **Ploter** | `google/gemini-2.5-flash-lite` | Muy bajo | Suficiente para plots | ✅ ÓPTIMO | Mantener |
| **Consolidator Polish** | `google/gemini-2.5-flash` | Medio | Buena para transiciones | ✅ ADECUADO | Mantener |
| **Consolidator Summary** | `google/gemini-2.5-pro` | Alto | Excelente para síntesis ejecutiva | ✅ ÓPTIMO | Mantener (crítico) |

**Análisis PRODUCTION:**
- ✅ **Bien optimizado**: Usa modelos premium solo donde es crítico (Executive Summary)
- ✅ **Costo eficiente**: Flash Lite para tareas simples, Flash para tareas medias, Pro solo para summary
- ✅ **Costo estimado**: ~$0.50 por proyecto (7 items) - Excelente balance calidad/precio
- ⚠️ **Analyst podría mejorarse**: Para reportes críticos (Strategic, Financial, Due_Diligence), considerar Gemini Pro

### 2.2 ECONOMIC Profile

| Rol | Modelo Actual | Costo (aprox) | Capacidad | Adecuación | Recomendación |
|-----|---------------|---------------|-----------|------------|---------------|
| **Matcher** | `google/gemini-2.5-flash-lite` | Muy bajo | Alta | ✅ ÓPTIMO | Mantener |
| **Planner** | `google/gemini-2.5-flash-lite` | Muy bajo | Alta | ✅ ÓPTIMO | Mantener |
| **Judge** | `deepseek/deepseek-chat` | Muy bajo | Buena | ✅ ÓPTIMO | Mantener |
| **Analyst** | `deepseek/deepseek-chat` | Muy bajo | Media-Baja | ⚠️ RIESGO | Considerar Flash si calidad es crítica |
| **Ploter** | `deepseek/deepseek-chat` | Muy bajo | Suficiente | ✅ ADECUADO | Mantener |
| **Consolidator Polish** | `deepseek/deepseek-chat` | Muy bajo | Media | ⚠️ RIESGO | Considerar Flash para mejor coherencia |
| **Consolidator Summary** | `google/gemini-2.5-flash` | Medio | Buena | ✅ ADECUADO | Mantener (balance costo/calidad) |

**Análisis ECONOMIC:**
- ✅ **Muy económico**: DeepSeek en la mayoría de roles reduce costos significativamente
- ✅ **Costo estimado**: ~$0.25 por proyecto (7 items) - **50% más barato que PRODUCTION**
- ⚠️ **Riesgo de calidad**: DeepSeek puede tener menor coherencia narrativa que Gemini Flash
- ⚠️ **Analyst crítico**: Para reportes largos, DeepSeek puede perder contexto o coherencia (contexto limitado a 64K tokens)
- ⚠️ **Consolidator Polish**: DeepSeek puede no generar transiciones tan fluidas como Gemini Flash
- 💡 **Recomendación**: Considerar un "ECONOMIC_PLUS" profile que use Flash para Analyst y Polish

### 2.3 TEST Profile

| Modo | Modelo | Costo | Capacidad | Adecuación | Recomendación |
|------|--------|-------|-----------|------------|---------------|
| **Offline** | `local/stub` | $0 | Determinístico | ✅ PERFECTO | Mantener |
| **Online** | `deepseek/deepseek-chat` | Muy bajo | Media | ✅ ADECUADO | Mantener |

**Análisis TEST:**
- ✅ **Offline perfecto**: LocalStubLLM permite CI/CD sin API keys
- ✅ **Online adecuado**: DeepSeek es suficiente para integration tests
- ✅ **Bien diseñado**: Separación clara entre offline/online

---

## 3. REVISIÓN DE ROBUSTEZ OPERATIVA

### 3.1 Manejo de Errores y Fallbacks

**Fortalezas:**
- ✅ **Retries con backoff exponencial**: Implementado en `planner.py` y `extractor.py` (3 intentos, 2/4/8s)
- ✅ **Detección de rate limits**: Maneja errores 429 específicamente
- ✅ **Fallback en consolidator**: Si falla polish/summary, continúa sin ellos
- ✅ **Fallback en reporter**: Si falla LLM, genera reporte simple con lista de fuentes

**Debilidades:**
- ❌ **Sin fallback de modelos**: Si un modelo falla persistentemente, no hay fallback a otro modelo
- ❌ **Sin validación de API keys**: Si falta API key, el error solo aparece al hacer la llamada
- ❌ **Asyncio handling problemático**: En `processor.py` líneas 1204-1210, `loop.run_until_complete()` puede causar deadlocks
- ⚠️ **Error handling inconsistente**: Algunos módulos tienen retries, otros no

### 3.2 TEST Offline Mode

**Verificación:**
- ✅ **LocalStubLLM implementado**: Funciona correctamente
- ✅ **Skip de LLM calls**: En TEST offline, polish y summary se saltan correctamente
- ✅ **Determinístico**: Outputs predecibles para testing

**Problemas:**
- ⚠️ **Stubs muy simples**: Los outputs de LocalStubLLM son básicos y pueden no reflejar calidad real
- ⚠️ **Falsos positivos**: Tests pueden pasar con stubs pero fallar en producción

### 3.3 Validación y Safeguards

**Fortalezas:**
- ✅ **Validación post-consolidación**: `validate_consolidation()` verifica citas, plots, headings, TOC
- ✅ **Coherencia narrativa**: Checks de transiciones, términos clave, exec summary
- ✅ **Fallback robusto**: Si validación falla, usa versión simplificada

**Debilidades:**
- ⚠️ **Validación básica**: No valida coherencia semántica profunda
- ⚠️ **Sin validación de calidad LLM**: No verifica que el output del LLM tenga sentido

---

## 4. RECOMENDACIONES DE OPTIMIZACIÓN

### 4.1 Críticas (Implementar Urgente)

#### 4.1.1 Integrar model_routing.py con config.toml
**Problema:** Configuración fragmentada entre TOML y código.

**Solución:**
```python
def get_role_config(role: str) -> Dict[str, Any]:
    # 1. Leer de PROFILE_MODELS (defaults)
    # 2. Override con config.toml si existe
    # 3. Override con env vars (máxima prioridad)
```

**Prioridad:** ALTA - Afecta mantenibilidad

#### 4.1.2 Añadir Fallback de Modelos
**Problema:** Si un modelo falla, no hay alternativa.

**Solución:**
```python
FALLBACK_MODELS = {
    "google/gemini-2.5-pro": "google/gemini-2.5-flash",
    "google/gemini-2.5-flash": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat": "google/gemini-2.5-flash-lite",
}
```

**Prioridad:** ALTA - Afecta robustez

#### 4.1.3 Corregir Asyncio Handling
**Problema:** `loop.run_until_complete()` puede causar deadlocks.

**Solución:** Usar `nest_asyncio` o `asyncio.create_task()` con thread pool.

**Prioridad:** ALTA - Puede causar bloqueos

### 4.2 Importantes (Implementar Pronto)

#### 4.2.1 Crear Profile ECONOMIC_PLUS
**Propuesta:**
```python
Profile.ECONOMIC_PLUS: {
    "analyst": {"provider": "openrouter", "model": "google/gemini-2.5-flash", ...},
    "consolidator_polish": {"provider": "openrouter", "model": "google/gemini-2.5-flash", ...},
    # Resto igual que ECONOMIC
}
```

**Beneficio:** Mejor calidad que ECONOMIC sin el costo de PRODUCTION.

#### 4.2.2 Mejorar LocalStubLLM
**Problema:** Stubs muy simples pueden dar falsos positivos.

**Solución:** Hacer stubs más realistas (ya implementado parcialmente, mejorar más).

#### 4.2.3 Validación de API Keys al Inicio
**Problema:** Errores solo aparecen al hacer llamadas.

**Solución:** Validar API keys al inicializar `ModelConfig`.

### 4.3 Mejoras (Opcionales)

#### 4.3.1 Añadir Métricas de Costo
- Trackear costo por rol y perfil
- Logging de tokens usados
- Alertas si costo excede umbral

#### 4.3.2 A/B Testing de Modelos
- Comparar outputs de diferentes modelos
- Métricas de calidad (coherencia, longitud, etc.)

#### 4.3.3 Cache de Respuestas LLM
- Cachear respuestas de modelos deterministas (temperature=0.0)
- Reducir costos en desarrollo/testing

---

## 5. ANÁLISIS DE RIESGOS

### 5.1 Riesgos por Perfil

#### PRODUCTION
- **Riesgo:** Costo alto si se procesan muchos proyectos
- **Mitigación:** ✅ Ya optimizado (Pro solo para summary)
- **Riesgo:** Latencia alta con Gemini Pro
- **Mitigación:** ⚠️ Aceptable para consolidación (no tiempo real)

#### ECONOMIC
- **Riesgo:** Calidad inferior (especialmente Analyst con DeepSeek)
- **Mitigación:** ⚠️ Considerar ECONOMIC_PLUS para reportes críticos
- **Riesgo:** Coherencia narrativa reducida
- **Mitigación:** ⚠️ Validación post-consolidación ayuda pero no suficiente

#### TEST
- **Riesgo:** Falsos positivos con stubs simples
- **Mitigación:** ⚠️ Mejorar LocalStubLLM (en progreso)
- **Riesgo:** Tests offline no reflejan producción
- **Mitigación:** ✅ TEST_ONLINE=1 permite tests reales cuando necesario

### 5.2 Riesgos Generales

1. **Dependencia de APIs externas**
   - **Impacto:** ALTO
   - **Probabilidad:** MEDIA
   - **Mitigación:** ✅ Retries implementados, ⚠️ Falta fallback de modelos

2. **Configuración fragmentada (TOML vs código)**
   - **Impacto:** MEDIO
   - **Probabilidad:** ALTA
   - **Mitigación:** ❌ No implementado (recomendación crítica)

3. **Asyncio deadlocks**
   - **Impacto:** ALTO
   - **Probabilidad:** MEDIA
   - **Mitigación:** ❌ No corregido (recomendación crítica)

---

## 6. EVALUACIÓN FINAL

### 6.1 Robustez General: 7/10

**Fortalezas:**
- ✅ Sistema de routing bien diseñado
- ✅ Retries y manejo de rate limits
- ✅ Fallbacks básicos implementados
- ✅ TEST offline funcional

**Debilidades:**
- ❌ Sin fallback de modelos
- ❌ Configuración fragmentada
- ❌ Asyncio handling problemático
- ⚠️ Validación básica

### 6.2 Optimización Costo/Calidad: 8/10

**PRODUCTION:** 9/10 - Excelente balance
**ECONOMIC:** 7/10 - Muy económico pero riesgo de calidad
**TEST:** 9/10 - Perfecto para su propósito

### 6.3 Recomendaciones Prioritarias

1. **CRÍTICO:** Integrar model_routing.py con config.toml
2. **CRÍTICO:** Añadir fallback de modelos
3. **CRÍTICO:** Corregir asyncio handling
4. **IMPORTANTE:** Crear profile ECONOMIC_PLUS
5. **IMPORTANTE:** Mejorar LocalStubLLM
6. **MEJORA:** Añadir métricas de costo

---

## 7. CONCLUSIÓN

La aplicación es **generalmente robusta** pero tiene **3 problemas críticos** que deben corregirse antes de producción:

1. Configuración fragmentada (TOML vs código)
2. Falta de fallback de modelos
3. Asyncio handling problemático

La optimización costo/calidad está **bien diseñada** pero podría mejorarse con un perfil ECONOMIC_PLUS para casos donde se necesita mejor calidad sin el costo de PRODUCTION.

**Veredicto:** ✅ **ACEPTABLE con correcciones críticas necesarias**
