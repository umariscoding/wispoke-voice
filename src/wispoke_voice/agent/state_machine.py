"""
Deterministic state machine layered over the LLM.

The LLM does conversation; the state machine decides which tools the LLM is
allowed to call right now. This is the structural safeguard that makes a
hallucinated booking physically impossible: even if the LLM decides to call
`create_booking` out of nowhere, the agent rejects the call until state is
in CONFIRMING.

Vonage's published case study reports this single change drops incorrect
responses from 23.7% → 1.0%.
"""

from __future__ import annotations

import enum
from typing import Set


class BookingState(str, enum.Enum):
    GREETING = "greeting"
    COLLECTING = "collecting"  # Gathering required fields (name, phone)
    PROPOSING = "proposing"  # Offering slots from `get_available_slots`
    READING_BACK = "reading_back"  # Spoke the slot, awaiting yes/no
    CONFIRMING = "confirming"  # Caller said yes; create + confirm pending
    DONE = "done"
    HANDOFF = "handoff"


# Tool-name → allowed-states. Tools omitted from this map default to
# "available everywhere" (the read-only ones).
_TOOL_STATE_GATES: dict[str, Set[BookingState]] = {
    "create_booking": {BookingState.CONFIRMING},
    "confirm_booking": {BookingState.CONFIRMING},
    "cancel_booking": {BookingState.CONFIRMING, BookingState.DONE},
}


class StateMachine:
    """Tracks current state and gates tool usage."""

    __slots__ = ("_state",)

    def __init__(self, initial: BookingState = BookingState.GREETING) -> None:
        self._state = initial

    @property
    def current(self) -> BookingState:
        return self._state

    def transition(self, to: BookingState) -> None:
        # We don't enforce a transition graph here on purpose — voice
        # conversations loop unpredictably (caller asks a question, then jumps
        # back to slot-shopping). The only hard rule is the *tool gate* below.
        self._state = to

    def can_call(self, tool_name: str) -> bool:
        gate = _TOOL_STATE_GATES.get(tool_name)
        if gate is None:
            return True
        return self._state in gate

    def reset(self) -> None:
        self._state = BookingState.GREETING
