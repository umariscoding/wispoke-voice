"""Booking agent + state machine.

State machine is dependency-free; `BookingAgent` pulls livekit so it's
lazy-imported via `__getattr__` to keep CI test runs cheap.
"""

from typing import TYPE_CHECKING

from wispoke_voice.agent.state_machine import BookingState, StateMachine

__all__ = ["BookingAgent", "BookingState", "StateMachine"]


if TYPE_CHECKING:  # pragma: no cover
    from wispoke_voice.agent.booking_agent import BookingAgent


def __getattr__(name: str):
    if name == "BookingAgent":
        from wispoke_voice.agent.booking_agent import BookingAgent

        return BookingAgent
    raise AttributeError(f"module 'wispoke_voice.agent' has no attribute {name!r}")
