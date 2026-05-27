"""
Read-back string builders for en + da.

These are the *only* place where the agent generates human-language slot
descriptions. The LLM never improvises a slot phrasing on its own — it calls
the read-back function via a tool and reads the returned string verbatim.
That removes any chance of the model paraphrasing a wrong date/time.

Numbers and dates are pre-normalized here (English-spoken digits / Danish
spelled-out dates) because ElevenLabs `apply_text_normalization` is Enterprise
only. Doing it in the prompt sidesteps the gate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from wispoke_voice.tenant.models import Slot


Language = Literal["en", "da"]


GREETING_FALLBACKS: dict[Language, str] = {
    "en": "Hello! Thanks for calling. How can I help you today?",
    "da": "Hej! Tak fordi du ringer. Hvordan kan jeg hjælpe dig i dag?",
}


_DA_MONTHS: dict[int, str] = {
    1: "januar", 2: "februar", 3: "marts", 4: "april", 5: "maj", 6: "juni",
    7: "juli", 8: "august", 9: "september", 10: "oktober", 11: "november", 12: "december",
}

_DA_WEEKDAYS: dict[int, str] = {
    0: "mandag", 1: "tirsdag", 2: "onsdag", 3: "torsdag",
    4: "fredag", 5: "lørdag", 6: "søndag",
}

_EN_MONTHS: dict[int, str] = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}

_EN_WEEKDAYS: dict[int, str] = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


def _format_date(d: date, language: Language) -> str:
    weekday = d.weekday()  # 0=Monday … 6=Sunday
    if language == "da":
        return f"{_DA_WEEKDAYS[weekday]} den {d.day}. {_DA_MONTHS[d.month]}"
    return f"{_EN_WEEKDAYS[weekday]} {_EN_MONTHS[d.month]} {d.day}"


def _format_time(time_hhmm: str, language: Language) -> str:
    """`time_hhmm` is "HH:MM" 24h. Danish uses "kl. 14:30"; English "2:30 PM"."""
    try:
        h, m = (int(x) for x in time_hhmm.split(":")[:2])
    except (ValueError, IndexError):
        return time_hhmm

    if language == "da":
        return f"klokken {h:02d}:{m:02d}"

    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    if m == 0:
        return f"{h12} {suffix}"
    return f"{h12}:{m:02d} {suffix}"


def read_back_slot(language: Language, slot: Slot, business_name: str) -> str:
    """Build the exact sentence the agent will speak before `confirm_booking`."""
    try:
        d = datetime.strptime(slot.scheduled_date, "%Y-%m-%d").date()
    except ValueError:
        # Fall back to raw values if the API hands us something unexpected —
        # better a slightly clunky read-back than a crash mid-call.
        date_part = slot.scheduled_date
    else:
        date_part = _format_date(d, language)

    time_part = _format_time(slot.start_time, language)

    if language == "da":
        return (
            f"Jeg har en tid til dig {date_part} {time_part} hos {business_name}. "
            f"Skal jeg bekræfte?"
        )
    return (
        f"I have an opening on {date_part} at {time_part} with {business_name}. "
        f"Should I confirm that for you?"
    )
