"""Tests for the ISO 8601 duration helpers in protocol_pipeline.stage.

These power the per-procedure and protocol-wide `total_duration` fields.
The 'conservative-by-design' return-None-on-any-missing behavior is the
key invariant — researchers plan their day around these numbers."""

from __future__ import annotations

import pytest

from protocol_pipeline.stage import (
    _iso_duration_to_seconds,
    _seconds_to_iso_duration,
    _sum_iso8601_durations,
)


# ---- Parsing ------------------------------------------------------------

@pytest.mark.parametrize("iso,expected", [
    ("PT5M", 300),
    ("PT1H", 3600),
    ("PT1H30M", 5400),
    ("PT30S", 30),
    ("P1D", 86400),
    ("P3D", 86400 * 3),
    ("P2W", 86400 * 14),
    ("P1DT2H", 86400 + 7200),
    ("P1DT2H30M", 86400 + 7200 + 1800),
    ("PT5.5S", 5.5),
])
def test_parse_well_formed_iso(iso, expected):
    assert _iso_duration_to_seconds(iso) == expected


@pytest.mark.parametrize("garbage", [
    "", "P", "PT", None, "garbage", "1h", "30m", "5 min", "P1X",
])
def test_parse_returns_none_on_garbage(garbage):
    assert _iso_duration_to_seconds(garbage) is None


# ---- Formatting --------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (300, "PT5M"),
    (3600, "PT1H"),
    (5400, "PT1H30M"),
    (86400, "P1D"),
    (86400 + 7200, "P1DT2H"),
    (86400 * 3 + 1800, "P3DT30M"),
    (0, "PT0S"),
    (-5, "PT0S"),  # negative -> zero, defensive
])
def test_format_seconds(seconds, expected):
    assert _seconds_to_iso_duration(seconds) == expected


# ---- Sum ----------------------------------------------------------------

def test_sum_simple_minutes():
    assert _sum_iso8601_durations(["PT5M", "PT10M", "PT15M"]) == "PT30M"


def test_sum_mixed_hours_and_days():
    assert _sum_iso8601_durations(["P1D", "PT2H", "PT30M"]) == "P1DT2H30M"


def test_sum_carry_into_hours():
    """45m + 30m = 75m which should format as 1h15m, not 75m."""
    assert _sum_iso8601_durations(["PT45M", "PT30M"]) == "PT1H15M"


def test_sum_carry_into_days():
    """23h + 2h = 25h = 1d1h."""
    assert _sum_iso8601_durations(["PT23H", "PT2H"]) == "P1DT1H"


def test_sum_returns_none_on_any_missing():
    """Conservative: if any duration is None or empty, the whole sum is
    None. A partial sum is a misleading lower bound."""
    assert _sum_iso8601_durations(["PT5M", None, "PT10M"]) is None
    assert _sum_iso8601_durations(["PT5M", "", "PT10M"]) is None


def test_sum_returns_none_on_any_malformed():
    assert _sum_iso8601_durations(["PT5M", "garbage"]) is None
    assert _sum_iso8601_durations(["PT5M", "P"]) is None  # bare P is invalid


def test_sum_empty_list_returns_none():
    """Distinguish 'no steps had durations' from 'sum is zero' — None is
    correct because we don't know what the missing data implies."""
    assert _sum_iso8601_durations([]) is None
