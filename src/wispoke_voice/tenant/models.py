"""
Typed config + draft dataclasses.

`TenantConfig` mirrors the shape returned by GET /voice/internal/tenant/{id}.
`BookingDraft` is the working-memory accumulator the state machine carries
across turns — filled progressively as the LLM collects fields.
`Slot` is what `get_available_slots` returns, normalized into a stable shape
the read-back logic can format without conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


Language = Literal["en", "da"]
LlmProvider = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class ProviderConfig:
    stt: str
    llm: LlmProvider
    tts: str


@dataclass(frozen=True)
class ModelConfig:
    voice: str  # e.g. ElevenLabs voice_id
    llm: str  # e.g. "gpt-4o" / "claude-sonnet-4-5"


@dataclass(frozen=True)
class WeeklyScheduleSlot:
    day_of_week: int  # 0=Sunday … 6=Saturday
    start_time: str  # "HH:MM:SS" from Postgres
    end_time: str
    is_active: bool


@dataclass(frozen=True)
class TenantConfig:
    """All the static config the worker needs for one session."""

    company_id: str
    is_enabled: bool
    business_name: str
    business_type: Optional[str]
    business_phone: Optional[str]
    greeting_message: Optional[str]
    system_prompt: Optional[str]
    language: Language
    timezone: str
    appointment_duration_min: int
    appointment_fields: List[str]
    providers: ProviderConfig
    models: ModelConfig
    weekly_schedule: List[WeeklyScheduleSlot] = field(default_factory=list)


@dataclass
class Slot:
    """A bookable time slot. Identified by (date, start_time) because the
    underlying availability table doesn't issue slot IDs."""

    scheduled_date: str  # "YYYY-MM-DD"
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"

    @property
    def key(self) -> str:
        return f"{self.scheduled_date}T{self.start_time}"


@dataclass
class BookingDraft:
    """Accumulated booking fields. Filled across turns by the state machine."""

    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    caller_email: Optional[str] = None
    notes: Optional[str] = None
    selected_slot: Optional[Slot] = None
    confirmed: bool = False
    booking_id: Optional[str] = None  # set after create_appointment returns

    def is_ready_to_propose(self, required_fields: List[str]) -> bool:
        """True when every tenant-required field is filled."""
        mapping = {
            "name": self.caller_name,
            "phone": self.caller_phone,
            "email": self.caller_email,
        }
        return all(mapping.get(f) for f in required_fields)

    def is_ready_to_book(self, required_fields: List[str]) -> bool:
        return self.is_ready_to_propose(required_fields) and self.selected_slot is not None
