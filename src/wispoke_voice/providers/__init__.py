"""
Provider factories — STT / LLM / TTS.

Each factory takes a `TenantConfig` and returns a LiveKit-compatible plugin
instance. The agent never branches on provider type; it just calls these
factories and trusts the protocol. Adding a new provider = new branch in one
of these files (OCP) without touching the agent.
"""

from wispoke_voice.providers.stt import make_stt
from wispoke_voice.providers.llm import make_llm
from wispoke_voice.providers.tts import make_tts

__all__ = ["make_stt", "make_llm", "make_tts"]
