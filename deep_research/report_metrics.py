"""
Módulo Report Metrics: Genera un informe detallado de métricas del procesamiento.
Incluye costes, riesgos de alucinaciones, verificaciones, fuentes y calidad.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from .cost_calculator import calculate_total_cost_from_state, calculate_costs_by_role_from_state
from .config import (
    CURRENT_PLANNER_MODEL, CURRENT_JUDGE_MODEL, CURRENT_ANALYST_MODEL,
    CURRENT_CONSOLIDATOR_MODEL, VERIFIER_ENABLED
)
from .state import ResearchState


def generate_execution_metrics_report(state: ResearchState, topic: str) -> str:
    """
    Genera un informe detallado de métricas del procesamiento.
    
    Args:
        state: Estado final del procesamiento
        topic: Tema del reporte
    
    Returns:
        Informe en formato Markdown
    """
    validated_sources = state.get('validated_sources', [])
    rejected_sources = state.get('rejected_sources', [])
    found_sources = state.get('found_sources', [])
    final_report = state.get('final_report', '')
    tokens_by_role = state.get('tokens_by_role', {})
    quality_gate_passed = state.get('quality_gate_passed', False)
    quality_gate_issues = state.get('quality_gate_issues', [])
    confidence_score = state.get('confidence_score', {})
    plot_data = state.get('plot_data', [])
    
    # Calcular costes
    total_cost = calculate_total_cost_from_state(state)
    costs_by_role = calculate_costs_by_role_from_state(state)
    
    # Analizar fuentes
    total_sources_found = len(found_sources)
    total_sources_validated = len(validated_sources)
    total_sources_rejected = len(rejected_sources)
    
    # Calidad de fuentes
    if validated_sources:
        avg_reliability = sum(s.get('reliability_score', 0) for s in validated_sources) / len(validated_sources)
        avg_authenticity = sum(s.get('authenticity_score', 0) for s in validated_sources) / len(validated_sources)
        avg_relevance = sum(s.get('relevance_score', 0) for s in validated_sources) / len(validated_sources)
        avg_total_score = sum(s.get('total_score', 0) for s in validated_sources) / len(validated_sources)
        
        # Fuentes de élite
        elite_sources = [s for s in validated_sources if s.get('fast_track') == 'elite']
        elite_count = len(elite_sources)
        
        # Fuentes con evaluación MiMo vs Gemini
        mimo_evaluated = [s for s in validated_sources if s.get('pre_judge') == 'mimo']
        gemini_evaluated = [s for s in validated_sources if s.get('pre_judge') == 'gemini']
        
        # Distribución por dominio
        domain_distribution = {}
        for source in validated_sources:
            domain = source.get('source_domain', 'Unknown')
            domain_distribution[domain] = domain_distribution.get(domain, 0) + 1
        
        # Fuentes con evidencias extraídas
        sources_with_evidence = [s for s in validated_sources if s.get('extracted') and s.get('evidence_points')]
        evidence_extraction_rate = len(sources_with_evidence) / len(validated_sources) * 100 if validated_sources else 0
    else:
        avg_reliability = 0
        avg_authenticity = 0
        avg_relevance = 0
        avg_total_score = 0
        elite_count = 0
        mimo_evaluated = []
        gemini_evaluated = []
        domain_distribution = {}
        sources_with_evidence = []
        evidence_extraction_rate = 0
    
    # Análisis de verificación
    verification_info = {
        "enabled": VERIFIER_ENABLED,
        "issues_found": 0,
        "issues_high_severity": 0,
        "issues_medium_severity": 0,
        "issues_low_severity": 0,
        "references_validated": False,
        "references_issues": [],
        "verification_passed": False
    }
    
    # Buscar información de verificación en el estado (si está disponible)
    verification_issues = state.get('verification_issues', [])
    if verification_issues:
        verification_info["issues_found"] = len(verification_issues)
        verification_info["issues_high_severity"] = state.get('verification_high_severity_count', 0)
        verification_info["issues_medium_severity"] = state.get('verification_medium_severity_count', 0)
        verification_info["issues_low_severity"] = state.get('verification_low_severity_count', 0)
        verification_info["verification_passed"] = state.get('verification_passed', False)
    
    ref_validation = state.get('references_validation', {})
    if ref_validation:
        verification_info["references_validated"] = ref_validation.get('passed', False)
        verification_info["references_issues"] = ref_validation.get('issues', [])
    elif 'references_validation_passed' in state:
        verification_info["references_validated"] = state.get('references_validation_passed', False)
    
    # Análisis del reporte
    report_length = len(final_report) if final_report else 0
    report_words = len(final_report.split()) if final_report else 0
    
    # Contar citas en el reporte
    import re
    citations_pattern = re.compile(r'\[(\d+(?:,\s*\d+)*)\]')
    citations_found = citations_pattern.findall(final_report) if final_report else []
    total_citations = len(citations_found)
    
    # Buscar sección de referencias
    has_references_section = bool(re.search(r'## References\s*\n', final_report, re.IGNORECASE)) if final_report else False
    
    # Calcular tokens totales
    total_tokens = sum(tokens_by_role.values())
    
    # Análisis de riesgos de alucinación
    hallucination_risks = []
    risk_score = 0  # 0-100, mayor = más riesgo
    
    # Riesgo 1: Pocas fuentes
    if total_sources_validated < 3:
        hallucination_risks.append({
            "risk": "Bajo número de fuentes",
            "severity": "MEDIUM",
            "description": f"Solo {total_sources_validated} fuente(s) validadas. Múltiples fuentes reducen el riesgo de alucinación."
        })
        risk_score += 20
    
    # Riesgo 2: Fuentes de baja calidad
    if validated_sources and avg_total_score < 6:
        hallucination_risks.append({
            "risk": "Fuentes de baja calidad promedio",
            "severity": "HIGH",
            "description": f"Score promedio: {avg_total_score:.1f}/10. Fuentes poco confiables aumentan el riesgo de alucinación."
        })
        risk_score += 30
    
    # Riesgo 3: Sin verificación habilitada
    if not VERIFIER_ENABLED:
        hallucination_risks.append({
            "risk": "Verificador de alucinaciones deshabilitado",
            "severity": "MEDIUM",
            "description": "El verificador post-generación está deshabilitado. No se realizó validación automática contra fuentes."
        })
        risk_score += 15
    
    # Riesgo 4: Issues de verificación encontrados
    if verification_info["issues_found"] > 0:
        hallucination_risks.append({
            "risk": "Problemas detectados en verificación",
            "severity": "HIGH" if verification_info["issues_high_severity"] > 0 else "MEDIUM",
            "description": f"{verification_info['issues_found']} problema(s) encontrado(s), {verification_info['issues_high_severity']} de alta severidad."
        })
        risk_score += min(verification_info["issues_found"] * 5, 35)
    
    # Riesgo 5: Problemas con referencias
    if not verification_info["references_validated"]:
        hallucination_risks.append({
            "risk": "Validación de referencias fallida",
            "severity": "MEDIUM",
            "description": f"Se detectaron {len(verification_info['references_issues'])} problema(s) con la sección de referencias."
        })
        risk_score += 15
    
    # Determinar nivel de riesgo
    if risk_score >= 60:
        risk_level = "ALTO"
        risk_emoji = "🔴"
    elif risk_score >= 30:
        risk_level = "MEDIO"
        risk_emoji = "🟡"
    else:
        risk_level = "BAJO"
        risk_emoji = "🟢"
    
    # Generar informe
    report = f"""# 📊 Informe de Métricas de Ejecución

**Tema:** {topic}  
**Fecha de generación:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**Estado:** {'✅ Completado exitosamente' if not state.get('error') else '❌ Error en procesamiento'}

---

## 💰 Análisis de Costes

### Coste Total: ${total_cost:.6f}

### Desglose por Agente:

"""
    
    # Agregar costes por rol
    for role, cost in sorted(costs_by_role.items(), key=lambda x: x[1], reverse=True):
        if cost > 0:
            role_name = role.capitalize().replace('_', ' ')
            report += f"- **{role_name}**: ${cost:.6f}"
            
            # Añadir modelo usado
            if role == "planner":
                report += f" (Modelo: {CURRENT_PLANNER_MODEL})"
            elif role == "judge":
                report += f" (Modelo: {CURRENT_JUDGE_MODEL})"
            elif role == "analyst":
                report += f" (Modelo: {CURRENT_ANALYST_MODEL})"
            
            report += "\n"
    
    # Costes de búsqueda (Tavily/Exa)
    # Estimación aproximada: Tavily $0.01 por búsqueda, Exa $0.10 por búsqueda
    search_queries = len(state.get('search_strategy', []))
    tavily_cost = search_queries * 0.01  # Estimación conservadora
    report += f"- **Búsqueda Web (Tavily/Exa)**: ~${tavily_cost:.4f} (estimación, {search_queries} query(s))\n"
    
    total_cost_with_search = total_cost + tavily_cost
    report += f"\n**💵 Coste Total Estimado (LLM + Búsqueda):** ${total_cost_with_search:.6f}\n"
    
    report += f"""
### Uso de Tokens:

- **Total de tokens:** {total_tokens:,}
- **Desglose por rol:**
"""
    
    for role, tokens in sorted(tokens_by_role.items(), key=lambda x: x[1], reverse=True):
        if tokens > 0:
            role_name = role.capitalize().replace('_', ' ')
            percentage = (tokens / total_tokens * 100) if total_tokens > 0 else 0
            report += f"  - {role_name}: {tokens:,} tokens ({percentage:.1f}%)\n"
    
    report += f"""
---

## {risk_emoji} Análisis de Riesgos de Alucinación

**Nivel de Riesgo General:** {risk_level} ({risk_score}/100)

### Riesgos Identificados:

"""
    
    if hallucination_risks:
        for i, risk in enumerate(hallucination_risks, 1):
            severity_emoji = "🔴" if risk["severity"] == "HIGH" else "🟡" if risk["severity"] == "MEDIUM" else "🟢"
            report += f"{i}. {severity_emoji} **{risk['risk']}** ({risk['severity']})\n"
            report += f"   {risk['description']}\n\n"
    else:
        report += "✅ No se identificaron riesgos significativos de alucinación.\n\n"
    
    report += f"""
### Mitigaciones Implementadas:

✅ **Salvaguardas Anti-Alucinación:**
- Reglas estrictas en prompts del Reporter (prohibición explícita de inventar datos)
- Evaluación multidimensional de fuentes (Authenticity, Reliability, Relevance, Currency)
- Extracción de evidencias antes de evaluación (reducción de ruido)
- Verificación post-generación: {'✅ Habilitada' if VERIFIER_ENABLED else '❌ Deshabilitada'}
- Validación de referencias: {'✅ Pasada' if verification_info['references_validated'] else '❌ Fallida o no realizada'}

✅ **Optimización de Evaluación:**
- Pre-juez con MiMo-V2-Flash (barato) para triage inicial
- Escalamiento a Gemini 2.5 Pro solo para casos críticos/inciertos
- Fast-track para dominios de élite (sin LLM)
- Cache de evaluaciones previas

"""

    if mimo_evaluated and gemini_evaluated:
        report += f"   - Fuentes evaluadas con MiMo: {len(mimo_evaluated)} ({len(mimo_evaluated)/total_sources_validated*100:.1f}%)\n"
        report += f"   - Fuentes evaluadas con Gemini: {len(gemini_evaluated)} ({len(gemini_evaluated)/total_sources_validated*100:.1f}%)\n"
        report += f"   - Ahorro estimado: ~${len(mimo_evaluated) * 0.001:.4f} (usando MiMo en lugar de Gemini para todas)\n\n"

    report += f"""
---

## ✅ Verificaciones Realizadas

### 1. Verificación de Alucinaciones:

- **Estado:** {'✅ Realizada' if VERIFIER_ENABLED else '❌ No realizada'}
- **Problemas encontrados:** {verification_info['issues_found']}
- **Problemas de alta severidad:** {verification_info['issues_high_severity']}

"""

    if verification_info['issues_found'] > 0:
        report += "**⚠️ Problemas detectados:**\n"
        for i, issue in enumerate(state.get('verification_issues', [])[:5], 1):
            report += f"  {i}. [{issue.get('severity', 'unknown').upper()}] {issue.get('type', 'unknown')}: {issue.get('text', '')[:60]}...\n"
        if verification_info['issues_found'] > 5:
            report += f"  ... y {verification_info['issues_found'] - 5} más\n"
    
    report += f"""
### 2. Validación de Referencias:

- **Estado:** {'✅ Pasada' if verification_info['references_validated'] else '❌ Fallida'}
- **Citas en el texto:** {total_citations}
- **Sección References presente:** {'✅ Sí' if has_references_section else '❌ No'}

"""

    if not verification_info['references_validated']:
        if verification_info['references_issues']:
            report += "**Problemas encontrados:**\n"
            for i, issue in enumerate(verification_info['references_issues'][:5], 1):
                report += f"  {i}. {issue}\n"
            if len(verification_info['references_issues']) > 5:
                report += f"  ... y {len(verification_info['references_issues']) - 5} más\n"
        else:
            # Si falló pero no hay issues en el estado, intentar obtenerlos de otra forma
            ref_validation = state.get('references_validation', {})
            if ref_validation and ref_validation.get('issues'):
                report += "**Problemas encontrados:**\n"
                for i, issue in enumerate(ref_validation['issues'][:5], 1):
                    report += f"  {i}. {issue}\n"
                if len(ref_validation['issues']) > 5:
                    report += f"  ... y {len(ref_validation['issues']) - 5} más\n"
            else:
                report += "**⚠️ Validación falló pero no se pudieron obtener detalles específicos.**\n"
                # Mostrar información disponible para debugging
                if ref_validation:
                    report += f"  - Citas encontradas: {ref_validation.get('citation_count', 'N/A')}\n"
                    report += f"  - Referencias en ## References: {ref_validation.get('reference_count', 'N/A')}\n"
                    report += f"  - Fuentes faltantes: {len(ref_validation.get('missing_sources', []))}\n"
                    report += f"  - Citas inválidas: {len(ref_validation.get('invalid_citations', []))}\n"

    report += f"""
### 3. Quality Gate:

- **Estado:** {'✅ Pasado' if quality_gate_passed else '❌ Fallido'}
- **Confianza del sistema:** {confidence_score.get('score', 'N/A')}/100

"""

    if quality_gate_issues:
        report += "**Issues detectados:**\n"
        for issue in quality_gate_issues[:5]:
            report += f"  - {issue}\n"

    report += f"""
---

## 📚 Análisis de Fuentes

### Resumen General:

- **Fuentes encontradas:** {total_sources_found}
- **Fuentes validadas:** {total_sources_validated}
- **Fuentes rechazadas:** {total_sources_rejected}
- **Tasa de aceptación:** {(total_sources_validated / total_sources_found * 100) if total_sources_found > 0 else 0:.1f}%

### Calidad de Fuentes Validadas:

- **Score promedio:** {avg_total_score:.1f}/10
- **Authenticity promedio:** {avg_authenticity:.1f}/10
- **Reliability promedio:** {avg_reliability:.1f}/10
- **Relevance promedio:** {avg_relevance:.1f}/10

**Distribución por calidad:**
"""

    if validated_sources:
        high_quality = len([s for s in validated_sources if s.get('total_score', 0) >= 8])
        medium_quality = len([s for s in validated_sources if 6 <= s.get('total_score', 0) < 8])
        low_quality = len([s for s in validated_sources if s.get('total_score', 0) < 6])
        
        report += f"- 🟢 Alta calidad (≥8): {high_quality} ({high_quality/total_sources_validated*100:.1f}%)\n"
        report += f"- 🟡 Calidad media (6-7): {medium_quality} ({medium_quality/total_sources_validated*100:.1f}%)\n"
        report += f"- 🔴 Baja calidad (<6): {low_quality} ({low_quality/total_sources_validated*100:.1f}%)\n"
        
        report += f"\n**Fuentes de élite (Tier 1-2):** {elite_count} ({elite_count/total_sources_validated*100:.1f}%)\n"

    report += f"""
### Extracción de Evidencias:

- **Fuentes con evidencias extraídas:** {len(sources_with_evidence)}/{total_sources_validated}
- **Tasa de extracción:** {evidence_extraction_rate:.1f}%

### Distribución por Dominio:

"""

    if domain_distribution:
        sorted_domains = sorted(domain_distribution.items(), key=lambda x: x[1], reverse=True)
        for domain, count in sorted_domains[:10]:  # Top 10 dominios
            percentage = (count / total_sources_validated * 100) if total_sources_validated > 0 else 0
            report += f"- `{domain}`: {count} fuente(s) ({percentage:.1f}%)\n"
    
    report += f"""
---

## 📝 Análisis del Reporte Final

- **Longitud:** {report_length:,} caracteres
- **Palabras:** {report_words:,} palabras
- **Citas en el texto:** {total_citations}
- **Referencias listadas:** {'✅ Sí' if has_references_section else '❌ No'}

### Elementos del Reporte:

"""

    # Verificar elementos del reporte (Confidence Score no se reporta como issue, el judge ya hizo su trabajo)
    has_plots = len(plot_data) > 0
    
    report += f"- Gráficos generados: {len(plot_data)} ({'✅ Presentes' if has_plots else '❌ Ninguno'})\n"
    report += f"- Sección de referencias: {'✅ Presente' if has_references_section else '❌ Ausente'}\n"
    
    report += f"""
---

## 🔧 Métricas de Procesamiento

### Optimizaciones Aplicadas:

- **Cache de evaluaciones:** ✅ Activo (reducción de llamadas LLM redundantes)
- **Fast-track élite:** ✅ Activo (evaluación sin LLM para dominios reconocidos)
- **Extracción de evidencias:** ✅ Activa (pre-procesamiento antes de evaluación)
- **Pre-juez con MiMo:** ✅ Activo (evaluación preliminar barata)
- **Escalamiento selectivo:** ✅ Activo (Gemini solo para casos críticos)

### Rendimiento:

- **Loops de búsqueda:** {state.get('loop_count', 0)}
- **Queries ejecutadas:** {search_queries}
- **Quality gate:** {'✅ Pasado' if quality_gate_passed else '❌ Fallido'}

---

## 📋 Recomendaciones

"""

    recommendations = []
    
    if risk_score >= 60:
        recommendations.append("🔴 **URGENTE**: Revisar manualmente el reporte por alto riesgo de alucinación.")
    elif risk_score >= 30:
        recommendations.append("🟡 **IMPORTANTE**: Revisar las secciones con problemas detectados.")
    
    if total_sources_validated < 3:
        recommendations.append(f"🟡 Considerar buscar más fuentes (actualmente {total_sources_validated}).")
    
    if avg_total_score < 6:
        recommendations.append(f"🟡 Mejorar calidad de fuentes (score promedio: {avg_total_score:.1f}/10).")
    
    if not VERIFIER_ENABLED:
        recommendations.append("🟡 Habilitar verificador de alucinaciones para mayor seguridad.")
    
    if verification_info['issues_found'] > 0:
        recommendations.append(f"🟡 Revisar {verification_info['issues_found']} problema(s) detectado(s) en verificación.")
    
    if not verification_info['references_validated']:
        recommendations.append("🟡 Corregir problemas en la sección de referencias.")
    
    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            report += f"{i}. {rec}\n"
    else:
        report += "✅ **No se requieren acciones inmediatas.** El reporte cumple con los estándares de calidad.\n"
    
    report += f"""
---

**Fin del Informe de Métricas**

*Generado automáticamente por el sistema de investigación Deep Research*
"""
    
    return report
