"""Prompt assembly, i18n, and voice catalog."""

from wispoke_voice.prompts.i18n import GREETING_FALLBACKS, read_back_slot
from wispoke_voice.prompts.system import build_system_prompt
from wispoke_voice.prompts.voices import CURATED_VOICES, VoiceOption

__all__ = [
    "GREETING_FALLBACKS",
    "read_back_slot",
    "build_system_prompt",
    "CURATED_VOICES",
    "VoiceOption",
]
