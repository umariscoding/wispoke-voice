"""
TTS factory.

ElevenLabs Flash v2.5 is the Phase 0 path (75ms model latency, native Danish).
Cartesia / Azure are stubs — wire when needed.
"""

from __future__ import annotations

from wispoke_voice.config import get_settings
from wispoke_voice.prompts.voices import get_voice
from wispoke_voice.tenant.models import TenantConfig


class UnsupportedTtsProviderError(RuntimeError):
    pass


class MissingProviderKeyError(RuntimeError):
    pass


def make_tts(tenant: TenantConfig):
    """Return a LiveKit-compatible TTS instance for this tenant."""
    provider = tenant.providers.tts
    cfg = get_settings()

    if provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        if not cfg.elevenlabs_api_key:
            raise MissingProviderKeyError(
                "ELEVENLABS_API_KEY is not set in wispoke-voice/.env"
            )

        # If the tenant's voice_id isn't in our curated catalog (e.g. saved
        # from a previous catalog version that ElevenLabs has since dropped),
        # fall back to the current default. Keeps stale config from breaking
        # a call.
        from wispoke_voice.prompts.voices import DEFAULT_VOICE_ID

        voice = get_voice(tenant.models.voice)
        voice_id = voice.voice_id if voice else DEFAULT_VOICE_ID

        # Pass api_key explicitly — the plugin looks for ELEVEN_API_KEY (not
        # ELEVENLABS_API_KEY) in env, and we don't want to depend on env var
        # name compatibility across SDK versions.
        return elevenlabs.TTS(
            voice_id=voice_id,
            model="eleven_flash_v2_5",  # ~75ms model latency, en + da native
            api_key=cfg.elevenlabs_api_key,
        )

    if provider in ("cartesia", "azure"):
        raise UnsupportedTtsProviderError(
            f"{provider!r} TTS isn't wired yet — extend providers/tts.py."
        )

    raise UnsupportedTtsProviderError(f"Unknown TTS provider: {provider!r}")
