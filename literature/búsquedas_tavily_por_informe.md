# Análisis: Búsquedas Tavily por Informe

## 📊 Estadísticas Reales (de logs)

### Datos Observados:
- **Items por informe**: ~9 items (promedio)
- **Queries por item**: 3-6 queries (promedio: ~4 queries)
- **Búsquedas élite (fallback)**: ~60 búsquedas (cuando se activa el fallback)
- **Configuración**: `max_search_queries = 6` (límite máximo)

---

## 🧮 Cálculo de Búsquedas Tavily por Informe

### Componentes:

#### 1. **Búsquedas Principales (por item)**
```
Items × Queries por item = Búsquedas principales
9 items × 4 queries = 36 búsquedas
```

#### 2. **Búsquedas Élite (fallback)**
Se activan cuando:
- No hay Tier 1-2 en resultados
- Menos de 4 resultados encontrados

Cada búsqueda élite ejecuta:
- 5 sitios élite (McKinsey, BCG, Bain, HBR, FT)
- 2 resultados por sitio
- **Total**: 5 queries por búsqueda élite

```
Búsquedas élite × 5 queries = Búsquedas élite totales
~12 búsquedas élite × 5 queries = 60 búsquedas élite
```

#### 3. **Total por Informe**
```
Búsquedas principales: 36
Búsquedas élite: 60
─────────────────────────
TOTAL: ~96 búsquedas Tavily por informe
```

---

## 📈 Desglose Detallado

### Por Item:
- **Queries generadas**: 3-6 queries (promedio: 4)
- **Búsquedas Tavily**: 4 búsquedas (una por query)
- **Búsquedas élite**: 0-2 búsquedas (solo si se activa fallback)

### Por Informe Completo:
- **Items**: 8-12 items (promedio: 9)
- **Búsquedas principales**: 9 × 4 = **36 búsquedas**
- **Búsquedas élite**: ~12 activaciones × 5 queries = **60 búsquedas**
- **TOTAL**: **~96 búsquedas Tavily por informe**

---

## 💰 Costo Estimado

### Costo por Búsqueda:
- **Tavily básico**: ~$0.01 por búsqueda
- **Tavily avanzado** (`search_depth="advanced"`): ~$0.02 por búsqueda

### Costo por Informe:
```
96 búsquedas × $0.02 = $1.92 por informe
```

**Rango estimado**: $1.50 - $2.50 por informe (dependiendo de activación de búsquedas élite)

---

## 🔍 Factores que Afectan el Número

### Aumentan las búsquedas:
1. **Más items**: Más items = más búsquedas
2. **Búsquedas élite activas**: Si muchos items activan fallback
3. **Loops/retries**: Si el quality gate rechaza resultados y se reintenta
4. **Query expansion**: Si está habilitado (actualmente deshabilitado)

### Reducen las búsquedas:
1. **Menos items**: Informes más cortos
2. **Búsquedas exitosas**: Si las búsquedas principales encuentran buenos resultados, no se activa élite
3. **Límite de queries**: `max_search_queries = 6` limita el máximo

---

## 📊 Ejemplo Real (del log analizado)

### Informe con 9 items:
```
Item 1: 6 queries → 6 búsquedas Tavily
Item 2: 4 queries → 4 búsquedas Tavily
Item 3: 5 queries → 5 búsquedas Tavily
Item 4: 3 queries → 3 búsquedas Tavily
Item 5: 6 queries → 6 búsquedas Tavily
Item 6: 4 queries → 4 búsquedas Tavily
Item 7: 3 queries → 3 búsquedas Tavily
Item 8: 4 queries → 4 búsquedas Tavily
Item 9: 5 queries → 5 búsquedas Tavily
─────────────────────────────────────
Total principal: 40 búsquedas

Búsquedas élite (fallback):
- 12 activaciones × 5 queries = 60 búsquedas
─────────────────────────────────────
TOTAL: 100 búsquedas Tavily
```

---

## 🎯 Resumen

### Por Informe Típico:
- **Items**: 9
- **Búsquedas principales**: 36-40
- **Búsquedas élite**: 40-60
- **TOTAL**: **~80-100 búsquedas Tavily por informe**

### Costo:
- **Por búsqueda**: $0.01-0.02
- **Por informe**: **~$1.50-2.00**

### Configuración Actual:
- `max_search_queries = 6` (límite máximo por item)
- `tavily_search_depth = "advanced"` (2 créditos por búsqueda)
- `smart_search_enabled = true` (activa búsquedas élite como fallback)

---

## 💡 Optimizaciones Posibles

### Para Reducir Búsquedas:
1. **Reducir `max_search_queries`**: De 6 a 4 (ahorra ~20% de búsquedas)
2. **Deshabilitar búsquedas élite**: Solo si la calidad es suficiente
3. **Usar `search_depth="basic"`**: Reduce costo a la mitad (pero menos exhaustivo)

### Para Aumentar Calidad:
1. **Aumentar `max_search_queries`**: Más queries = más cobertura
2. **Mantener `search_depth="advanced"`**: Más exhaustivo
3. **Mantener búsquedas élite**: Mejor calidad de fuentes

---

## 📝 Notas Técnicas

### Flujo de Búsquedas:
1. **Planner** genera 3-6 queries por item
2. **Searcher** ejecuta cada query en Tavily
3. **Smart Search** evalúa resultados
4. **Fallback élite** se activa si es necesario (5 queries adicionales)
5. **Loops** pueden reintentar con queries diferentes si falla quality gate

### Límites Configurados:
- `max_search_queries = 6`: Máximo de queries por iteración
- `max_results_per_query = 5`: Resultados por búsqueda
- `tavily_search_depth = "advanced"`: Profundidad de búsqueda
