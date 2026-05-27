"""
Curated TTS voice catalogs, keyed by provider.

The dashboard picker shows these lists to tenants; the worker reads from the
same catalogs so a voice stored in `voice_agent_settings.voice_model` resolves
to the right provider. A voice not found for its provider falls back to that
provider's default (never another provider's voice — passing a Deepgram model
name to OpenAI, or vice versa, errors).

Keep these lists identical to
`wispoke-admin/src/components/voice-agent/VoiceModelPicker.tsx`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple


TtsProvider = Literal["deepgram", "openai", "elevenlabs", "azure"]


@dataclass(frozen=True)
class VoiceOption:
    voice_id: str  # provider-specific id (Aura model name / OpenAI voice name)
    name: str  # display label
    gender: Literal["Male", "Female", "Neutral"]
    accent: str  # short description for the picker tooltip
    languages: Tuple[str, ...]  # ISO 639-1 codes the voice handles well


# Deepgram Aura-2 — purpose-built for real-time voice agents (low TTFB,
# streaming). English-only. Order matters: first entry is the provider default.
_DEEPGRAM_VOICES: Tuple[VoiceOption, ...] = (
    VoiceOption("aura-2-thalia-en", "Thalia", "Female", "Clear, friendly", ("en",)),
    VoiceOption("aura-2-andromeda-en", "Andromeda", "Female", "Warm, casual", ("en",)),
    VoiceOption("aura-2-helena-en", "Helena", "Female", "Calm, professional", ("en",)),
    VoiceOption("aura-2-apollo-en", "Apollo", "Male", "Confident, friendly", ("en",)),
    VoiceOption("aura-2-arcas-en", "Arcas", "Male", "Natural, smooth", ("en",)),
    VoiceOption("aura-2-orion-en", "Orion", "Male", "Deep, approachable", ("en",)),
)

# OpenAI gpt-4o-mini-tts — speaks any language but English-tuned (Danish is
# mildly English-accented). Higher TTFB than Aura-2 from most regions.
_OPENAI_VOICES: Tuple[VoiceOption, ...] = (
    VoiceOption("alloy", "Alloy", "Neutral", "Balanced, professional", ("en", "da")),
    VoiceOption("nova", "Nova", "Female", "Warm, friendly", ("en", "da")),
    VoiceOption("shimmer", "Shimmer", "Female", "Gentle, calm", ("en", "da")),
    VoiceOption("coral", "Coral", "Female", "Bright, upbeat", ("en", "da")),
    VoiceOption("ash", "Ash", "Male", "Clear, confident", ("en", "da")),
    VoiceOption("onyx", "Onyx", "Male", "Deep, authoritative", ("en", "da")),
)

VOICES_BY_PROVIDER: Dict[str, Tuple[VoiceOption, ...]] = {
    "deepgram": _DEEPGRAM_VOICES,
    "openai": _OPENAI_VOICES,
}

DEFAULT_VOICE_BY_PROVIDER: Dict[str, str] = {
    "deepgram": _DEEPGRAM_VOICES[0].voice_id,  # "aura-2-thalia-en"
    "openai": _OPENAI_VOICES[0].voice_id,  # "alloy"
}

# Global fallback used when a provider has no catalog wired (elevenlabs/azure).
DEFAULT_VOICE_ID = DEFAULT_VOICE_BY_PROVIDER["deepgram"]


def get_voice(voice_id: str, provider: str) -> Optional[VoiceOption]:
    """Look up a voice within a specific provider's catalog only."""
    for v in VOICES_BY_PROVIDER.get(provider, ()):  # unknown provider → no match
        if v.voice_id == voice_id:
            return v
    return None


def default_voice_for(provider: str) -> str:
    """The fallback voice for a provider when the stored one isn't in-catalog."""
    return DEFAULT_VOICE_BY_PROVIDER.get(provider, DEFAULT_VOICE_ID)
