"""
Environment-driven config. Single source of truth — every other module reads
from `get_settings()` (cached) rather than reaching into `os.environ`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so config loads correctly even when the
# process cwd is something LiveKit picked (job subprocesses don't inherit the
# parent's cwd reliably on macOS spawn).
_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Process-wide config loaded once at startup."""

    # --- Wispoke API ---
    wispoke_api_url: str = "http://localhost:8081"
    wispoke_service_jwt_secret: str

    # --- LiveKit ---
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # --- Provider keys ---
    deepgram_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # --- Logging ---
    log_level: str = "INFO"

    # --- Agent identity (LiveKit dispatch hooks this) ---
    agent_name: str = "wispoke-booking-agent"

    model_config = SettingsConfigDict(
        env_file=str(_DOTENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("wispoke_service_jwt_secret")
    @classmethod
    def _secret_not_empty(cls, v: str) -> str:
        if not v or v.startswith("your-") or len(v) < 32:
            raise ValueError(
                "WISPOKE_SERVICE_JWT_SECRET must be at least 32 chars. "
                'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
