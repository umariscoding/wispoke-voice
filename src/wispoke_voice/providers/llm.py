"""
LLM factory.

Routes to OpenAI or Anthropic based on tenant config. Both plugin imports are
deferred so a missing optional dependency surfaces a clean error only when
that provider is actually requested.
"""

from __future__ import annotations

from wispoke_voice.config import get_settings
from wispoke_voice.tenant.models import TenantConfig


class UnsupportedLlmProviderError(RuntimeError):
    pass


class MissingProviderKeyError(RuntimeError):
    pass


# Per-provider model fallbacks if the tenant left llm_model unset or stored a
# value that doesn't belong to their selected provider.
_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
}

_OPENAI_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"}
_ANTHROPIC_MODELS = {
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-5",
}


def _resolve_model(provider: str, requested: str) -> str:
    """Falls back to provider default if requested model is from the other
    provider — prevents a stale tenant config from blowing up the session."""
    catalog = _OPENAI_MODELS if provider == "openai" else _ANTHROPIC_MODELS
    if requested in catalog:
        return requested
    return _DEFAULT_MODELS[provider]


def make_llm(tenant: TenantConfig):
    """Return a LiveKit-compatible LLM instance for this tenant."""
    provider = tenant.providers.llm
    cfg = get_settings()

    if provider == "openai":
        from livekit.plugins import openai

        if not cfg.openai_api_key:
            raise MissingProviderKeyError("OPENAI_API_KEY is not set in wispoke-voice/.env")

        model = _resolve_model("openai", tenant.models.llm)
        return openai.LLM(model=model, temperature=0.2, api_key=cfg.openai_api_key)

    if provider == "anthropic":
        from livekit.plugins import anthropic

        if not cfg.anthropic_api_key:
            raise MissingProviderKeyError("ANTHROPIC_API_KEY is not set in wispoke-voice/.env")

        model = _resolve_model("anthropic", tenant.models.llm)
        return anthropic.LLM(model=model, temperature=0.2, api_key=cfg.anthropic_api_key)

    raise UnsupportedLlmProviderError(f"Unknown LLM provider: {provider!r}")
