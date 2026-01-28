"""
Model Routing Configuration
Supports PRODUCTION, ECONOMIC, and TEST profiles with per-role overrides.
Integrates with config.toml for centralized configuration.
"""

from typing import Dict, Optional, Any
from enum import Enum
from .settings_manager import settings

class Profile(Enum):
    """Execution profile for model routing."""
    PRODUCTION = "PRODUCTION"
    PRODUCTION_OPTIMIZED = "PRODUCTION_OPTIMIZED"
    ECONOMIC = "ECONOMIC"
    TEST = "TEST"

# ==========================================
# PROFILE DETECTION
# ==========================================

def get_active_profile() -> Profile:
    """Determine the active profile."""
    # 1. ENV var
    env_profile = (settings.get_env("ENV_PROFILE") or "").upper().strip()
    if env_profile in (p.value for p in Profile):
        return Profile(env_profile)

    # 2. config.toml
    toml_profile = (settings.get_nested("general", "profile") or "").upper().strip()
    for p in Profile:
        if toml_profile == p.value:
            return p

    # 3. Legacy flags
    if settings.is_true("use_deepseek_for_testing"):
        return Profile.ECONOMIC
    if settings.is_true("use_cheap_openrouter_models"):
        return Profile.TEST

    return Profile.PRODUCTION

# ==========================================
# MODEL ROUTING CONFIGURATION
# ==========================================

# Target model routing per profile (lowest priority; config.toml can override)
PROFILE_MODELS = {
    Profile.PRODUCTION: {
        "matcher": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "planner": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "judge": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "analyst": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.3},
        "ploter": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_polish": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_summary": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_polish_premium": {"provider": "openrouter", "model": "google/gemini-2.0-pro", "temperature": 0.0},
        "consolidator_summary_premium": {"provider": "openrouter", "model": "google/gemini-2.0-pro", "temperature": 0.0},
    },
    Profile.PRODUCTION_OPTIMIZED: {
        "matcher": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "planner": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "judge": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "analyst": {"provider": "openrouter", "model": "google/gemini-2.0-pro-exp:free", "temperature": 0.3},
        "ploter": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator": {"provider": "openrouter", "model": "google/gemini-2.0-pro-exp:free", "temperature": 0.0},
        "consolidator_polish": {"provider": "openrouter", "model": "google/gemini-2.0-pro-exp:free", "temperature": 0.0},
        "consolidator_summary": {"provider": "openrouter", "model": "anthropic/claude-3.5-sonnet", "temperature": 0.0},
        "consolidator_polish_premium": {"provider": "openrouter", "model": "google/gemini-2.0-pro-exp:free", "temperature": 0.0},
        "consolidator_summary_premium": {"provider": "openrouter", "model": "google/gemini-2.0-pro-exp:free", "temperature": 0.0},
    },
    Profile.ECONOMIC: {
        "matcher": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "planner": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "judge": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "analyst": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.3},
        "ploter": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_polish": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_summary": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_polish_premium": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
        "consolidator_summary_premium": {"provider": "openrouter", "model": "deepseek/deepseek-chat", "temperature": 0.0},
    },
    Profile.TEST: {
        "matcher": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "planner": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "judge": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "analyst": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.3},
        "ploter": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "consolidator": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "consolidator_polish": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "consolidator_summary": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "consolidator_polish_premium": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
        "consolidator_summary_premium": {"provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "temperature": 0.0},
    },
}

def get_role_config(role: str) -> Dict[str, Any]:
    """Get model configuration for a role with priority: ENV > TOML > Defaults."""
    profile = get_active_profile()
    base_config = PROFILE_MODELS[profile].get(role, {}).copy()

    # TOML Overrides
    roles_config = settings.get_nested("profiles", profile.value, "roles")
    if not roles_config:
        # Legacy fallbacks
        if profile == Profile.TEST:
            roles_config = settings.get("roles_test", {})
        elif profile == Profile.ECONOMIC:
            roles_config = settings.get("roles_economic") or settings.get("roles_cheap", {})
        else:
            roles_config = settings.get("roles", {})
    
    toml_role_config = roles_config.get(role, {})
    if toml_role_config:
        for key in ["model", "provider", "temperature", "max_tokens"]:
            if toml_role_config.get(key) is not None:
                base_config[key] = toml_role_config[key]
    
    # ENV Overrides
    for key, env_suffix in [("model", "MODEL"), ("temperature", "TEMP"), ("max_tokens", "MAXTOKENS")]:
        env_val = settings.get_env(f"ROLE_{env_suffix}_{role.upper()}")
        if env_val:
            try:
                base_config[key] = float(env_val) if key == "temperature" else int(env_val) if key == "max_tokens" else env_val
            except ValueError:
                pass
    
    return base_config

def get_consolidator_config() -> Dict[str, Dict[str, Any]]:
    """Get consolidator configuration (polish + summary)."""
    return {
        "polish": get_role_config("consolidator_polish"),
        "summary": get_role_config("consolidator_summary"),
    }
