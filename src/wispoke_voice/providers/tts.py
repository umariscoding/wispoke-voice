"""
TTS factory.

Deepgram Aura-2 is the Phase 0 default — measured ~0.77s TTFB from our region
vs ~1.6s for OpenAI TTS, it streams, and it rides the Deepgram key we already
use for STT (one vendor, one less key). English-only, which is fine for the
English-first MVP.

Other providers stay wired behind the abstraction:
  • OpenAI gpt-4o-mini-tts — good quality, but ~2x the TTFB from our region.
  • ElevenLabs Flash v2.5 — best native Danish, but needs a paid plan (free
    tier gets flagged for "unusual activity" under any real volume).
  • Azure da-DK-JeppeNeural — the brand-safe native-Danish option to add when
    Danish quality becomes critical. (stub — wire when needed)

The agent never branches on provider; it just calls `make_tts(tenant)`.
"""

from __future__ import annotations

from wispoke_voice.config import get_settings
from wispoke_voice.prompts.voices import default_voice_for, get_voice
from wispoke_voice.tenant.models import TenantConfig


class UnsupportedTtsProviderError(RuntimeError):
    pass


class MissingProviderKeyError(RuntimeError):
    pass


def _resolve_voice(tenant: TenantConfig) -> str:
    """Catalog voice for this tenant's TTS provider, falling back to that
    provider's default if the stored voice belongs to a different provider
    (e.g. a leftover Deepgram model name after switching to OpenAI)."""
    provider = tenant.providers.tts
    voice = get_voice(tenant.models.voice, provider)
    return voice.voice_id if voice else default_voice_for(provider)


def make_tts(tenant: TenantConfig):
    """Return a LiveKit-compatible TTS instance for this tenant."""
    provider = tenant.providers.tts
    cfg = get_settings()

    if provider == "deepgram":
        from livekit.plugins import deepgram

        if not cfg.deepgram_api_key:
            raise MissingProviderKeyError("DEEPGRAM_API_KEY is not set in wispoke-voice/.env")
        return deepgram.TTS(model=_resolve_voice(tenant), api_key=cfg.deepgram_api_key)

    if provider == "openai":
        from livekit.plugins import openai

        if not cfg.openai_api_key:
            raise MissingProviderKeyError("OPENAI_API_KEY is not set in wispoke-voice/.env")
        return openai.TTS(model="gpt-4o-mini-tts", voice=_resolve_voice(tenant), api_key=cfg.openai_api_key)

    if provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        if not cfg.elevenlabs_api_key:
            raise MissingProviderKeyError("ELEVENLABS_API_KEY is not set in wispoke-voice/.env")
        return elevenlabs.TTS(
            voice_id=_resolve_voice(tenant),
            model="eleven_flash_v2_5",
            api_key=cfg.elevenlabs_api_key,
        )

    if provider == "azure":
        raise UnsupportedTtsProviderError(
            "Azure TTS isn't wired yet — add it here for native Danish (da-DK-JeppeNeural)."
        )

    raise UnsupportedTtsProviderError(f"Unknown TTS provider: {provider!r}")
