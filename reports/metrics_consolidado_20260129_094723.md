# Reporte Consolidado de Métricas

**Fecha de Generación:** 2026-01-29 09:47:23
**Total de Reportes Procesados:** 1

---

## 📊 Resumen Ejecutivo

- **Costo Total:** $0.020712
- **Tokens Totales:** 109,012
- **Fuentes Validadas Total:** 56
- **Fuentes Encontradas Total:** 10
- **Costo Promedio por Reporte:** $0.020712
- **Tokens Promedio por Reporte:** 109,012

---

## 📋 Detalle por Reporte

### 1. 2.3 Spain’s positioning and policy stance

- **Costo:** $0.020712
- **Tokens:** 109,012
- **Fuentes Validadas:** 56
- **Record ID:** recbl0yvNLk6c7ubl

---

## 📊 Métricas Detalladas por Reporte

---

## Reporte 1: 2.3 Spain’s positioning and policy stance

# 📊 Informe de Métricas de Ejecución

**Tema:** 2.3 Spain’s positioning and policy stance  
**Fecha de generación:** 2026-01-29 09:47:23  
**Estado:** ✅ Completado exitosamente

---

## 💰 Análisis de Costes

### Coste Total: $0.020712

### Desglose por Agente:

- **Analyst**: $0.020256 (Modelo: google/gemini-2.5-flash-lite)
- **Judge**: $0.000304 (Modelo: google/gemini-2.5-flash-lite)
- **Planner**: $0.000152 (Modelo: google/gemini-2.5-flash-lite)
- **Búsqueda Web (Tavily/Exa)**: ~$0.0100 (estimación, 1 query(s))

**💵 Coste Total Estimado (LLM + Búsqueda):** $0.030712

### Uso de Tokens:

- **Total de tokens:** 109,012
- **Desglose por rol:**
  - Analyst: 106,612 tokens (97.8%)
  - Judge: 1,600 tokens (1.5%)
  - Planner: 800 tokens (0.7%)

---

## 🟢 Análisis de Riesgos de Alucinación

**Nivel de Riesgo General:** BAJO (15/100)

### Riesgos Identificados:

1. 🟡 **Validación de referencias fallida** (MEDIUM)
   Se detectaron 0 problema(s) con la sección de referencias.


### Mitigaciones Implementadas:

✅ **Salvaguardas Anti-Alucinación:**
- Reglas estrictas en prompts del Reporter (prohibición explícita de inventar datos)
- Evaluación multidimensional de fuentes (Authenticity, Reliability, Relevance, Currency)
- Extracción de evidencias antes de evaluación (reducción de ruido)
- Verificación post-generación: ✅ Habilitada
- Validación de referencias: ❌ Fallida o no realizada

✅ **Optimización de Evaluación:**
- Pre-juez con MiMo-V2-Flash (barato) para triage inicial
- Escalamiento a Gemini 2.5 Pro solo para casos críticos/inciertos
- Fast-track para dominios de élite (sin LLM)
- Cache de evaluaciones previas


---

## ✅ Verificaciones Realizadas

### 1. Verificación de Alucinaciones:

- **Estado:** ✅ Realizada
- **Problemas encontrados:** 0
- **Problemas de alta severidad:** 0


### 2. Validación de Referencias:

- **Estado:** ❌ Fallida
- **Citas en el texto:** 53
- **Sección References presente:** ✅ Sí

**⚠️ Validación falló pero no se pudieron obtener detalles específicos.**

### 3. Quality Gate:

- **Estado:** ✅ Pasado
- **Confianza del sistema:** 96/100


---

## 📚 Análisis de Fuentes

### Resumen General:

- **Fuentes encontradas:** 10
- **Fuentes validadas:** 56
- **Fuentes rechazadas:** 3
- **Tasa de aceptación:** 560.0%

### Calidad de Fuentes Validadas:

- **Score promedio:** 8.4/10
- **Authenticity promedio:** 8.9/10
- **Reliability promedio:** 8.7/10
- **Relevance promedio:** 8.4/10

**Distribución por calidad:**
- 🟢 Alta calidad (≥8): 56 (100.0%)
- 🟡 Calidad media (6-7): 0 (0.0%)
- 🔴 Baja calidad (<6): 0 (0.0%)

**Fuentes de élite (Tier 1-2):** 0 (0.0%)

### Extracción de Evidencias:

- **Fuentes con evidencias extraídas:** 24/56
- **Tasa de extracción:** 42.9%

### Distribución por Dominio:

- `exteriores.gob.es`: 16 fuente(s) (28.6%)
- `cooperacionespanola.es`: 8 fuente(s) (14.3%)
- `ficheiros-web.xunta.gal`: 8 fuente(s) (14.3%)
- `bbvaresearch.com`: 8 fuente(s) (14.3%)
- `euronews.com`: 8 fuente(s) (14.3%)
- `en.ara.cat`: 8 fuente(s) (14.3%)

---

## 📝 Análisis del Reporte Final

- **Longitud:** 10,481 caracteres
- **Palabras:** 966 palabras
- **Citas en el texto:** 53
- **Referencias listadas:** ✅ Sí

### Elementos del Reporte:

- Gráficos generados: 0 (❌ Ninguno)
- Sección de referencias: ✅ Presente

---

## 🔧 Métricas de Procesamiento

### Optimizaciones Aplicadas:

- **Cache de evaluaciones:** ✅ Activo (reducción de llamadas LLM redundantes)
- **Fast-track élite:** ✅ Activo (evaluación sin LLM para dominios reconocidos)
- **Extracción de evidencias:** ✅ Activa (pre-procesamiento antes de evaluación)
- **Pre-juez con MiMo:** ✅ Activo (evaluación preliminar barata)
- **Escalamiento selectivo:** ✅ Activo (Gemini solo para casos críticos)

### Rendimiento:

- **Loops de búsqueda:** 0
- **Queries ejecutadas:** 1
- **Quality gate:** ✅ Pasado

---

## 📋 Recomendaciones

1. 🟡 Corregir problemas en la sección de referencias.

---

**Fin del Informe de Métricas**

*Generado automáticamente por el sistema de investigación Deep Research*


---

**Fin del Reporte Consolidado de Métricas**

*Generado automáticamente por el sistema de investigación Deep Research*