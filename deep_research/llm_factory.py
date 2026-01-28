"""
LLM Factory: Centralizes the creation of LLM clients.
Supports OpenAI, DeepSeek, Gemini, Anthropic, and OpenRouter via LangChain.
"""

from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from .settings_manager import settings

# Attempt Anthropic import
try:
    from langchain_anthropic import ChatAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ChatAnthropic = None
    ANTHROPIC_AVAILABLE = False

class LLMFactory:
    """Factory for creating LangChain LLM clients."""

    @staticmethod
    def create_llm(
        provider: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        extra_headers: Optional[Dict[str, str]] = None
    ):
        """
        Creates an LLM client based on provider and model.
        
        Args:
            provider: 'openai', 'deepseek', 'gemini', 'anthropic', or 'openrouter'
            model: Model name string
            temperature: LLM temperature
            max_tokens: Optional token limit
            extra_headers: Optional headers (mainly for OpenRouter)
        """
        
        if provider == "openai" or provider == "deepseek":
            return LLMFactory._create_openai_style(provider, model, temperature, max_tokens)
            
        elif provider == "gemini":
            return LLMFactory._create_gemini(model, temperature, max_tokens)
            
        elif provider == "anthropic":
            return LLMFactory._create_anthropic(model, temperature, max_tokens)
            
        elif provider == "openrouter":
            return LLMFactory._create_openrouter(model, temperature, max_tokens, extra_headers)
            
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    @staticmethod
    def _create_openai_style(provider: str, model: str, temperature: float, max_tokens: Optional[int]):
        """Creates clients for OpenAI or DeepSeek API (compatible with ChatOpenAI)."""
        api_key = settings.get_env("OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY")
        base_url = settings.get_nested("providers", provider, "base_url")
        
        if not api_key:
            raise ValueError(f"API Key for {provider} not found in environment.")

        kwargs = {
            "model": model,
            "temperature": temperature,
            "openai_api_key": api_key,
        }
        if base_url:
            kwargs["openai_api_base"] = base_url
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
            
        return ChatOpenAI(**kwargs)

    @staticmethod
    def _create_gemini(model: str, temperature: float, max_tokens: Optional[int]):
        """Creates Google Gemini client."""
        api_key = settings.get_env("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment.")

        kwargs = {
            "model": model,
            "temperature": temperature,
            "google_api_key": api_key,
        }
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
            
        return ChatGoogleGenerativeAI(**kwargs)

    @staticmethod
    def _create_anthropic(model: str, temperature: float, max_tokens: Optional[int]):
        """Creates Anthropic Claude client."""
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("langchain-anthropic not installed.")
            
        api_key = settings.get_env("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment.")

        kwargs = {
            "model": model,
            "temperature": temperature,
            "anthropic_api_key": api_key,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
            
        return ChatAnthropic(**kwargs)

    @staticmethod
    def _create_openrouter(model: str, temperature: float, max_tokens: Optional[int], extra_headers: Optional[Dict[str, str]]):
        """Creates OpenRouter client (OpenAI compatible)."""
        api_key = settings.get_env("OPENROUTER_API_KEY")
        base_url = settings.get_nested("providers", "openrouter", "base_url") or "https://openrouter.ai/api/v1"
        
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment.")

        headers = extra_headers or {}
        # Standard OpenRouter headers
        referer = settings.get_env("OPENROUTER_HTTP_REFERER")
        title = settings.get_env("OPENROUTER_X_TITLE")
        if referer: headers.setdefault("HTTP-Referer", referer)
        if title: headers.setdefault("X-Title", title)

        kwargs = {
            "model": model,
            "temperature": temperature,
            "openai_api_key": api_key,
            "openai_api_base": base_url,
            "default_headers": headers,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
            
        return ChatOpenAI(**kwargs)
