"""
Configuration and global variables for the Deep Research agent.
Centralized settings via SettingsManager, LLMFactory, and constants.
"""

import os
import sys
import warnings
import time
import json
from pathlib import Path
from typing import Optional, Dict

from .settings_manager import settings
from .constants import DEFAULT_DOCX_STYLES, MODEL_FALLBACKS
from .llm_factory import LLMFactory
from .model_routing import get_active_profile, get_role_config, Profile

# ==========================================
# PATCHES & WORKAROUNDS
# ==========================================

def _patch_importlib_metadata():
    """Patches importlib.metadata to add packages_distributions if missing."""
    try:
        import importlib.metadata as std_metadata
    except (ImportError, AttributeError):
        std_metadata = None

    try:
        import importlib_metadata as ext_metadata
    except ImportError:
        ext_metadata = None

    def packages_distributions():
        return {}

    # Target the module itself in sys.modules
    for mod in [std_metadata, ext_metadata]:
        if mod and not hasattr(mod, "packages_distributions"):
            try:
                mod.packages_distributions = packages_distributions
            except (AttributeError, TypeError):
                pass

_patch_importlib_metadata()
warnings.filterwarnings("ignore")

# PyTorch workaround
os.environ.setdefault("TORCH_LOGS", "+dynamo")
os.environ.setdefault("TORCHDYNAMO_VERBOSE", "0")

# ==========================================
# CORE CONFIGURATION
# ==========================================

TOML_CONFIG = settings.config
general_config = settings.get("general", {})

# Compatibility with legacy code
def load_company_context() -> dict:
    return {}

COMPANY_CONTEXT = {}

# Deferred Imports of Clients
try:
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from tavily import TavilyClient
    from exa_py import Exa
    from pyairtable import Api
except ImportError as e:
    print(f"❌ Critical import error: {e}")
    raise

# ==========================================
# ENVIRONMENT & FEATURES
# ==========================================

# Buscar en sección [general] del config.toml
UPLOAD_TO_R2 = settings.get_nested("general", "upload_to_r2") == True
ENABLE_PLOTS = settings.get_nested("general", "enable_plots") == True

# API Keys
openai_api_key = settings.get_env("OPENAI_API_KEY")
google_api_key = settings.get_env("GOOGLE_API_KEY")
tavily_api_key = settings.get_env("TAVILY_API_KEY")
EXA_API_KEY = settings.get_env("EXA_API_KEY")
ANTHROPIC_API_KEY = settings.get_env("ANTHROPIC_API_KEY")
OPENROUTER_API_KEY = settings.get_env("OPENROUTER_API_KEY")
AIRTABLE_API_KEY = settings.get_env("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = settings.get_env("AIRTABLE_BASE_ID")

# R2 Configuration
R2_ACCESS_KEY_ID = settings.get_env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = settings.get_env("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = settings.get_env("R2_ENDPOINT_URL")
R2_BUCKET_NAME = settings.get_env("R2_BUCKET_NAME")
R2_PUBLIC_DOMAIN = (settings.get_env("R2_PUBLIC_DOMAIN") or "").rstrip("/")

# OpenRouter Metadata
OPENROUTER_HTTP_REFERER = settings.get_env("OPENROUTER_HTTP_REFERER")
OPENROUTER_X_TITLE = settings.get_env("OPENROUTER_X_TITLE")

# Legacy Flags
USE_DEEPSEEK_FOR_TESTING = settings.is_true("use_deepseek_for_testing")
USE_CHEAP_OPENROUTER_MODELS = settings.is_true("use_cheap_openrouter_models")
DEEPSEEK_API_KEY = settings.get_env("DEEPSEEK_API_KEY")

# ==========================================
# TOOL CLIENTS
# ==========================================

# Tavily
tavily_client = None
if settings.get_nested("tools", "tavily_enabled", default=True):
    if tavily_api_key:
        try:
            tavily_client = TavilyClient(api_key=tavily_api_key)
            print("✅ Tavily client initialized")
        except Exception as e:
            print(f"⚠️ Error initializing Tavily: {e}")
    else:
        print("⚠️ TAVILY_API_KEY not found. Tavily disabled.")

# Exa
exa_client = None
if EXA_API_KEY and settings.get_nested("tools", "exa_enabled", default=True):
    try:
        exa_client = Exa(api_key=EXA_API_KEY)
        print("✅ Exa client initialized")
    except Exception as e:
        print(f"⚠️ Could not initialize Exa: {e}")

# ==========================================
# LLM INSTANTIATION SYSTEM
# ==========================================

class ModelConfig:
    """Centralizes LLM model configuration and instantiation."""
    def __init__(self):
        self.profile = get_active_profile()
        print(f"🚀 [CONFIG] ACTIVE PROFILE: {self.profile.value}")

    def get_llm(self, role: str):
        return get_llm_for_role(role)

def get_llm_for_role(role: str, use_fallback: bool = True):
    """Factory function to get an LLM client for any role with fallback support."""
    try:
        config = get_role_config(role)
        provider = config.get("provider", "openrouter")
        model = config.get("model")
        
        if not model:
            print(f"⚠️ No model defined for role {role}, falling back to 'planner'")
            config = get_role_config("planner")
            model = config.get("model")

        try:
            return LLMFactory.create_llm(
                provider=provider,
                model=model,
                temperature=config.get("temperature", 0.0),
                max_tokens=config.get("max_tokens")
            )
        except Exception as e:
            if use_fallback and model in MODEL_FALLBACKS:
                fallback_model = MODEL_FALLBACKS[model]
                print(f"      ⚠️ Error with {model}, trying fallback: {fallback_model}")
                return LLMFactory.create_llm(
                    provider=provider,
                    model=fallback_model,
                    temperature=config.get("temperature", 0.0),
                    max_tokens=config.get("max_tokens")
                )
            raise e
    except Exception as e:
        print(f"      ❌ Critical error in get_llm_for_role({role}): {e}")
        return LLMFactory.create_llm("openrouter", "deepseek/deepseek-chat")

# Instantiate configuration
model_config = ModelConfig()

# Expose instances for backward compatibility
llm_planner = model_config.get_llm("planner")
llm_analyst = model_config.get_llm("analyst")
llm_judge = model_config.get_llm("judge")
llm_matcher = model_config.get_llm("matcher")
llm_ploter = model_config.get_llm("ploter")
llm_consolidator = model_config.get_llm("consolidator")

# Special Clients - Profile Aware
# TEST: xiaomi/mimo-v2-flash:free (gratis)
# ECONOMIC: deepseek/deepseek-chat (muy barato)
# PRODUCTION/PRODUCTION_OPTIMIZED: modelos premium

active_profile = get_active_profile()

if active_profile == Profile.TEST:
    # TEST: Todo xiaomi via OpenRouter
    llm_mimo_cheap = LLMFactory.create_llm("openrouter", "xiaomi/mimo-v2-flash:free", temperature=0.0)
    llm_judge_cheap = LLMFactory.create_llm("openrouter", "xiaomi/mimo-v2-flash:free", temperature=0.0, max_tokens=700)
    llm_analyst_fast = LLMFactory.create_llm("openrouter", "xiaomi/mimo-v2-flash:free", temperature=0.3)
    llm_analyst_precision = None
    llm_judge_premium = llm_judge  # Fallback al judge del perfil
elif active_profile == Profile.ECONOMIC:
    # ECONOMIC: Todo Flash-Lite 2.5 (pipeline trick)
    llm_mimo_cheap = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.0)
    llm_judge_cheap = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.0, max_tokens=700)
    llm_analyst_fast = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.3)  # 1M contexto
    llm_analyst_precision = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.1)
    llm_judge_premium = llm_judge  # Fallback al judge del perfil
else:
    # PRODUCTION/PRODUCTION_OPTIMIZED: Flash-Lite (portero) + Flash (analista)
    llm_mimo_cheap = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.0)
    JUDGE_CHEAP_MAX_OUTPUT_TOKENS = settings.get_nested("general", "judge_cheap_max_output_tokens", default=700)
    llm_judge_cheap = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash-lite", temperature=0.0, max_tokens=JUDGE_CHEAP_MAX_OUTPUT_TOKENS)
    llm_analyst_fast = LLMFactory.create_llm("openrouter", "google/gemini-2.5-flash", temperature=0.3)
    try:
        llm_analyst_precision = LLMFactory.create_llm("openrouter", "anthropic/claude-3-5-sonnet-20241022", temperature=0.1)
    except Exception as e:
        print(f"⚠️ Could not initialize llm_analyst_precision: {e}")
        llm_analyst_precision = None
    llm_judge_premium = llm_analyst_precision if llm_analyst_precision else llm_judge

# Judge escalation thresholds
JUDGE_CHEAP_MAX_OUTPUT_TOKENS = settings.get_nested("general", "judge_cheap_max_output_tokens", default=700)
JUDGE_PREMIUM_MAX_OUTPUT_TOKENS = settings.get_nested("general", "judge_premium_max_output_tokens", default=900)
JUDGE_ESCALATE_SCORE_LOW = settings.get_nested("general", "judge_escalate_score_low", default=4.5)
JUDGE_ESCALATE_SCORE_HIGH = settings.get_nested("general", "judge_escalate_score_high", default=6.5)

# ==========================================
# AIRTABLE & STORAGE
# ==========================================

airtable_api = Api(AIRTABLE_API_KEY)
airtable_base = airtable_api.base(AIRTABLE_BASE_ID)

ITEMS_TABLE_NAME = settings.get_nested("airtable", "items_table_name", default="Items_indice")
PROYECTOS_TABLE_NAME = settings.get_nested("airtable", "proyectos_table_name", default="Proyectos")

items_table = airtable_base.table(ITEMS_TABLE_NAME)
proyectos_table = airtable_base.table(PROYECTOS_TABLE_NAME)

# ==========================================
# REPORT SETTINGS
# ==========================================

TARGET_AUDIENCE = settings.get_nested("general", "target_audience") or "CEO/Directivos"
REPORT_LANGUAGE = settings.get_nested("general", "report_language") or "Español"

# REFERENCES_STYLE and ENABLE_HYPERLINKS
REFERENCES_ENABLE_HYPERLINKS = settings.get_nested("references", "enable_hyperlinks", default=True)
REFERENCES_STYLE = (settings.get_nested("references", "style", default="IEEE")).upper()

# ==========================================
# SEARCH & POLICY CONFIG
# ==========================================

from .search_policy import PolicyConfig, SearchPolicy, SearchDepth

TAVILY_DEPTH = str(settings.get_nested("search", "tavily_search_depth") or "advanced")
SEARCH_POLICY_CONFIG = PolicyConfig(
    general_min_sources=settings.get_nested("search_policy", "general_min_sources", default=7),
    critical_min_sources=settings.get_nested("search_policy", "critical_min_sources", default=10),
    firecrawl_min_content_chars=settings.get_nested("search_policy", "firecrawl_min_existing_content_chars", default=3000),
    max_firecrawl_per_item_general=settings.get_nested("search_policy", "max_firecrawl_pages_general", default=5),
    max_firecrawl_per_item_critical=settings.get_nested("search_policy", "max_firecrawl_pages_critical", default=7),
    tavily_depth_override=SearchDepth(TAVILY_DEPTH) if TAVILY_DEPTH in ["basic", "advanced"] else None
)
search_policy = SearchPolicy(SEARCH_POLICY_CONFIG)

EXCLUDED_DOMAINS = settings.get_nested("search", "excluded_domains") or []
MAX_RESULTS_PER_QUERY = settings.get_nested("search", "max_results_per_query", default=5)
MAX_SEARCH_QUERIES = settings.get_nested("search", "max_search_queries", default=5)
SMART_SEARCH_ENABLED = settings.is_true("smart_search_enabled")

# ==========================================
# CONTEXT & EVALUATOR
# ==========================================

CONTEXT_SOURCE = settings.get_nested("context", "source", default="local")
CONTEXT_LOCAL_FOLDER = settings.get_nested("context", "local_folder", default="private_context")

# Evaluator Thresholds
TOTAL_SCORE_THRESHOLD = settings.get_nested("evaluator", "total_score_threshold", default=7)
RELEVANCE_THRESHOLD = settings.get_nested("evaluator", "relevance_score_threshold", default=8)
MIN_ACCEPTED_SOURCES = settings.get_nested("evaluator", "min_accepted_sources", default=3)
MAX_ACCEPTED_SOURCES = settings.get_nested("evaluator", "max_accepted_sources", default=15)

# ==========================================
# FIRECRAWL
# ==========================================

FIRECRAWL_ENABLED = settings.is_true("enabled", "firecrawl")
FIRECRAWL_API_KEY = settings.get_env("FIRECRAWL_API_KEY")
FIRECRAWL_ONLY_FOR_VALIDATED_SOURCES = settings.is_true("only_for_validated_sources", "firecrawl")
FIRECRAWL_MAX_CHARS_PER_SOURCE = settings.get_nested("firecrawl", "max_chars_per_source", default=15000)
FIRECRAWL_TIMEOUT_SECONDS = settings.get_nested("firecrawl", "timeout_seconds", default=30)
FIRECRAWL_MAX_CALLS_PER_ITEM = settings.get_nested("firecrawl", "max_calls_per_item", default=7)
FIRECRAWL_MIN_EXISTING_CONTENT_CHARS = settings.get_nested("firecrawl", "min_existing_content_chars", default=3000)

# ==========================================
# TOKEN LIMITS LOGIC
# ==========================================

# Additional Evaluator Configuration
evaluator_config = settings.get("evaluator", {})
EVAL_ELITE_FAST_TRACK_ENABLED = settings.is_true("elite_fast_track_enabled", "evaluator")
EVAL_GRAY_ZONE_ENABLED = settings.is_true("gray_zone_enabled", "evaluator")
EVAL_GRAY_ZONE_LOW_REJECT = settings.get_nested("evaluator", "gray_zone_low_reject", default=5.5)
EVAL_GRAY_ZONE_HIGH_ACCEPT = settings.get_nested("evaluator", "gray_zone_high_accept", default=7.5)
EVAL_CONSULTING_MIN_RELEVANCE = settings.get_nested("evaluator", "consulting_min_relevance", default=7.0)
EVAL_INSTITUTIONAL_MIN_RELEVANCE = settings.get_nested("evaluator", "institutional_min_relevance", default=5.5)
EVAL_GENERAL_MEDIA_MIN_RELEVANCE = settings.get_nested("evaluator", "general_media_min_relevance", default=8.5)
EVAL_GENERAL_MEDIA_MAX_RATIO = settings.get_nested("evaluator", "general_media_max_ratio", default=0.1)
EVAL_CONSULTING_MAX_RATIO = settings.get_nested("evaluator", "consulting_max_ratio", default=0.3)

AUTHENTICITY_THRESHOLD = settings.get_nested("evaluator", "authenticity_threshold", default=6)
RELIABILITY_THRESHOLD = settings.get_nested("evaluator", "reliability_threshold", default=6)

# Search Settings
MAX_CHARS_PER_SOURCE = settings.get_nested("search", "max_chars_per_source", default=30000)
EXA_MAX_CHARACTERS = settings.get_nested("search", "exa_max_characters", default=35000)
TAVILY_ENABLED = settings.get_nested("tools", "tavily_enabled", default=True)
EXA_ENABLED = settings.get_nested("tools", "exa_enabled", default=True)

# Search Policy Constants
MAX_RETRIES = settings.get_nested("general", "max_retries", default=3)
VERIFIER_ENABLED = settings.get_nested("tools", "verifier_enabled", default=True)
QUERY_EXPANSION_ENABLED = settings.get_nested("optimizations", "query_expansion_enabled", default=True)
URL_VALIDATION_ENABLED = settings.get_nested("optimizations", "url_validation_enabled", default=True)
CONTEXT_QUERY_VARIANTS_ENABLED = settings.get_nested("optimizations", "context_query_variants_enabled", default=True)
EXTRACTOR_ENABLED = settings.get_nested("optimizations", "extractor_enabled", default=True)

# Dynamic Config Support
CRITICAL_REPORT_TYPES = ["Strategy", "Financial", "Due_Diligence"]

def get_dynamic_config(report_type: Optional[str] = None) -> Dict[str, int]:
    """Obtains dynamic configurations based on report type."""
    is_critical = report_type in CRITICAL_REPORT_TYPES if report_type else False
    if is_critical:
        return {
            "max_retries": 3,
            "max_search_queries": 8,
            "max_results_per_query": 5,
            "max_firecrawl_calls": 7,
            "min_accepted_sources": 10,
            "max_accepted_sources": 15,
        }
    else:
        return {
            "max_retries": 2,
            "max_search_queries": 6,
            "max_results_per_query": 3,
            "max_firecrawl_calls": 5,
            "min_accepted_sources": 7,
            "max_accepted_sources": 10,
        }

# ==========================================
# TOKEN LIMITS LOGIC
# ==========================================

def get_model_limits(model_name: str, provider: str = None) -> tuple[int, int]:
    """Returns (MAX_TOKENS_MODEL, MAX_TOKENS_AVAILABLE) for a given model."""
    if not model_name:
        return 128000, 122000
    
    name = model_name.lower()
    if "gpt-4o" in name or "gpt-4-turbo" in name:
        limit = 128000
    elif "claude-3" in name:
        limit = 200000
    elif "gemini-2.0-pro" in name:
        limit = 2000000
    elif "gemini-2.0-flash" in name:
        limit = 1000000
    else:
        limit = 128000
        
    # Provider constraints - DeepSeek and MiMo have 32K limit via any provider
    if "deepseek" in name or "mimo" in name:
        limit = min(limit, 32768)
        
    reserved = 6000
    return limit, max(4000, limit - reserved)

# Descriptive variables for logs
def _get_model_name(llm):
    for attr in ["model_name", "model"]:
        if hasattr(llm, attr):
            return getattr(llm, attr)
    return "unknown"

CURRENT_PLANNER_MODEL = _get_model_name(llm_planner)
CURRENT_JUDGE_MODEL = _get_model_name(llm_judge)
CURRENT_ANALYST_MODEL = _get_model_name(llm_analyst)
CURRENT_CONSOLIDATOR_MODEL = _get_model_name(llm_consolidator)
CURRENT_MATCHER_MODEL = _get_model_name(llm_matcher)
CURRENT_PLOTER_MODEL = _get_model_name(llm_ploter) if llm_ploter else "unknown"

# Exports
CONFIG = TOML_CONFIG
CONCURRENCY_LIMIT = settings.get_nested("general", "concurrency_limit") or 3
