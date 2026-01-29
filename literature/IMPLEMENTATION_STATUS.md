# Implementation Status: New Profile System & Consolidator Refactor

## ✅ Completed

1. **Model Routing System** (`deep_research/model_routing.py`)
   - ✅ Profile enum (PRODUCTION, ECONOMIC, TEST)
   - ✅ Profile detection with backward compatibility
   - ✅ TEST_ONLINE env var support
   - ✅ Per-role model configuration
   - ✅ Env var overrides (ROLE_MODEL_*, ROLE_TEMP_*, ROLE_MAXTOKENS_*)

2. **LocalStubLLM** (`deep_research/stub_llm.py`)
   - ✅ Deterministic stub LLM for offline testing
   - ✅ Compatible with LangChain interface
   - ✅ Specialized responses for Judge, Executive Summary, Narrative Polish

3. **Consolidator Module** (`deep_research/consolidator.py`)
   - ✅ `assemble_markdown()` - deterministic assembly
   - ✅ `generate_toc()` - table of contents generation
   - ✅ `renumber_citations()` - sequential citation renumbering
   - ✅ `preserve_plot_markers()` - plot marker extraction
   - ✅ `inject_exec_summary()` - executive summary injection
   - ✅ `validate_consolidation()` - post-stage validation
   - ✅ `llm_narrative_polish()` - optional LLM polish
   - ✅ `llm_exec_summary()` - optional LLM exec summary

4. **Config Integration** (`deep_research/config.py`)
   - ✅ Import new routing system
   - ✅ `get_llm_for_role()` helper function
   - ✅ `_create_llm_client()` supports "local" provider
   - ✅ Backward compatibility maintained

## 🚧 In Progress

5. **Processor Integration** (`deep_research/processor.py`)
   - ⏳ Replace old consolidator LLM call with new staged pipeline
   - ⏳ Use `assemble_markdown()` → `generate_toc()` → `renumber_citations()`
   - ⏳ Add optional `llm_narrative_polish()` and `llm_exec_summary()`
   - ⏳ Use `validate_consolidation()` for safeguards
   - ⏳ Handle TEST offline mode (skip LLM calls, use stub)

## 📋 Remaining Tasks

6. **Config.toml Update**
   - ⏳ Add PRODUCTION/ECONOMIC/TEST profile sections (optional, can use env vars)
   - ⏳ Document new env vars

7. **Unit Tests**
   - ⏳ Test `renumber_citations()` with various patterns
   - ⏳ Test `preserve_plot_markers()`
   - ⏳ Test `generate_toc()` heading extraction
   - ⏳ Test consolidator end-to-end in TEST offline mode
   - ⏳ Verify no external calls in offline mode

8. **Documentation**
   - ⏳ Update README with ENV_PROFILE and TEST_ONLINE
   - ⏳ Document new consolidator architecture

## 🔧 Integration Points

### Current Consolidator Call (processor.py ~line 1151)
```python
response = llm_consolidator.invoke([
    {"role": "system", "content": system_msg},
    {"role": "user", "content": user_msg},
])
final_report = response.content
```

### New Staged Pipeline (to implement)
```python
from .consolidator import (
    assemble_markdown, generate_toc, renumber_citations,
    llm_narrative_polish, llm_exec_summary, inject_exec_summary,
    validate_consolidation
)
from .config import get_llm_for_role, get_active_profile, Profile, is_test_online

# 1. Assemble chapters
markdown = assemble_markdown(chapter_reports, project_context, project_name)

# 2. Generate TOC
markdown = generate_toc(markdown)

# 3. Renumber citations
markdown, citation_map = renumber_citations(markdown)

# 4. Optional: Narrative polish (skip in TEST offline)
profile = get_active_profile()
if profile != Profile.TEST or is_test_online():
    llm_polish = get_llm_for_role("consolidator_polish")
    markdown = await llm_narrative_polish(markdown, project_context, llm_polish)

# 5. Generate Executive Summary (skip in TEST offline)
if profile != Profile.TEST or is_test_online():
    llm_summary = get_llm_for_role("consolidator_summary")
    exec_summary = await llm_exec_summary(markdown, project_context, project_name, llm_summary)
    markdown = inject_exec_summary(markdown, exec_summary)

# 6. Validate
validation = validate_consolidation(markdown)
if not validation["valid"]:
    logger.warning(f"Validation issues: {validation['issues']}")

final_report = markdown
```

## 🎯 Next Steps

1. Update `consolidate_specific_project()` in `processor.py` to use new pipeline
2. Add unit tests for consolidator functions
3. Update README with new env vars
4. Test in TEST offline mode (no API keys)
