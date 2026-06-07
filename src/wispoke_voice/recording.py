"""
Call recording via LiveKit Egress → Supabase Storage (S3-compatible).

We use **audio-only room-composite egress**: LiveKit mixes every participant's
audio (caller + agent) into one OGG file and uploads it straight to our
Supabase Storage bucket over the S3 protocol. The worker never touches the
audio bytes — it just starts/stops the egress job.

The object key is deterministic — `{company_id}/{call_log_id}.ogg` — so the
caller doesn't need anything back from `start_recording` except the egress id
(used to stop the job). The same key is written to `voice_call_logs.recording_url`,
and the dashboard mints a signed URL from it on demand.

Everything here is best-effort: a missing config or a failed egress call logs
and returns None rather than disturbing the live call.
"""

from __future__ import annotations

from typing import Optional

from livekit import api

from wispoke_voice.config import get_settings
from wispoke_voice.observability import get_logger

logger = get_logger("wispoke.voice.recording")

RECORDING_FORMAT = "ogg"


def recording_key(company_id: str, call_log_id: str) -> str:
    """Deterministic object key for a session's recording."""
    return f"{company_id}/{call_log_id}.{RECORDING_FORMAT}"


def _lk_api() -> api.LiveKitAPI:
    s = get_settings()
    return api.LiveKitAPI(s.livekit_url, s.livekit_api_key, s.livekit_api_secret)


async def start_recording(room_name: str, company_id: str, call_log_id: str) -> Optional[str]:
    """Start audio-only egress for `room_name`. Returns the egress id, or None.

    None means "not recording" — either storage isn't configured, or the
    egress request failed. Callers treat None as "no recording for this call"
    and skip writing `recording_url`.
    """
    s = get_settings()
    if not s.recording_configured:
        logger.info(
            "recording not configured (no Supabase S3 creds) — skipping egress",
            extra={"room": room_name},
        )
        return None

    key = recording_key(company_id, call_log_id)
    request = api.RoomCompositeEgressRequest(
        room_name=room_name,
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.OGG,
                filepath=key,
                disable_manifest=True,  # don't litter the bucket with .json sidecars
                s3=api.S3Upload(
                    access_key=s.supabase_s3_access_key,
                    secret=s.supabase_s3_secret,
                    region=s.supabase_s3_region,
                    endpoint=s.supabase_s3_endpoint,
                    bucket=s.recording_bucket,
                    force_path_style=True,  # Supabase Storage requires path-style
                ),
            )
        ],
    )

    lk = _lk_api()
    try:
        info = await lk.egress.start_room_composite_egress(request)
        logger.info(
            "recording started",
            extra={"room": room_name, "egress_id": info.egress_id, "key": key},
        )
        return info.egress_id
    except Exception:
        logger.exception("failed to start egress", extra={"room": room_name, "key": key})
        return None
    finally:
        await lk.aclose()


async def stop_recording(egress_id: Optional[str]) -> None:
    """Stop an egress job. Best-effort — room-composite egress also auto-stops
    when the room empties, so a failure here just means we rely on that."""
    if not egress_id:
        return
    lk = _lk_api()
    try:
        await lk.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
        logger.info("recording stopped", extra={"egress_id": egress_id})
    except Exception:
        # Often benign: the room already closed and egress finalized itself.
        logger.warning("stop_egress failed (likely already finalized)", extra={"egress_id": egress_id})
    finally:
        await lk.aclose()
