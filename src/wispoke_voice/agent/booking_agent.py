"""
BookingAgent — the LiveKit Agent subclass that runs the booking conversation.

Design notes:
- Tools live as `@function_tool` methods on this class because LiveKit's
  introspection picks them up from the Agent instance.
- All business logic is delegated: the agent only orchestrates. The
  `WispokeApiClient` does HTTP; `StateMachine` decides if a tool is allowed
  to fire right now; `prompts.read_back_slot` formats the read-back string.
- Tool docstrings double as the description the LLM sees in the function
  schema, so phrasing matters.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from livekit.agents import Agent, RunContext, function_tool

from wispoke_voice.agent.state_machine import BookingState, StateMachine
from wispoke_voice.api_client import WispokeApiClient, WispokeApiError
from wispoke_voice.observability import LatencyTimer
from wispoke_voice.prompts import GREETING_FALLBACKS, build_system_prompt, read_back_slot
from wispoke_voice.tenant.models import BookingDraft, Slot, TenantConfig


logger = logging.getLogger("wispoke.voice.agent")


# Loose phone normalization — strip whitespace, dashes, parens. We don't
# enforce country code here because Phase 0 is web-test where callers may
# type any format; tightening happens at the FastAPI/DB layer if needed.
_PHONE_STRIP = re.compile(r"[\s\-\(\)\.]")


def _normalize_phone(raw: str) -> str:
    return _PHONE_STRIP.sub("", raw)


# Filler phrases spoken while a tool runs. Without these, the caller hears
# 1-2s of dead air during DB / LLM round-trips and starts to talk over the
# agent. Production voice platforms (Retell, Vapi) treat these as mandatory.
# Pick one randomly per call to avoid the "robot says the same thing every
# time" feel.
_FILLER_PHRASES = {
    "en": (
        "Let me check that for you.",
        "One moment please.",
        "Just a second.",
        "Let me pull that up.",
    ),
    "da": (
        "Lad mig lige tjekke det.",
        "Et øjeblik, tak.",
        "Lige et sekund.",
        "Jeg finder det lige frem.",
    ),
}


def _pick_filler(language: str) -> str:
    """Cheap deterministic-ish pick — `random` is plenty for this."""
    import random

    phrases = _FILLER_PHRASES.get(language, _FILLER_PHRASES["en"])
    return random.choice(phrases)


async def _speak_filler(ctx: RunContext, language: str) -> None:
    """Fire the filler phrase BEFORE the slow work starts.

    `session.say()` returns once the TTS is scheduled — the actual playback
    runs concurrently with whatever we do next. So the caller hears
    "Let me check..." while the API/LLM call is in flight, masking 200-1500ms
    of latency. Non-fatal: if scheduling the speech fails, we just proceed.
    """
    try:
        await ctx.session.say(_pick_filler(language), allow_interruptions=True)
    except Exception:
        logger.debug("filler phrase scheduling failed (non-fatal)", exc_info=True)


class BookingAgent(Agent):
    """Voice booking agent. One instance per LiveKit session."""

    def __init__(
        self,
        *,
        tenant: TenantConfig,
        api_client: WispokeApiClient,
        timer: Optional[LatencyTimer] = None,
    ) -> None:
        super().__init__(instructions=build_system_prompt(tenant))
        self._tenant = tenant
        self._api = api_client
        self._timer = timer or LatencyTimer()
        self._state = StateMachine()
        self._draft = BookingDraft()

    # ─── Public read-only accessors (used by worker.py on disconnect) ──────

    @property
    def tenant(self) -> TenantConfig:
        return self._tenant

    @property
    def draft(self) -> BookingDraft:
        return self._draft

    @property
    def state(self) -> BookingState:
        return self._state.current

    @property
    def timer(self) -> LatencyTimer:
        return self._timer

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    async def on_enter(self) -> None:
        """Fired by the framework the moment the agent joins the session.

        This is the canonical LiveKit greeting hook. We `say()` the configured
        greeting WITHOUT awaiting the SpeechHandle — that schedules the speech
        and returns immediately, so a slow/stalled TTS connection can never
        block the session. `allow_interruptions=True` means even if the
        greeting hangs mid-playout, the caller's speech still breaks through
        and the agent stays responsive. (A previous version awaited the speech
        with interruptions disabled, which could lock the session in a
        permanent "agent speaking" state if TTS stalled.)
        """
        greeting = self._tenant.greeting_message or GREETING_FALLBACKS.get(
            self._tenant.language, GREETING_FALLBACKS["en"]
        )
        self.session.say(greeting, allow_interruptions=True)

    # ─── Tools (the LLM-callable surface) ──────────────────────────────────
    #
    # The order roughly follows the conversation arc: collect → propose →
    # confirm. Each tool docstring is the description the LLM sees.

    @function_tool
    async def record_caller_details(
        self,
        ctx: RunContext,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> str:
        """Save what the caller has told you about themselves so far.

        Call this every time the caller gives a new field (name, phone,
        email). Pass only the field(s) they just provided; we'll merge it
        with what's already collected. After calling this, check whether
        you still need to ask for any missing required fields before
        offering appointment times.
        """
        if name:
            self._draft.caller_name = name.strip()
        if phone:
            self._draft.caller_phone = _normalize_phone(phone)
        if email:
            self._draft.caller_email = email.strip()

        # Promote state once we have everything required to propose slots.
        if self._draft.is_ready_to_propose(self._tenant.appointment_fields):
            if self._state.current in (BookingState.GREETING, BookingState.COLLECTING):
                self._state.transition(BookingState.PROPOSING)

        missing = [
            f
            for f in self._tenant.appointment_fields
            if getattr(self._draft, f"caller_{f}", None) in (None, "")
        ]
        if missing:
            return f"Got it. Still need: {', '.join(missing)}."
        return "Got it — I have what I need to offer you a time."

    @function_tool
    async def get_available_slots(
        self,
        ctx: RunContext,
        date_from: str,
        date_to: Optional[str] = None,
    ) -> dict:
        """Look up real appointment slots from the booking calendar.

        Use this whenever the caller asks about availability. NEVER state
        times to the caller until this tool has returned them. `date_from`
        and `date_to` are ISO dates (YYYY-MM-DD); if `date_to` is omitted
        we look up just that one day. Returns a list of slots in the format
        the read-back tool can consume.
        """
        # Phase 0: single-day lookup. Multi-day support is a Phase 1 nicety
        # (e.g. "show me anytime this week") that we'll layer in once the
        # FastAPI side exposes a range endpoint to the worker.
        target = date_from
        if date_to and date_to != date_from:
            logger.info(
                "voice_agent: multi-day slot request collapsed to %s (range not wired in Phase 0)",
                date_from,
                extra={"company_id": self._tenant.company_id, "date_to": date_to},
            )

        # Speak a filler BEFORE the API call so the caller hears the agent
        # "thinking" instead of dead air. The TTS playback runs concurrently
        # with the API request.
        await _speak_filler(ctx, self._tenant.language)

        with self._timer.span("tool.get_available_slots"):
            try:
                payload = await self._api.get_available_slots(self._tenant.company_id, target)
            except WispokeApiError as e:
                logger.warning("get_available_slots failed: %s", e)
                return {
                    "error": "Couldn't reach the calendar just now. Try again in a moment.",
                    "slots": [],
                }

        raw_slots = payload.get("slots", [])
        # Materialize as our typed Slot objects so we can build the read-back
        # string later without re-parsing.
        slots = [
            Slot(scheduled_date=target, start_time=s["start_time"][:5], end_time=s["end_time"][:5])
            for s in raw_slots
        ]
        return {
            "date": target,
            "slots": [
                {"key": s.key, "start_time": s.start_time, "end_time": s.end_time} for s in slots
            ],
            "count": len(slots),
        }

    @function_tool
    async def propose_slot(
        self,
        ctx: RunContext,
        scheduled_date: str,
        start_time: str,
    ) -> str:
        """Read a specific slot back to the caller and ask for confirmation.

        Call this AFTER `get_available_slots` returned the slot you want to
        offer, and AFTER you have the caller's name + phone. The returned
        string is what you should SAY VERBATIM. Once you've said it,
        you're in the read-back state and must wait for a clear yes before
        calling `create_booking`.

        `scheduled_date` must be a YYYY-MM-DD string; `start_time` must be
        an HH:MM string that appeared in a recent `get_available_slots`
        response.
        """
        if not self._draft.is_ready_to_propose(self._tenant.appointment_fields):
            missing = [
                f
                for f in self._tenant.appointment_fields
                if getattr(self._draft, f"caller_{f}", None) in (None, "")
            ]
            return f"Need {', '.join(missing)} from the caller before offering a slot."

        # Compute end_time from configured duration; the availability layer
        # already validated the slot fits, so we mirror its math here.
        try:
            h, m = (int(x) for x in start_time.split(":"))
        except ValueError:
            return "start_time must be HH:MM."

        total_min = h * 60 + m + self._tenant.appointment_duration_min
        end_h, end_m = divmod(total_min, 60)
        end_time = f"{end_h:02d}:{end_m:02d}"

        slot = Slot(scheduled_date=scheduled_date, start_time=start_time, end_time=end_time)
        self._draft.selected_slot = slot
        self._state.transition(BookingState.READING_BACK)

        return read_back_slot(self._tenant.language, slot, self._tenant.business_name)

    @function_tool
    async def confirm_intent(self, ctx: RunContext, caller_said_yes: bool) -> str:
        """Record whether the caller confirmed the proposed slot.

        Call this immediately after you spoke the read-back string and the
        caller responded. Pass `caller_said_yes=True` only if their answer
        was unambiguously affirmative ("yes", "ja", "that works", "sounds
        good"). For "maybe", "uh", or any hesitation, pass False and offer
        to look up alternatives.
        """
        if self._state.current != BookingState.READING_BACK:
            return "Not in read-back state. Call `propose_slot` first."

        if caller_said_yes:
            self._state.transition(BookingState.CONFIRMING)
            return "OK. Call `create_booking` now."

        self._draft.selected_slot = None
        self._state.transition(BookingState.PROPOSING)
        return "OK — find an alternative slot."

    @function_tool
    async def create_booking(self, ctx: RunContext) -> str:
        """Commit the booking to the calendar.

        Call this ONLY after `confirm_intent(caller_said_yes=True)`. We use
        the caller details and slot already in working memory — no args
        needed. Returns a short confirmation string you should read back to
        the caller along with a booking reference.
        """
        if not self._state.can_call("create_booking"):
            return (
                "Not allowed yet. You need a confirmed yes from the caller. "
                "Call `confirm_intent` first."
            )
        if not self._draft.is_ready_to_book(self._tenant.appointment_fields):
            return "Missing required fields — cannot book."

        slot = self._draft.selected_slot
        assert slot is not None  # is_ready_to_book guarantees this

        # Filler — booking write is the slowest tool (~1s for DB insert +
        # conflict check). Speaking while we work hides almost all of it.
        await _speak_filler(ctx, self._tenant.language)

        with self._timer.span("tool.create_booking"):
            try:
                appt = await self._api.create_appointment(
                    self._tenant.company_id,
                    caller_name=self._draft.caller_name,
                    caller_phone=self._draft.caller_phone,
                    caller_email=self._draft.caller_email,
                    scheduled_date=slot.scheduled_date,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    duration_min=self._tenant.appointment_duration_min,
                    notes=self._draft.notes,
                )
            except WispokeApiError as e:
                logger.warning(
                    "create_appointment failed",
                    extra={"company_id": self._tenant.company_id, "error": str(e)},
                )
                # 400 from the booking service usually means the slot just
                # filled — recover gracefully so the caller can pick another.
                self._draft.selected_slot = None
                self._draft.confirmed = False
                self._state.transition(BookingState.PROPOSING)
                return (
                    "That slot just filled. Apologize briefly and call "
                    "`get_available_slots` again."
                )

        self._draft.confirmed = True
        self._draft.booking_id = appt.get("appointment_id")
        self._state.transition(BookingState.DONE)

        # Phase 0 doesn't issue user-facing booking refs — the appointment_id
        # is internal. Keep the spoken response short.
        if self._tenant.language == "da":
            return f"Booket. Bekræft det kort til kunden."
        return f"Booked. Confirm it briefly to the caller."

    @function_tool
    async def request_human_handoff(self, ctx: RunContext, reason: str) -> str:
        """Mark this call for handoff to a human agent.

        Call this when the caller asks for a person, when you've failed
        a task twice, or when something the caller asks is clearly out of
        scope (medical advice, account changes, etc). `reason` is a short
        free-text note that gets attached to the call log.
        """
        self._state.transition(BookingState.HANDOFF)
        self._draft.notes = (self._draft.notes or "") + f"\n[handoff] {reason}"
        if self._tenant.language == "da":
            return (
                "Markeret til overdragelse til en kollega. "
                "Sig kort: 'Jeg sætter dig over til en kollega.'"
            )
        return (
            "Marked for human handoff. Briefly say: "
            "'Let me transfer you to a colleague.'"
        )
