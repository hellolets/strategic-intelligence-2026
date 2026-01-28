"""
Unit tests for consolidator module deterministic functions.
Tests can run offline without API keys (using LocalStubLLM).
"""

import pytest
import re
from deep_research.consolidator import (
    assemble_markdown,
    generate_toc,
    renumber_citations,
    preserve_plot_markers,
    inject_exec_summary,
    validate_consolidation,
)


class TestAssembleMarkdown:
    """Tests for assemble_markdown function."""
    
    def test_assemble_empty(self):
        """Test assembling with no chapters."""
        result = assemble_markdown([], project_name="Test Project")
        assert "# Test Project" in result
        assert "*No chapters available*" in result
    
    def test_assemble_single_chapter(self):
        """Test assembling with a single chapter."""
        chapters = [{"title": "Chapter 1", "content": "Content here"}]
        result = assemble_markdown(chapters, project_name="Test")
        assert "# Test" in result
        assert "## Chapter 1" in result
        assert "Content here" in result
    
    def test_assemble_multiple_chapters(self):
        """Test assembling with multiple chapters."""
        chapters = [
            {"title": "Chapter 1", "content": "Content 1"},
            {"title": "Chapter 2", "content": "Content 2"},
        ]
        result = assemble_markdown(chapters, project_name="Test")
        assert "## Chapter 1" in result
        assert "## Chapter 2" in result
        assert "Content 1" in result
        assert "Content 2" in result
    
    def test_assemble_auto_adds_h2(self):
        """Test that titles without ## get H2 added."""
        chapters = [{"title": "Chapter 1", "content": "Content"}]
        result = assemble_markdown(chapters, project_name="Test")
        assert "## Chapter 1" in result
        assert "# Chapter 1" not in result


class TestGenerateTOC:
    """Tests for generate_toc function."""
    
    def test_toc_simple_headings(self):
        """Test TOC generation with simple headings."""
        markdown = """# Title

## Chapter 1
Content

## Chapter 2
Content
"""
        result = generate_toc(markdown)
        assert "## Table of Contents" in result
        assert "Chapter 1" in result
        assert "Chapter 2" in result
    
    def test_toc_replaces_placeholder(self):
        """Test that [[TOC]] placeholder is replaced."""
        markdown = """# Title

[[TOC]]

## Chapter 1
Content
"""
        result = generate_toc(markdown)
        assert "[[TOC]]" not in result
        assert "## Table of Contents" in result
    
    def test_toc_no_headings(self):
        """Test TOC with no headings."""
        markdown = "Just text, no headings."
        result = generate_toc(markdown)
        assert "*No headings found*" in result
    
    def test_toc_nested_headings(self):
        """Test TOC with nested headings (H2, H3, H4)."""
        markdown = """# Title

## Chapter 1
### Section 1.1
#### Subsection 1.1.1
## Chapter 2
"""
        result = generate_toc(markdown)
        assert "Chapter 1" in result
        assert "Chapter 2" in result


class TestRenumberCitations:
    """Tests for renumber_citations function."""
    
    def test_renumber_sequential(self):
        """Test renumbering already sequential citations."""
        markdown = "Text [1] and [2] and [3]."
        result, _ = renumber_citations(markdown)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result
    
    def test_renumber_non_sequential(self):
        """Test renumbering non-sequential citations."""
        markdown = "Text [5] and [2] and [5] again."
        result, citation_map = renumber_citations(markdown)
        # First occurrence of each unique citation should be sequential
        citations = re.findall(r'\[(\d+)\]', result)
        assert len(set(citations)) <= 2  # Should have at most 2 unique citations
    
    def test_renumber_empty(self):
        """Test renumbering with no citations."""
        markdown = "Text with no citations."
        result, citation_map = renumber_citations(markdown)
        assert result == markdown
        assert citation_map == {}
    
    def test_renumber_preserves_positions(self):
        """Test that citation positions are preserved."""
        markdown = "Start [1] middle [2] end [1]."
        result, _ = renumber_citations(markdown)
        # Should still have 3 citations
        citations = re.findall(r'\[(\d+)\]', result)
        assert len(citations) == 3


class TestPreservePlotMarkers:
    """Tests for preserve_plot_markers function."""
    
    def test_preserve_simple_plot(self):
        """Test preserving simple plot markers."""
        markdown = "Text [[PLOT:1]] more text."
        markers = preserve_plot_markers(markdown)
        assert len(markers) == 1
        assert "[[PLOT:1]]" in markers
    
    def test_preserve_multiple_plots(self):
        """Test preserving multiple plot markers."""
        markdown = "Text [[PLOT:1]] and [[PLOT:2]] and [[PLOT:3]]."
        markers = preserve_plot_markers(markdown)
        assert len(markers) == 3
        assert "[[PLOT:1]]" in markers
        assert "[[PLOT:2]]" in markers
        assert "[[PLOT:3]]" in markers
    
    def test_preserve_plot_with_title(self):
        """Test preserving plot markers with titles."""
        markdown = "Text [[PLOT:1|Chart Title]] more."
        markers = preserve_plot_markers(markdown)
        assert len(markers) == 1
        assert "[[PLOT:1|Chart Title]]" in markers[0]
    
    def test_preserve_no_plots(self):
        """Test with no plot markers."""
        markdown = "Text with no plots."
        markers = preserve_plot_markers(markdown)
        assert len(markers) == 0


class TestInjectExecSummary:
    """Tests for inject_exec_summary function."""
    
    def test_inject_after_toc(self):
        """Test injecting exec summary after TOC."""
        markdown = """# Title

## Table of Contents
- Chapter 1

## Chapter 1
Content
"""
        summary = "## Executive Summary\n\nSummary text here."
        result = inject_exec_summary(markdown, summary)
        assert "## Executive Summary" in result
        assert "Summary text here" in result
        # Should be after TOC
        toc_pos = result.find("## Table of Contents")
        summary_pos = result.find("## Executive Summary")
        assert summary_pos > toc_pos
    
    def test_inject_before_first_chapter(self):
        """Test injecting when no TOC exists."""
        markdown = """# Title

## Chapter 1
Content
"""
        summary = "## Executive Summary\n\nSummary."
        result = inject_exec_summary(markdown, summary)
        assert "## Executive Summary" in result
        # Should be before first chapter
        summary_pos = result.find("## Executive Summary")
        chapter_pos = result.find("## Chapter 1")
        assert summary_pos < chapter_pos


class TestValidateConsolidation:
    """Tests for validate_consolidation function."""
    
    def test_validate_valid_document(self):
        """Test validation of a valid document."""
        markdown = """# Title

## Table of Contents
- Chapter 1

## Executive Summary
This is a comprehensive summary of the findings.

## Chapter 1
Content with citation [1].

## References
[1] Source 1 - URL
"""
        result = validate_consolidation(markdown)
        assert result["valid"] is True
        assert len(result["issues"]) == 0
        assert result["citation_count"] == 1
        assert result["coherence_checks"]["has_exec_summary"] is True
    
    def test_validate_missing_toc(self):
        """Test validation detects missing TOC."""
        markdown = """# Title

## Chapter 1
Content
"""
        result = validate_consolidation(markdown)
        assert result["valid"] is False
        assert any("Table of Contents" in issue for issue in result["issues"])
    
    def test_validate_missing_exec_summary(self):
        """Test validation detects missing exec summary."""
        markdown = """# Title

## Table of Contents
- Chapter 1

## Chapter 1
Content
"""
        result = validate_consolidation(markdown)
        assert result["valid"] is False
        assert any("Executive Summary" in issue for issue in result["issues"])
        assert result["coherence_checks"]["has_exec_summary"] is False
    
    def test_validate_citation_gaps(self):
        """Test validation detects citation gaps."""
        markdown = """# Title

## Chapter 1
Content [1] and [3] but missing [2].
"""
        result = validate_consolidation(markdown)
        # Should detect missing citation [2]
        assert any("Missing citations" in issue for issue in result["issues"])
    
    def test_validate_coherence_checks(self):
        """Test that coherence checks are performed."""
        markdown = """# Title

## Table of Contents
- Chapter 1

## Executive Summary
This is a comprehensive executive summary that provides detailed insights into the strategic implications of the findings. The analysis reveals key opportunities and challenges that require careful consideration.

## Chapter 1
Content with transitions. Furthermore, this builds on previous findings.

## References
[1] Source 1 - URL
"""
        result = validate_consolidation(markdown)
        assert "coherence_checks" in result
        assert result["coherence_checks"]["has_exec_summary"] is True
        assert result["coherence_checks"]["transition_count"] > 0
        assert result["coherence_checks"]["chapter_count"] >= 1
    
    def test_validate_short_exec_summary(self):
        """Test validation detects too-short exec summary."""
        markdown = """# Title

## Executive Summary
Short.

## Chapter 1
Content
"""
        result = validate_consolidation(markdown)
        # Should warn about short exec summary
        assert any("too short" in issue.lower() for issue in result["issues"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
