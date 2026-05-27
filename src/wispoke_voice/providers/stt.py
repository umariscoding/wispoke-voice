"""
STT factory.

Currently only Deepgram Nova-3 is wired (the v1 stack); Speechmatics is a
Phase 3 add for regulated tenants — slot it in here when needed.
"""

from __future__ import annotations

from wispoke_voice.config import get_settings
from wispoke_voice.tenant.models import TenantConfig


class UnsupportedSttProviderError(RuntimeError):
    pass


class MissingProviderKeyError(RuntimeError):
    pass


def make_stt(tenant: TenantConfig):
    """Return a LiveKit-compatible STT instance for this tenant."""
    provider = tenant.providers.stt
    cfg = get_settings()

    if provider == "deepgram":
        from livekit.plugins import deepgram

        if not cfg.deepgram_api_key:
            raise MissingProviderKeyError("DEEPGRAM_API_KEY is not set in wispoke-voice/.env")

        # Nova-3 supports da, da-DK, en, en-US monolingually. Caller language
        # comes from tenant config and can change per session.
        return deepgram.STT(
            model="nova-3",
            language=tenant.language,
            smart_format=True,
            interim_results=True,
            # 300ms balances snappy turn-taking against cutting people off.
            # The semantic turn detector (MultilingualModel) is the real
            # end-of-turn authority; this is just the STT-level floor. Danish
            # has elided endings so we don't go lower than 300.
            endpointing_ms=300,
            api_key=cfg.deepgram_api_key,
        )

    if provider == "speechmatics":
        raise UnsupportedSttProviderError(
            "Speechmatics support is planned for Phase 3 (regulated tenants)."
        )

    raise UnsupportedSttProviderError(f"Unknown STT provider: {provider!r}")
