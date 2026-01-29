# Integration Patch for processor.py

## Changes Required

### 1. Add imports after line 48:
```python
from .consolidator import (
    assemble_markdown,
    generate_toc,
    renumber_citations as renumber_citations_new,
    llm_narrative_polish,
    llm_exec_summary,
    inject_exec_summary,
    validate_consolidation,
    preserve_plot_markers
)
try:
    from .config import get_llm_for_role, get_active_profile, Profile, is_test_online
except ImportError:
    get_llm_for_role = None
    get_active_profile = None
    Profile = None
    is_test_online = None
import asyncio
```

### 2. Replace lines ~1147-1203 (the LLM consolidation section) with the new staged pipeline.

The new code is in the file `NEW_CONSOLIDATOR_CODE.txt` (to be created).

## Status
- ✅ Imports added
- ⏳ Consolidation section replacement pending (manual edit needed due to file state)
