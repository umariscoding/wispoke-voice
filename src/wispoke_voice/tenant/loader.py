"""
Async tenant-config loader.

Wraps `api_client.get_tenant_config` and converts the raw dict into typed
dataclasses. Keeping the dict→dataclass translation here means everywhere else
in the worker speaks `TenantConfig`, not raw JSON.
"""

from __future__ import annotations

from typing import Any, Dict

from wispoke_voice.api_client import WispokeApiClient
from wispoke_voice.tenant.models import (
    Language,
    LlmProvider,
    ModelConfig,
    ProviderConfig,
    TenantConfig,
    WeeklyScheduleSlot,
)


_VALID_LANGUAGES: set[str] = {"en", "da"}
_VALID_LLM_PROVIDERS: set[str] = {"openai", "anthropic"}


def _coerce_language(raw: Any) -> Language:
    return raw if raw in _VALID_LANGUAGES else "en"  # type: ignore[return-value]


def _coerce_llm_provider(raw: Any) -> LlmProvider:
    return raw if raw in _VALID_LLM_PROVIDERS else "openai"  # type: ignore[return-value]


async def load_tenant_config(api_client: WispokeApiClient, company_id: str) -> TenantConfig:
    raw: Dict[str, Any] = await api_client.get_tenant_config(company_id)

    providers_raw = raw.get("providers") or {}
    models_raw = raw.get("models") or {}

    schedule = [
        WeeklyScheduleSlot(
            day_of_week=row["day_of_week"],
            start_time=str(row["start_time"]),
            end_time=str(row["end_time"]),
            is_active=bool(row.get("is_active", True)),
        )
        for row in (raw.get("weekly_schedule") or [])
    ]

    return TenantConfig(
        company_id=raw["company_id"],
        is_enabled=bool(raw.get("is_enabled", False)),
        business_name=raw.get("business_name") or "our office",
        business_type=raw.get("business_type"),
        business_phone=raw.get("business_phone"),
        greeting_message=raw.get("greeting_message"),
        system_prompt=raw.get("system_prompt"),
        language=_coerce_language(raw.get("language")),
        timezone=raw.get("timezone") or "Europe/Copenhagen",
        appointment_duration_min=int(raw.get("appointment_duration_min") or 30),
        appointment_fields=list(raw.get("appointment_fields") or ["name", "phone"]),
        providers=ProviderConfig(
            stt=providers_raw.get("stt") or "deepgram",
            llm=_coerce_llm_provider(providers_raw.get("llm")),
            tts=providers_raw.get("tts") or "elevenlabs",
        ),
        models=ModelConfig(
            voice=models_raw.get("voice") or "21m00Tcm4TlvDq8ikWAM",
            llm=models_raw.get("llm") or "gpt-4o",
        ),
        weekly_schedule=schedule,
    )
