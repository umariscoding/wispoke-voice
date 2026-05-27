"""
Curated ElevenLabs voice catalog.

These are vetted Flash v2.5-compatible voices from ElevenLabs' current default
"premade" set — confirmed available on free + paid tiers. The dashboard picker
shows this list to tenants; the worker reads from the same catalog so a
voice_id stored in `voice_agent_settings.voice_model` is guaranteed to exist.

ElevenLabs refreshes their premade set periodically. When that happens:
  1. Hit `GET https://api.elevenlabs.io/v1/voices` with any account API key
  2. Filter for `category == "premade"` voices that work on the free tier
  3. Update this catalog AND the matching list in
     `wispoke-admin/src/components/voice-agent/VoiceModelPicker.tsx`

The two lists MUST stay in lockstep — the worker falls back to the first
entry here if the stored voice_id isn't found, which would silently override
a tenant's saved selection if the lists drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple


@dataclass(frozen=True)
class VoiceOption:
    voice_id: str  # ElevenLabs voice_id
    name: str  # display label
    gender: Literal["Male", "Female", "Neutral"]
    accent: str  # rough description for the picker tooltip
    languages: Tuple[str, ...]  # ISO 639-1 codes the voice handles well


# Order matters — the first entry is the default for new tenants.
# All these voices are part of ElevenLabs' current premade catalog and
# Flash v2.5 supports multilingual generation including Danish.
CURATED_VOICES: Tuple[VoiceOption, ...] = (
    VoiceOption(
        voice_id="EXAVITQu4vr4xnSDxMaL",
        name="Sarah",
        gender="Female",
        accent="Mature, Reassuring, Confident",
        languages=("en", "da"),
    ),
    VoiceOption(
        voice_id="FGY2WhTYpPnrIDTdsKH5",
        name="Laura",
        gender="Female",
        accent="Enthusiast, Quirky Attitude",
        languages=("en", "da"),
    ),
    VoiceOption(
        voice_id="SAz9YHcvj6GT2YYXdXww",
        name="River",
        gender="Neutral",
        accent="Relaxed, Neutral, Informative",
        languages=("en", "da"),
    ),
    VoiceOption(
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        name="George",
        gender="Male",
        accent="Warm, Captivating Storyteller",
        languages=("en", "da"),
    ),
    VoiceOption(
        voice_id="IKne3meq5aSn9XLyUdCD",
        name="Charlie",
        gender="Male",
        accent="Deep, Confident, Energetic",
        languages=("en", "da"),
    ),
    VoiceOption(
        voice_id="CwhRBWXzGAHq8TQ4Fs17",
        name="Roger",
        gender="Male",
        accent="Laid-Back, Casual, Resonant",
        languages=("en", "da"),
    ),
)

DEFAULT_VOICE_ID = CURATED_VOICES[0].voice_id


def get_voice(voice_id: str) -> VoiceOption | None:
    for v in CURATED_VOICES:
        if v.voice_id == voice_id:
            return v
    return None
