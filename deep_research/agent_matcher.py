"""
Agent Matcher: Handles automatic assignment of agents to research topics.
Supports both rule-based (keywords/frameworks) and LLM-based matching.
"""

import re
import time
import os
from .config import (
    items_table,
    proyectos_table,
    llm_matcher,
    AIRTABLE_BASE_ID,
    airtable_base
)
from .constants import AGENT_KEYWORDS, FRAMEWORK_HINTS
from .logger import logger

def _norm_agent_name(name: str) -> str:
    """Normalizes agent names for robust comparison."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())

def _framework_match_agent(topic: str, agents_info: list):
    """Deterministic match by explicit frameworks (Porter, PESTEL, etc.)."""
    topic_lower = topic.lower()
    for fw, agent_key in FRAMEWORK_HINTS.items():
        if fw in topic_lower:
            # Find the actual agent record
            for agent in agents_info:
                if _norm_agent_name(agent['name']) == _norm_agent_name(agent_key):
                    return {
                        'agent': agent,
                        'agent_key': agent_key,
                        'method': 'framework',
                        'score': 10,
                        'reason': f"Match por framework detectado: '{fw}'"
                    }
    return None

def _keyword_match_agent(topic: str, agents_info: list):
    """Assigns an agent based on simple keyword rules."""
    topic_lower = topic.lower()
    best_match = None
    max_score = 0
    
    for agent_key, keywords in AGENT_KEYWORDS.items():
        matches = [kw for kw in keywords if kw.lower() in topic_lower]
        if matches:
            score = len(matches)
            if score > max_score:
                # Find agent record
                for agent in agents_info:
                    if _norm_agent_name(agent['name']) == _norm_agent_name(agent_key):
                        max_score = score
                        best_match = {
                            'agent': agent,
                            'agent_key': agent_key,
                            'method': 'keywords',
                            'score': score,
                            'matched_keywords': matches
                        }
                        break
    return best_match

def process_agent_matching():
    """
    Automatically assigns the best agent to each index item.
    Uses rules first, then falls back to LLM.
    """
    logger.log_section("AGENT MATCHING", "Asignación inteligente de agentes")
    logger.log_info("Buscando registros con Status='Todo'...")

    # 1. Load available agents
    try:
        prompts_table_name = os.environ.get("AIRTABLE_PROMPTS_TABLE_NAME", "System_Prompts")
        prompts_table = airtable_base.table(prompts_table_name)

        all_agents = prompts_table.all(formula="{Active}=TRUE()")
        if not all_agents:
            all_agents = prompts_table.all()

        if not all_agents:
            logger.log_error("No agents found in System_Prompts. Aborting.")
            return

        agents_info = []
        for agent_record in all_agents:
            fields = agent_record.get("fields", {})
            if fields.get("Active", True):
                agents_info.append({
                    "id": agent_record["id"], 
                    "name": fields.get("Prompt_Name", "Sin nombre"), 
                    "description": fields.get("Description", "Sin descripción")
                })
        
        logger.log_info(f"{len(agents_info)} agente(s) cargado(s).")

    except Exception as e:
        logger.log_error(f"Error loading agents: {e}")
        raise

    # 2. Find items to process
    try:
        items = items_table.all(formula="{Status}='Todo'")
        if not items:
            logger.log_info("No items found with Status='Todo'")
            return
        logger.log_info(f"Found {len(items)} items to assign.")
    except Exception as e:
        logger.log_error(f"Error finding items: {e}")
        raise

    # 3. Process each item
    for item_record in items:
        item_id = item_record["id"]
        fields = item_record.get("fields", {})
        topic = fields.get("Topic", fields.get("Tema", "Sin tema"))

        logger.log_phase("MATCH", f"Procesando: {topic}")

        # 3.1. Check project status
        if _check_project_submitted(fields):
            logger.log_warning(f"⏭️ Item skipped: Project is 'Submitted'")
            continue

        # 3.2. Update project status
        _update_project_status(fields, "Generating items")

        # 3.3. Attempt Matching
        match_result = _framework_match_agent(str(topic), agents_info) or _keyword_match_agent(str(topic), agents_info)
        
        if match_result:
            agent = match_result['agent']
            reason = match_result.get('reason') or f"Auto-matching ({match_result['method']}): {match_result['agent_key']}"
            _apply_agent_match(item_id, agent, reason)
            continue

        # 3.4. LLM Fallback
        _llm_match_agent(item_id, topic, agents_info)
        time.sleep(1)

    logger.log_success("Agent matching completed.")

def _check_project_submitted(fields):
    """Checks if the linked project is in 'Submitted' status."""
    project_link = fields.get("Proyectos_NEW") or fields.get("Projectos_NEW") or fields.get("Project")
    if project_link and isinstance(project_link, list) and len(project_link) > 0:
        try:
            project = proyectos_table.get(project_link[0])
            return project.get("fields", {}).get("Status") == "Submitted"
        except:
            pass
    return False

def _update_project_status(fields, new_status):
    """Updates linked project status."""
    project_link = fields.get("Proyectos_NEW") or fields.get("Projectos_NEW") or fields.get("Project")
    if project_link:
        p_id = project_link[0] if isinstance(project_link, list) else project_link
        try:
            proyectos_table.update(p_id, {"Status": new_status})
        except:
            pass

def _apply_agent_match(item_id, agent, reason):
    """Saves agent assignment to Airtable."""
    update_data = {
        "System_Prompt_Link": [agent["id"]],
        "Status": "Pending",
        "Matching_Reason": reason
    }
    try:
        items_table.update(item_id, update_data)
        logger.log_success(f"Agente asignado: {agent['name']}")
    except Exception as e:
        # Fallback if Matching_Reason field doesn't exist
        if "UNKNOWN_FIELD_NAME" in str(e):
            items_table.update(item_id, {
                "System_Prompt_Link": update_data["System_Prompt_Link"],
                "Status": update_data["Status"]
            })
        else:
            logger.log_error(f"Error applying match: {e}")

def _llm_match_agent(item_id, topic, agents_info):
    """Uses LLM to select the best agent."""
    agents_desc = "\n".join([f"{i+1}. **{a['name']}**: {a['description']}" for i, a in enumerate(agents_info)])
    
    system_msg = "Eres un experto en investigación. Selecciona el mejor agente para el tema. Formato: NUMERO: X, RAZON: [explicación]"
    user_msg = f"Tema: {topic}\n\nAgentes:\n{agents_desc}"

    try:
        items_table.update(item_id, {"Status": "Matching"})
        response = llm_matcher.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ])
        
        content = response.content.strip()
        num_match = re.search(r'NUMERO:\s*(\d+)', content, re.I)
        reason_match = re.search(r'RAZON:\s*(.+)', content, re.I | re.S)
        
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(agents_info):
                agent = agents_info[idx]
                reason = reason_match.group(1).strip() if reason_match else "Selected by LLM"
                _apply_agent_match(item_id, agent, reason)
                return
        
        logger.log_warning(f"LLM returned invalid response: {content}")
    except Exception as e:
        logger.log_error(f"Error in LLM matching: {e}")
