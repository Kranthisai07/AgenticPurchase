from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

try:
    from langchain_community.chat_models import ChatOllama
except ModuleNotFoundError:  # pragma: no cover - optional
    ChatOllama = None  # type: ignore

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ModuleNotFoundError:  # pragma: no cover - optional
    ChatGoogleGenerativeAI = None  # type: ignore


def _read_env(keys: list[str], default: str | None = None) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def _env_flag(keys: list[str], default: str = "0") -> bool:
    raw = _read_env(keys, default)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_chat_model(
    *,
    feature: str,
    explicit_model: str | None = None,
) -> BaseChatModel:
    """
    Build a LangChain chat model honoring layered environment overrides.

    Args:
        feature: logical feature name (e.g., "intent", "sourcing").
        explicit_model: optional hard override supplied by caller.

    Environment knobs:
      - LANGCHAIN_{FEATURE}_PROVIDER, LANGCHAIN_PROVIDER (default: "openai")
      - LANGCHAIN_{FEATURE}_MODEL, LANGCHAIN_MODEL
      - LANGCHAIN_{FEATURE}_TEMPERATURE, LANGCHAIN_TEMPERATURE (default: 0)
      - LANGCHAIN_{FEATURE}_BASE_URL, LANGCHAIN_BASE_URL
      - LANGCHAIN_PROVIDER=ollama enables local Ollama models (requires langchain-community)
    """

    feature_upper = feature.upper()
    provider = (
        _read_env([f"LANGCHAIN_{feature_upper}_PROVIDER", "LANGCHAIN_PROVIDER"], "openai")
        or "openai"
    ).strip().lower()

    temperature = float(
        _read_env(
            [f"LANGCHAIN_{feature_upper}_TEMPERATURE", "LANGCHAIN_TEMPERATURE"], "0"
        )
        or 0.0
    )

    model_name = (
        explicit_model
        or _read_env([f"LANGCHAIN_{feature_upper}_MODEL", "LANGCHAIN_MODEL"])
        or None
    )

    base_url = _read_env([f"LANGCHAIN_{feature_upper}_BASE_URL", "LANGCHAIN_BASE_URL"])

    if provider in {"ollama", "local"}:
        if ChatOllama is None:
            raise RuntimeError(
                "LANGCHAIN_PROVIDER is set to 'ollama' but langchain-community is not installed. "
                "Run `pip install langchain-community` or switch providers."
            )
        chosen_model = model_name or "llama3"
        endpoint = base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
        return ChatOllama(model=chosen_model, base_url=endpoint, temperature=temperature)

    if provider in {"google-genai", "gemini", "google"}:
        if ChatGoogleGenerativeAI is None:
            raise RuntimeError(
                "LANGCHAIN_PROVIDER is set to 'google-genai' but langchain-google-genai is not installed. "
                "Run `pip install google-generativeai langchain-google-genai` or switch providers."
            )
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Create a key via Google AI Studio "
                "(https://aistudio.google.com/app/apikey) and export GOOGLE_API_KEY before starting the backend."
            )
        chosen_model = model_name or "gemini-1.5-flash"
        return ChatGoogleGenerativeAI(
            model=chosen_model,
            temperature=temperature,
            api_key=api_key,
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Provide a key or set LANGCHAIN_PROVIDER=google-genai/ollama "
            "with a supported installation."
        )

    params: dict[str, Any] = {
        "model": model_name or "gpt-4o-mini",
        "temperature": temperature,
        "api_key": api_key,
    }
    if base_url:
        params["base_url"] = base_url
    return ChatOpenAI(**params)
