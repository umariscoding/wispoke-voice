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

    # --- Call recording (LiveKit Egress → Supabase Storage, S3-compatible) ---
    # Recording is best-effort and self-gating: if the S3 creds below aren't
    # set, the worker simply skips egress (calls still work, just no audio).
    recording_enabled: bool = True
    recording_bucket: str = "call-recordings"
    # Supabase Storage exposes an S3-compatible endpoint:
    #   https://<project-ref>.supabase.co/storage/v1/s3
    # Generate the access key/secret in Supabase → Project → Storage → S3 access.
    supabase_s3_endpoint: Optional[str] = None
    supabase_s3_region: str = "us-east-1"
    supabase_s3_access_key: Optional[str] = None
    supabase_s3_secret: Optional[str] = None

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

    @property
    def recording_configured(self) -> bool:
        """True only when egress has somewhere to upload to.

        Used by the recording module to decide whether to start egress — keeps
        the worker fully functional (calls + transcripts) on deploys that
        haven't wired Supabase Storage creds yet.
        """
        return bool(
            self.recording_enabled
            and self.supabase_s3_endpoint
            and self.supabase_s3_access_key
            and self.supabase_s3_secret
        )

    @field_validator("wispoke_api_url")
    @classmethod
    def _normalize_api_url(cls, v: str) -> str:
        """Guarantee a scheme + no trailing slash.

        httpx's AsyncClient(base_url=...) silently fails to route a schemeless
        host like `api.wispoke.com` ("Request URL is missing a protocol"), so
        every /voice/internal/* call would crash the session. Deploys commonly
        set the env var without `https://`, so we self-heal here rather than
        depend on it being set perfectly.
        """
        v = (v or "").strip().rstrip("/")
        if not v:
            return "http://localhost:8081"
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
