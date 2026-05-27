"""
LiveKit Agents worker entrypoint.

One process serves all tenants — `ctx.job.metadata` carries the company_id
that came in from /voice-agent/livekit-token. For each session we:
  1. parse metadata → company_id, language
  2. open a call log row (so partial transcripts persist on early disconnect)
  3. load tenant config from wispoke-api
  4. build providers (STT/LLM/TTS) per tenant
  5. start AgentSession; greet
  6. on close: flush transcript + outcome + latency metrics

Run with:
    uv run python -m wispoke_voice.worker dev
"""

from __future__ import annotations

# Load .env into os.environ BEFORE importing livekit. Critical detail:
# LiveKit dispatches each job into a *spawned subprocess* whose cwd is NOT
# our project root, so the default `load_dotenv()` (which searches cwd) finds
# nothing. We compute the .env path relative to this file so it works in
# both the parent worker AND every spawned job subprocess.
import os  # noqa: E402
from pathlib import Path  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"  # src/wispoke_voice/worker.py → wispoke-voice/.env
load_dotenv(_DOTENV_PATH, override=False)

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

from livekit import agents  # noqa: E402
from livekit.agents import AgentServer, AgentSession, JobContext, TurnHandlingOptions  # noqa: E402
from livekit.plugins import silero  # noqa: E402
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

from wispoke_voice.agent import BookingAgent, BookingState
from wispoke_voice.api_client import WispokeApiClient
from wispoke_voice.config import get_settings
from wispoke_voice.observability import LatencyTimer, get_logger, setup_logging
from wispoke_voice.prompts import GREETING_FALLBACKS
from wispoke_voice.providers import make_llm, make_stt, make_tts
from wispoke_voice.tenant import load_tenant_config


logger = get_logger("wispoke.voice.worker")


def _parse_job_metadata(raw: Optional[str]) -> Dict[str, Any]:
    """LiveKit hands metadata as a string — we always serialize JSON on the
    API side, but be permissive to keep the worker robust against future
    routing paths (SIP dispatch, manual room create from CLI)."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("job metadata not JSON-decodable: %r", raw[:200])
        return {}


def _classify_outcome(agent: BookingAgent) -> str:
    """Map terminal state + draft into the call_log `outcome` enum."""
    if agent.draft.confirmed and agent.draft.booking_id:
        return "booked"
    if agent.state == BookingState.HANDOFF:
        return "handoff"
    if agent.state == BookingState.DONE:
        return "no_booking"
    return "aborted"


def _collect_transcript(session: AgentSession) -> List[Dict[str, Any]]:
    """Best-effort transcript extraction.

    LiveKit exposes the conversation through `session.history` (or a similar
    field depending on SDK version). We gracefully degrade: if the field
    isn't present, we return an empty list rather than crashing the flush.
    """
    history = getattr(session, "history", None)
    if not history:
        return []
    items = getattr(history, "items", history)
    out: List[Dict[str, Any]] = []
    for item in items or []:
        # Try a few attribute shapes used across LiveKit SDK versions.
        role = getattr(item, "role", None) or (item.get("role") if isinstance(item, dict) else None)
        content = (
            getattr(item, "content", None)
            or getattr(item, "text", None)
            or (item.get("content") if isinstance(item, dict) else None)
        )
        if role is None and content is None:
            continue
        # Flatten content blocks to a single string for the call log.
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        out.append({"role": str(role) if role else "system", "content": str(content or "")})
    return out


async def _run_session(ctx: JobContext) -> None:
    """One LiveKit job = one tenant voice session."""

    meta = _parse_job_metadata(ctx.job.metadata)
    company_id = meta.get("company_id")
    if not company_id:
        # Without a tenant we can't safely run — bail before any setup.
        logger.error(
            "job dispatched with no company_id in metadata",
            extra={"room": ctx.room.name, "metadata": meta},
        )
        return

    language = meta.get("language") or "en"
    source = meta.get("source") or "browser"

    # Log resolved settings ONCE per session so misconfiguration (wrong API
    # URL, missing key) is immediately visible without grepping startup logs.
    from wispoke_voice.config import get_settings as _get_settings

    _cfg = _get_settings()
    logger.info(
        "session starting",
        extra={
            "company_id": company_id,
            "room": ctx.room.name,
            "language": language,
            "source": source,
            "wispoke_api_url": _cfg.wispoke_api_url,
            "dotenv_path": str(_DOTENV_PATH),
        },
    )

    api = WispokeApiClient(company_id=company_id)
    timer = LatencyTimer()
    started_at = datetime.now(timezone.utc)
    call_log_id: Optional[str] = None
    agent: Optional[BookingAgent] = None
    # `session` is referenced in the finally block; declare here so the
    # exception path sees `None` rather than UnboundLocalError if we crash
    # before assignment.
    session: Optional[AgentSession] = None

    try:
        # Connect to the room FIRST so LiveKit sees the participant join.
        # Without this the framework warns "job task completed without
        # establishing a connection" — even if session.start would do it
        # implicitly, doing it eagerly tightens the dispatch ack and gives
        # us a clean place to fail loudly if room setup itself is broken.
        await ctx.connect()

        # Open the call log second. Non-fatal: if the API is down we still
        # let the session run so the caller hears the agent — they just
        # won't get a transcript row.
        try:
            with timer.span("api.open_call_log"):
                call_log_id = await api.open_call_log(
                    company_id,
                    room_name=ctx.room.name,
                    language=language,
                    source=source,
                )
        except Exception:
            logger.exception(
                "couldn't open call_log — is wispoke-api reachable?",
                extra={"wispoke_api_url": _cfg.wispoke_api_url},
            )

        with timer.span("api.load_tenant_config"):
            tenant = await load_tenant_config(api, company_id)

        # The `is_enabled` toggle only gates production traffic (SIP/phone).
        # Browser test calls from the dashboard are the *means* of validating
        # the agent before enabling it for real callers, so we let them through
        # regardless of the toggle. SIP callers (Phase 2) will respect the flag.
        if not tenant.is_enabled and source != "browser":
            logger.warning(
                "tenant has voice agent disabled — declining session",
                extra={"company_id": company_id, "call_log_id": call_log_id, "source": source},
            )
            return

        # Override tenant language with the per-session language if the FE
        # specified one (e.g. dashboard language toggle).
        if language in ("en", "da") and language != tenant.language:
            tenant = type(tenant)(  # frozen dataclass — clone with override
                **{**tenant.__dict__, "language": language}
            )

        agent = BookingAgent(tenant=tenant, api_client=api, timer=timer)

        session = AgentSession(
            stt=make_stt(tenant),
            llm=make_llm(tenant),
            tts=make_tts(tenant),
            vad=silero.VAD.load(),
            turn_handling=TurnHandlingOptions(
                turn_detection=MultilingualModel(),
            ),
        )

        await session.start(room=ctx.room, agent=agent)

        # Greet first so the caller hears the agent immediately.
        greeting = tenant.greeting_message or GREETING_FALLBACKS.get(tenant.language, GREETING_FALLBACKS["en"])
        with timer.span("greeting"):
            await session.generate_reply(instructions=f"Greet the caller exactly with: {greeting}")

        # Hold the coroutine open until the room closes; the LiveKit runtime
        # cancels this task automatically when the participant disconnects.
        await asyncio.Future()

    except asyncio.CancelledError:
        # Normal shutdown path (participant disconnected). Let it propagate
        # after we flush in the finally block.
        raise
    except Exception:
        logger.exception(
            "voice session crashed",
            extra={"company_id": company_id, "call_log_id": call_log_id},
        )
    finally:
        # Flush the call log regardless of how we got here. We always want a
        # row in the dashboard so the user can see what happened.
        if call_log_id:
            try:
                outcome = _classify_outcome(agent) if agent else "aborted"
                transcript: List[Dict[str, Any]] = []
                try:
                    # `session` may not exist if we crashed before its assignment.
                    transcript = _collect_transcript(session)  # type: ignore[name-defined]
                except NameError:
                    pass
                await api.finalize_call_log(
                    call_log_id,
                    transcript=transcript,
                    outcome=outcome,
                    appointment_id=(agent.draft.booking_id if agent else None),
                    latency_metrics=timer.snapshot(),
                    started_at_iso=started_at.isoformat(),
                )
            except Exception:
                logger.exception("call log flush failed", extra={"call_log_id": call_log_id})

        await api.aclose()


# ─── AgentServer bootstrap ─────────────────────────────────────────────────


_settings = get_settings()
setup_logging(_settings.log_level)

server = AgentServer()


@server.rtc_session(agent_name=_settings.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    await _run_session(ctx)


def main() -> None:
    """CLI entry — picks up `dev` / `start` / `download-files` from argv."""
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
