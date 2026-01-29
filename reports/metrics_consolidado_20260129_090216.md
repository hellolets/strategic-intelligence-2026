# Reporte Consolidado de Métricas

**Fecha de Generación:** 2026-01-29 09:02:16
**Total de Reportes Procesados:** 1

---

## 📊 Resumen Ejecutivo

- **Costo Total:** $0.021029
- **Tokens Totales:** 110,680
- **Fuentes Validadas Total:** 208
- **Fuentes Encontradas Total:** 76
- **Costo Promedio por Reporte:** $0.021029
- **Tokens Promedio por Reporte:** 110,680

---

## 📋 Detalle por Reporte

### 1. 2. Global Defense Investment Outlook

- **Costo:** $0.021029
- **Tokens:** 110,680
- **Fuentes Validadas:** 208
- **Record ID:** recAvV1mLEC69joze

---

## 📊 Métricas Detalladas por Reporte

---

## Reporte 1: 2. Global Defense Investment Outlook

# 📊 Informe de Métricas de Ejecución

**Tema:** 2. Global Defense Investment Outlook  
**Fecha de generación:** 2026-01-29 09:02:15  
**Estado:** ✅ Completado exitosamente

---

## 💰 Análisis de Costes

### Coste Total: $0.021029

### Desglose por Agente:

- **Analyst**: $0.020269 (Modelo: google/gemini-2.5-flash-lite)
- **Planner**: $0.000456 (Modelo: google/gemini-2.5-flash-lite)
- **Judge**: $0.000304 (Modelo: google/gemini-2.5-flash-lite)
- **Búsqueda Web (Tavily/Exa)**: ~$0.0300 (estimación, 3 query(s))

**💵 Coste Total Estimado (LLM + Búsqueda):** $0.051029

### Uso de Tokens:

- **Total de tokens:** 110,680
- **Desglose por rol:**
  - Analyst: 106,680 tokens (96.4%)
  - Planner: 2,400 tokens (2.2%)
  - Judge: 1,600 tokens (1.4%)

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
- **Citas en el texto:** 78
- **Sección References presente:** ✅ Sí

**⚠️ Validación falló pero no se pudieron obtener detalles específicos.**

### 3. Quality Gate:

- **Estado:** ✅ Pasado
- **Confianza del sistema:** 97/100

**Issues detectados:**
  - ⚠️ Solo 4 fuentes únicas. Considerar ampliar búsqueda.

---

## 📚 Análisis de Fuentes

### Resumen General:

- **Fuentes encontradas:** 76
- **Fuentes validadas:** 208
- **Fuentes rechazadas:** 24
- **Tasa de aceptación:** 273.7%

### Calidad de Fuentes Validadas:

- **Score promedio:** 8.3/10
- **Authenticity promedio:** 9.3/10
- **Reliability promedio:** 9.4/10
- **Relevance promedio:** 7.3/10

**Distribución por calidad:**
- 🟢 Alta calidad (≥8): 208 (100.0%)
- 🟡 Calidad media (6-7): 0 (0.0%)
- 🔴 Baja calidad (<6): 0 (0.0%)

**Fuentes de élite (Tier 1-2):** 0 (0.0%)

### Extracción de Evidencias:

- **Fuentes con evidencias extraídas:** 54/208
- **Tasa de extracción:** 26.0%

### Distribución por Dominio:

- `state.gov`: 56 fuente(s) (26.9%)
- `congress.gov`: 24 fuente(s) (11.5%)
- `deloitte.com`: 24 fuente(s) (11.5%)
- `jpmorgan.com`: 24 fuente(s) (11.5%)
- `news.usni.org`: 20 fuente(s) (9.6%)
- `ey.com`: 20 fuente(s) (9.6%)
- `bcg.com`: 20 fuente(s) (9.6%)
- `cfr.org`: 20 fuente(s) (9.6%)

---

## 📝 Análisis del Reporte Final

- **Longitud:** 12,397 caracteres
- **Palabras:** 1,138 palabras
- **Citas en el texto:** 78
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

- **Loops de búsqueda:** 2
- **Queries ejecutadas:** 3
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