"""
Processor: Main entry point for coordinating agents, research items, and project consolidation.
"""

import time
import os
from .logger import logger
from .config import items_table, proyectos_table
from .agent_matcher import process_agent_matching
from .project_processor import process_project_consolidation, consolidate_specific_project
from .manager import run_async_processor
from .utils import cleanup_temp_plots

def process_items_queue(run_once=False):
    """Wrapper for the asynchronous research processor."""
    run_async_processor(run_once=run_once)

def check_and_consolidate_completed_projects():
    """
    Scans for projects where all linked items are marked 'Done' and runs consolidation.
    """
    logger.log_section("AUTO CONSOLIDATION", "Checking for completed projects")
    try:
        # Finding projects that are generating or in 'Todo' status
        formula = "OR({Status}='Generating items', {Status}='Todo', {Status}='To Do')"
        projects = proyectos_table.all(formula=formula)
        
        for project in projects:
            p_id = project["id"]
            fields = project.get("fields", {})
            name = fields.get("Project_Name", p_id)
            
            # Logic for checking all item statuses is now handled inside consolidate_specific_project
            # including the 'wait' if items are not ready.
            consolidate_specific_project(p_id, name, fields)
            
    except Exception as e:
        logger.log_error(f"Error in auto-consolidation: {e}")

def process_pipeline():
    """
    Runs the full workflow:
    1. Match agents to items.
    2. Execute research for pending items.
    3. Consolidate completed projects.
    """
    logger.log_section("AUTOMATIC PIPELINE", "Starting full research cycle")
    
    try:
        # Step 1: Matching
        process_agent_matching()
        time.sleep(2)
        
        # Step 2: Research
        process_items_queue(run_once=True)
        time.sleep(2)
        
        # Step 3: Consolidation
        check_and_consolidate_completed_projects()
        
        cleanup_temp_plots()
        logger.log_success("PIPELINE COMPLETED")
        
    except Exception as e:
        logger.log_error(f"Pipeline failed: {e}")
        raise

    return 0.0 # Cost tracking placeholder