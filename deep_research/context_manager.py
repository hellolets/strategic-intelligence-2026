"""
Context Manager Simplificado

FILOSOFÍA: El usuario ya sube un documento de contexto a Airtable.
- Extraemos automáticamente: sector, geografía, competidores, entidades
- UN solo campo opcional "Context_Config" para correcciones rápidas
- Sin duplicar trabajo manual

FLUJO:
1. Usuario sube documento a campo "Context" (ya lo hace)
2. Sistema extrae project_specific_context (ya lo hace doc_parser.py)
3. NUEVO: Extraemos metadata estructurada del texto
4. OPCIONAL: Usuario puede añadir correcciones en "Context_Config"
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import re
import json
import hashlib



@dataclass
class ProjectContext:
    """Contexto estructurado extraído automáticamente del documento."""

    # Extraídos automáticamente
    sector: str = ""
    geography: List[str] = field(default_factory=list)
    client_company: str = ""
    competitors: List[str] = field(default_factory=list)
    entity_map: Dict[str, str] = field(default_factory=dict)
    negative_keywords: List[str] = field(default_factory=list)
    disambiguation_negatives: Dict[str, List[str]] = field(default_factory=dict)

    # Derivados
    query_suffix: str = ""
    sector_keywords: List[str] = field(default_factory=list)
    filter_patterns: List = field(default_factory=list)

    def __post_init__(self):
        self._build_derived_fields()

    def _build_derived_fields(self):
        """Genera campos derivados."""
        parts: List[str] = []

        # Sector → términos de búsqueda
        if self.sector:
            sector_terms = {
                "defense": "defense military",
                "infrastructure": "infrastructure construction",
                "energy": "energy power",
                "technology": "technology digital",
            }
            parts.append(sector_terms.get(self.sector.lower(), self.sector))

        # Geografía → preferir específica frente a genérica
        if self.geography:
            preferred = [g for g in self.geography if str(g).strip()]
            preferred = preferred or self.geography

            # Drop generic labels first
            preferred2 = [g for g in preferred if str(g).lower() not in {"global", "worldwide", "international"}]
            preferred2 = preferred2 or preferred

            # Priority order (most decision-useful first)
            priority = [
                "Spain", "USA", "UK", "Germany", "France", "Poland", "Italy",
                "Europe", "LATAM", "Global",
            ]
            chosen = None
            for pr in priority:
                if any(str(g).lower() == pr.lower() for g in preferred2):
                    chosen = pr
                    break
            parts.append(chosen if chosen else str(preferred2[0]))

        self.query_suffix = " ".join([p for p in parts if p]).strip()

        # Palabras clave por sector para reranking
        sector_kw = {
            "defense": ["defense", "military", "nato", "armed forces", "weapons", "aerospace"],
            "infrastructure": ["infrastructure", "construction", "highway", "bridge", "PPP"],
            "energy": ["energy", "renewable", "power", "solar", "wind"],
            "technology": ["technology", "software", "digital", "AI", "cloud"],
        }
        self.sector_keywords = sector_kw.get(self.sector.lower(), [])

        # Patrones de filtrado
        self._build_filter_patterns()

    def _build_filter_patterns(self):
        """Construye patrones de filtrado (post-retrieval)."""
        patterns = []

        # Negativos explícitos
        for kw in self.negative_keywords:
            kw = str(kw).strip()
            if kw:
                patterns.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))

        # Negativos automáticos por sector (evitar drift obvio, sin penalizar subtemas legítimos)
        sector_negatives = {
            "defense": [
                r"american chemical society",
                r"chemical society",
                r"chemistry journal",
                r"recipe",
                r"cooking",
                r"fashion",
            ],
            "infrastructure": [
                r"body building",
                r"workout",
                r"fitness program",
            ],
        }
        for pattern in sector_negatives.get(self.sector.lower(), []):
            patterns.append(re.compile(pattern, re.I))

        # Entity disambiguation: si la entidad aparece junto a cualquiera de sus negativos
        for ent, negs in (self.disambiguation_negatives or {}).items():
            ent = str(ent).strip()
            if not ent:
                continue
            for n in (negs or []):
                n = str(n).strip()
                if not n:
                    continue
                patterns.append(re.compile(rf"(?:\b{re.escape(ent)}\b.*{re.escape(n)}|{re.escape(n)}.*\b{re.escape(ent)}\b)", re.I))

        self.filter_patterns = patterns

    def is_empty(self) -> bool:
        return not self.sector and not self.competitors


def extract_context_from_document(

    document_text: str,
    project_name: str = "",
    llm = None
) -> ProjectContext:
    """
    Extrae contexto estructurado del documento subido.
    
    Args:
        document_text: Texto del documento de contexto (project_specific_context)
        project_name: Nombre del proyecto
        llm: LLM opcional para extracción inteligente
    """
    if not document_text and not project_name:
        return ProjectContext()
    
    # Combinar fuentes de texto
    full_text = f"{project_name}\n\n{document_text or ''}"
    text_lower = full_text.lower()
    
    # Si hay LLM disponible, usar extracción inteligente
    if llm and len(document_text or "") > 500:
        try:
            return _extract_with_llm(document_text, project_name, llm)
        except Exception as e:
            print(f"      ⚠️ Extracción LLM falló, usando patrones: {e}")
    
    # Extracción basada en patrones (rápida, sin coste)
    return _extract_with_patterns(full_text, text_lower)


def _extract_with_patterns(full_text: str, text_lower: str) -> ProjectContext:
    """Extracción rápida basada en patrones."""
    
    context = ProjectContext()
    
    # === SECTOR ===
    sector_patterns = {
        "defense": [
            r"\bdefense\b", r"\bdefence\b", r"\bmilitary\b", r"\bnato\b",
            r"\barmed forces\b", r"\bweapon", r"\baerospace\b", r"\bmissile\b"
        ],
        "infrastructure": [
            r"\binfrastructure\b", r"\bconstruction\b", r"\bhighway\b",
            r"\bbridge\b", r"\btunnel\b", r"\bairport\b", r"\brailway\b"
        ],
        "energy": [
            r"\benergy\b", r"\brenewable\b", r"\bsolar\b", r"\bwind power\b",
            r"\boil and gas\b", r"\belectricity\b"
        ],
        "technology": [
            r"\btechnology\b", r"\bsoftware\b", r"\bdigital\b",
            r"\bartificial intelligence\b", r"\bcloud\b"
        ],
    }
    
    sector_scores = {}
    for sector, patterns in sector_patterns.items():
        score = sum(1 for p in patterns if re.search(p, text_lower))
        if score > 0:
            sector_scores[sector] = score
    
    if sector_scores:
        context.sector = max(sector_scores, key=sector_scores.get)
    
    # === GEOGRAFÍA ===
    geo_patterns = {
        "Europe": [r"\beurope\b", r"\beuropean\b", r"\beu\b"],
        "Spain": [r"\bspain\b", r"\bspanish\b", r"\bespaña\b"],
        "USA": [r"\bunited states\b", r"\busa\b", r"\bu\.s\.\b"],
        "LATAM": [r"\blatin america\b", r"\blatam\b", r"\bbrazil\b", r"\bmexico\b"],
        "Global": [r"\bglobal\b", r"\bworldwide\b", r"\binternational\b"],
    }
    
    for geo, patterns in geo_patterns.items():
        if any(re.search(p, text_lower) for p in patterns):
            context.geography.append(geo)
    
    # === EMPRESAS (Cliente y Competidores) ===
    # Empresas españolas infraestructura/defensa
    spanish_infra = {
        "ferrovial": "Ferrovial",
        "acciona": "Acciona",
        "acs": "ACS",
        "fcc": "FCC",
        "sacyr": "Sacyr",
        "ohl": "OHL",
        "indra": "Indra",
    }
    
    # Empresas europeas
    european_infra = {
        "vinci": "Vinci",
        "bouygues": "Bouygues",
        "eiffage": "Eiffage",
        "strabag": "Strabag",
        "skanska": "Skanska",
    }
    
    # Defensa
    defense_companies = {
        "bae systems": "BAE Systems",
        "thales": "Thales",
        "leonardo": "Leonardo",
        "rheinmetall": "Rheinmetall",
        "airbus": "Airbus Defence",
        "lockheed": "Lockheed Martin",
        "raytheon": "Raytheon",
        "northrop": "Northrop Grumman",
    }
    
    all_companies = {**spanish_infra, **european_infra, **defense_companies}
    
    found_companies = []
    for key, name in all_companies.items():
        # Buscar con word boundary para evitar falsos positivos
        if re.search(rf'\b{re.escape(key)}\b', text_lower):
            found_companies.append(name)
    
    # Identificar cliente: buscar en las primeras líneas del documento o en el nombre del proyecto
    # Generalmente el cliente aparece en el título o en las primeras menciones
    first_lines = '\n'.join(full_text.split('\n')[:10]).lower() if full_text else ""
    
    # Buscar el cliente en las primeras líneas
    for key, name in all_companies.items():
        if key in first_lines:
            context.client_company = name
            break
    
    # Si no se encontró cliente, intentar con el nombre del proyecto
    if not context.client_company:
        project_lower = full_text.split('\n')[0].lower() if full_text else ""
        for key, name in all_companies.items():
            if key in project_lower:
                context.client_company = name
                break
    
    # El resto son competidores (excluir el cliente)
    context.competitors = [c for c in found_companies if c != context.client_company]
    
    # Si Ferrovial está en la lista de competidores pero también es el cliente, eliminarlo
    if context.client_company == "Ferrovial" and "Ferrovial" in context.competitors:
        context.competitors = [c for c in context.competitors if c != "Ferrovial"]
    
    # === ENTITY MAP (desambiguación automática) ===
    # Si encontramos ACS en contexto de construcción/defensa, es la constructora
    ambiguous_entities = {
        "ACS": {
            "pattern": r'\bacs\b',
            "defense_meaning": "ACS Actividades de Construcción y Servicios (constructora española)",
            "infra_meaning": "ACS Actividades de Construcción y Servicios (constructora española)",
        },
        "FCC": {
            "pattern": r'\bfcc\b',
            "defense_meaning": "Fomento de Construcciones y Contratas (constructora española)",
            "infra_meaning": "Fomento de Construcciones y Contratas (constructora española)",
        },
        "BAE": {
            "pattern": r'\bbae\b',
            "defense_meaning": "BAE Systems (defensa UK)",
        },
    }
    
    for entity, config in ambiguous_entities.items():
        if re.search(config["pattern"], text_lower):
            # Determinar significado según sector
            if context.sector == "defense":
                meaning = config.get("defense_meaning", config.get("infra_meaning", entity))
            else:
                meaning = config.get("infra_meaning", config.get("defense_meaning", entity))
            context.entity_map[entity] = meaning
            # Add pre-retrieval disambiguation negatives for ambiguous acronyms
            if entity.upper() == "ACS" and ("construct" in meaning.lower() or "constructora" in meaning.lower()):
                context.disambiguation_negatives["ACS"] = ["American Chemical Society", "chemistry", "chemical society"]
    
    # === NEGATIVE KEYWORDS (automáticos según sector) ===
    if context.sector == "defense":
        context.negative_keywords = [
            "American Chemical Society", "chemical society", "chemistry"
        ]
    elif context.sector == "infrastructure":
        context.negative_keywords = ["body building", "workout", "fitness"]
    
    # Rebuild derived fields con la nueva data
    context._build_derived_fields()
    
    return context






def _validate_llm_extraction(data: dict) -> dict:
    """Validate and normalize LLM extraction output."""
    if not isinstance(data, dict):
        raise ValueError("LLM extraction is not a dict")

    out: Dict[str, Any] = {}

    # Sector
    sector = str(data.get("sector", "") or "").strip().lower()
    if sector and sector not in _ALLOWED_SECTORS:
        sector = "other"
    out["sector"] = sector

    # Geography
    geo = data.get("geography", [])
    if isinstance(geo, str):
        geo = [geo]
    if not isinstance(geo, list):
        geo = []
    out["geography"] = [str(g).strip() for g in geo if str(g).strip()][:8]

    # Client
    out["client_company"] = str(data.get("client_company", "") or "").strip()

    # Competitors
    comps = data.get("competitors", [])
    if isinstance(comps, str):
        comps = [comps]
    if not isinstance(comps, list):
        comps = []
    # Limpiar y deduplicar competidores (normalizar nombres similares)
    cleaned_comps = []
    seen = set()
    for c in comps:
        c_clean = str(c).strip()
        if not c_clean:
            continue
        # Normalizar variantes comunes
        c_normalized = c_clean.upper()
        # Agrupar variantes de la misma empresa
        if "VINCI" in c_normalized:
            c_normalized = "VINCI"
        elif "ACS" in c_normalized and "/" not in c_clean:
            c_normalized = "ACS"
        elif "ACCIONA" in c_normalized or "ACCONA" in c_normalized:
            c_normalized = "ACCIONA"
        elif "HOCHTIEF" in c_normalized:
            c_normalized = "HOCHTIEF"
        elif "DRAGADOS" in c_normalized:
            c_normalized = "DRAGADOS"
        
        if c_normalized not in seen:
            seen.add(c_normalized)
            cleaned_comps.append(c_clean)
    
    out["competitors"] = cleaned_comps[:25]

    # Entity map
    em = data.get("entity_map", {})
    if not isinstance(em, dict):
        em = {}
    norm_em: Dict[str, str] = {}
    for k, v in em.items():
        kk = str(k).strip()
        vv = str(v).strip()
        if not kk or not vv:
            continue
        norm_em[kk.upper() if len(kk) <= 10 else kk] = vv
    out["entity_map"] = norm_em

    # Negative keywords
    neg = data.get("negative_keywords", [])
    if isinstance(neg, str):
        neg = [neg]
    if not isinstance(neg, list):
        neg = []
    out["negative_keywords"] = [str(n).strip() for n in neg if str(n).strip()][:30]

    # Disambiguation negatives (derived)
    disamb: Dict[str, List[str]] = {}
    # Example: ACS acronym frequently collides with "American Chemical Society"
    if "ACS" in norm_em and ("construct" in norm_em["ACS"].lower() or "constructora" in norm_em["ACS"].lower()):
        disamb["ACS"] = ["American Chemical Society", "chemistry", "chemical society"]
    out["disambiguation_negatives"] = disamb

    return out


def _extract_with_llm(document_text: str, project_name: str, llm) -> ProjectContext:
    """Extracción inteligente con LLM (más precisa pero con coste)."""

    # Priorizar secciones importantes: buscar sección de competidores primero
    text_lower = document_text.lower()
    competitors_section_start = -1
    
    # Buscar sección de competidores
    for pattern in ["## 5. competidores", "5. competidores", "competidores y", "peer set"]:
        idx = text_lower.find(pattern)
        if idx != -1:
            competitors_section_start = idx
            break
    
    # Si encontramos la sección de competidores, incluirla en el sample
    if competitors_section_start != -1:
        # Incluir desde 2000 caracteres antes de la sección hasta 4000 después
        start = max(0, competitors_section_start - 2000)
        end = min(len(document_text), competitors_section_start + 4000)
        text_sample = document_text[start:end]
        # Añadir inicio del documento para contexto general
        if start > 0:
            text_sample = document_text[:1000] + "\n\n[...]\n\n" + text_sample
    else:
        # Limitar texto para no gastar tokens
        text_sample = document_text[:6000] if len(document_text) > 6000 else document_text

    prompt = f"""Analiza este documento de contexto de proyecto y extrae información estructurada.

PROYECTO: {project_name}

DOCUMENTO:
{text_sample}

Extrae en JSON:
{{
    "sector": "defense|infrastructure|energy|technology|healthcare|other",
    "geography": ["lista de geografías relevantes"],
    "client_company": "empresa cliente principal",
    "competitors": ["lista de competidores mencionados"],
    "entity_map": {{"SIGLA": "significado en este contexto"}},
    "negative_keywords": ["términos a filtrar por ser de otros sectores"]
}}

INSTRUCCIONES CRÍTICAS:
1. Para "competitors": Busca específicamente en secciones tituladas "Competidores", "Peer set", "Competition", o tablas que listan empresas competidoras. Incluye TODAS las empresas mencionadas como competidores/peers, incluso si están en listas separadas por punto y coma o en tablas.

2. Para "client_company": Identifica la empresa principal del proyecto (generalmente mencionada en el título o resumen ejecutivo).

3. Para "entity_map": Si mencionan "ACS" en contexto de construcción/defensa → "ACS Actividades de Construcción (constructora española)". Identifica siglas ambiguas y su significado CORRECTO en este contexto.

4. IMPORTANTE: Si encuentras una tabla o lista de competidores (ej: "ACS; VINCI; ACCIONA; Skanska"), extrae TODAS las empresas mencionadas en la lista.

Responde SOLO con JSON válido."""

    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)

        # Limpiar y parsear
        content = content.strip()
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        
        # Intentar extraer JSON incluso si está mal formado
        # Buscar el primer { y el último }
        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            content = content[first_brace:last_brace+1]

        raw = json.loads(content)
        data = _validate_llm_extraction(raw)
        disamb = data.pop("disambiguation_negatives", {})
    except (json.JSONDecodeError, ValueError, Exception) as e:
        # Si falla el LLM, usar extracción por patrones como fallback
        print(f"      ⚠️ Extracción LLM falló ({type(e).__name__}: {str(e)[:100]}), usando patrones")
        return _extract_with_patterns(document_text, document_text.lower())

    return ProjectContext(
        sector=data.get("sector", ""),
        geography=data.get("geography", []),
        client_company=data.get("client_company", ""),
        competitors=data.get("competitors", []),
        entity_map=data.get("entity_map", {}),
        negative_keywords=data.get("negative_keywords", []),
        disambiguation_negatives=disamb,
    )

def apply_config_overrides(context: ProjectContext, config_json: str) -> ProjectContext:
    """
    Aplica correcciones del campo opcional Context_Config.
    
    Formato simple:
    {
        "sector": "defense",  // Override sector
        "entity_map": {"ACS": "constructora española"},  // Añadir/corregir entidades
        "negative_keywords": ["chemistry"],  // Añadir keywords negativos
        "competitors": ["Vinci", "Bechtel"]  // Añadir competidores
    }
    """
    if not config_json or not config_json.strip():
        return context
    
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        print(f"      ⚠️ Context_Config no es JSON válido, ignorando")
        return context
    
    # Aplicar overrides
    if "sector" in config:
        context.sector = config["sector"]
    
    if "geography" in config:
        context.geography = config["geography"]
    
    if "client_company" in config:
        context.client_company = config["client_company"]
    
    if "competitors" in config:
        # Merge, no reemplazar
        for comp in config["competitors"]:
            if comp not in context.competitors:
                context.competitors.append(comp)
    
    if "entity_map" in config:
        # Merge, override si existe
        context.entity_map.update(config["entity_map"])
    
    if "negative_keywords" in config:
        # Merge
        for kw in config["negative_keywords"]:
            if kw not in context.negative_keywords:
                context.negative_keywords.append(kw)
    
    # Rebuild derived fields
    context._build_derived_fields()
    
    return context


# ============================================================================
# INTEGRACIÓN PRINCIPAL
# ============================================================================



# Allowed values for normalization / validation
_ALLOWED_SECTORS = {"defense", "infrastructure", "energy", "technology", "healthcare", "other"}

def _stable_hash(text: str) -> str:
    """Stable hash for cache keys (avoids Python's randomized hash())."""
    if not text:
        return "0"
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]

_cache: Dict[str, ProjectContext] = {}

def get_project_context(
    project_id: str,
    project_specific_context: str = "",
    project_name: str = "",
    config_override: str = "",
    llm = None
) -> ProjectContext:
    """
    Obtiene contexto del proyecto.
    
    Flujo:
    1. Buscar en cache
    2. Extraer del documento (project_specific_context)
    3. Aplicar overrides de Context_Config
    4. Cachear y retornar
    
    Args:
        project_id: ID del proyecto (para cache)
        project_specific_context: Texto del documento subido a "Context"
        project_name: Nombre del proyecto
        config_override: JSON del campo opcional "Context_Config"
        llm: LLM opcional para extracción inteligente
    """
    # 1. Cache
    cache_key = f"{project_id}_"             f"n{_stable_hash(project_name or '')}_"             f"c{_stable_hash(project_specific_context or '')}_"             f"o{_stable_hash(config_override or '')}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    # 2. Extraer del documento
    context = extract_context_from_document(
        project_specific_context,
        project_name,
        llm
    )
    
    # 3. Aplicar overrides
    if config_override:
        context = apply_config_overrides(context, config_override)
    
    # 4. Cache
    _cache[cache_key] = context
    
    return context


def clear_cache(project_id: str = None):
    """Limpia cache."""
    global _cache
    if project_id:
        keys_to_remove = [k for k in _cache if k.startswith(project_id)]
        for k in keys_to_remove:
            del _cache[k]
    else:
        _cache.clear()


# ============================================================================
# FUNCIONES DE APLICACIÓN (para planner, searcher, reporter)
# ============================================================================



def build_query_variants(query: str, context: ProjectContext) -> List[str]:
    """Build 2-3 query variants: broad, precise, and disambiguated."""
    if not context:
        return [query] if query else []
    
    q = (query or "").strip()
    if not q:
        return []

    suffix = (context.query_suffix or "").strip()
    broad = f"{q} {suffix}".strip() if suffix else q

    # Disambiguation negatives (only if entity appears in query)
    disamb_parts: List[str] = []
    q_lower = q.lower()
    for ent, negs in (context.disambiguation_negatives or {}).items():
        if ent.lower() in q_lower:
            # Use quoted negatives for multi-word phrases
            quoted = []
            for n in negs:
                n = str(n).strip()
                if not n:
                    continue
                quoted.append(f'"{n}"' if " " in n else n)
            if quoted:
                disamb_parts.append(f"-({ ' OR '.join(quoted) })")

    disamb = f"{broad} {' '.join(disamb_parts)}".strip() if disamb_parts else broad

    # Precise variant: add minimal boolean anchors for common topics
    anchors = []
    ql = broad.lower()
    if context.sector == "defense" and ("m&a" in ql or "merger" in ql or "acquisition" in ql or "consolidation" in ql):
        anchors.append("(M&A OR merger OR acquisition OR consolidation)")
        anchors.append("(defense industry OR defense contractor OR aerospace defense)")
    precise = f"{q} {' '.join(anchors)} {suffix}".strip() if anchors else disamb

    # De-duplicate while preserving order
    out = []
    for cand in [precise, disamb, broad]:
        cand = re.sub(r"\s+", " ", cand).strip()
        if cand and cand not in out:
            out.append(cand)
    return out




def enrich_query(query: str, context: ProjectContext) -> str:
    """Enriquece query con contexto.

    Backward compatible: returns the *best* variant (precise/disambiguated) from build_query_variants().
    """
    variants = build_query_variants(query, context)
    return variants[0] if variants else (query or "")



def filter_results(
    results: List[Dict],
    context: ProjectContext
) -> Tuple[List[Dict], List[Dict]]:
    """Filtra resultados irrelevantes."""
    if not context or not context.filter_patterns:
        return results, []
    
    valid, filtered = [], []
    
    for r in results:
        if not r:  # Skip None results
            continue
        content = f"{r.get('title', '')} {r.get('snippet', '')[:500]}".lower()
        
        is_filtered = False
        for pattern in context.filter_patterns:
            if pattern.search(content):
                r["_filter_reason"] = pattern.pattern
                filtered.append(r)
                is_filtered = True
                break
        
        if not is_filtered:
            valid.append(r)
    
    if filtered:
        print(f"      🔍 Filtrados: {len(filtered)}/{len(results)}")
    
    return valid, filtered




def rerank_results(
    results: List[Dict],
    context: ProjectContext,
    top_n: int = 10
) -> List[Dict]:
    """Re-rankea por relevancia contextual (mejorado: title-weight, geo, penalizaciones)."""
    if not context:
        return results
    
    geo_terms = [g.lower() for g in (context.geography or []) if isinstance(g, str)]
    
    for r in results:
        if not r:  # Skip None results
            continue
        title = (r.get('title', '') or '').lower()
        snippet = (r.get('snippet', '') or '').lower()

        score = 0.0

        # Sector keywords (title > snippet)
        sector_keywords = context.sector_keywords or []
        for kw in sector_keywords:
            k = str(kw).lower()
            if k in title:
                score += 3.0
            if k in snippet:
                score += 1.5

        # Geography hints
        for g in geo_terms:
            if g and g in title:
                score += 1.5
            if g and g in snippet:
                score += 0.75

        # Competitors
        competitors = context.competitors or []
        for comp in competitors:
            c = str(comp).lower()
            if c in title:
                score += 4.0
            if c in snippet:
                score += 2.0

        # Client
        if context.client_company:
            cc = context.client_company.lower()
            if cc in title:
                score += 6.0
            if cc in snippet:
                score += 3.0

        # Penalty if matches filter patterns (soft, because filter already removed many)
        if context.filter_patterns:
            content = f"{title} {snippet}"
            for pat in context.filter_patterns:
                if pat.search(content):
                    score -= 10.0
                    break

        r["_score"] = score

    results.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return results[:top_n]



def build_context_prompt(context: ProjectContext) -> str:
    """Genera prompt de contexto para reporter."""
    if context.is_empty():
        return ""
    
    lines = [
        "=" * 50,
        "CONTEXTO DEL PROYECTO",
        "=" * 50,
        f"SECTOR: {context.sector}",
        f"GEOGRAFÍA: {', '.join(context.geography)}",
    ]
    
    if context.client_company:
        lines.append(f"CLIENTE: {context.client_company}")
    
    if context.competitors:
        lines.append(f"COMPETIDORES: {', '.join(context.competitors)}")
    
    if context.entity_map:
        lines.append("\nENTIDADES (usar estos significados):")
        for e, m in context.entity_map.items():
            lines.append(f"  • {e} = {m}")
    
    lines.append("=" * 50)
    return "\n".join(lines)


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    # Simular documento de contexto
    sample_doc = """
    Analysis of Defense Sector Opportunity for Ferrovial
    
    This strategic report examines opportunities in the European defense 
    infrastructure market for Ferrovial.
    
    Key competitors in this space include ACS, Acciona, and Vinci.
    The focus is on NATO member countries, particularly Spain, Germany, and Poland.
    
    ACS has recently pivoted toward defense contracts, winning several 
    military base construction projects.
    """
    
    # Extraer contexto
    context = extract_context_from_document(
        sample_doc, 
        "Analysis of Defense Sector Opportunity for Ferrovial"
    )
    
    print("=== CONTEXTO EXTRAÍDO AUTOMÁTICAMENTE ===")
    print(f"Sector: {context.sector}")
    print(f"Geografía: {context.geography}")
    print(f"Cliente: {context.client_company}")
    print(f"Competidores: {context.competitors}")
    print(f"Entity Map: {context.entity_map}")
    print(f"Query Suffix: '{context.query_suffix}'")
    print(f"Filtros: {len(context.filter_patterns)}")
    
    print("\n=== TEST QUERY VARIANTS ===")
    queries = ["M&A trends 2024", "ACS strategy", "defense budget NATO"]
    for q in queries:
        vars = build_query_variants(q, context)
        print(f"  '{q}' →")
        for v in vars:
            print(f"     - {v}")
    
    print("\n=== TEST FILTER ===")
    fake_results = [
        {"title": "Defense M&A in Europe", "snippet": "NATO allies..."},
        {"title": "ACS wins military contract", "snippet": "Spanish builder..."},
        {"title": "American Chemical Society news", "snippet": "Chemistry research..."},
        {"title": "Pharma M&A record high", "snippet": "Drug makers..."},
    ]
    valid, filtered = filter_results(fake_results, context)
    print(f"  Válidos: {len(valid)}, Filtrados: {len(filtered)}")
    for f in filtered:
        print(f"    ❌ {f['title']}")
    
    print("\n=== OPTIONAL: CONFIG OVERRIDE ===")
    config = '{"entity_map": {"FCC": "Fomento de Construcciones, competidor español"}}'
    context = apply_config_overrides(context, config)
    print(f"  Entity Map actualizado: {context.entity_map}")
