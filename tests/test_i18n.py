"""
Read-back i18n: the only place we generate human-language slot strings.

If these tests regress, the agent is paraphrasing slots somewhere it shouldn't.
"""

from __future__ import annotations

import pytest

from wispoke_voice.prompts.i18n import read_back_slot
from wispoke_voice.tenant.models import Slot


# ─── Date normalization ────────────────────────────────────────────────────


def test_english_readback_includes_weekday_and_business_name():
    slot = Slot(scheduled_date="2026-06-04", start_time="14:30", end_time="15:00")
    out = read_back_slot("en", slot, "ACME Clinic")
    # Thursday June 4 2026
    assert "Thursday" in out
    assert "June" in out
    assert "4" in out
    assert "ACME Clinic" in out


def test_danish_readback_uses_danish_month_and_weekday():
    slot = Slot(scheduled_date="2026-06-04", start_time="14:30", end_time="15:00")
    out = read_back_slot("da", slot, "ACME Klinik")
    assert "torsdag" in out  # weekday: 2026-06-04 is Thursday
    assert "juni" in out
    assert "ACME Klinik" in out
    assert "Skal jeg bekræfte" in out


# ─── Time normalization ────────────────────────────────────────────────────


def test_english_morning_time_uses_am():
    slot = Slot(scheduled_date="2026-06-04", start_time="09:00", end_time="09:30")
    assert "9 AM" in read_back_slot("en", slot, "ACME")


def test_english_afternoon_time_uses_pm():
    slot = Slot(scheduled_date="2026-06-04", start_time="14:30", end_time="15:00")
    assert "2:30 PM" in read_back_slot("en", slot, "ACME")


def test_english_noon_renders_as_12_pm():
    slot = Slot(scheduled_date="2026-06-04", start_time="12:00", end_time="12:30")
    assert "12 PM" in read_back_slot("en", slot, "ACME")


def test_danish_uses_24h_klokken():
    slot = Slot(scheduled_date="2026-06-04", start_time="14:30", end_time="15:00")
    assert "klokken 14:30" in read_back_slot("da", slot, "ACME")


# ─── Robustness ────────────────────────────────────────────────────────────


def test_invalid_date_falls_back_to_raw_string():
    slot = Slot(scheduled_date="not-a-date", start_time="14:30", end_time="15:00")
    out = read_back_slot("en", slot, "ACME")
    # Doesn't crash; raw date appears somewhere in the output.
    assert "not-a-date" in out


@pytest.mark.parametrize("lang", ["en", "da"])
def test_business_name_always_present(lang):
    slot = Slot(scheduled_date="2026-06-04", start_time="14:30", end_time="15:00")
    assert "Test Co" in read_back_slot(lang, slot, "Test Co")
