# =====================================================
# NUEVO PIPELINE DE CONSOLIDACIÓN (POR ETAPAS)
# =====================================================
print(f"      🔄 Iniciando consolidación por etapas...")

try:
    # Preparar chapter_reports en formato para assemble_markdown
    chapter_reports = []
    for item in all_contents_sorted:
        # El contenido ya tiene citas renumeradas
        renumbered_content = renumber_citations_in_text(
            item['content'],
            item['refs'],
            url_to_new_num
        )
        chapter_reports.append({
            'title': item['topic'],
            'content': renumbered_content
        })
    
    # ETAPA 1: Ensamblar markdown básico
    print(f"      📝 Etapa 1: Ensamblando markdown...")
    markdown = assemble_markdown(
        chapter_reports,
        project_specific_context,
        project_name,
        CONFIG
    )
    
    # ETAPA 2: Generar tabla de contenidos
    print(f"      📋 Etapa 2: Generando tabla de contenidos...")
    markdown = generate_toc(markdown)
    
    # ETAPA 3: Renumerar citas (ya están renumeradas, pero validamos)
    print(f"      🔢 Etapa 3: Validando numeración de citas...")
    markdown, citation_map = renumber_citations_new(markdown)
    
    # ETAPA 4: Preservar marcadores de plots
    plot_markers = preserve_plot_markers(markdown)
    if plot_markers:
        print(f"      📊 Encontrados {len(plot_markers)} marcadores de plots")
    
    # ETAPA 5: Narrative Polish (opcional, skip en TEST offline)
    profile = get_active_profile() if get_active_profile else Profile.PRODUCTION
    use_online = is_test_online() if is_test_online else False
    
    if profile != Profile.TEST or use_online:
        print(f"      ✨ Etapa 4: Aplicando polish narrativo...")
        try:
            llm_polish = get_llm_for_role("consolidator_polish") if get_llm_for_role else llm_consolidator
            # Usar asyncio para llamadas async
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop.is_running():
                markdown = loop.run_until_complete(
                    llm_narrative_polish(markdown, project_specific_context, llm_polish, CONFIG)
                )
            else:
                markdown = loop.run_until_complete(
                    llm_narrative_polish(markdown, project_specific_context, llm_polish, CONFIG)
                )
            print(f"      ✅ Polish narrativo aplicado")
        except Exception as e:
            print(f"      ⚠️ Error en polish narrativo: {e}, continuando sin polish")
    else:
        print(f"      ⏭️  Saltando polish narrativo (TEST offline mode)")
    
    # ETAPA 6: Executive Summary (opcional, skip en TEST offline)
    if profile != Profile.TEST or use_online:
        print(f"      📄 Etapa 5: Generando Executive Summary...")
        try:
            llm_summary = get_llm_for_role("consolidator_summary") if get_llm_for_role else llm_consolidator
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop.is_running():
                exec_summary = loop.run_until_complete(
                    llm_exec_summary(markdown, project_specific_context, project_name, llm_summary, CONFIG)
                )
            else:
                exec_summary = loop.run_until_complete(
                    llm_exec_summary(markdown, project_specific_context, project_name, llm_summary, CONFIG)
                )
            
            markdown = inject_exec_summary(markdown, exec_summary)
            print(f"      ✅ Executive Summary generado e insertado")
        except Exception as e:
            print(f"      ⚠️ Error generando Executive Summary: {e}, continuando sin summary")
    else:
        print(f"      ⏭️  Saltando Executive Summary (TEST offline mode)")
    
    # ETAPA 7: Validación
    print(f"      ✅ Etapa 6: Validando consolidación...")
    validation = validate_consolidation(markdown)
    if not validation["valid"]:
        print(f"      ⚠️ Problemas de validación detectados:")
        for issue in validation["issues"]:
            print(f"         - {issue}")
    else:
        print(f"      ✅ Validación exitosa: {validation['citation_count']} citas, {validation['plot_marker_count']} plots, {validation['heading_count']} headings")
    
    # ETAPA 8: Añadir referencias consolidadas
    print(f"      📚 Etapa 7: Añadiendo referencias consolidadas...")
    # Eliminar cualquier sección ## References que pueda existir
    markdown = re.sub(r'\n*##\s*References.*', '', markdown, flags=re.DOTALL | re.IGNORECASE)
    markdown = re.sub(r'\n*##\s*Referencias.*', '', markdown, flags=re.DOTALL | re.IGNORECASE)
    
    # Añadir referencias consolidadas al final
    final_report = markdown.rstrip() + "\n\n" + consolidated_references_section
    
    # Validar referencias finales
    issues = validate_references(final_report)
    print_validation_summary(issues)
    
    print(f"      ✅ Consolidación completada ({len(final_report)} caracteres, {len(unique_refs)} refs únicas)")
    
except Exception as e:
    print(f"      ❌ Error en consolidación por etapas: {e}")
    import traceback
    print(f"      Traceback: {traceback.format_exc()}")
    print(f"      🔄 Usando fallback: concatenación simple de reportes")

    # Fallback: estructura básica si falla el pipeline
    final_report = f"# {project_name}\n\n"
    final_report += "## Índice\n\n"
    final_report += index_simple + "\n\n"

    # Usar contenidos ya procesados (sin referencias duplicadas)
    for i, item in enumerate(all_contents_sorted, 1):
        final_report += f"## {item['topic']}\n\n"
        # Usar contenido renumerado
        renumbered = renumber_citations_in_text(item['content'], item['refs'], url_to_new_num)
        final_report += renumbered + "\n\n"

    # Añadir referencias consolidadas
    final_report += consolidated_references_section
