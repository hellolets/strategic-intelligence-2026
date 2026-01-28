import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

class SearchEngine(Enum):
    TAVILY = "tavily"
    EXA = "exa"

class SearchDepth(Enum):
    BASIC = "basic"
    ADVANCED = "advanced"

@dataclass
class SearchStep:
    engine: SearchEngine
    depth: SearchDepth
    max_queries: int
    results_per_query: int

@dataclass
class Playbook:
    name: str
    min_sources_target: int
    preferred_range: tuple
    steps: List[SearchStep]
    max_firecrawl_pages: int
    critical: bool = False

@dataclass
class PolicyConfig:
    general_min_sources: int = 7
    critical_min_sources: int = 10
    firecrawl_min_content_chars: int = 3000
    max_firecrawl_per_item_general: int = 5
    max_firecrawl_per_item_critical: int = 7
    tavily_depth_override: Optional[SearchDepth] = None

class SearchPolicy:
    def __init__(self, config: PolicyConfig):
        self.config = config
        self.critical_types = {"Strategy", "Financial", "Due_Diligence", "Strategic"}

    def _get_depth(self, preferred: SearchDepth) -> SearchDepth:
        if self.config.tavily_depth_override:
            return self.config.tavily_depth_override
        return preferred

    def get_playbook(self, report_type: str, topic: str) -> Playbook:
        topic_lower = topic.lower()
        is_critical = report_type in self.critical_types
        
        # Playbook B: Hard Facts / Regulation
        if any(kw in topic_lower for kw in ["regulation", "standard", "iso", "law", "legislation", "cagr", "revenue", "market size"]):
            return Playbook(
                name="HARD_FACTS",
                min_sources_target=self.config.critical_min_sources if is_critical else self.config.general_min_sources,
                preferred_range=(10, 15) if is_critical else (7, 10),
                steps=[
                    SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.BASIC), 6, 5)
                ],
                max_firecrawl_pages=self.config.max_firecrawl_per_item_critical if is_critical else self.config.max_firecrawl_per_item_general,
                critical=is_critical
            )
            
        # Playbook D: Deep Tech
        if any(kw in topic_lower for kw in ["ai", "quantum", "biotech", "semiconductor", "innovation"]):
            return Playbook(
                name="DEEP_TECH",
                min_sources_target=self.config.general_min_sources,
                preferred_range=(7, 10),
                steps=[
                    SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.BASIC), 3, 5),
                    SearchStep(SearchEngine.EXA, SearchDepth.BASIC, 2, 10)
                ],
                max_firecrawl_pages=7,
                critical=is_critical
            )

        # Default Playbooks (A/C)
        if is_critical:
            return Playbook(
                name="CRITICAL_STRATEGY",
                min_sources_target=self.config.critical_min_sources,
                preferred_range=(10, 15),
                steps=[
                    SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.BASIC), 8, 8),
                    SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.ADVANCED), 6, 10)
                ],
                max_firecrawl_pages=self.config.max_firecrawl_per_item_critical,
                critical=True
            )
        
        return Playbook(
            name="GENERAL_MARKET",
            min_sources_target=self.config.general_min_sources,
            preferred_range=(7, 10),
            steps=[
                SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.BASIC), 6, 5),
                SearchStep(SearchEngine.TAVILY, self._get_depth(SearchDepth.ADVANCED), 4, 8)
            ],
            max_firecrawl_pages=self.config.max_firecrawl_per_item_general,
            critical=False
        )

    def should_escalate(self, accepted_count: int, current_step_idx: int, playbook: Playbook) -> bool:
        if accepted_count >= playbook.min_sources_target:
            return False
        return current_step_idx < len(playbook.steps) - 1

    def should_call_exa_booster(self, accepted_count: int, playbook: Playbook) -> bool:
        # Exa is used as a booster if targets aren't met after planned steps, 
        # or if explicitly part of the playbook (like DEEP_TECH)
        return accepted_count < playbook.min_sources_target

    def has_hard_facts(self, text: str) -> bool:
        """Heurística simple para detectar si el contenido tiene datos duros."""
        patterns = [
            r"\d+%", r"\$\d+", r"€\d+", r"CAGR", r"Regulation", r"Directive", 
            r"ISO\s\d+", r"10-K", r"Annual Report", r"\b(19|20)\d{2}\b"
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def select_firecrawl_candidates(self, validated_sources: List[Dict], playbook: Playbook) -> List[Dict]:
        """
        Selecciona candidatos para Firecrawl priorizando:
        1. raw_content pobre (< threshold)
        2. Presencia de hard facts
        3. Según report_type crítico
        """
        candidates = []
        for src in validated_sources:
            raw_content = src.get("raw_content", "")
            content_len = len(raw_content)
            
            # Prioridad 1: Contenido pobre
            if content_len < self.config.firecrawl_min_content_chars:
                candidates.append((src, 10)) # Score alto
                continue
                
            # Prioridad 2: Hard facts (aunque tenga contenido, queremos extraer tablas/datos)
            if self.has_hard_facts(src.get("title", "") + " " + (src.get("snippet", "") or "")):
                candidates.append((src, 5))
                continue
            
            # Prioridad 3: Siempre en top fuentes si es crítico
            if playbook.critical:
                candidates.append((src, 1))

        # Ordenar por score y limitar al cap
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [c[0] for c in candidates[:playbook.max_firecrawl_pages]]
