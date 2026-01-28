"""
LocalStubLLM: Deterministic stub LLM for offline testing.
Returns predictable outputs without external API calls.
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class StubResponse:
    """Mock response object compatible with LangChain LLM interface."""
    content: str
    
    def __str__(self):
        return self.content


class LocalStubLLM:
    """
    Deterministic stub LLM for offline testing.
    Implements minimal interface compatible with LangChain ChatOpenAI.
    """
    
    def __init__(self, model: str = "local/stub", temperature: float = 0.0, **kwargs):
        self.model_name = model
        self.temperature = temperature
        self.max_tokens = kwargs.get("max_tokens")
    
    def invoke(self, messages: List[Dict[str, str]], **kwargs) -> StubResponse:
        """
        Synchronous invoke (for backward compatibility).
        
        Args:
            messages: List of dicts with 'role' and 'content'
            **kwargs: Additional parameters (ignored)
        
        Returns:
            StubResponse with deterministic output
        """
        return self._generate(messages)
    
    async def ainvoke(self, messages: List[Dict[str, str]], **kwargs) -> StubResponse:
        """
        Async invoke.
        
        Args:
            messages: List of dicts with 'role' and 'content'
            **kwargs: Additional parameters (ignored)
        
        Returns:
            StubResponse with deterministic output
        """
        return self._generate(messages)
    
    def _generate(self, messages: List[Dict[str, str]]) -> StubResponse:
        """Generate deterministic stub response based on message content."""
        if not messages:
            return StubResponse("")
        
        # Get user message (last message with role='user')
        user_msg = ""
        system_msg = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
            elif msg.get("role") == "system":
                system_msg = msg.get("content", "")
        
        # Determine task type from system message or user message
        content = user_msg or system_msg
        
        # Judge task: return deterministic JSON
        if "evaluar" in content.lower() or "evaluate" in content.lower() or "judge" in content.lower():
            return self._generate_judge_response(content)
        
        # Executive Summary task
        if "executive summary" in content.lower() or "resumen ejecutivo" in content.lower():
            return self._generate_exec_summary(content)
        
        # Narrative Polish task
        if "coherencia narrativa" in content.lower() or "narrative" in content.lower() or "transiciones" in content.lower():
            return self._generate_narrative_polish(content)
        
        # Default: return input with marker
        return StubResponse(f"[STUB OUTPUT] {content[:200]}...")
    
    def _generate_judge_response(self, content: str) -> StubResponse:
        """Generate deterministic judge response (JSON format)."""
        # Return a simple deterministic evaluation
        response = {
            "score": 7.5,
            "relevance": 8.0,
            "authenticity": 7.0,
            "reliability": 7.5,
            "currency": 8.0,
            "reasoning": "Stub evaluation: Source appears relevant and reliable based on deterministic analysis."
        }
        import json
        return StubResponse(json.dumps(response, indent=2))
    
    def _generate_exec_summary(self, content: str) -> StubResponse:
        """Generate deterministic executive summary with realistic structure."""
        # Extract project name if possible
        project_match = re.search(r'proyecto\s+"([^"]+)"|project\s+"([^"]+)"', content, re.I)
        project_name = project_match.group(1) or project_match.group(2) if project_match else "the project"
        
        # Try to extract chapter titles from content to make summary more realistic
        chapter_titles = re.findall(r'^##\s+(?!Table of Contents|Executive Summary|Resumen Ejecutivo|References|Referencias)(.+)$', content, re.MULTILINE)
        chapter_count = len(chapter_titles)
        
        # Extract key terms (capitalized words) to mention in summary
        key_terms = re.findall(r'\b[A-Z][a-z]{4,}\b', content)
        key_terms_freq = {}
        for term in key_terms:
            if term not in ['Executive', 'Summary', 'Table', 'Contents', 'References', 'Chapter']:
                key_terms_freq[term] = key_terms_freq.get(term, 0) + 1
        top_terms = sorted(key_terms_freq.items(), key=lambda x: x[1], reverse=True)[:3]
        top_terms_str = ", ".join([term for term, _ in top_terms]) if top_terms else "strategic initiatives"
        
        # Build more realistic summary
        summary = f"""## Executive Summary

This comprehensive report synthesizes findings from {chapter_count} research chapters analyzing {project_name}. The investigation examines critical aspects of {top_terms_str} and provides strategic insights for decision-making.

**Key Findings:**

The analysis reveals significant opportunities and challenges across multiple dimensions. Market dynamics indicate evolving trends that require strategic attention. The research identifies key factors influencing the sector's trajectory, with particular emphasis on competitive positioning and growth potential.

**Strategic Implications:**

The findings suggest that {project_name} faces both opportunities for expansion and risks that require mitigation. Strategic alignment with market trends and competitive dynamics will be essential for success. The report provides actionable recommendations based on comprehensive data analysis.

**Recommendations:**

Based on the consolidated findings, the following strategic actions are recommended: (1) further investigation in critical areas identified across chapters, (2) strategic alignment with organizational objectives, and (3) development of an implementation roadmap that addresses key risk factors while capitalizing on identified opportunities.

*[STUB OUTPUT - This is a deterministic placeholder for testing. In production, this would be generated by an LLM with full context awareness.]*
"""
        return StubResponse(summary)
    
    def _generate_narrative_polish(self, content: str) -> StubResponse:
        """Generate deterministic narrative polish (adds realistic transitions)."""
        # Extract markdown content
        lines = content.split('\n')
        
        # Find chapter boundaries (## headings)
        polished_lines = []
        prev_was_heading = False
        chapter_count = 0
        transition_phrases = [
            "Furthermore, this analysis builds upon the previous findings by examining",
            "In this context, the following section explores",
            "Complementing the above discussion, this chapter delves into",
            "Expanding on the strategic implications identified earlier, this section addresses",
            "Building on the foundation established in previous chapters, we now turn to",
        ]
        
        for i, line in enumerate(lines):
            if line.startswith('## ') and 'Table of Contents' not in line and 'Executive Summary' not in line and 'References' not in line:
                chapter_count += 1
                # Add transition before new chapter (except first)
                if prev_was_heading and polished_lines and chapter_count > 1:
                    polished_lines.append("")
                    # Use rotating transition phrases for variety
                    transition = transition_phrases[(chapter_count - 2) % len(transition_phrases)]
                    # Extract chapter title for context
                    chapter_title = line.replace('##', '').strip()
                    polished_lines.append(f"{transition} {chapter_title.lower()}.")
                    polished_lines.append("")
                prev_was_heading = True
            else:
                prev_was_heading = False
            
            polished_lines.append(line)
        
        result = '\n'.join(polished_lines)
        return StubResponse(result)
