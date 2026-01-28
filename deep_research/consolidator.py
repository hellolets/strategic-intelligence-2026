"""
Consolidator Module: Deterministic consolidation functions + optional LLM polish.

This module splits consolidation into:
1. Deterministic code functions (assemble, toc, renumber citations)
2. Optional LLM calls (narrative polish, executive summary)
"""

import re
from typing import List, Dict, Tuple, Optional, Any
from collections import OrderedDict


# ==========================================
# DETERMINISTIC FUNCTIONS
# ==========================================

def assemble_markdown(
    chapter_reports: List[Dict[str, Any]],
    project_context: Optional[str] = None,
    project_name: str = "Project",
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Assemble markdown from chapter reports.
    
    Args:
        chapter_reports: List of dicts with 'title' and 'content' (markdown)
        project_context: Optional project-specific context
        project_name: Project name for title
        config: Optional configuration dict
    
    Returns:
        Assembled markdown with title and chapters
    """
    if not chapter_reports:
        return f"# {project_name}\n\n*No chapters available.*\n"
    
    # Build title
    markdown = f"# {project_name}\n\n"
    
    # Add chapters
    for i, chapter in enumerate(chapter_reports, 1):
        title = chapter.get("title", f"Chapter {i}")
        content = chapter.get("content", "")
        
        # Ensure title is H2
        if not title.startswith("## "):
            title = f"## {title}"
        
        markdown += f"{title}\n\n{content}\n\n"
    
    return markdown


def generate_toc(markdown: str) -> str:
    """
    Generate table of contents from markdown headings.
    
    IMPORTANTE: Si existe [[TOC]], NO lo reemplazamos. El marcador [[TOC]] 
    se convertirá en un campo TOC nativo de Word en report_generator.py.
    Si no existe [[TOC]], generamos un TOC en markdown como fallback.
    
    Args:
        markdown: Markdown content with headings
    
    Returns:
        Markdown con [[TOC]] preservado (si existe) o TOC en markdown (si no existe)
    """
    # Si ya existe [[TOC]], preservarlo - NO reemplazarlo
    # El campo TOC de Word se generará automáticamente en report_generator.py
    if "[[TOC]]" in markdown:
        # Solo verificar que hay headings para el TOC
        headings = []
        lines = markdown.split('\n')
        for line in lines:
            match = re.match(r'^(#{1,4})\s+(.+)$', line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headings.append((level, text))
        
        if not headings:
            # Si no hay headings, reemplazar con mensaje
            return markdown.replace("[[TOC]]", "## Table of Contents\n\n*No headings found.*\n")
        
        # Preservar [[TOC]] - se convertirá en campo TOC de Word
        return markdown
    
    # Si NO existe [[TOC]], generar TOC en markdown como fallback
    # Extract headings
    headings = []
    lines = markdown.split('\n')
    
    for line in lines:
        # Match H1, H2, H3, H4
        match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            headings.append((level, text))
    
    if not headings:
        return "## Table of Contents\n\n*No headings found.*\n"
    
    # Generate TOC
    toc_lines = ["## Table of Contents\n"]
    for level, text in headings:
        # Skip H1 (title)
        if level == 1:
            continue
        
        indent = "  " * (level - 2)
        # Create anchor (simple slug)
        anchor = re.sub(r'[^\w\s-]', '', text.lower())
        anchor = re.sub(r'[-\s]+', '-', anchor)
        toc_lines.append(f"{indent}- [{text}](#{anchor})")
    
    toc_markdown = "\n".join(toc_lines) + "\n"
    
    # Insert after first H1
    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('# '):
            # Insert TOC after H1
            lines.insert(i + 1, "")
            lines.insert(i + 2, toc_markdown.strip())
            break
    markdown = '\n'.join(lines)
    
    return markdown


def renumber_citations(markdown: str) -> Tuple[str, Dict[int, int]]:
    """
    Renumber citations sequentially throughout the document.
    First normalizes citations (removes spaces), then renumbers them.
    
    Args:
        markdown: Markdown content with citations [1], [2], etc. (may have spaces like [ 1 ])
    
    Returns:
        (renumbered_markdown, citation_map) where citation_map maps old_num -> new_num
    """
    # PRIMERO: Normalizar citas con espacios [ 1 ] -> [1]
    markdown = re.sub(r'\[\s*(\d+)\s*\]', r'[\1]', markdown)
    
    # También normalizar citas agrupadas con espacios: [ 1 , 2 , 3 ] -> [1, 2, 3]
    def normalize_grouped_citation(match):
        numbers = match.group(1)
        cleaned = ', '.join(n.strip() for n in numbers.split(','))
        return f'[{cleaned}]'
    
    markdown = re.sub(r'\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]', normalize_grouped_citation, markdown)
    
    # Extract ALL citation numbers to build the mapping sequentially
    # We use a pattern that matches both [1] and [1, 2, 3]
    full_pattern = r'\[(\d+(?:\s*,\s*\d+)*)\]'
    
    seen_citations = OrderedDict()  # old_num -> new_num
    
    # First pass: find all unique numbers in order of appearance
    for match in re.finditer(full_pattern, markdown):
        numbers_str = match.group(1)
        numbers = [int(n.strip()) for n in numbers_str.split(',')]
        for old_num in numbers:
            if old_num not in seen_citations:
                new_num = len(seen_citations) + 1
                seen_citations[old_num] = new_num
    
    if not seen_citations:
        return markdown, {}
    
    citation_map = dict(seen_citations)
    
    # Second pass: replace all citations
    def replace_any_citation(match):
        numbers_str = match.group(1)
        numbers = [int(n.strip()) for n in numbers_str.split(',')]
        new_numbers = []
        seen = set()
        for num in numbers:
            new_num = citation_map.get(num)
            if new_num is not None and new_num not in seen:
                new_numbers.append(new_num)
                seen.add(new_num)
        
        if not new_numbers:
            return match.group(0) # Safety fallback
            
        if len(new_numbers) == 1:
            return f'[{new_numbers[0]}]'
        return '[' + ', '.join(str(n) for n in sorted(new_numbers)) + ']'
    
    result = re.sub(full_pattern, replace_any_citation, markdown)
    
    return result, citation_map


def preserve_plot_markers(markdown: str) -> List[str]:
    """
    Extract and preserve plot markers from markdown.
    
    Args:
        markdown: Markdown content
    
    Returns:
        List of plot marker strings (e.g., ["[[PLOT:1]]", "[[PLOT:2|Title]]"])
    """
    plot_pattern = r'\[\[PLOT:(\d+)(?:\|([^\]]+))?\]\]'
    markers = []
    
    for match in re.finditer(plot_pattern, markdown):
        plot_id = match.group(1)
        title = match.group(2) if match.group(2) else None
        if title:
            markers.append(f"[[PLOT:{plot_id}|{title}]]")
        else:
            markers.append(f"[[PLOT:{plot_id}]]")
    
    return markers


def inject_exec_summary(markdown: str, executive_summary: str) -> str:
    """
    Inject executive summary into markdown after TOC.
    
    Args:
        markdown: Markdown content
        executive_summary: Executive summary text (markdown)
    
    Returns:
        Markdown with executive summary inserted
    """
    # Ensure executive summary has proper heading
    if not executive_summary.strip().startswith('##'):
        executive_summary = f"## Executive Summary\n\n{executive_summary}\n"
    
    # Check if executive summary already exists
    if "## Executive Summary" in markdown or "## Resumen Ejecutivo" in markdown:
        # Replace existing executive summary
        import re
        markdown = re.sub(
            r'##\s+(Executive Summary|Resumen Ejecutivo).*?(?=##|$)',
            lambda m: executive_summary.strip() + '\n\n',
            markdown,
            flags=re.IGNORECASE | re.DOTALL
        )
        return markdown
    
    # Find insertion point: after TOC or after first H1
    lines = markdown.split('\n')
    insert_idx = 0
    
    # Look for TOC section (puede ser "## Table of Contents" o "[[TOC]]")
    for i, line in enumerate(lines):
        if "## Table of Contents" in line or "[[TOC]]" in line or "Table of Contents" in line:
            # Find end of TOC section - buscar el siguiente heading H2 que no sea TOC
            for j in range(i + 1, min(i + 50, len(lines))):  # Buscar hasta 50 líneas después
                if lines[j].startswith('##') and "Table of Contents" not in lines[j] and "Executive Summary" not in lines[j]:
                    insert_idx = j
                    break
            # Si no encontramos un heading después del TOC, buscar después de algunas líneas
            if insert_idx == 0:
                # Buscar líneas vacías o saltos de página después del TOC
                for j in range(i + 1, min(i + 20, len(lines))):
                    if lines[j].strip() == "" or lines[j].strip() == "\\newpage" or lines[j].strip() == "\\\\newpage":
                        continue
                    if lines[j].startswith('##'):
                        insert_idx = j
                        break
                # Si aún no encontramos, usar un offset fijo
                if insert_idx == 0:
                    insert_idx = i + 5  # Fallback: después de 5 líneas del TOC
            break
    
    # If no TOC found, insert after first H1
    if insert_idx == 0:
        for i, line in enumerate(lines):
            if line.startswith('# ') and not line.startswith('##'):
                insert_idx = i + 1
                break
    
    # Si aún no encontramos un lugar, insertar al principio después del título
    if insert_idx == 0:
        insert_idx = 1
    
    # Insert executive summary
    lines.insert(insert_idx, "")
    lines.insert(insert_idx + 1, executive_summary.strip())
    lines.insert(insert_idx + 2, "")
    
    return '\n'.join(lines)


# ==========================================
# VALIDATION
# ==========================================

def validate_consolidation(markdown: str) -> Dict[str, Any]:
    """
    Validate consolidated markdown for common issues and narrative coherence.
    
    Args:
        markdown: Markdown content to validate
    
    Returns:
        Dict with validation results:
        - valid: bool
        - issues: List[str]
        - citation_count: int
        - plot_marker_count: int
        - heading_count: int
        - coherence_checks: Dict[str, Any] - Narrative coherence metrics
    """
    issues = []
    coherence_checks = {}
    
    # Check citations (individuales y agrupadas)
    # Extraer todas las citas individuales (pueden estar en grupos como [1, 2, 3])
    individual_citations = re.findall(r'\[(\d+)\]', markdown)
    # También extraer números de citas agrupadas
    grouped_citations = re.findall(r'\[(\d+(?:\s*,\s*\d+)+)\]', markdown)
    for group in grouped_citations:
        # Añadir cada número del grupo
        individual_citations.extend([n.strip() for n in group.split(',')])
    
    citation_nums = [int(c) for c in individual_citations]
    
    if citation_nums:
        max_citation = max(citation_nums)
        expected_range = set(range(1, max_citation + 1))
        actual_range = set(citation_nums)
        
        missing = expected_range - actual_range
        if missing:
            issues.append(f"Missing citations: {sorted(missing)}")
        
        # Check for malformed citations (con espacios)
        # Nota: Estas deberían haberse corregido en renumber_citations(), pero verificamos por si acaso
        malformed = re.findall(r'\[\s+\d+\s+\]', markdown)  # Solo espacios significativos, no espacios mínimos
        if malformed:
            issues.append(f"Malformed citations (with spaces): {len(malformed)} found - estas deberían corregirse automáticamente")
    
    # Check plot markers
    plot_markers = preserve_plot_markers(markdown)
    plot_ids = []
    for marker in plot_markers:
        match = re.search(r'\[\[PLOT:(\d+)\]\]', marker)
        if match:
            plot_ids.append(int(match.group(1)))
    
    if plot_ids:
        max_plot = max(plot_ids)
        expected_plots = set(range(1, max_plot + 1))
        actual_plots = set(plot_ids)
        missing_plots = expected_plots - actual_plots
        if missing_plots:
            issues.append(f"Missing plot markers: {sorted(missing_plots)}")
    
    # Check headings
    headings = re.findall(r'^#{1,4}\s+.+$', markdown, re.MULTILINE)
    if not headings:
        issues.append("No headings found")
    
    # Check TOC
    has_toc = "## Table of Contents" in markdown or "[[TOC]]" in markdown
    if not has_toc:
        issues.append("No Table of Contents found")
    
    # ==========================================
    # NARRATIVE COHERENCE CHECKS
    # ==========================================
    
    # Check 1: Executive Summary presence and structure
    exec_summary_patterns = [
        r'##\s+(Executive Summary|Resumen Ejecutivo)',
        r'##\s+Executive\s+Summary',
    ]
    has_exec_summary = any(re.search(pattern, markdown, re.IGNORECASE) for pattern in exec_summary_patterns)
    coherence_checks["has_exec_summary"] = has_exec_summary
    if not has_exec_summary:
        issues.append("Executive Summary section not found")
    else:
        # Check if exec summary has reasonable length (at least 100 chars)
        exec_match = re.search(r'##\s+(Executive Summary|Resumen Ejecutivo)(.*?)(?=##|$)', markdown, re.IGNORECASE | re.DOTALL)
        if exec_match:
            exec_content = exec_match.group(2).strip()
            if len(exec_content) < 100:
                issues.append("Executive Summary appears too short (< 100 chars)")
            coherence_checks["exec_summary_length"] = len(exec_content)
    
    # Check 2: Chapter transitions (look for transition words/phrases)
    transition_words = [
        r'\b(Además|Furthermore|Moreover|In addition|Additionally)\b',
        r'\b(En este contexto|In this context|In this regard)\b',
        r'\b(Complementando|Complementing|Building on)\b',
        r'\b(Profundizando|Delving deeper|Expanding on)\b',
        r'\b(Por otro lado|On the other hand|However|Nevertheless)\b',
    ]
    transition_count = sum(len(re.findall(pattern, markdown, re.IGNORECASE)) for pattern in transition_words)
    coherence_checks["transition_count"] = transition_count
    if transition_count == 0:
        # Warning, not error - transitions are optional but recommended
        coherence_checks["transition_warning"] = "No transition words/phrases detected (may indicate lack of narrative polish)"
    
    # Check 3: Consistent terminology (basic check for repeated key terms)
    # Extract potential key terms (capitalized words that appear multiple times)
    words = re.findall(r'\b[A-Z][a-z]+\b', markdown)
    word_freq = {}
    for word in words:
        if len(word) > 4:  # Ignore short words
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Find terms that appear frequently (potential key concepts)
    key_terms = {word: count for word, count in word_freq.items() if count >= 3}
    coherence_checks["key_terms_count"] = len(key_terms)
    coherence_checks["key_terms"] = list(key_terms.keys())[:10]  # Top 10
    
    # Check 4: Chapter structure consistency
    # Count H2 headings (main chapters)
    h2_headings = re.findall(r'^##\s+(?!Table of Contents|Executive Summary|Resumen Ejecutivo|References|Referencias)(.+)$', markdown, re.MULTILINE)
    coherence_checks["chapter_count"] = len(h2_headings)
    if len(h2_headings) < 2:
        issues.append("Document appears to have fewer than 2 chapters")
    
    # Check 5: References section presence
    has_references = bool(re.search(r'##\s+(References|Referencias)', markdown, re.IGNORECASE))
    coherence_checks["has_references"] = has_references
    if not has_references:
        issues.append("References section not found")
    
    # Check 6: Citation-to-reference ratio (basic coherence check)
    if has_references:
        # Count references in References section
        ref_section_match = re.search(r'##\s+(References|Referencias)(.*?)(?=##|$)', markdown, re.IGNORECASE | re.DOTALL)
        if ref_section_match:
            ref_section = ref_section_match.group(2)
            ref_count = len(re.findall(r'\[\d+\]', ref_section))
            coherence_checks["references_in_section"] = ref_count
            
            # Contar citas únicas (no duplicadas) para comparación más precisa
            unique_citation_nums = len(set(citation_nums))
            coherence_checks["unique_citations"] = unique_citation_nums
            coherence_checks["total_citation_mentions"] = len(citation_nums)
            
            if ref_count == 0:
                issues.append("References section appears empty")
            elif ref_count < unique_citation_nums * 0.8:  # Should have at least 80% of unique citations
                # El desajuste puede ser normal si hay citas agrupadas [1, 2, 3] que se cuentan múltiples veces
                if len(citation_nums) > unique_citation_nums * 1.5:
                    # Hay muchas citas duplicadas/agrupadas, esto es normal
                    issues.append(f"References section: {ref_count} refs vs {unique_citation_nums} unique citations ({len(citation_nums)} total mentions). Esto es normal si hay citas agrupadas [1, 2, 3].")
                else:
                    issues.append(f"References section may be incomplete ({ref_count} refs vs {unique_citation_nums} unique citations, {len(citation_nums)} total mentions)")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "citation_count": len(citation_nums),
        "plot_marker_count": len(plot_markers),
        "heading_count": len(headings),
        "coherence_checks": coherence_checks,
    }


# ==========================================
# LLM INTEGRATION (OPTIONAL)
# ==========================================

async def llm_narrative_polish(
    markdown: str,
    project_context: Optional[str],
    llm_client: Any,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Apply LLM-based narrative polish to add transitions between chapters.
    
    Args:
        markdown: Markdown content
        project_context: Optional project context
        llm_client: LLM client (LocalStubLLM or real LLM)
        config: Optional configuration
    
    Returns:
        Polished markdown with transitions
    """
    if not markdown:
        return ""
        
    # SEGURIDAD: Si el documento es muy largo, saltar el pulido narrativo
    # Los LLMs tienen límites de tokens de salida (normalmente ~4k-8k tokens, o ~16k-32k caracteres).
    # Si intentamos pulir un documento de 100k caracteres, el LLM truncará la respuesta
    # y perderemos la mayor parte del reporte.
    CHAR_LIMIT_FOR_POLISH = 20000
    if len(markdown) > CHAR_LIMIT_FOR_POLISH:
        print(f"⚠️ Reporte muy extenso ({len(markdown)} chars > {CHAR_LIMIT_FOR_POLISH}). Saltando pulido narrativo para evitar truncamiento por límite de tokens del LLM.")
        return markdown

    system_msg = """You are a professional document editor specializing in narrative coherence.

Your task is to add smooth transitions between chapters in a consolidated research report.

RULES:
1. Add 1-2 sentences at the START of each chapter (after the ## heading) that connect it to the previous chapter
2. Use professional connectors: "Además", "En este contexto", "Complementando lo anterior", "Profundizando en", etc.
3. Maintain the original content - only add transitions, do not rewrite
4. Preserve all citations [X] exactly as they are
5. Preserve all plot markers [[PLOT:ID]] exactly as they are
6. Keep the same vocabulary and terminology throughout

OUTPUT: Return the complete markdown with transitions added."""
    
    user_msg = f"""Apply narrative polish to this document:

{markdown}

{f"Project Context: {project_context}" if project_context else ""}

Add smooth transitions between chapters while preserving all content, citations, and plot markers."""
    
    try:
        if hasattr(llm_client, 'ainvoke'):
            response = await llm_client.ainvoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
        else:
            response = llm_client.invoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
        
        polished = response.content if hasattr(response, 'content') else str(response)
        return polished
    except Exception as e:
        # Fallback: return original
        print(f"⚠️ Error in narrative polish: {e}, using original")
        return markdown


async def llm_exec_summary(
    markdown: str,
    project_context: Optional[str],
    project_name: str,
    llm_client: Any,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate executive summary using LLM.
    
    Args:
        markdown: Full markdown document
        project_context: Optional project context
        project_name: Project name
        llm_client: LLM client (LocalStubLLM or real LLM)
        config: Optional configuration
    
    Returns:
        Executive summary markdown
    """
    system_msg = """You are a senior executive assistant specializing in strategic summaries.

Generate a concise Executive Summary (2-3 paragraphs) that:
1. Synthesizes the key findings from all chapters
2. Highlights strategic opportunities and risks
3. Provides actionable recommendations
4. Uses professional, executive-level language
5. References specific findings from the document when relevant

OUTPUT: Return ONLY the Executive Summary text (markdown format, ## Executive Summary heading)."""
    
    user_msg = f"""Generate an Executive Summary for this research report:

Project: {project_name}

{f"Project Context: {project_context}" if project_context else ""}

Document Content:
{markdown[:10000]}  # Truncate if too long

Generate a comprehensive Executive Summary that synthesizes all key findings."""
    
    try:
        if hasattr(llm_client, 'ainvoke'):
            response = await llm_client.ainvoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
        else:
            response = llm_client.invoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
        
        summary = response.content if hasattr(response, 'content') else str(response)
        
        # Ensure it has the heading
        if not summary.strip().startswith('##'):
            summary = f"## Executive Summary\n\n{summary}"
        
        return summary
    except Exception as e:
        # Fallback: generate basic summary
        print(f"⚠️ Error generating exec summary: {e}, using fallback")
        return f"## Executive Summary\n\n*Summary generation failed. Please review the full document.*\n"
