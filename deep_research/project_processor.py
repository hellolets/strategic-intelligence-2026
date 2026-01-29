"""
Project Processor: Handles the consolidation of research items into a final report.
Includes high-quality prompt engineering for professional strategic reports.
"""

import os
import time
import re
from concurrent.futures import ThreadPoolExecutor
from .config import (
    items_table,
    proyectos_table,
    airtable_base,
    llm_consolidator,
    REPORT_LANGUAGE,
    TARGET_AUDIENCE,
    REFERENCES_STYLE,
    CONTEXT_SOURCE,
    UPLOAD_TO_R2,
    PROYECTOS_TABLE_NAME,
    CURRENT_CONSOLIDATOR_MODEL,
    CONFIG
)
from .logger import logger
from .utils import cleanup_temp_plots
from .doc_parser import get_project_context
from .reference_consolidator import (
    extract_references_from_report,
    consolidate_references,
    renumber_citations_in_text,
    format_references_section,
    canonicalize_url
)
from .verifier import _remove_system_generated_sections
from .report_generator import generate_docx_from_markdown
from .r2_utils import r2_manager

def process_project_consolidation():
    """Main loop to find and consolidate projects ready for final reporting."""
    logger.log_section("PROJECT CONSOLIDATION", "Consolidando proyectos manualmente")
    
    try:
        proyectos_table.all(max_records=1)
        items_table.all(max_records=1)
        logger.log_success("Conexión exitosa con Airtable")
    except Exception as e:
        logger.log_error(f"Error al conectar con Airtable: {e}")
        raise

    while True:
        try:
            formula = "OR({Status}='Generating items', {Status}='Todo', {Status}='To Do')"
            proyectos = proyectos_table.all(formula=formula)

            if not proyectos:
                time.sleep(3)
                continue

            for proyecto in proyectos:
                proyecto_id = proyecto["id"]
                fields = proyecto.get("fields", {})
                project_name = fields.get("Project_Name", fields.get("Title", f"Proyecto {proyecto_id}"))
                consolidate_specific_project(proyecto_id, project_name, fields)
                time.sleep(0.5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.log_error(f"Error in loop: {e}")
            time.sleep(3)

def check_item_status(item_id):
    try:
        item = items_table.get(item_id)
        fields = item.get("fields", {})
        return {"item_id": item_id, "topic": fields.get("Topic", "Sin tema"), "status": fields.get("Status", "")}
    except:
        return {"item_id": item_id, "topic": "Unknown", "status": "Error"}

def collect_item_report(item_id):
    try:
        item = items_table.get(item_id)
        fields = item.get("fields", {})
        return {"item_id": item_id, "topic": fields.get("Topic", "Sin tema"), "report": fields.get("Final_Report", "")}
    except:
        return {"item_id": item_id, "topic": "Unknown", "report": ""}

def sort_items_by_numbering(topic):
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', topic)
    if match: return tuple(int(x) if x else 0 for x in match.groups())
    return (9999, 0, 0)

def consolidate_specific_project(proyecto_id, project_name, fields):
    """Unified function to consolidate a specific project with high quality."""
    import time as _time
    consolidation_start = _time.time()

    try:
        logger.log_info(f"🚀 Iniciando consolidación: {project_name}")
        proyectos_table.update(proyecto_id, {"Status": "Processing"})

        # 1. Load context
        step_start = _time.time()
        logger.log_info("   📋 Paso 1/5: Cargando contexto del proyecto...")
        project_context = ""
        if CONTEXT_SOURCE == "airtable":
            attachments = fields.get("Context") or fields.get("contexto") or []
            project_context = get_project_context(project_id=proyecto_id, attachments=attachments)
            if not project_context:
                logger.log_error("OBLIGATORY CONTEXT NOT AVAILABLE.")
                proyectos_table.update(proyecto_id, {"Status": "Error"})
                return
        logger.log_info(f"      ✅ Contexto cargado ({len(project_context):,} chars) en {_time.time() - step_start:.1f}s")

        cleanup_temp_plots()

        # 2. Collect Items
        step_start = _time.time()
        item_ids = fields.get("Items_Relacionados", fields.get("Items", []))
        logger.log_info(f"   📦 Paso 2/5: Recolectando {len(item_ids)} items...")

        with ThreadPoolExecutor(max_workers=10) as executor:
            status_results = list(executor.map(check_item_status, item_ids))

        pending_items = [r for r in status_results if r["status"] != "Done"]
        if pending_items:
            logger.log_warning(f"      ⏳ {len(pending_items)} items aún no completados. Esperando...")
            for item in pending_items[:3]:  # Mostrar solo los primeros 3
                logger.log_info(f"         - {item['topic']}: {item['status']}")
            return

        with ThreadPoolExecutor(max_workers=10) as executor:
            report_results = list(executor.map(collect_item_report, item_ids))
        logger.log_info(f"      ✅ {len(report_results)} reportes recolectados en {_time.time() - step_start:.1f}s")
        
        # 3. Process Content & Refs
        step_start = _time.time()
        logger.log_info("   🔗 Paso 3/5: Procesando contenido y referencias...")

        all_contents = []
        all_references = []
        for item in report_results:
            if not item["report"]: continue
            cleaned = _remove_system_generated_sections(item["report"])
            content, refs = extract_references_from_report(cleaned)
            all_contents.append({'topic': item['topic'], 'content': content, 'refs': refs})
            all_references.append(refs)

        # 3. Consolidate References
        # Sort items first so global numbering (1, 2, 3...) follows the report order
        all_contents_sorted = sorted(all_contents, key=lambda x: sort_items_by_numbering(x['topic']))
        
        # Build references list in the sorted order
        all_references_sorted = [item['refs'] for item in all_contents_sorted]
        
        url_to_new_num, unique_refs = consolidate_references(all_references_sorted)

        all_reports_text = ""
        for i, item in enumerate(all_contents_sorted, 1):
            renumbered = renumber_citations_in_text(item['content'], item['refs'], url_to_new_num)
            all_reports_text += f"\n\n{'='*40}\nITEM {i}: {item['topic']}\n{'='*40}\n\n{renumbered}"

        ref_section = format_references_section(unique_refs, (REFERENCES_STYLE or "IEEE").upper())
        logger.log_info(f"      ✅ {len(all_contents)} capítulos procesados, {len(unique_refs)} referencias únicas ({_time.time() - step_start:.1f}s)")

        # 4. Final High-Quality Prompt
        project_description = fields.get("Description", "")
        project_role = fields.get("Role", "")
        company_name = fields.get("Company", "")
        
        # Generate section list for Executive Summary context
        section_list = "\n".join([f"  - {item['topic']}" for item in all_contents_sorted])

        system_msg = f"""You are a SENIOR STRATEGY CONSULTANT at a top-tier firm (McKinsey, BCG, Bain level).
Your task is to ASSEMBLE multiple research chapters into ONE professional, coherent strategic report, PRESERVING THE FULL CONTENT of each chapter.

=== PROJECT CONTEXT ===
PROJECT: "{project_name}"
COMPANY: {company_name}
ROLE: {project_role}
DESCRIPTION: {project_description}

=== SECTIONS TO CONSOLIDATE ===
{section_list}

=== CRITICAL REQUIREMENTS ===

1. **LANGUAGE**: Write entirely in {REPORT_LANGUAGE}. No mixed languages.

2. **AUDIENCE**: {TARGET_AUDIENCE} - Senior executives who need actionable insights, not academic text.

3. **PROFESSIONAL TONE**:
   - Use formal, strategic consulting language
   - NO emojis, NO ###, NO casual symbols
   - Use bullet points sparingly, prefer flowing prose
   - Include specific data, numbers, and concrete recommendations

4. **DOCUMENT STRUCTURE** (STRICT ORDER):

   # {project_name}
   
   [[TOC]]
   \\newpage
   
   ## Executive Summary
   [COMPREHENSIVE 400-500 word summary (4-5 paragraphs) that covers:
    - Purpose and scope of this research
    - Top 5-8 key findings with specific data points
    - Strategic implications for the company
    - 3-5 prioritized actionable recommendations with timeframes]
   
   ## [First Section Title]
   [Full chapter content with its subsections 1.1, 1.2, etc.]
   
   ## [Next Section Title]
   [Continue with all remaining chapters, following their original numbering...]
   
   ## Conclusions and Recommendations
   [Final synthesis with prioritized action items]

5. **HEADING HIERARCHY**:
   - H1 (#): Document title only
   - H2 (##): Major sections (1., 2., 3., etc.)
   - H3 (###): Subsections (1.1, 1.2, 2.1, etc.)
   - H4 (####): Sub-subsections (1.1.1, 1.1.2, etc.)
   - PRESERVE the original numbering from chapter topics

6. **CONTENT PRESERVATION** (CRITICAL — THIS IS THE MOST IMPORTANT REQUIREMENT):
   - PRESERVE the FULL content of every chapter — do NOT summarize, compress, or omit details
   - Include ALL data points, statistics, examples, and analysis from each chapter
   - Add smooth transition paragraphs BETWEEN sections to create narrative flow
   - Standardize terminology throughout the document
   - Cross-reference between sections when relevant (e.g., "As discussed in Section 2.1...")
   - ONLY remove content that is EXACTLY duplicated word-for-word across chapters
   - When similar topics appear in different chapters, KEEP BOTH — they provide different perspectives
   - The final document MUST be approximately the same length as the sum of all input chapters

7. **CHARTS AND VISUALIZATIONS**:
   - PRESERVE all [[PLOT:ID|Title]] markers exactly as they appear
   - Do not modify or remove these markers

8. **CITATIONS AND REFERENCES**:
   - PRESERVE all existing [X] citation numbers exactly as they are.
   - These numbers are already synchronized and unique across the entire consolidated document.
   - Do NOT renumber, Do NOT generate a References section (this is handled programmatically).
   - Ensure citations remain attached to their relevant data/claims after consolidation.

9. **QUALITY CHECKLIST** (ensure all are met):
   ✓ Executive Summary covers ALL main sections
   ✓ No orphan sections without context
   ✓ Data and statistics are properly attributed
   ✓ Recommendations are specific and actionable
   ✓ Document flows logically from analysis to conclusions
   ✓ No placeholder text or TODO items
   ✓ Professional formatting throughout
"""

        user_msg = f"Capítulos a consolidar:\n{all_reports_text}"

        # 4. LLM Consolidation
        step_start = _time.time()
        total_input_chars = len(system_msg) + len(user_msg)
        logger.log_info(f"   🤖 Paso 4/5: Consolidando con LLM ({CURRENT_CONSOLIDATOR_MODEL})...")
        logger.log_info(f"      📊 Input: {total_input_chars:,} chars ({len(all_contents_sorted)} capítulos)")
        logger.log_info(f"      ⏳ Esto puede tardar 1-5 minutos dependiendo del tamaño...")

        response = llm_consolidator.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ])

        final_report = response.content.strip()
        logger.log_info(f"      ✅ Consolidación LLM completada ({len(final_report):,} chars) en {_time.time() - step_start:.1f}s")

        # Construir mapa de referencias para links directos en Word
        reference_map = {str(ref['num']): {'url': ref['url'], 'title': ref['title']} for ref in unique_refs}

        # Post-procesamiento: Registro de Referencias (Traceability)
        registry_path = save_reference_registry(project_name, all_contents_sorted, url_to_new_num)
        if registry_path:
            logger.log_info(f"      📋 Registro de referencias generado: {registry_path}")

        # Post-procesamiento: Asegurar que [[TOC]] esté presente para generar TOC nativo de Word
        if "[[TOC]]" not in final_report:
            logger.log_info("      🔧 Insertando marcador [[TOC]] (el LLM no lo incluyó)")
            # Buscar "## Table of Contents" o similar y reemplazar con [[TOC]]
            import re
            # Patrón para encontrar TOC estático generado por el LLM
            toc_patterns = [
                r'## Table of Contents\n(?:.*?\n)*?(?=\n## |\n# |\Z)',  # TOC section completa
                r'## Tabla de Contenidos\n(?:.*?\n)*?(?=\n## |\n# |\Z)',
                r'## TABLA DE CONTENIDOS\n(?:.*?\n)*?(?=\n## |\n# |\Z)',
                r'## TABLE OF CONTENTS\n(?:.*?\n)*?(?=\n## |\n# |\Z)',
            ]
            replaced = False
            for pattern in toc_patterns:
                if re.search(pattern, final_report, re.IGNORECASE | re.DOTALL):
                    final_report = re.sub(pattern, '[[TOC]]\n' + '\\\\newpage' + '\n\n', final_report, flags=re.IGNORECASE | re.DOTALL)
                    replaced = True
                    logger.log_info("      ✅ TOC estático reemplazado con [[TOC]]")
                    break

            if not replaced:
                # Si no hay TOC, insertar después del título principal (# Title)
                title_match = re.match(r'(# .+?\n)', final_report)
                if title_match:
                    title_end = title_match.end()
                    final_report = final_report[:title_end] + '\n[[TOC]]\n' + '\\\\newpage' + '\n' + final_report[title_end:]
                    logger.log_info("      ✅ [[TOC]] insertado después del título")
        
        # Post-procesamiento: Re-inyectar [[PLOT:...]] markers que el LLM eliminó
        import re as _re
        # Recopilar todos los plot markers de los reportes individuales, asociados a su topic
        all_plot_markers = []  # [(topic, marker_full_text)]
        for item in all_contents_sorted:
            item_content = item.get('content', '')
            markers = _re.findall(r'\[\[PLOT:.*?\]\]', item_content)
            for m in markers:
                all_plot_markers.append((item['topic'], m))

        if all_plot_markers and '[[PLOT:' not in final_report:
            logger.log_info(f"      🔧 Re-inyectando {len(all_plot_markers)} marcadores [[PLOT:]] que el LLM eliminó")
            # Estrategia: para cada plot, buscar la sección correspondiente en el consolidado
            # e insertar el plot marker al final de esa sección
            lines = final_report.split('\n')
            # Construir mapa de secciones: buscar headers que coincidan con topics
            section_indices = {}  # topic_key -> line index of the section's last line before next header
            for i, line in enumerate(lines):
                if line.startswith('#'):
                    section_indices[i] = line

            # Para cada plot, encontrar la mejor sección donde insertarlo
            insertions = {}  # line_index -> [markers]
            for topic, marker in all_plot_markers:
                # Extraer número del topic (e.g., "7.1" from "7.1 Direct investment...")
                topic_num_match = _re.match(r'^(\d+(?:\.\d+)*)\.?\s+', topic)
                if not topic_num_match:
                    continue
                topic_num = topic_num_match.group(1)

                # Buscar la sección en el consolidado que coincida con este topic number
                best_line = None
                for idx in sorted(section_indices.keys()):
                    header = section_indices[idx]
                    # Match: header contiene el número del topic (e.g., "## 7.1" or "## 7.1.")
                    if _re.search(r'#+ *' + _re.escape(topic_num) + r'[\.\s]', header):
                        # Encontrar el final de esta sección (antes del siguiente header)
                        next_headers = [j for j in sorted(section_indices.keys()) if j > idx]
                        if next_headers:
                            # Insertar justo antes del siguiente header
                            end_line = next_headers[0] - 1
                        else:
                            end_line = len(lines) - 1
                        # Retroceder sobre líneas vacías
                        while end_line > idx and lines[end_line].strip() == '':
                            end_line -= 1
                        best_line = end_line
                        break

                if best_line is not None:
                    if best_line not in insertions:
                        insertions[best_line] = []
                    insertions[best_line].append(marker)

            # Insertar markers en orden reverso para no alterar los índices
            for line_idx in sorted(insertions.keys(), reverse=True):
                markers_to_insert = insertions[line_idx]
                for marker in markers_to_insert:
                    lines.insert(line_idx + 1, '')
                    lines.insert(line_idx + 2, marker)
                    lines.insert(line_idx + 3, '')

            final_report = '\n'.join(lines)
            reinjected = final_report.count('[[PLOT:')
            logger.log_info(f"      ✅ {reinjected} marcadores [[PLOT:]] re-inyectados en el documento consolidado")
        elif all_plot_markers:
            logger.log_info(f"      ✅ {len(all_plot_markers)} marcadores [[PLOT:]] preservados por el LLM")

        # 5. Save & Export
        step_start = _time.time()
        logger.log_info("   💾 Paso 5/5: Generando documento Word y guardando...")

        safe_name = (project_name or "unnamed_project").replace(" ", "_").replace("/", "_")
        docx_output_path = os.path.join("reports", f"{safe_name}.docx")
        report_url = None

        # Generate and upload Word document first
        try:
             logger.log_info(f"      📄 Generando DOCX: {docx_output_path}")
             docx_path = generate_docx_from_markdown(final_report, docx_output_path, reference_map=reference_map)
             logger.log_info(f"      ✅ DOCX generado correctamente")
             if docx_path and UPLOAD_TO_R2:
                  logger.log_info(f"      ☁️ Subiendo a R2...")
                  report_url = r2_manager.upload_file(docx_output_path, f"reports/{safe_name}.docx")
                  logger.log_info(f"      ✅ Subido a R2: {report_url[:50]}...")
        except Exception as e:
             logger.log_error(f"DOCX error: {e}")

        update_data = {"Consolidated_Report": final_report, "Status": "Done"}
        if report_url:
            update_data["Report_URL"] = report_url
        
        # Try to save full report, fallback to summary if too large
        try:
            logger.log_info(f"      📤 Guardando en Airtable ({len(final_report):,} chars)...")
            proyectos_table.update(proyecto_id, update_data)
            total_time = _time.time() - consolidation_start
            logger.log_success(f"✅ Proyecto '{project_name}' completado en {total_time:.1f}s")
        except Exception as e:
            error_str = str(e)
            if "422" in error_str or "INVALID_VALUE_FOR_COLUMN" in error_str:
                # Report too large for Airtable field, save summary + link
                logger.log_warning(f"Report too large for Airtable. Saving summary + R2 link...")
                MAX_AIRTABLE_CHARS = 80000
                truncated_report = final_report[:MAX_AIRTABLE_CHARS]
                truncated_report += f"\n\n---\n\n⚠️ **Reporte truncado** (excede límite de Airtable)\n\n"
                if report_url:
                    truncated_report += f"📄 **[Descargar reporte completo (Word)]({report_url})**\n"
                else:
                    truncated_report += f"📁 Reporte completo disponible localmente: `{docx_output_path}`\n"
                
                update_data["Consolidated_Report"] = truncated_report
                try:
                    proyectos_table.update(proyecto_id, update_data)
                    logger.log_success(f"Project '{project_name}' done! (summary + R2 link saved)")
                except Exception as e2:
                    logger.log_error(f"Failed to save even truncated report: {e2}")
                    proyectos_table.update(proyecto_id, {"Status": "Error"})
            else:
                raise e

    except Exception as e:
        logger.log_error(f"Consolidation failed: {e}")
        proyectos_table.update(proyecto_id, {"Status": "Error"})


def save_reference_registry(project_name, all_contents_sorted, url_to_new_num):
    """
    Genera un archivo Markdown con el mapeo de referencias locales a globales para trazabilidad.
    """
    safe_name = (project_name or "unnamed_project").replace(" ", "_").replace("/", "_")
    registry_path = os.path.join("reports", f"reference_registry_{safe_name}.md")
    
    os.makedirs("reports", exist_ok=True)
    
    table = []
    table.append("| Capítulo / Item | Cita Local | Cita Global | Título | URL |")
    table.append("| :--- | :---: | :---: | :--- | :--- |")
    
    for item in all_contents_sorted:
        topic = item['topic']
        for ref in item.get('refs', []):
            local_num = ref.get('original_num', '?')
            url = ref.get('url', '')
            url_norm = canonicalize_url(url) if url else ''
            global_num = url_to_new_num.get(url_norm, '?')
            title = ref.get('title', 'Sin título').replace('|', '-')
            table.append(f"| {topic} | [{local_num}] | [{global_num}] | {title} | {url} |")
    
    registry_content = f"# Registro de Referencias y Trazabilidad\n\n"
    registry_content += f"**Proyecto:** {project_name}\n\n"
    registry_content += "Este documento permite rastrear cómo se han mapeado las citas originales de cada capítulo individual "
    registry_content += "a la numeración global utilizada en el reporte final consolidado.\n\n"
    registry_content += "\n".join(table)
    
    try:
        with open(registry_path, "w", encoding="utf-8") as f:
            f.write(registry_content)
        return registry_path
    except Exception as e:
        from .logger import logger
        logger.log_error(f"Error guardando el registro de referencias: {e}")
        return None
