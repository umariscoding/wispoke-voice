"""Prompt assembly, i18n, and voice catalog."""

from wispoke_voice.prompts.i18n import GREETING_FALLBACKS, read_back_slot
from wispoke_voice.prompts.system import build_system_prompt
from wispoke_voice.prompts.voices import (
    DEFAULT_VOICE_BY_PROVIDER,
    VOICES_BY_PROVIDER,
    VoiceOption,
    default_voice_for,
    get_voice,
)

__all__ = [
    "GREETING_FALLBACKS",
    "read_back_slot",
    "build_system_prompt",
    "VOICES_BY_PROVIDER",
    "DEFAULT_VOICE_BY_PROVIDER",
    "VoiceOption",
    "default_voice_for",
    "get_voice",
]
