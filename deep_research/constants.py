"""
Constants Module: Centralizes static configuration and mappings.
"""

# ==========================================
# AGENT MATCHING CONSTANTS
# ==========================================

AGENT_KEYWORDS = {
    "Market_Analyst": [
        "market size", "market growth", "TAM", "SAM", "SOM", "CAGR", 
        "industry overview", "industry analysis", "market landscape",
        "mercado", "tamaño de mercado", "crecimiento", "sector", "industria"
    ],
    "Regulatory_Expert": [
        "regulation", "regulatory", "compliance", "directive", "law", "legislation",
        "EPR", "policy", "legal", "normative", "standard", "ISO",
        "regulación", "normativa", "legislación", "directiva", "ley", "cumplimiento"
    ],
    "Technology_Analyst": [
        "technology", "innovation", "AI", "artificial intelligence", "automation",
        "digital", "IoT", "robotics", "software", "platform", "tech",
        "tecnología", "innovación", "automatización", "digital", "plataforma"
    ],
    "Sustainability_Expert": [
        "sustainability", "sustainable", "circular economy", "recycling", "carbon",
        "environmental", "ESG", "green", "eco", "LCA", "lifecycle",
        "sostenibilidad", "circular", "reciclaje", "carbono", "ambiental", "verde"
    ],
    "Competitive_Intel": [
        "competitor", "competitive", "benchmark", "benchmarking", "rivalry",
        "player", "market share", "positioning", "SWOT",
        "competidor", "competencia", "benchmark", "rival", "cuota de mercado"
    ],
    "Financial_Analyst": [
        "financial", "finance", "investment", "ROI", "business case", "valuation",
        "revenue", "cost", "margin", "profitability", "NPV", "IRR",
        "financiero", "inversión", "valoración", "rentabilidad", "coste"
    ],
    "Startup_Scout": [
        "startup", "startups", "venture", "VC", "funding", "series A", "series B",
        "acquisition", "M&A", "unicorn", "scale-up", "founder",
        "startup", "inversión", "adquisición", "emprendimiento"
    ],
    "Risk_Analyst": [
        "risk", "risks", "threat", "mitigation", "scenario", "contingency",
        "vulnerability", "exposure", "hedging",
        "riesgo", "amenaza", "mitigación", "escenario", "contingencia"
    ],
    "Strategic_Consultant": [
        "strategy", "strategic", "recommendation", "roadmap", "action plan",
        "executive summary", "synthesis", "conclusion",
        "estrategia", "estratégico", "recomendación", "hoja de ruta", "conclusión"
    ]
}

FRAMEWORK_HINTS = {
    "porter": "Competitive_Intel",
    "five forces": "Competitive_Intel",
    "5 forces": "Competitive_Intel",
    "pestel": "Strategic_Consultant",
    "p.e.s.t.e.l": "Strategic_Consultant",
    "swot": "Competitive_Intel",
    "bcg": "Strategic_Consultant",
    "value chain": "Strategic_Consultant",
}

# ==========================================
# DOCX STYLE CONSTANTS
# ==========================================

DEFAULT_DOCX_STYLES = {
    "normal": {"font": "Calibri", "size_pt": 10, "align": "LEFT"},
    "heading1": {"font": "Aptos Display", "size_pt": 22, "bold": True, "align": "LEFT"},
    "heading2": {"font": "Aptos Display", "size_pt": 20, "bold": True, "align": "LEFT"},
    "heading3": {"font": "Aptos Display", "size_pt": 16, "bold": True, "align": "LEFT"},
    "heading4": {"font": "Aptos", "size_pt": 14, "bold": True, "align": "LEFT"},
    "link": {"font": "Calibri", "size_pt": 10, "blue": True, "underline": True},
}

# ==========================================
# MODEL NAME FALLBACKS
# ==========================================

MODEL_FALLBACKS = {
    "google/gemini-2.5-pro": "google/gemini-2.5-flash",
    "google/gemini-2.5-flash": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat": "google/gemini-2.5-flash-lite",
    "google/gemini-2.5-flash-lite": "deepseek/deepseek-chat",
}
