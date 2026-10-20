from datetime import datetime, timedelta, timezone

import pytest

from watchtiming.hands import HandCandidate
from watchtiming.reading import (
    SECONDS_CONFIDENCE_THRESHOLD,
    DialTime,
    UnreadableDialError,
    angles_to_time,
    assign_hands,
    confidence,
    hour_residual_min,
    minute_residual_s,
    nearest_to_reference,
)


def hand(angle: float, length: float, width: float) -> HandCandidate:
    return HandCandidate(angle=angle, length=length, width=width, strength=1.0)


def angles(h: int, m: int, s: float) -> tuple[float, float, float]:
    return ((h % 12) + m / 60 + s / 3600) * 30, (m + s / 60) * 6, s * 6


HOUR, MINUTE, SECOND = (0.5, 0.06), (0.82, 0.04), (0.82, 0.015)


def dial_hands(h: int, m: int, s: float) -> list[HandCandidate]:
    ah, am, as_ = angles(h, m, s)
    return [hand(am, *MINUTE), hand(as_, *SECOND), hand(ah, *HOUR)]


@pytest.mark.parametrize(
    "time", [(10, 8, 37.0), (12, 0, 0.0), (3, 59, 59.9), (6, 0, 0.1), (11, 59, 30.0)]
)
def test_angles_to_time_round_trip(time):
    t = angles_to_time(*angles(*time))
    assert (t.hours, t.minutes) == (time[0] % 12, time[1])
    assert t.seconds == pytest.approx(time[2])


def test_minute_boundary_comes_from_the_seconds_hand():
    # Minute hand a hair before 9 minutes, but the seconds hand says 0.5 s past: 9 minutes.
    t = angles_to_time(hour=4.5, minute=53.99, second=3.0)
    assert (t.minutes, t.seconds) == (9, pytest.approx(0.5))


def test_residuals_are_zero_for_consistent_hands():
    h, m, s = angles(7, 41, 41.5)
    assert minute_residual_s(m, s) == pytest.approx(0, abs=1e-9)
    assert hour_residual_min(h, m) == pytest.approx(0, abs=1e-9)
    assert minute_residual_s(m + 1, s) == pytest.approx(10, abs=0.01)  # 1° of minute hand = 10 s


@pytest.mark.parametrize("time", [(10, 8, 37), (4, 41, 12.4), (1, 5, 50), (8, 47, 3)])
def test_assignment_finds_the_hands_in_any_order(time):
    a = assign_hands(dial_hands(*time))
    t = angles_to_time(a.hour_angle, a.minute_angle, a.second_angle)
    assert (t.hours, t.minutes, round(t.seconds, 1)) == (time[0] % 12, time[1], time[2])
    assert a.margin > 4


def test_tails_are_never_hands():
    hands = dial_hands(10, 8, 37) + [hand(42.0, 0.22, 0.015)]
    a = assign_hands(hands)
    assert a.second is not None and a.second.length > 0.5


def test_overlapping_minute_and_seconds_share_a_candidate():
    h, m, s = angles(7, 41, 41.5)
    merged = hand((m + s) / 2, 0.82, 0.04)  # 1.15° apart: one blended candidate
    a = assign_hands([merged, hand(h, *HOUR)])
    assert a.second is a.minute
    assert a.seconds_shared


def test_no_seconds_hand():
    """Without a seconds hand the reading can't tell it from one hidden under the minute hand
    (real minute hands sit up to ~20 s off the seconds hand). Either way the seconds are not
    reported and the reading asks for confirmation."""
    h, m, _ = angles(10, 8, 37)
    a = assign_hands([hand(h, *HOUR), hand(m, *MINUTE)])
    assert a.second is None or a.seconds_shared
    c = confidence(a, pivot_well_determined=True, twelve_from_markers=True)
    assert c.seconds < SECONDS_CONFIDENCE_THRESHOLD and c.needs_confirmation


def test_a_misjudged_twelve_is_solved_from_the_hands():
    rotated = [
        HandCandidate(c.angle + 3.0, c.length, c.width, c.strength) for c in dial_hands(10, 8, 37)
    ]
    a = assign_hands(rotated, twelve_uncertainty_deg=4.0)
    # Loosely: the hands' tolerances allow real watches' misalignment. Without markers the
    # seconds are withheld anyway; the hour and minute come out right.
    assert a.rotation_deg == pytest.approx(-3.0, abs=0.5)
    t = angles_to_time(a.hour_angle, a.minute_angle, a.second_angle)
    assert (t.hours, t.minutes) == (10, 8)


def test_no_hands():
    with pytest.raises(UnreadableDialError):
        assign_hands([hand(10.0, 0.2, 0.01)])


def test_confidence_for_a_clean_reading():
    c = confidence(assign_hands(dial_hands(10, 8, 37)), True, True)
    assert c.overall > 0.9 and c.seconds > 0.9 and not c.needs_confirmation and not c.reasons


def test_confidence_without_markers_withholds_seconds():
    c = confidence(assign_hands(dial_hands(10, 8, 37)), True, twelve_from_markers=False)
    assert c.overall > 0.9
    assert c.needs_confirmation
    assert any("markers" in r for r in c.reasons)


CET = timezone(timedelta(hours=1))


@pytest.mark.parametrize(
    "dial,reference,expected",
    [
        # Same half of the day.
        ((10, 8, 37.0), datetime(2026, 10, 18, 10, 8, 30, tzinfo=CET), (10, 8, 37)),
        # PM: the dial shows 10:08, the reference is 22:08.
        ((10, 8, 37.0), datetime(2026, 10, 18, 22, 8, 30, tzinfo=CET), (22, 8, 37)),
        # Watch a little slow across midnight: dial 11:59:50, reference 00:00:05 next day.
        ((11, 59, 50.0), datetime(2026, 10, 19, 0, 0, 5, tzinfo=CET), (23, 59, 50)),
        # Watch a little fast across noon: dial 12:00:20, reference 11:59:55.
        ((0, 0, 20.0), datetime(2026, 10, 18, 11, 59, 55, tzinfo=CET), (12, 0, 20)),
    ],
)
def test_am_pm_and_date_from_the_reference(dial, reference, expected):
    shown = nearest_to_reference(DialTime(*dial), reference)
    assert (shown.hour, shown.minute, shown.second) == expected
    assert abs((shown - reference).total_seconds()) < 6 * 3600
