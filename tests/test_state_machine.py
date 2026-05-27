"""
State machine tool-gating tests.

The single most important guarantee in the voice agent: `create_booking`
cannot fire from any state except CONFIRMING. If this test ever fails, the
agent could book a phantom slot.
"""

from __future__ import annotations

import pytest

from wispoke_voice.agent.state_machine import BookingState, StateMachine


@pytest.mark.parametrize(
    "state",
    [
        BookingState.GREETING,
        BookingState.COLLECTING,
        BookingState.PROPOSING,
        BookingState.READING_BACK,
        BookingState.DONE,
        BookingState.HANDOFF,
    ],
)
def test_create_booking_blocked_outside_confirming(state):
    sm = StateMachine(initial=state)
    assert sm.can_call("create_booking") is False


def test_create_booking_allowed_in_confirming():
    sm = StateMachine(initial=BookingState.CONFIRMING)
    assert sm.can_call("create_booking") is True


def test_read_only_tools_always_allowed():
    for state in BookingState:
        sm = StateMachine(initial=state)
        assert sm.can_call("get_available_slots") is True
        assert sm.can_call("record_caller_details") is True
        assert sm.can_call("propose_slot") is True


def test_cancel_booking_allowed_in_confirming_and_done():
    for state in (BookingState.CONFIRMING, BookingState.DONE):
        sm = StateMachine(initial=state)
        assert sm.can_call("cancel_booking") is True
    for state in (BookingState.GREETING, BookingState.COLLECTING, BookingState.PROPOSING):
        sm = StateMachine(initial=state)
        assert sm.can_call("cancel_booking") is False


def test_transitions_are_free_form():
    sm = StateMachine()
    sm.transition(BookingState.CONFIRMING)
    assert sm.current == BookingState.CONFIRMING
    sm.transition(BookingState.GREETING)  # going backwards is allowed
    assert sm.current == BookingState.GREETING


def test_reset_returns_to_greeting():
    sm = StateMachine(initial=BookingState.DONE)
    sm.reset()
    assert sm.current == BookingState.GREETING
