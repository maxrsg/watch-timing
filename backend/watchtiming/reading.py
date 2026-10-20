"""Hand angles → time. Steps 7–8 of the pipeline (assignment, time, AM/PM).

Pure functions. Angles are clock angles: degrees clockwise from 12 o'clock.
"""

import itertools
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from watchtiming.hands import HandCandidate

# How far real hands may disagree with each other: the minute hand vs the seconds hand (in
# seconds) and the hour hand vs the minute hand (in minutes). Watches aren't perfectly aligned:
# a real minute hand can sit 20 s off the seconds hand (an Orient diver, 2026-10-18).
MINUTE_TOLERANCE_S = 20.0
HOUR_TOLERANCE_MIN = 4.0
# When two hands overlap they share one candidate, whose angle blends both (hands merge when
# they're under ~3° apart), so their consistency can only be checked loosely: 1.5° between the
# minute and seconds hands is 15 s, 3° between the hour and minute hands 6 min.
SHARED_MINUTE_TOLERANCE_S = 25.0
SHARED_HOUR_TOLERANCE_MIN = 8.0
# Cost added when no seconds hand is assigned (comparable to a seconds hand hidden under the
# minute hand at the edge of its tolerance), and for each long hand left unexplained, scaled by
# its strength relative to the strongest: leaving out the strongest candidates costs most,
# leaving out faint clutter (lettering, a strip of dial between hands) hardly does.
NO_SECONDS_COST = 3.0
UNEXPLAINED_HAND_COST = 6.0
# How a common rotation δ of all hands (12 o'clock misjudged) moves the residuals:
# minute vs seconds by (1/6 − 1/360)·60 s per degree, hour vs minute by (1/30 − 1/360)·60 min.
MINUTE_RESIDUAL_PER_DEG = (1 / 6 - 1 / 360) * 60
HOUR_RESIDUAL_PER_DEG = (1 / 30 - 1 / 360) * 60
# Shape rules: the hour hand is the shortest and not much thinner than the minute hand (also
# when it overlaps the seconds hand: their merged trace is as wide as the hour hand), the
# seconds hand the thinnest.
SHAPE_VIOLATION_COST = 25.0
LENGTH_MARGIN = 0.05
HOUR_MIN_WIDTH = 0.5  # of the minute hand's
# The minute and seconds hands reach well out (lettering and logos that pass as short bars
# don't), unless they ran into a date window.
LONG_HAND_MIN = 0.6


class UnreadableDialError(ValueError):
    """No consistent set of hands was found."""


@dataclass(frozen=True)
class Assignment:
    hour: HandCandidate
    minute: HandCandidate
    second: HandCandidate | None
    # Common rotation applied to all three angles, solved from the hands' consistency when the
    # direction of 12 o'clock is uncertain (no hour markers); 0 otherwise.
    rotation_deg: float
    # Disagreement between hands: minute vs seconds (seconds), hour vs minute (minutes).
    minute_residual_s: float | None
    hour_residual_min: float
    cost: float
    # Hands that share a candidate because they overlap.
    seconds_shared: bool
    hour_minute_shared: bool
    # How much worse the best assignment giving a different time is (∞ if there is none).
    margin: float = float("inf")

    @property
    def hour_angle(self) -> float:
        return (self.hour.angle + self.rotation_deg) % 360

    @property
    def minute_angle(self) -> float:
        return (self.minute.angle + self.rotation_deg) % 360

    @property
    def second_angle(self) -> float | None:
        return None if self.second is None else (self.second.angle + self.rotation_deg) % 360


@dataclass(frozen=True)
class DialTime:
    hours: int  # 0–11 (12 o'clock is 0)
    minutes: int
    seconds: float | None  # None when the seconds hand couldn't be read

    def seconds_into_12h(self) -> float:
        return self.hours * 3600 + self.minutes * 60 + (self.seconds or 0.0)

    def __str__(self) -> str:
        s = f"{self.seconds:04.1f}" if self.seconds is not None else "??"
        return f"{self.hours or 12}:{self.minutes:02d}:{s}"


def _wrap(value: float, period: float) -> float:
    """Into [−period/2, period/2)."""
    return (value + period / 2) % period - period / 2


def minute_residual_s(minute: float, second: float) -> float:
    """Where the minute hand sits within its minute vs where the seconds hand says it should."""
    return _wrap((minute / 6) % 1 - second / 360, 1) * 60


def hour_residual_min(hour: float, minute: float) -> float:
    """Where the hour hand sits within its hour vs where the minute hand says it should."""
    return _wrap((hour / 30) % 1 - minute / 360, 1) * 60


def _shape_cost(h: HandCandidate, m: HandCandidate, s: HandCandidate | None) -> float:
    cost = 0.0
    if h is not m and h.length > m.length + LENGTH_MARGIN:
        cost += SHAPE_VIOLATION_COST
    if h is not m and h.width < HOUR_MIN_WIDTH * m.width:
        cost += SHAPE_VIOLATION_COST
    for hand in (m, s):
        if hand is not None and not hand.blocked and hand.length < LONG_HAND_MIN:
            cost += SHAPE_VIOLATION_COST
    if s is not None and s is not m and s is not h:
        if s.width > min(m.width, h.width):
            cost += SHAPE_VIOLATION_COST
        if s.length + LENGTH_MARGIN < m.length:
            cost += SHAPE_VIOLATION_COST
    return cost


def _residuals(h: float, m: float, s: float | None) -> tuple[float, float | None]:
    return hour_residual_min(h, m), (None if s is None else minute_residual_s(m, s))


def _evaluate(
    h: HandCandidate, m: HandCandidate, s: HandCandidate | None, twelve_uncertainty_deg: float
) -> Assignment:
    hour_tol = SHARED_HOUR_TOLERANCE_MIN if h is m else HOUR_TOLERANCE_MIN
    minute_tol = SHARED_MINUTE_TOLERANCE_S if s is m else MINUTE_TOLERANCE_S
    hr, mr = _residuals(h.angle, m.angle, s.angle if s else None)

    rotation = 0.0
    if twelve_uncertainty_deg > 0:
        # Residuals are linear in a common rotation δ; minimize the consistency cost plus a prior
        # keeping δ within the tap's uncertainty (weighted least squares in one unknown).
        num = HOUR_RESIDUAL_PER_DEG * hr / hour_tol**2
        den = HOUR_RESIDUAL_PER_DEG**2 / hour_tol**2 + 1 / twelve_uncertainty_deg**2
        if mr is not None:
            num += MINUTE_RESIDUAL_PER_DEG * mr / minute_tol**2
            den += MINUTE_RESIDUAL_PER_DEG**2 / minute_tol**2
        rotation = -num / den
        hr, mr = _residuals(
            h.angle + rotation, m.angle + rotation, s.angle + rotation if s else None
        )

    cost = (hr / hour_tol) ** 2 + _shape_cost(h, m, s)
    if twelve_uncertainty_deg > 0:
        cost += (rotation / twelve_uncertainty_deg) ** 2
    cost += NO_SECONDS_COST if mr is None else (mr / minute_tol) ** 2
    return Assignment(
        h, m, s, rotation, mr, hr, cost,
        seconds_shared=s is not None and (s is m or s is h),
        hour_minute_shared=h is m,
    )  # fmt: skip


def assign_hands(
    candidates: list[HandCandidate], twelve_uncertainty_deg: float = 0.0
) -> Assignment:
    """Which candidate is which hand: the assignment where the hands agree best (step 7).

    Overlapping hands share a candidate. Tails (short candidates) are never hands. When the
    direction of 12 o'clock is uncertain (no hour markers, only the tap), pass its uncertainty:
    each assignment then also solves for the common rotation that makes the hands agree.
    """
    hands = [c for c in candidates if not c.is_tail]
    if not hands:
        raise UnreadableDialError("No hands were found on the dial.")

    strongest = max(c.strength for c in hands) or 1.0
    scored = []
    for h, m in itertools.product(hands, repeat=2):
        for s in [*hands, None]:
            a = _evaluate(h, m, s, twelve_uncertainty_deg)
            used = {id(h), id(m), id(s)}
            unexplained = UNEXPLAINED_HAND_COST * sum(
                c.strength / strongest for c in hands if id(c) not in used
            )
            scored.append(replace(a, cost=a.cost + unexplained))
    scored.sort(key=lambda a: a.cost)
    best = scored[0]
    best_time = _time_of(best)
    rival = next((a for a in scored[1:] if _differs(_time_of(a), best_time)), None)
    return replace(best, margin=float("inf") if rival is None else rival.cost - best.cost)


def _time_of(a: Assignment) -> "DialTime":
    return angles_to_time(a.hour_angle, a.minute_angle, a.second_angle)


def _differs(a: "DialTime", b: "DialTime") -> bool:
    """Different readings: another hour or minute, or (when both have seconds) another second."""
    if (a.hours, a.minutes) != (b.hours, b.minutes):
        return True
    return a.seconds is not None and b.seconds is not None and abs(a.seconds - b.seconds) > 1


def angles_to_time(hour: float, minute: float, second: float | None) -> DialTime:
    """Hand angles → 12-hour time. Each hand fixes the boundary of the next coarser one."""
    if second is None:
        minutes_float = minute / 6
        m = int(minutes_float) % 60
        h = round(hour / 30 - minutes_float / 60) % 12
        return DialTime(h, m, None)
    s = (second / 6) % 60
    m = round(minute / 6 - s / 60) % 60
    h = round(hour / 30 - (m + s / 60) / 60) % 12
    return DialTime(h, m, s)


def nearest_to_reference(dial: DialTime, reference_local: datetime) -> datetime:
    """The datetime shown on the dial closest to the reference: resolves AM/PM and the date
    (step 8). `reference_local` must be in the time zone the watch is set to."""
    midnight = reference_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ref = (reference_local - midnight).total_seconds()
    offset = _wrap(dial.seconds_into_12h() - ref, 12 * 3600)
    return reference_local + timedelta(seconds=offset)


def deviation_seconds(dial: DialTime, reference_local: datetime) -> float:
    """Dial time − reference time, in seconds. Positive = the watch is fast.

    Needs the dial's seconds; `reference_local` must be in the watch's time zone.
    """
    if dial.seconds is None:
        raise ValueError("The deviation needs the dial's seconds.")
    return (nearest_to_reference(dial, reference_local) - reference_local).total_seconds()


# --- Step 9: confidence ------------------------------------------------------------------------

# Below this, the frontend shows the detected hands over the photo and asks the user to confirm
# or correct them.
CONFIDENCE_THRESHOLD = 0.6
# Seconds below this are reported as unknown instead of guessed.
SECONDS_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class Confidence:
    overall: float  # 0–1: is the reading (to the minute) right?
    seconds: float  # 0–1: can the seconds be trusted to about ±0.2 s?
    reasons: tuple[str, ...]  # why confidence was lowered, for the user

    @property
    def needs_confirmation(self) -> bool:
        return self.overall < CONFIDENCE_THRESHOLD or self.seconds < SECONDS_CONFIDENCE_THRESHOLD


def confidence(a: Assignment, pivot_well_determined: bool, twelve_from_markers: bool) -> Confidence:
    """How far to trust a reading (step 9)."""
    reasons: list[str] = []
    hour_ok = math.exp(-0.5 * (a.hour_residual_min / HOUR_TOLERANCE_MIN) ** 2)
    if a.hour_minute_shared:
        hour_ok = max(hour_ok, 0.8)  # a blended angle can't be checked tightly
    if hour_ok < 0.6:
        reasons.append("The hour hand doesn't match the minute hand well.")
    # Another assignment of the hands, giving a different time, fits almost as well.
    distinct = 1 - math.exp(-a.margin / 2) if math.isfinite(a.margin) else 1.0
    if distinct < 0.6:
        reasons.append("The hands could be read in more than one way.")
    overall = hour_ok * distinct
    if not pivot_well_determined:
        overall *= 0.7
        reasons.append("The hands overlap, so the center of the dial is less certain.")

    if a.second is None or a.minute_residual_s is None:
        return Confidence(overall, 0.0, (*reasons, "No seconds hand was found."))
    seconds = overall * math.exp(-0.5 * (a.minute_residual_s / MINUTE_TOLERANCE_S) ** 2)
    if a.seconds_shared:
        seconds = min(seconds, 0.45)
        reasons.append("The seconds hand overlaps another hand.")
    elif abs(a.minute_residual_s) > 2 * MINUTE_TOLERANCE_S:
        reasons.append("The seconds hand doesn't match the minute hand well.")
    if not twelve_from_markers:
        seconds = min(seconds, 0.45)
        reasons.append("No hour markers: 12 o'clock comes only from your tap.")
    return Confidence(overall, seconds, tuple(reasons))
