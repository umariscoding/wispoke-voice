"""
System prompt template.

The agent's instructions are composed from:
1. base rules every tenant inherits (booking integrity, tool discipline)
2. tenant-specific overrides (business name/type, custom instructions)
3. language-specific opener so the agent answers in the right tongue from
   the first token

The base rules are deliberately blunt: never invent times, always read back,
always use tools. These rules + the state machine + JSON-schema args are the
three layers that prevent hallucinated bookings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

from wispoke_voice.tenant.models import TenantConfig, WeeklyScheduleSlot


Language = Literal["en", "da"]


_BASE_RULES_EN = """\
You are a voice booking agent. Follow these rules without exception:

1. NEVER state availability you did not receive from `get_available_slots`. \
If asked about times before calling that tool, say you'll check and call it.
2. ALWAYS read the slot back to the caller (using the exact words from \
`read_back_slot`) and get a clear "yes" BEFORE calling `create_booking`. \
"Maybe" or silence is NOT a yes.
3. Collect required fields (name, phone) before offering slots. Spell phone \
digits back one at a time to confirm.
4. If the caller asks something off-topic, briefly answer then steer back to \
booking. If they ask for a human, call `request_human_handoff`.
5. Speak in the caller's language. Default is the tenant default; if they \
switch, switch with them.
6. Keep responses short — one to two sentences. Voice users hate monologues.
7. When unsure, say so and call `get_available_slots` again. Do NOT guess.
"""

_BASE_RULES_DA = """\
Du er en stemmebookingagent. Følg disse regler uden undtagelse:

1. NÆVN ALDRIG ledige tider, du ikke har modtaget fra `get_available_slots`. \
Hvis kunden spørger om tider, før du har kaldt værktøjet, sig at du tjekker \
og kald det.
2. Læs ALTID tiden op for kunden (med ordlyden fra `read_back_slot`) og få \
en tydelig "ja" FØR du kalder `create_booking`. "Måske" eller tavshed er IKKE \
et ja.
3. Indhent de påkrævede oplysninger (navn, telefon), før du tilbyder tider. \
Stav telefonnummeret tilbage ét ciffer ad gangen.
4. Hvis kunden spørger om noget andet, svar kort og drej tilbage til \
bookingen. Hvis de vil tale med en person, kald `request_human_handoff`.
5. Tal kundens sprog. Standardsproget er tenantens; skifter de, skifter du med.
6. Hold svarene korte — én til to sætninger. Stemmesamtaler kræver det.
7. Når du er i tvivl, sig det og kald `get_available_slots` igen. GÆT IKKE.
"""


# 0 = Sunday in our DB (matches Postgres convention chosen in migration 004).
_DAY_NAMES_EN = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_DAY_NAMES_DA = ("søndag", "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag")


def _hhmm(time_str: str) -> str:
    """Coerce a Postgres TIME (`HH:MM:SS` or `HH:MM`) into spoken-friendly `H:MM`/`H` form."""
    parts = time_str.split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return time_str
    if m == 0:
        return f"{h}:00"
    return f"{h}:{m:02d}"


def _is_full_day(slot: WeeklyScheduleSlot) -> bool:
    """A slot spanning ~00:00 to ~24:00 counts as a full day. We allow some
    slack (23:59 / 23:59:59) because the DB CHECK constraint forbids 24:00."""
    starts_at_zero = slot.start_time.startswith("00:00")
    ends_at_eod = slot.end_time.startswith(("23:59", "24:00"))
    return starts_at_zero and ends_at_eod


def format_business_hours(slots: Iterable[WeeklyScheduleSlot], language: Literal["en", "da"]) -> str:
    """Render the weekly schedule as a single short sentence the LLM can read.

    Raw schedule arrays are LLM-hostile: the model wastes tokens parsing them
    and sometimes hallucinates wrong hours. Pre-formatting once at session
    start eliminates both problems and saves ~30-50 tokens per turn.

    Three cases produce three styles:
      • All 7 days fully open       → "open 24/7"
      • All days same window        → "open daily 9 AM to 5 PM"
      • Mixed                       → "open Mon-Fri 9 AM to 5 PM, Sat 10-2; closed Sun"
    """
    active = [s for s in slots if s.is_active]
    if not active:
        return "no business hours configured" if language == "en" else "ingen åbningstider konfigureret"

    # Group by (start, end) so identical windows collapse.
    days_by_window: dict[tuple[str, str], list[int]] = {}
    for s in active:
        key = (s.start_time, s.end_time)
        days_by_window.setdefault(key, []).append(s.day_of_week)

    full_day_days = {dow for s in active if _is_full_day(s) for dow in [s.day_of_week]}

    # Case 1: 24/7 — all 7 days, all full-day.
    if len(full_day_days) == 7:
        return "open 24/7 (any time of day)" if language == "en" else "åben døgnet rundt"

    day_names = _DAY_NAMES_DA if language == "da" else _DAY_NAMES_EN
    parts: list[str] = []
    for (start, end), days in days_by_window.items():
        days_sorted = sorted(days)
        # Render day list as "Mon-Fri" if contiguous, otherwise "Mon, Wed, Fri".
        if len(days_sorted) > 1 and days_sorted == list(range(days_sorted[0], days_sorted[-1] + 1)):
            day_label = f"{day_names[days_sorted[0]]}-{day_names[days_sorted[-1]]}"
        else:
            day_label = ", ".join(day_names[d] for d in days_sorted)
        window = f"{_hhmm(start)} to {_hhmm(end)}" if language == "en" else f"{_hhmm(start)} til {_hhmm(end)}"
        parts.append(f"{day_label} {window}")

    closed_days = [day_names[d] for d in range(7) if d not in {dow for dows in days_by_window.values() for dow in dows}]
    closed_clause = ""
    if closed_days:
        closed_clause = f"; closed {', '.join(closed_days)}" if language == "en" else f"; lukket {', '.join(closed_days)}"

    prefix = "open " if language == "en" else "åben "
    return prefix + "; ".join(parts) + closed_clause


def _today_in_tenant_tz(tenant: TenantConfig) -> str:
    """Today's date in YYYY-MM-DD in the tenant's local timezone.

    The LLM has no inherent notion of "today" — its training cutoff means it
    will happily pick a date from 2023 if not told otherwise. Injecting the
    current date here is the single fix that prevents stale-year hallucinations.
    """
    try:
        tz = ZoneInfo(tenant.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).strftime("%Y-%m-%d")


def build_system_prompt(tenant: TenantConfig) -> str:
    """Compose the final system prompt from base rules + tenant context."""
    rules = _BASE_RULES_DA if tenant.language == "da" else _BASE_RULES_EN
    today = _today_in_tenant_tz(tenant)
    hours = format_business_hours(tenant.weekly_schedule, tenant.language)

    if tenant.language == "da":
        identity = (
            f"Du er receptionist hos {tenant.business_name}"
            + (f" — en {tenant.business_type}." if tenant.business_type else ".")
        )
        booking_ctx = (
            f"I dag er {today} (tidszone: {tenant.timezone}). "
            f"Forretningen er {hours}. "
            f"Når kunden siger 'i morgen', 'næste tirsdag' osv., omsæt det "
            f"til en ISO-dato (YYYY-MM-DD) ud fra denne dato. "
            f"Standardvarigheden for en aftale er {tenant.appointment_duration_min} minutter."
        )
    else:
        identity = (
            f"You are the receptionist at {tenant.business_name}"
            + (f" — a {tenant.business_type}." if tenant.business_type else ".")
        )
        booking_ctx = (
            f"Today is {today} (timezone: {tenant.timezone}). "
            f"The business is {hours}. "
            f"When the caller says 'tomorrow', 'next Tuesday', etc., convert "
            f"it to an ISO date (YYYY-MM-DD) relative to today. NEVER use a "
            f"date from your training data — always compute from today. "
            f"Default appointment length is {tenant.appointment_duration_min} minutes."
        )

    parts = [identity, booking_ctx, rules]
    if tenant.system_prompt:
        # Tenant overrides come last so they can refine but never weaken the
        # base safety rules above.
        parts.append("Additional tenant instructions:\n" + tenant.system_prompt.strip())

    return "\n\n".join(parts)
