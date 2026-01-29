import os
import json
import re
import uuid

# IMPORTANTE: Configurar backend 'Agg' ANTES de importar pyplot para evitar errores en server (headless)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import asyncio
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any
from .config import llm_ploter, CURRENT_PLOTER_MODEL, ENABLE_PLOTS, REPORT_LANGUAGE
from .logger import logger
from .r2_utils import r2_manager
from .utils import clean_and_parse_json

# Configuración visual corporativa
CORPORATE_YELLOW = "#FFD700"
CORPORATE_GREY = "#747678"
CORPORATE_BLUE = "#0F4761"
SNC_WHITE = "white"

# Lock global para evitar que múltiples hilos/tareas asíncronas corrompan la state-machine de Matplotlib
plot_lock = asyncio.Lock()

async def evaluate_and_generate_plot(report_text: str, topic: str) -> List[Dict[str, Any]]:
    """
    Analiza un reporte para encontrar datos visualizables y genera el código para los gráficos.
    """
    if not ENABLE_PLOTS:
        return []

    logger.log_info(f"🎨 [PLOTER] Analizando reporte para: {topic[:50]}...")

    system_msg = f"""Eres un experto en visualización de datos especializado en informes corporativos.
Tu objetivo es analizar un reporte de investigación y decidir si algún dato estadístico o tendencia se beneficiaría de un gráfico.

REGLAS DE DISEÑO (ESTILO CORPORATIVO):
1. Librería: Usa exclusivamente Matplotlib o Seaborn.
2. Colores de datos: Usa principalmente Amarillo ({CORPORATE_YELLOW}) y Gris ({CORPORATE_GREY}).
3. Colores de texto: Todo el texto (etiquetas, ejes, leyendas) DEBE ser Azul ({CORPORATE_BLUE}).
4. Fondo: Siempre Blanco ({SNC_WHITE}).
5. Idioma: Todo el contenido del gráfico (nombres de ejes, leyendas, etiquetas) DEBE estar en {REPORT_LANGUAGE}.
6. Estética: 
   - Limpio, profesional, minimalista.
   - SIN marcos (spines) superiores o derechos.
   - SIN TÍTULO interno (el título se gestionará en Word).
7. Formato: El código DEBE guardar el gráfico usando la variable `SAVE_PATH`. No hardcodees rutas.
   OBLIGATORIO: Debes incluir la línea `plt.savefig(SAVE_PATH, bbox_inches='tight')` al final.
   Ejemplo: `plt.savefig(SAVE_PATH, bbox_inches='tight')`
8. Datos: Usa únicamente datos Reales mencionados en el reporte.
9. Título: Genera un título descriptivo para el gráfico (MÁXIMO 15 PALABRAS). Debe estar en {REPORT_LANGUAGE}.
10. Palabra de Figura: Indica la palabra correcta para "Figura" o "Gráfico" en el idioma {REPORT_LANGUAGE} (ej: "Figure", "Figura", "Abbildung").
11. LIBRERÍAS DISPONIBLES: `plt` (matplotlib.pyplot), `sns` (seaborn), `pd` (pandas), `np` (numpy). No intentes importar otras.
12. MANEJO DE DATOS: Si usas datos que representen números (años, valores, porcentajes), asegúrate de convertirlos a float o int ANTES de graficar. Matplotlib puede fallar o mostrar advertencias si usas strings para datos numéricos.
13. PARÁMETROS DE MATPLOTLIB (CRÍTICO):
    - `plt.tick_params()` NO acepta `ha` (horizontal alignment). Usa solo: `labelsize`, `labelcolor`, `length`, `width`, `color`, etc.
    - `ha` solo se usa en `plt.text()`, `ax.text()`, o `plt.xlabel()/ylabel()` para alineación de texto.
    - Para rotar etiquetas de ejes, usa `plt.xticks(rotation=45)` o `plt.setp(ax.get_xticklabels(), rotation=45)`.
    - NO uses `ha` en `tick_params()`, `set_xticklabels()`, o funciones de configuración de ejes.
    - Para colores de texto: usa `color` NO `title_color`, `label_color`, `text_color`, etc.
    - Ejemplos correctos: `plt.title('Título', color='blue')`, `plt.xlabel('X', color='blue')`, `ax.text(x, y, 'texto', color='blue')`
    - En seaborn: `sns.barplot()`, `sns.lineplot()`, etc. NO aceptan `title_color`. Usa `plt.title()` después del plot.
    - NO uses parámetros como `title_color`, `label_color`, `text_color` en funciones de matplotlib/seaborn.

14. INDENTACIÓN (CRÍTICO):
    - Python requiere indentación correcta. Después de cualquier línea que termine con ':', la siguiente línea DEBE estar indentada.
    - Ejemplo CORRECTO:
      if condition:
          plt.gca().spines['top'].set_visible(False)
    - Ejemplo INCORRECTO:
      if condition:
      plt.gca().spines['top'].set_visible(False)  # ❌ Falta indentación
    - Usa 4 espacios por nivel de indentación. NO mezcles tabs y espacios.
    - Si usas bloques if/for/try/with/etc., TODAS las líneas dentro del bloque deben estar indentadas.

15. PARÁMETROS DE plt.legend() (CRÍTICO):
    - `plt.legend()` NO acepta el parámetro `color` directamente.
    - Para cambiar el color del texto de la leyenda, usa `labelcolor` en lugar de `color`.
    - Ejemplo CORRECTO: `plt.legend(labelcolor=CORPORATE_BLUE)` o `plt.legend(labelcolor='blue')`
    - Ejemplo INCORRECTO: `plt.legend(color=CORPORATE_BLUE)`  # ❌ No funciona
    - Alternativa: Crear la leyenda y luego cambiar el color: `leg = plt.legend(); [text.set_color(CORPORATE_BLUE) for text in leg.get_texts()]`

REGLAS DE INTEGRACIÓN:
13. Escribe siempre el bookmark después de un punto final de frase. Después deja un salto de línea, escribe el bookmark y deja otro salto de linea.
14. No escribas bookmarks más abajo de la sección ## References. 
15. Debes escribir los bookmarks en el lugar del texto que corresponde.

FORMATO DE RESPUESTA JSON:
{{
  "plots": [
    {{
      "explanation": "Breve explicación",
      "figure_word": "Palabra localizada para Figura (sin número)",
      "title": "Título descriptivo (sin número ni prefijo)",
      "python_code": "import matplotlib.pyplot as plt\nimport seaborn as sns\n...\nplt.savefig(SAVE_PATH, bbox_inches='tight')",
      "insertion_context": "Frase exacta del reporte"
    }}
  ]
}}

Si no encuentras datos para un gráfico valioso, devuelve {{"plots": []}}.
"""

    user_msg = f"""REPORTE SOBRE: {topic}

CONTENIDO DEL REPORTE:
{report_text}

Analiza el texto y genera hasta 2 gráficos de alto valor si los datos lo permiten."""

    try:
        response = await llm_ploter.ainvoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ])

        content = response.content.strip()
        data = clean_and_parse_json(content)
        plots = data.get("plots", [])
        
        final_plots = []
        import tempfile

        for i, plot in enumerate(plots):
            plot_id = str(uuid.uuid4())[:8]
            code = plot.get("python_code", "")
            if not code:
                continue

            # Crear un archivo temporal para el plot en temp_plots
            os.makedirs("temp_plots", exist_ok=True)
            local_filename = os.path.abspath(f"temp_plots/plot_{plot_id}.png")
            
            try:
                # USAR LOCK: Solo un gráfico se genera a la vez
                async with plot_lock:
                    plt.figure() # Crear nueva figura
                    plt.clf()    # Limpiar cualquier residuo
                    
                    exec_globals = {
                        "plt": plt,
                        "sns": sns,
                        "pd": pd,
                        "np": np,
                        "SAVE_PATH": local_filename,
                        "__name__": "__main__",
                        # Definir variables de color comunes para evitar errores
                        "CORPORATE_YELLOW": CORPORATE_YELLOW,
                        "CORPORATE_GREY": CORPORATE_GREY,
                        "CORPORATE_BLUE": CORPORATE_BLUE,
                        "SNC_WHITE": SNC_WHITE,
                        # Variables de color como alias para evitar errores si el LLM las usa
                        "text_color": CORPORATE_BLUE,
                        "title_color": CORPORATE_BLUE,
                        "label_color": CORPORATE_BLUE,
                        "axis_color": CORPORATE_BLUE,
                        "legend_color": CORPORATE_BLUE,
                    }
                    
                    try:
                        # Limpiar código: remover usos incorrectos de parámetros comunes
                        # Esto previene errores comunes donde el LLM usa parámetros incorrectos
                        code_cleaned = code
                        import re
                        
                        # 1. Remover 'ha' de tick_params
                        pattern_ha = r'tick_params\([^)]*ha\s*=\s*[^,)]+[^)]*\)'
                        if re.search(pattern_ha, code_cleaned):
                            logger.log_warning("⚠️ Detectado uso incorrecto de 'ha' en tick_params, corrigiendo...")
                            code_cleaned = re.sub(r',\s*ha\s*=\s*[^,)]+', '', code_cleaned)
                            code_cleaned = re.sub(r'ha\s*=\s*[^,)]+\s*,', '', code_cleaned)
                        
                        # 2. Reemplazar title_color, label_color, text_color por 'color' en parámetros de función
                        # Patrón para encontrar funciones con title_color, label_color, text_color
                        color_params = ['title_color', 'label_color', 'text_color', 'axis_color', 'legend_color']
                        for param in color_params:
                            # Reemplazar en llamadas de función: func(..., param=value, ...)
                            pattern = rf'{param}\s*=\s*[^,)]+'
                            if re.search(pattern, code_cleaned):
                                logger.log_warning(f"⚠️ Detectado uso incorrecto de '{param}' como parámetro, reemplazando por 'color'...")
                                # Reemplazar param=value por color=value
                                code_cleaned = re.sub(rf'{param}\s*=', 'color=', code_cleaned)
                        
                        # 2b. Detectar y reemplazar uso de variables de color como valores (ej: color=text_color)
                        # Aunque están en exec_globals, es más seguro reemplazarlas por valores directos
                        # para evitar problemas de ámbito o timing
                        for param in color_params:
                            # Buscar color=param (donde param es una variable de color)
                            pattern = rf'color\s*=\s*{param}\b'
                            if re.search(pattern, code_cleaned):
                                logger.log_warning(f"⚠️ Detectado 'color={param}', reemplazando por 'color=CORPORATE_BLUE'...")
                                code_cleaned = re.sub(pattern, 'color=CORPORATE_BLUE', code_cleaned)
                        
                        # 3. Si se usan como variables independientes (ej: text_color = 'blue'), 
                        # ya están definidas en exec_globals, así que no hay problema
                        
                        # 4. Limpiar parámetros inválidos en seaborn plots
                        # Seaborn plots no aceptan title_color directamente
                        sns_functions = ['sns.barplot', 'sns.lineplot', 'sns.scatterplot', 'sns.boxplot', 
                                       'sns.violinplot', 'sns.heatmap', 'sns.histplot', 'sns.countplot']
                        for sns_func in sns_functions:
                            # Remover title_color de llamadas a seaborn
                            pattern = rf'{re.escape(sns_func)}\([^)]*title_color\s*=\s*[^,)]+[^)]*\)'
                            if re.search(pattern, code_cleaned):
                                logger.log_warning(f"⚠️ Detectado 'title_color' en {sns_func}, removiendo...")
                                code_cleaned = re.sub(rf',\s*title_color\s*=\s*[^,)]+', '', code_cleaned)
                                code_cleaned = re.sub(rf'title_color\s*=\s*[^,)]+\s*,', '', code_cleaned)
                        
                        # 5. Corregir uso incorrecto de 'color' en plt.legend()
                        # plt.legend() NO acepta 'color', debe usar 'labelcolor'
                        # Primero, corregir cualquier duplicación existente (labellabelcolor -> labelcolor)
                        code_cleaned = re.sub(r'labellabelcolor', r'labelcolor', code_cleaned)
                        
                        # Verificar que no haya labelcolor ya presente para evitar duplicación
                        legend_pattern = r'(plt|ax)\.legend\([^)]*color\s*=\s*([^,)]+)'
                        # Solo reemplazar si hay color= y NO hay labelcolor ya presente en esa llamada
                        def replace_color_in_legend_safe(match):
                            full_match = match.group(0)
                            # Si ya tiene labelcolor o labellabelcolor, no reemplazar
                            if 'labelcolor' in full_match or 'labellabelcolor' in full_match:
                                return full_match
                            func_name = match.group(1)  # plt o ax
                            prefix = match.group(2) if len(match.groups()) > 2 else ""
                            value = match.group(3) if len(match.groups()) > 2 else match.group(2)
                            # Si el prefix termina con "label", no reemplazar (ya es labelcolor)
                            if prefix and prefix.rstrip().endswith('label'):
                                return full_match
                            logger.log_warning("⚠️ Detectado uso incorrecto de 'color' en plt.legend(), reemplazando por 'labelcolor'...")
                            return f'{func_name}.legend({prefix}labelcolor={value}'
                        
                        # Buscar y reemplazar solo si no hay labelcolor ya presente
                        if re.search(legend_pattern, code_cleaned):
                            code_cleaned = re.sub(
                                r'(plt|ax)\.legend\(([^)]*?)color\s*=\s*([^,)]+)',
                                replace_color_in_legend_safe,
                                code_cleaned
                            )
                            # También manejar el caso donde color está al inicio (sin otros parámetros antes)
                            code_cleaned = re.sub(
                                r'(plt|ax)\.legend\(\s*color\s*=\s*([^,)]+)',
                                lambda m: f'{m.group(1)}.legend(labelcolor={m.group(2)}' if 'labelcolor' not in m.group(0) and 'labellabelcolor' not in m.group(0) else m.group(0),
                                code_cleaned
                            )
                        
                        # Verificación final después de todos los reemplazos: corregir cualquier labellabelcolor restante
                        if 'labellabelcolor' in code_cleaned:
                            logger.log_warning("⚠️ Detectado 'labellabelcolor' después de reemplazos. Corrigiendo...")
                            code_cleaned = re.sub(r'labellabelcolor', r'labelcolor', code_cleaned)
                        
                        # Validar que las variables de color estén disponibles ANTES de ejecutar
                        # Si el código usa text_color, label_color, etc. como variables, asegurar que existan
                        # Ya están en exec_globals, pero verificar que el código no intente redefinirlas incorrectamente
                        
                        
                        # Validar sintaxis antes de ejecutar
                        syntax_fixed = False
                        try:
                            compile(code_cleaned, '<string>', 'exec')
                        except (SyntaxError, IndentationError) as syntax_err:
                            # Intentar corregir errores de indentación automáticamente
                            if "expected an indented block" in str(syntax_err.msg):
                                logger.log_warning(f"⚠️ Error de sintaxis detectado (línea {syntax_err.lineno}): {syntax_err.msg}")
                                logger.log_warning("💡 Detectado error de indentación. Intentando corrección automática...")
                                
                                try:
                                    lines = code_cleaned.split('\n')
                                    if syntax_err.lineno and syntax_err.lineno <= len(lines):
                                        problem_line = lines[syntax_err.lineno - 1]
                                        logger.log_info(f"   Línea problemática ({syntax_err.lineno}): {problem_line}")
                                        # Mostrar contexto (líneas antes y después)
                                        start = max(0, syntax_err.lineno - 5)
                                        end = min(len(lines), syntax_err.lineno + 3)
                                        logger.log_info(f"   Contexto (líneas {start+1}-{end}):")
                                        for i in range(start, end):
                                            marker = ">>>" if i == syntax_err.lineno - 1 else "   "
                                            logger.log_info(f"   {marker} {i+1}: {lines[i]}")
                                            if i == syntax_err.lineno - 1:
                                                # Mostrar qué tipo de bloque se esperaba
                                                if i > 0:
                                                    prev_line = lines[i-1].strip()
                                                    if prev_line.endswith(':'):
                                                        logger.log_info(f"   💡 La línea anterior ({i}) termina con ':', se espera un bloque indentado")
                                    
                                    # Estrategia mejorada: corregir TODAS las líneas que necesitan indentación de una vez
                                    fixed_indent_lines = []
                                    indent_corrections_made = []
                                    
                                    # Primero, identificar la línea problemática específica
                                    problem_line_idx = syntax_err.lineno - 1 if syntax_err.lineno else None
                                    
                                    for i, line in enumerate(lines):
                                        current_line = line
                                        current_stripped = line.strip()
                                        
                                        # Saltar líneas vacías y comentarios (mantenerlas como están)
                                        if not current_stripped or current_stripped.startswith('#'):
                                            fixed_indent_lines.append(line)
                                            continue
                                        
                                        if i > 0:
                                            prev_line = lines[i-1]
                                            prev_line_stripped = prev_line.strip()
                                            prev_indent = len(prev_line) - len(prev_line.lstrip())
                                            current_indent = len(current_line) - len(current_line.lstrip())
                                            
                                            # Detectar si la línea anterior es una continuación (termina con \ o tiene paréntesis/corchetes sin cerrar)
                                            prev_is_continuation = (
                                                prev_line_stripped.endswith('\\') or
                                                prev_line_stripped.count('(') > prev_line_stripped.count(')') or
                                                prev_line_stripped.count('[') > prev_line_stripped.count(']') or
                                                prev_line_stripped.count('{') > prev_line_stripped.count('}')
                                            )
                                            
                                            # Si la línea anterior termina con ':' y la actual no está vacía ni es comentario
                                            # O si la línea anterior es una continuación y la actual no está indentada
                                            needs_indent = False
                                            new_indent = current_indent
                                            if prev_line_stripped.endswith(':'):
                                                # Debe estar indentada más que la anterior (al menos 4 espacios más)
                                                if current_indent <= prev_indent:
                                                    needs_indent = True
                                                    new_indent = prev_indent + 4
                                            elif prev_is_continuation:
                                                # Para continuaciones, debe tener al menos la misma indentación
                                                if current_indent < prev_indent:
                                                    needs_indent = True
                                                    new_indent = prev_indent
                                            
                                            # Si es la línea problemática específica reportada por el error, forzar corrección
                                            if problem_line_idx is not None and i == problem_line_idx:
                                                if not needs_indent and prev_line_stripped.endswith(':'):
                                                    # Forzar indentación para la línea problemática
                                                    needs_indent = True
                                                    new_indent = prev_indent + 4
                                            
                                            if needs_indent:
                                                fixed_line = " " * new_indent + current_line.lstrip()
                                                fixed_indent_lines.append(fixed_line)
                                                indent_corrections_made.append((i+1, current_indent, new_indent))
                                                continue
                                        
                                        fixed_indent_lines.append(line)
                                    
                                    # Si se hicieron correcciones, intentar compilar
                                    if indent_corrections_made:
                                        logger.log_info(f"   🔧 Corrigiendo {len(indent_corrections_made)} línea(s) con problemas de indentación:")
                                        for line_num, old_indent, new_indent in indent_corrections_made:
                                            logger.log_info(f"      Línea {line_num}: {old_indent} -> {new_indent} espacios")
                                        
                                        code_cleaned_indent = '\n'.join(fixed_indent_lines)
                                        try:
                                            compile(code_cleaned_indent, '<string>', 'exec')
                                            logger.log_success("   ✅ Corrección de indentación exitosa. Reintentando ejecución...")
                                            code_cleaned = code_cleaned_indent
                                            syntax_fixed = True  # Marcar como corregido
                                        except (SyntaxError, IndentationError) as indent_fix_err:
                                            logger.log_warning(f"   ⚠️  La corrección automática no resolvió completamente el error: {indent_fix_err.msg}")
                                            logger.log_warning(f"   🔧 Error en línea {indent_fix_err.lineno}. Intentando corrección más agresiva...")
                                            
                                            # Segunda pasada: corrección más agresiva considerando bloques anidados y continuaciones
                                            fixed_indent_lines_v2 = []
                                            
                                            for j, line_v2 in enumerate(lines):
                                                current_stripped = line_v2.strip()
                                                
                                                # Saltar líneas vacías y comentarios
                                                if not current_stripped or current_stripped.startswith('#'):
                                                    fixed_indent_lines_v2.append(line_v2)
                                                    continue
                                                
                                                current_indent = len(line_v2) - len(line_v2.lstrip())
                                                
                                                # Si la línea anterior termina con ':' o es una continuación, necesita indentación
                                                if j > 0:
                                                    prev_line = lines[j-1]
                                                    prev_line_stripped = prev_line.strip()
                                                    prev_indent = len(prev_line) - len(prev_line.lstrip())
                                                    
                                                    # Detectar si la línea anterior es una continuación
                                                    prev_is_continuation = (
                                                        prev_line_stripped.endswith('\\') or
                                                        prev_line_stripped.count('(') > prev_line_stripped.count(')') or
                                                        prev_line_stripped.count('[') > prev_line_stripped.count(']') or
                                                        prev_line_stripped.count('{') > prev_line_stripped.count('}')
                                                    )
                                                    
                                                    if prev_line_stripped.endswith(':'):
                                                        # Debe estar indentada más que la línea anterior
                                                        if current_indent <= prev_indent:
                                                            new_indent = prev_indent + 4
                                                            fixed_line = " " * new_indent + current_stripped
                                                            fixed_indent_lines_v2.append(fixed_line)
                                                            continue
                                                    elif prev_is_continuation:
                                                        # Para continuaciones, debe tener al menos la misma indentación
                                                        if current_indent < prev_indent:
                                                            new_indent = prev_indent
                                                            fixed_line = " " * new_indent + current_stripped
                                                            fixed_indent_lines_v2.append(fixed_line)
                                                            continue
                                                
                                                fixed_indent_lines_v2.append(line_v2)
                                            
                                            # Intentar compilar la versión corregida
                                            code_cleaned_indent_v2 = '\n'.join(fixed_indent_lines_v2)
                                            try:
                                                compile(code_cleaned_indent_v2, '<string>', 'exec')
                                                logger.log_success("   ✅ Corrección agresiva exitosa. Reintentando ejecución...")
                                                code_cleaned = code_cleaned_indent_v2
                                                syntax_fixed = True  # Marcar como corregido
                                            except (SyntaxError, IndentationError) as second_fix_err:
                                                logger.log_error(f"❌ Error de sintaxis en código generado (línea {second_fix_err.lineno}): {second_fix_err.msg}")
                                                logger.log_warning(f"   ⚠️  Corrección agresiva también falló: {second_fix_err.msg}")
                                                logger.log_warning("💡 Sugerencia: Error de indentación complejo detectado.")
                                                logger.log_warning("   - Verifica que todos los bloques después de ':', 'if', 'for', 'try', 'def', etc. estén indentados")
                                                logger.log_warning("   - Python requiere indentación consistente (normalmente 4 espacios por nivel)")
                                                logger.log_warning("   - No mezcles tabs y espacios")
                                                raise syntax_err
                                    else:
                                        logger.log_error(f"❌ Error de sintaxis en código generado (línea {syntax_err.lineno}): {syntax_err.msg}")
                                        logger.log_warning("   ⚠️  No se detectaron líneas que necesiten corrección de indentación.")
                                        logger.log_warning("💡 Sugerencia: Error de indentación detectado.")
                                        logger.log_warning("   - Verifica que todos los bloques después de ':', 'if', 'for', 'try', 'def', etc. estén indentados")
                                        raise syntax_err
                                except Exception as correction_err:
                                    # Si hay un error durante la corrección, registrar y lanzar el error original
                                    logger.log_warning(f"   ⚠️  Error durante la corrección automática: {correction_err}")
                                    logger.log_warning("   Lanzando error de sintaxis original...")
                                    raise syntax_err
                            else:
                                # Otro tipo de error de sintaxis (no indentación)
                                logger.log_error(f"❌ Error de sintaxis en código generado (línea {syntax_err.lineno}): {syntax_err.msg}")
                                lines = code_cleaned.split('\n')
                                if syntax_err.lineno and syntax_err.lineno <= len(lines):
                                    problem_line = lines[syntax_err.lineno - 1]
                                    logger.log_error(f"   Línea problemática ({syntax_err.lineno}): {problem_line}")
                                
                                # Intentar sugerir corrección para otros tipos de errores
                                if "EOL" in syntax_err.msg or "string literal" in syntax_err.msg:
                                    logger.log_warning("💡 Sugerencia: Cadena de texto no cerrada correctamente.")
                                    logger.log_warning("   - Verifica que todas las comillas simples (') y dobles (\") estén balanceadas")
                                raise syntax_err
                        
                        # 6. Asegurar que haya un savefig al final si el LLM lo olvidó
                        if "savefig" not in code_cleaned:
                            logger.log_warning("⚠️ El código no incluía savefig(), añadiéndolo automáticamente...")
                            code_cleaned += "\nplt.savefig(SAVE_PATH, bbox_inches='tight')"
                        
                        # 7. Reemplazar plt.show() por un comentario para evitar bloqueos
                        code_cleaned = code_cleaned.replace("plt.show()", "# plt.show()")
                        
                        # Ejecutar código generado (limpiado o corregido)
                        try:
                            exec(code_cleaned, exec_globals)
                        except (SyntaxError, IndentationError) as exec_syntax_err:
                            # Si aún hay error de sintaxis después de la corrección, lanzarlo
                            logger.log_error(f"❌ Error de sintaxis persistente después de corrección automática: {exec_syntax_err}")
                            raise exec_syntax_err
                        # No cerramos aquí para verificar existencia primero
                    except (SyntaxError, IndentationError) as syntax_err:
                        # Error de sintaxis ya manejado arriba, re-lanzar
                        raise syntax_err
                    except Exception as exec_err:
                        # Log del código que falló para facilitar depuración
                        logger.log_error("❌ Error ejecutando código de plot:")
                        logger.log_error(f"   Tipo de error: {type(exec_err).__name__}")
                        logger.log_error(f"   Mensaje: {str(exec_err)}")
                        
                        # Mostrar código original y limpiado para comparación
                        logger.log_info("📋 Código original generado por LLM:")
                        logger.log_info(f"\n{code}")
                        if code_cleaned != code:
                            logger.log_info("📋 Código después de limpieza:")
                            logger.log_info(f"\n{code_cleaned}")
                        
                        # Intentar sugerir corrección según el tipo de error
                        err_str = str(exec_err).lower()
                        if "eol" in err_str and "string literal" in err_str:
                            logger.log_warning("💡 Sugerencia: Cadena de texto no cerrada correctamente. Verifica que todas las comillas (simples ' o dobles \") estén balanceadas.")
                        elif "ha" in err_str and "not recognized" in err_str:
                            logger.log_warning("💡 Sugerencia: El parámetro 'ha' no es válido en tick_params(). Usa 'rotation' en xticks/yticks para rotar etiquetas.")
                        elif "wedge sizes" in err_str and "non negative" in err_str:
                            # Error específico: valores negativos en gráfico de pastel
                            logger.log_warning("💡 Detectado error: valores negativos en gráfico de pastel. Intentando corrección automática...")
                            code_cleaned_pie = code_cleaned
                            
                            # Buscar y corregir cálculos de sizes que puedan resultar en valores negativos
                            # Patrón: sizes = [val1, val2, 100 - (val1 + val2)] o similar
                            def fix_negative_sizes(match):
                                var_name = match.group(1)  # 'sizes' o similar
                                values_str = match.group(2)  # contenido de la lista
                                
                                # Intentar evaluar la expresión de forma segura
                                try:
                                    # Reemplazar variables conocidas si existen
                                    safe_dict = {'__builtins__': {}}
                                    # Añadir funciones matemáticas básicas
                                    import math
                                    safe_dict.update({k: getattr(math, k) for k in dir(math) if not k.startswith('_')})
                                    
                                    # Evaluar cada elemento de la lista
                                    values = []
                                    for item in values_str.split(','):
                                        item = item.strip()
                                        try:
                                            # Intentar evaluar la expresión
                                            val = eval(item, safe_dict)
                                            values.append(max(0, float(val)))  # Asegurar no negativo
                                        except:
                                            # Si no se puede evaluar, mantener el original
                                            values.append(item)
                                    
                                    # Si todos los valores son numéricos, verificar suma
                                    numeric_values = [v for v in values if isinstance(v, (int, float))]
                                    if len(numeric_values) == len(values) and sum(numeric_values) > 100:
                                        # Normalizar a 100
                                        total = sum(numeric_values)
                                        values = [v * 100 / total for v in numeric_values]
                                    
                                    # Reconstruir la lista
                                    values_str_fixed = '[' + ', '.join(str(v) for v in values) + ']'
                                    return f'{var_name} = {values_str_fixed}'
                                except:
                                    # Si no se puede corregir automáticamente, usar max(0, ...)
                                    return f'{var_name} = [max(0, x) for x in {match.group(2)}]'
                            
                            # Buscar patrones como: sizes = [73, 34, 100 - (73 + 34)]
                            code_cleaned_pie = re.sub(
                                r'(\w+)\s*=\s*\[([^\]]+)\]',
                                lambda m: fix_negative_sizes(m) if 'sizes' in m.group(1).lower() or 'pie' in code_cleaned_pie.lower() else m.group(0),
                                code_cleaned_pie
                            )
                            
                            # También añadir validación antes de plt.pie()
                            if 'plt.pie' in code_cleaned_pie or 'ax.pie' in code_cleaned_pie:
                                # Buscar la variable sizes y añadir validación
                                sizes_pattern = r'(\w+)\s*=\s*\[([^\]]+)\]'
                                sizes_matches = list(re.finditer(sizes_pattern, code_cleaned_pie))
                                for match in sizes_matches:
                                    var_name = match.group(1)
                                    # Si es una variable relacionada con sizes
                                    if 'size' in var_name.lower():
                                        # Encontrar el final de la línea
                                        line_end = code_cleaned_pie.find('\n', match.end())
                                        if line_end == -1:
                                            line_end = len(code_cleaned_pie)
                                        
                                        # Añadir validación después de la definición para corregir valores negativos
                                        validation_code = f"\n# Corregir valores negativos (matplotlib requiere valores >= 0)\n{var_name} = [max(0, float(x)) for x in {var_name}]"
                                        code_cleaned_pie = code_cleaned_pie[:line_end] + validation_code + code_cleaned_pie[line_end:]
                                        logger.log_warning(f"   ✅ Añadida validación para corregir valores negativos en '{var_name}'")
                                        break
                            
                            if code_cleaned_pie != code_cleaned:
                                try:
                                    exec(code_cleaned_pie, exec_globals)
                                    logger.log_success("✅ Código corregido automáticamente (valores negativos en pie chart) y ejecutado con éxito")
                                    code_cleaned = code_cleaned_pie
                                    code = code_cleaned  # Actualizar código para uso posterior
                                except Exception as retry_err:
                                    logger.log_warning(f"   ⚠️ Corrección automática falló: {retry_err}")
                                    logger.log_warning("💡 Sugerencia: Los valores en plt.pie() deben ser no negativos.")
                                    logger.log_warning("   - Verifica que la suma de los valores no exceda 100% si estás usando porcentajes")
                                    logger.log_warning("   - Usa max(0, valor) para asegurar valores no negativos")
                                    logger.log_warning("   - Ejemplo: sizes = [max(0, x) for x in [73, 34, 100 - (73 + 34)]]")
                                    raise exec_err
                            else:
                                logger.log_warning("💡 Sugerencia: Los valores en plt.pie() deben ser no negativos.")
                                logger.log_warning("   - Verifica que la suma de los valores no exceda 100% si estás usando porcentajes")
                                logger.log_warning("   - Usa max(0, valor) para asegurar valores no negativos")
                                raise exec_err
                        elif "legend" in err_str and ("unexpected keyword argument 'color'" in err_str or "labellabelcolor" in err_str):
                            # Error específico: plt.legend() no acepta color, o hay duplicación de labelcolor
                            code_cleaned_legend = code_cleaned
                            
                            if "labellabelcolor" in err_str:
                                logger.log_warning("💡 Detectado error: 'labellabelcolor' (duplicación). Corrigiendo...")
                                # Primero, corregir la duplicación: labellabelcolor -> labelcolor
                                code_cleaned_legend = re.sub(
                                    r'labellabelcolor',
                                    r'labelcolor',
                                    code_cleaned_legend
                                )
                            else:
                                logger.log_warning("💡 Detectado error: plt.legend() no acepta 'color'. Intentando corrección automática...")
                            
                            # Función helper para reemplazar color sin duplicar labelcolor
                            def replace_color_safe(match):
                                full_match = match.group(0)
                                prefix = match.group(1)
                                value = match.group(2)
                                # Si el prefix termina con "label", no reemplazar (ya es labelcolor)
                                if prefix.rstrip().endswith('label'):
                                    return full_match
                                # Extraer el nombre de la función (plt.legend o ax.legend)
                                func_name = full_match.split('(')[0]
                                return f'{func_name}({prefix}labelcolor={value}'
                            
                            # Reemplazar color= por labelcolor= en plt.legend(), evitando duplicar labelcolor
                            # Solo reemplazar si la llamada NO contiene ya labelcolor
                            def replace_if_no_labelcolor(match):
                                full_match = match.group(0)
                                # Si ya tiene labelcolor, no reemplazar
                                if 'labelcolor' in full_match:
                                    return full_match
                                return replace_color_safe(match)
                            
                            code_cleaned_legend = re.sub(
                                r'(plt|ax)\.legend\(([^)]*?)color\s*=\s*([^,)]+)',
                                replace_if_no_labelcolor,
                                code_cleaned_legend
                            )
                            # También manejar el caso donde color está al inicio
                            code_cleaned_legend = re.sub(
                                r'(plt|ax)\.legend\(\s*color\s*=\s*([^,)]+)',
                                lambda m: f'{m.group(1)}.legend(labelcolor={m.group(2)}' if 'labelcolor' not in m.group(0) else m.group(0),
                                code_cleaned_legend
                            )
                            
                            if code_cleaned_legend != code_cleaned:
                                try:
                                    exec(code_cleaned_legend, exec_globals)
                                    logger.log_success("✅ Código corregido automáticamente (color -> labelcolor en legend) y ejecutado con éxito")
                                    code_cleaned = code_cleaned_legend
                                    code = code_cleaned  # Actualizar código para uso posterior
                                except Exception as retry_err:
                                    logger.log_warning(f"   ⚠️ Corrección automática falló: {retry_err}")
                                    logger.log_warning("💡 Sugerencia: plt.legend() NO acepta 'color'. Usa 'labelcolor' en su lugar.")
                                    logger.log_warning("   Ejemplo correcto: plt.legend(labelcolor=CORPORATE_BLUE)")
                                    raise exec_err
                            else:
                                logger.log_warning("💡 Sugerencia: plt.legend() NO acepta 'color'. Usa 'labelcolor' en su lugar.")
                                logger.log_warning("   Ejemplo correcto: plt.legend(labelcolor=CORPORATE_BLUE)")
                                raise exec_err
                        elif "title_color" in err_str or "label_color" in err_str or "text_color" in err_str or "axis_color" in err_str or "legend_color" in err_str:
                            # Si el error es "not defined" para estas variables, intentar reemplazarlas en el código
                            if "not defined" in err_str:
                                logger.log_warning("💡 Detectado uso de variable de color no definida. Intentando reemplazo automático...")
                                # Intentar reemplazar usos de estas variables por el valor directo
                                for param in ['text_color', 'title_color', 'label_color', 'axis_color', 'legend_color']:
                                    # Reemplazar color=param por color=CORPORATE_BLUE
                                    pattern = rf'color\s*=\s*{param}\b'
                                    if re.search(pattern, code_cleaned):
                                        logger.log_info(f"   Reemplazando 'color={param}' por 'color=CORPORATE_BLUE'...")
                                        code_cleaned = re.sub(pattern, 'color=CORPORATE_BLUE', code_cleaned)
                                    # Reemplazar param por CORPORATE_BLUE cuando se usa directamente
                                    pattern = rf'{param}\b(?!\s*=)'
                                    if re.search(pattern, code_cleaned) and f'color={param}' not in code_cleaned:
                                        # Solo si no está siendo usado como parámetro
                                        logger.log_info(f"   Reemplazando uso directo de '{param}' por 'CORPORATE_BLUE'...")
                                        code_cleaned = re.sub(rf'\b{param}\b', 'CORPORATE_BLUE', code_cleaned)
                                
                                # Intentar ejecutar de nuevo con el código corregido
                                try:
                                    exec(code_cleaned, exec_globals)
                                    logger.log_success("✅ Código corregido automáticamente y ejecutado con éxito")
                                    code = code_cleaned  # Actualizar código para uso posterior
                                except Exception as retry_err:
                                    logger.log_warning(f"   ⚠️ Corrección automática falló: {retry_err}")
                                    logger.log_warning("💡 Sugerencia: Usa 'color' directamente con el valor, por ejemplo: plt.title('Título', color=CORPORATE_BLUE)")
                                    raise exec_err  # Lanzar el error original
                            else:
                                logger.log_warning("💡 Sugerencia: Usa 'color' en lugar de 'title_color', 'label_color', o 'text_color'. Ejemplo: plt.title('Título', color=CORPORATE_BLUE)")
                        elif "not defined" in err_str:
                            logger.log_warning("💡 Sugerencia: Variable o función no definida. Verifica que todas las variables estén definidas antes de usarlas.")
                        raise exec_err
                    finally:
                        # Asegurar limpieza siempre
                        plt.close('all')
                
                if os.path.exists(local_filename):
                    # Subir a R2
                    r2_url = r2_manager.upload_file(local_filename, f"plots/{plot_id}.png")
                    
                    title = plot.get("title", "Gráfico")
                    fig_word = plot.get("figure_word", "Figura")
                    bookmark = f"[[PLOT:{plot_id}|{fig_word}|{title}]]"
                    
                    final_plots.append({
                        "id": plot_id,
                        "title": title,
                        "figure_word": fig_word,
                        "code": code,
                        "url": r2_url,
                        "path": local_filename,
                        "bookmark": bookmark,
                        "context": plot.get("insertion_context", "")
                    })
                    logger.log_success(f"✅ Gráfico generado y subido a R2: {bookmark}")
                else:
                    logger.log_error(f"❌ El código ejecutado no generó el archivo esperado.")
                    logger.log_info("📋 Código que falló en generar el archivo:")
                    logger.log_info(f"\n{code_cleaned}")

            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                logger.log_error(f"❌ Error ejecutando código de plot:")
                logger.log_error(f"   Tipo: {type(e).__name__}")
                logger.log_error(f"   Mensaje: {str(e)}")
                logger.log_error(f"   Traceback completo:")
                logger.log_error(f"\n{error_traceback}")
                
                # Mostrar información del plot que falló
                logger.log_info(f"📋 Plot que falló:")
                logger.log_info(f"   - ID: {plot_id}")
                logger.log_info(f"   - Título: {plot.get('title', 'N/A')}")
                logger.log_info(f"   - Código (primeros 200 chars): {code[:200] if code else 'N/A'}...")
                # Limpieza inmediata solo si falló o es necesario
                # NOTA: No eliminamos local_filename si tuvo éxito para que 
                # report_generator pueda usarlo sin re-descargar de R2
                pass

        return final_plots

    except Exception as e:
        logger.log_error(f"❌ Error en Ploter: {e}")
        return []

def insert_plots_in_markdown(report_md: str, plots: List[Dict[str, Any]]) -> str:
    """
    Inserta los marcadores de posición (bookmarks) en el reporte Markdown.

    MEJORA 2026-01: Búsqueda fuzzy de contexto
    - Primero intenta coincidencia exacta
    - Luego búsqueda fuzzy por similitud (Levenshtein)
    - Fallback: buscar sección más relevante por keywords del título
    """
    from difflib import SequenceMatcher

    def _find_best_paragraph_match(context: str, paragraphs: List[str], min_similarity: float = 0.5) -> int:
        """Encuentra el párrafo más similar al contexto usando SequenceMatcher."""
        if not context:
            return -1

        best_match = -1
        best_score = 0

        context_lower = context.lower().strip()

        for i, para in enumerate(paragraphs):
            if not para.strip():
                continue
            para_lower = para.lower().strip()
            # Calcular similitud
            score = SequenceMatcher(None, context_lower, para_lower).ratio()
            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = i

        return best_match

    def _find_section_by_keywords(title: str, paragraphs: List[str]) -> int:
        """Encuentra la sección más relevante basándose en keywords del título."""
        if not title:
            return -1

        # Extraer keywords significativos del título (ignorar palabras comunes)
        stop_words = {'the', 'a', 'an', 'of', 'in', 'to', 'for', 'and', 'or', 'by', 'on', 'at', 'de', 'la', 'el', 'en', 'y', 'del', 'los', 'las', 'por', 'para', 'con'}
        title_words = [w.lower() for w in re.split(r'\W+', title) if w.lower() not in stop_words and len(w) > 2]

        if not title_words:
            return -1

        best_match = -1
        best_count = 0

        for i, para in enumerate(paragraphs):
            if not para.strip():
                continue
            para_lower = para.lower()
            # Contar cuántas keywords aparecen
            matches = sum(1 for word in title_words if word in para_lower)
            if matches > best_count:
                best_count = matches
                best_match = i

        # Solo retornar si al menos la mitad de las keywords coinciden
        if best_count >= max(1, len(title_words) // 2):
            return best_match
        return -1

    plots_inserted = 0
    plots_fuzzy = 0
    plots_keywords = 0
    plots_end = 0

    for plot in plots:
        context = plot.get("context", "")
        bookmark = plot.get("bookmark", "")
        title = plot.get("title", "")

        if not bookmark:
            continue

        # 1. INTENTO 1: Coincidencia exacta
        if context and context in report_md:
            report_md = report_md.replace(context, f"{context}\n\n{bookmark}\n", 1)
            plots_inserted += 1
            logger.log_info(f"   📍 Plot insertado por coincidencia exacta: {title[:40]}...")
            continue

        # 2. INTENTO 2: Búsqueda fuzzy
        paragraphs = report_md.split('\n\n')
        best_idx = _find_best_paragraph_match(context, paragraphs, min_similarity=0.5)

        if best_idx >= 0:
            paragraphs[best_idx] = f"{paragraphs[best_idx]}\n\n{bookmark}"
            report_md = '\n\n'.join(paragraphs)
            plots_fuzzy += 1
            logger.log_info(f"   📍 Plot insertado por búsqueda fuzzy (similitud): {title[:40]}...")
            continue

        # 3. INTENTO 3: Buscar por keywords del título
        keyword_idx = _find_section_by_keywords(title, paragraphs)

        if keyword_idx >= 0:
            paragraphs = report_md.split('\n\n')
            paragraphs[keyword_idx] = f"{paragraphs[keyword_idx]}\n\n{bookmark}"
            report_md = '\n\n'.join(paragraphs)
            plots_keywords += 1
            logger.log_info(f"   📍 Plot insertado por keywords del título: {title[:40]}...")
            continue

        # 4. FALLBACK: Añadir al final del documento
        report_md += f"\n\n{bookmark}\n"
        plots_end += 1
        logger.log_warning(f"   ⚠️  Plot añadido al final (no se encontró contexto): {title[:40]}...")

    # Log resumen
    total = plots_inserted + plots_fuzzy + plots_keywords + plots_end
    if total > 0:
        logger.log_info(f"   📊 Resumen de inserción de plots: {plots_inserted} exactos, {plots_fuzzy} fuzzy, {plots_keywords} por keywords, {plots_end} al final")

    return report_md
