"""Hand angles → time. Steps 7–8 of the pipeline (assignment, time, AM/PM).

Pure functions. Angles are clock angles: degrees clockwise from 12 o'clock.
"""

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from watchtiming.geometry import angle_diff, wrap
from watchtiming.hands import HandCandidate

# How far real hands may disagree with each other: the minute hand vs the seconds hand (in
# seconds) and the hour hand vs the minute hand (in minutes). Measured on real photos (an
# Orient diver, 8 photos, 2026-10): the minute hand sits 20–25 s off the seconds hand, and the
# hour hand 5–9 min off the minute hand. The hour hand only has to pick the hour (±30 min) and
# the minute hand the minute (±30 s), so the tolerances are generous.
MINUTE_TOLERANCE_S = 30.0
HOUR_TOLERANCE_MIN = 15.0
# When two hands overlap they share one candidate, whose angle blends both (hands merge when
# they're under ~3° apart): 1.5° more between the minute and seconds hands is 15 s, 3° between
# the hour and minute hands 6 min.
SHARED_MINUTE_TOLERANCE_S = MINUTE_TOLERANCE_S + 15.0
SHARED_HOUR_TOLERANCE_MIN = HOUR_TOLERANCE_MIN + 6.0
# Cost added when no seconds hand is assigned (comparable to a seconds hand hidden under the
# minute hand at the edge of its tolerance), and for each long hand left unexplained, scaled by
# its strength relative to the strongest: leaving out the strongest candidates costs most,
# leaving out faint clutter (lettering, a strip of dial between hands) hardly does.
NO_SECONDS_COST = 3.0
UNEXPLAINED_HAND_COST = 6.0
# Two hands sharing one candidate is possible but less likely than each having its own: without
# a cost, one shared candidate "explains" as much with fewer hands.
SHARED_HAND_COST = 1.0
# The seconds hand's counterweight tail: short, pointing straight away from the seconds hand.
# It's the strongest cue for which candidate is the seconds hand, and never a hand itself.
TAIL_MAX_LENGTH = 0.45
TAIL_ANGLE_DEG = 5.0
TAIL_BONUS = 1.5
# The expected time may choose between assignments that read the same seconds (so it only
# changes the hour and minute, never the measured seconds) and fit nearly as well as the best:
# within this much cost. Readings further than PRIOR_WINDOW_S from the expected time are
# implausible.
PRIOR_MAX_EXTRA_COST = 3.0
PRIOR_WINDOW_S = 90.0
# How a common rotation δ of all hands (12 o'clock misjudged) moves the residuals:
# minute vs seconds by (1/6 − 1/360)·60 s per degree, hour vs minute by (1/30 − 1/360)·60 min.
MINUTE_RESIDUAL_PER_DEG = (1 / 6 - 1 / 360) * 60
HOUR_RESIDUAL_PER_DEG = (1 / 30 - 1 / 360) * 60
# Shape rules: the hour hand is the shortest and not much thinner than the minute hand (also
# when it overlaps the seconds hand: their merged trace is as wide as the hour hand), the
# seconds hand the thinnest. Measured lengths and widths are noisy (a logo cuts a hand short, a
# lit facet makes it look thin), so a violation costs in proportion to its size, up to
# SHAPE_COST per rule. Only clearly impossible shapes cost IMPOSSIBLE_COST.
SHAPE_COST = 3.0
IMPOSSIBLE_COST = 25.0
LENGTH_MARGIN = 0.05
LENGTH_SCALE = 0.1  # a length violation this large (fraction of R) costs SHAPE_COST
HOUR_MIN_WIDTH = 0.5  # of the minute hand's
MINUTE_MIN_WIDTH = 0.4  # of the hour hand's: a minute hand is never as thin as a seconds hand
# The minute and seconds hands reach well out (lettering and logos that pass as short bars
# don't), unless they ran into a date window. Shorter than LONG_HAND_IMPOSSIBLE: not a hand.
LONG_HAND_MIN = 0.6
LONG_HAND_IMPOSSIBLE = 0.45


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
    # The reading is further than PRIOR_WINDOW_S from the expected time (None: none given).
    far_from_expected: bool | None = None
    # The seconds hand's counterweight tail, if one was found.
    tail: HandCandidate | None = None
    # Angles used instead of the candidates' own, before the rotation: the minute hand's outer
    # part when the hour hand shares its candidate, the seconds hand's from its tail or outer
    # part when it shares one.
    minute_override_deg: float | None = None
    second_override_deg: float | None = None

    @property
    def seconds_readable(self) -> bool:
        """A seconds hand with an angle of its own (not blended with a hand it lies over)."""
        return self.second is not None and not (
            self.seconds_shared and self.second_override_deg is None
        )

    @property
    def hour_angle(self) -> float:
        return (self.hour.angle + self.rotation_deg) % 360

    @property
    def minute_angle(self) -> float:
        angle = self.minute.angle if self.minute_override_deg is None else self.minute_override_deg
        return (angle + self.rotation_deg) % 360

    @property
    def second_angle(self) -> float | None:
        if self.second is None:
            return None
        angle = self.second.angle if self.second_override_deg is None else self.second_override_deg
        return (angle + self.rotation_deg) % 360


@dataclass(frozen=True)
class DialTime:
    hours: int  # 0–11 (12 o'clock is 0)
    minutes: int
    seconds: float | None  # None when the seconds hand couldn't be read

    @property
    def dial_hours(self) -> int:
        """1–12, as the dial shows it."""
        return self.hours or 12

    def seconds_into_12h(self) -> float:
        return self.hours * 3600 + self.minutes * 60 + (self.seconds or 0.0)

    def __str__(self) -> str:
        s = f"{self.seconds:04.1f}" if self.seconds is not None else "??"
        return f"{self.dial_hours}:{self.minutes:02d}:{s}"


def minute_residual_s(minute: float, second: float) -> float:
    """Where the minute hand sits within its minute vs where the seconds hand says it should."""
    return wrap((minute / 6) % 1 - second / 360, 1) * 60


def hour_residual_min(hour: float, minute: float) -> float:
    """Where the hour hand sits within its hour vs where the minute hand says it should."""
    return wrap((hour / 30) % 1 - minute / 360, 1) * 60


def _shape_cost(h: HandCandidate, m: HandCandidate, s: HandCandidate | None) -> float:
    def graded(excess: float) -> float:
        return SHAPE_COST * min(max(excess, 0.0), 1.0)

    # A blocked hand's length is only a lower bound: it can't be too short, nor shorter than
    # another hand.
    cost = 0.0
    if h is not m:
        if not m.blocked:
            cost += graded((h.length - m.length - LENGTH_MARGIN) / LENGTH_SCALE)
        # Full cost at half the allowed width ratio.
        if m.width > 0:
            cost += graded((HOUR_MIN_WIDTH - h.width / m.width) / (HOUR_MIN_WIDTH / 2))
        if h.width > 0:
            cost += graded((MINUTE_MIN_WIDTH - m.width / h.width) / (MINUTE_MIN_WIDTH / 2))
    for hand in (m, s):
        if hand is None or hand.blocked:
            continue
        if hand.length < LONG_HAND_IMPOSSIBLE:
            cost += IMPOSSIBLE_COST
        else:
            cost += graded((LONG_HAND_MIN - hand.length) / LENGTH_SCALE)
    if s is not None and s is not m and s is not h:
        thinnest = min(m.width, h.width)
        if thinnest > 0:
            cost += graded((s.width - thinnest) / thinnest)
        if not s.blocked:
            cost += graded((m.length - s.length - LENGTH_MARGIN) / LENGTH_SCALE)
    return cost


def _residuals(h: float, m: float, s: float | None) -> tuple[float, float | None]:
    return hour_residual_min(h, m), (None if s is None else minute_residual_s(m, s))


def _tail_of(s: HandCandidate, others: list[HandCandidate]) -> HandCandidate | None:
    """The short candidate pointing straight away from the seconds hand: its counterweight."""
    tails = [
        c
        for c in others
        if c.length < TAIL_MAX_LENGTH
        and not c.blocked
        and angle_diff(c.angle, s.angle + 180) < TAIL_ANGLE_DEG
    ]
    return max(tails, key=lambda c: c.strength, default=None)


def _evaluate(
    h: HandCandidate,
    m: HandCandidate,
    s: HandCandidate | None,
    tail: HandCandidate | None,
    twelve_uncertainty_deg: float,
) -> Assignment:
    seconds_shared = s is not None and (s is m or s is h)
    hour_minute_shared = h is m
    hour_tol = SHARED_HOUR_TOLERANCE_MIN if hour_minute_shared else HOUR_TOLERANCE_MIN
    minute_tol = SHARED_MINUTE_TOLERANCE_S if s is m else MINUTE_TOLERANCE_S

    # Where hands overlap, use the part that belongs to one hand only: the minute hand reaches
    # beyond the hour hand, and the seconds hand's tail points away from everything.
    minute_override_deg = None
    if hour_minute_shared and s is not m and m.outer_angle is not None:
        minute_override_deg = m.outer_angle
    second_override_deg = None
    if s is not None and seconds_shared:
        if tail is not None:
            second_override_deg = (tail.angle + 180) % 360
        elif s is h and s is not m and s.outer_angle is not None:
            # Beyond the hour hand's tip there's only the seconds hand.
            second_override_deg = s.outer_angle
    m_angle = m.angle if minute_override_deg is None else minute_override_deg
    s_angle = (
        None if s is None else (s.angle if second_override_deg is None else second_override_deg)
    )
    hr, mr = _residuals(h.angle, m_angle, s_angle)

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
            h.angle + rotation, m_angle + rotation, None if s_angle is None else s_angle + rotation
        )

    cost = (hr / hour_tol) ** 2 + _shape_cost(h, m, s)
    if twelve_uncertainty_deg > 0:
        cost += (rotation / twelve_uncertainty_deg) ** 2
    cost += NO_SECONDS_COST if mr is None else (mr / minute_tol) ** 2
    cost += SHARED_HAND_COST * (hour_minute_shared + seconds_shared)
    if tail is not None:
        cost -= TAIL_BONUS
    return Assignment(
        h, m, s, rotation, mr, hr, cost,
        seconds_shared=seconds_shared,
        hour_minute_shared=hour_minute_shared,
        tail=tail,
        minute_override_deg=minute_override_deg,
        second_override_deg=second_override_deg,
    )  # fmt: skip


def assign_hands(
    candidates: list[HandCandidate],
    twelve_uncertainty_deg: float = 0.0,
    expected_s: float | None = None,
) -> Assignment:
    """Which candidate is which hand: the assignment where the hands agree best (step 7).

    Overlapping hands share a candidate. Tails (short candidates) are never hands; one pointing
    straight away from the seconds hand is its counterweight, which confirms it. When the
    direction of 12 o'clock is uncertain (no hour markers, only the tap), pass its uncertainty:
    each assignment then also solves for the common rotation that makes the hands agree.

    `expected_s` (seconds into the 12 hours) may only choose between assignments that read the
    same seconds and fit nearly as well (e.g. an hour and a minute hand that could be swapped
    because one runs into the date window): it changes the hour and minute, never which
    candidate is the seconds hand, so the reading stays a measurement.
    """
    scored = _score_all(candidates, twelve_uncertainty_deg)
    best = scored[0]
    if expected_s is None:
        return replace(best, margin=_margin(best, _rival(scored, best, None)))

    def plausible(a: Assignment) -> bool:
        shown = _time_of(a, expected_s).seconds_into_12h()
        return abs(wrap(shown - expected_s, 43200)) <= PRIOR_WINDOW_S

    # The expected time only picks among near-best assignments reading the same seconds.
    same_seconds = [
        a for a in scored if a.cost <= best.cost + PRIOR_MAX_EXTRA_COST and _same_seconds(a, best)
    ]
    best = next((a for a in same_seconds if plausible(a)), best)
    # Readings far from the expected time don't compete with one near it.
    near = plausible(best)
    rival = _rival(scored, best, expected_s, competes=lambda a: plausible(a) or not near)
    return replace(best, margin=_margin(best, rival), far_from_expected=not near)


def _score_all(candidates: list[HandCandidate], twelve_uncertainty_deg: float) -> list[Assignment]:
    """Every assignment of the candidates to hour, minute and (optionally) seconds hand, best
    (lowest cost) first. Candidates no hand explains cost in proportion to their strength."""
    hands = [c for c in candidates if not c.is_tail]
    if not hands:
        raise UnreadableDialError("No hands were found on the dial.")

    strongest = max(c.strength for c in hands) or 1.0
    scored = []
    for h, m in itertools.product(hands, repeat=2):
        for s in [*hands, None]:
            used = {id(h), id(m), id(s)}
            tail = None
            if s is not None:
                tail = _tail_of(s, [c for c in candidates if id(c) not in used])
                used.add(id(tail))
            a = _evaluate(h, m, s, tail, twelve_uncertainty_deg)
            unexplained = UNEXPLAINED_HAND_COST * sum(
                c.strength / strongest for c in hands if id(c) not in used
            )
            scored.append(replace(a, cost=a.cost + unexplained))
    scored.sort(key=lambda a: a.cost)
    return scored


def _rival(
    scored: list[Assignment],
    best: Assignment,
    expected_s: float | None,
    competes: Callable[[Assignment], bool] = lambda a: True,
) -> Assignment | None:
    """The best other assignment that gives a different time, if any."""
    best_time = _time_of(best, expected_s)
    return next(
        (
            a
            for a in scored
            if a is not best and _differs(_time_of(a, expected_s), best_time) and competes(a)
        ),
        None,
    )


def _margin(best: Assignment, rival: Assignment | None) -> float:
    return float("inf") if rival is None else max(rival.cost - best.cost, 0.0)


def _same_seconds(a: Assignment, b: Assignment) -> bool:
    if a.second_angle is None or b.second_angle is None:
        return a.second_angle is None and b.second_angle is None
    return angle_diff(a.second_angle, b.second_angle) < 1.0


def _time_of(a: Assignment, expected_s: float | None = None) -> DialTime:
    second = a.second_angle if a.seconds_readable else None
    return angles_to_time(a.hour_angle, a.minute_angle, second, expected_s)


def _differs(a: DialTime, b: DialTime) -> bool:
    """Different readings: another hour, or a minute more than one away (a neighboring minute
    is the same hands read across a minute boundary, which the expected time or the user
    settles), or (when both have seconds) another second."""
    minutes = abs(wrap((a.hours * 60 + a.minutes) - (b.hours * 60 + b.minutes), 720))
    if minutes > 1:
        return True
    return a.seconds is not None and b.seconds is not None and abs(a.seconds - b.seconds) > 1


def angles_to_time(
    hour: float, minute: float, second: float | None, expected_s: float | None = None
) -> DialTime:
    """Hand angles → 12-hour time. Each hand fixes the boundary of the next coarser one.

    `expected_s` (seconds into the 12 hours: the reference time plus the watch's predicted
    deviation) only decides which of the two neighboring minutes the minute hand means, for a
    minute hand sitting near a minute boundary. It never changes the seconds, so the deviation
    stays a measurement as long as the prediction is within 30 s of the truth.
    """
    if second is None:
        minutes_float = minute / 6
        if expected_s is None:
            m = int(minutes_float) % 60
        else:
            # Without a seconds hand, the expected seconds place the minute boundary instead.
            m = round(minutes_float - (expected_s % 60) / 60) % 60
        h = round(hour / 30 - (m + 0.5) / 60) % 12
        return DialTime(h, m, None)
    s = (second / 6) % 60
    base = minute / 6 - s / 60
    options = [round(base)]
    if expected_s is not None:
        options = [math.floor(base), math.floor(base) + 1]

    def at(minutes: int) -> DialTime:
        m = minutes % 60
        h = round(hour / 30 - (m + s / 60) / 60) % 12
        return DialTime(h, m, s)

    times = [at(m) for m in options]
    if expected_s is None:
        return times[0]
    return min(times, key=lambda t: abs(wrap(t.seconds_into_12h() - expected_s, 43200)))


def nearest_to_reference(dial: DialTime, reference_local: datetime) -> datetime:
    """The datetime shown on the dial closest to the reference: resolves AM/PM and the date
    (step 8). `reference_local` must be in the time zone the watch is set to."""
    midnight = reference_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ref = (reference_local - midnight).total_seconds()
    offset = wrap(dial.seconds_into_12h() - ref, 12 * 3600)
    return reference_local + timedelta(seconds=offset)


def seconds_into_12h(local: datetime) -> float:
    """A local time as seconds into its 12-hour half of the day (as a dial shows it)."""
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (local - midnight).total_seconds() % (12 * 3600)


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
# A minute hand further than this from where the seconds hand says it should be (in seconds)
# sits near a minute boundary: the minute could be the neighboring one (real minute hands sit
# up to ~25 s off). The expected time or the user settles it.
MINUTE_BOUNDARY_S = 25.0
MINUTE_BOUNDARY_SCALE_S = 5.0
# A factor of the confidence below this is worth telling the user about (its reason is added).
REASON_BELOW = 0.6
# How fast the confidence that the reading is unambiguous grows with the margin to the best
# assignment giving a different time (cost units): 1 − exp(−margin / MARGIN_SCALE).
MARGIN_SCALE = 2.0
# Confidence factors for a reading far from the expected time, and for a pivot the hands only
# locate across their common line.
FAR_FROM_EXPECTED_FACTOR = 0.5
PIVOT_UNCERTAIN_FACTOR = 0.7
# The seconds confidence when the seconds can't be trusted however well the hands agree (the
# seconds hand overlaps another, or 12 o'clock comes only from the tap): just below
# SECONDS_CONFIDENCE_THRESHOLD, so they're always withheld.
UNTRUSTED_SECONDS_CONFIDENCE = 0.45


@dataclass(frozen=True)
class Confidence:
    overall: float  # 0–1: is the reading (to the minute) right?
    seconds: float  # 0–1: can the seconds be trusted to about ±0.2 s?
    reasons: tuple[str, ...]  # why confidence was lowered, for the user

    @property
    def needs_confirmation(self) -> bool:
        return self.overall < CONFIDENCE_THRESHOLD or self.seconds < SECONDS_CONFIDENCE_THRESHOLD


def reported_time(
    a: Assignment, conf: Confidence, expected_s: float | None = None, placed: bool = False
) -> DialTime:
    """The time to report for an assignment: the one place that decides whether the seconds are
    shown. They're withheld (None, never guessed) when the seconds hand has no angle of its own
    (blended with a hand it lies over), or, unless the user `placed` the hands, when their
    confidence is below SECONDS_CONFIDENCE_THRESHOLD. A withheld seconds hand still placed the
    minute boundary."""
    time = _time_of(a, expected_s)
    if not placed and conf.seconds < SECONDS_CONFIDENCE_THRESHOLD:
        time = replace(time, seconds=None)
    return time


def confidence(
    a: Assignment,
    pivot_well_determined: bool,
    twelve_from_markers: bool,
    minute_settled: bool = False,
) -> Confidence:
    """How far to trust a reading (step 9).

    The seconds' confidence depends on the seconds hand itself (found, not hidden under
    another hand, 12 o'clock from the markers), not on how well the minute hand lines up with
    it: that only says which minute it is. `minute_settled`: the expected time picked the
    minute (`angles_to_time(expected_s=…)`), so a minute hand near a boundary doesn't matter.
    """
    reasons: list[str] = []
    hour_ok = math.exp(-0.5 * (a.hour_residual_min / HOUR_TOLERANCE_MIN) ** 2)
    if hour_ok < REASON_BELOW:
        reasons.append("The hour hand doesn't match the minute hand well.")
    # Another assignment of the hands, giving a different time, fits almost as well.
    distinct = 1 - math.exp(-a.margin / MARGIN_SCALE) if math.isfinite(a.margin) else 1.0
    if distinct < REASON_BELOW:
        reasons.append("The hands could be read in more than one way.")
    base = hour_ok * distinct
    if a.far_from_expected:
        base *= FAR_FROM_EXPECTED_FACTOR
        reasons.append("The reading is far from the expected time.")
    if not pivot_well_determined:
        base *= PIVOT_UNCERTAIN_FACTOR
        reasons.append("The hands overlap, so the center of the dial is less certain.")

    minute_ok = 1.0
    if a.minute_residual_s is not None and not minute_settled:
        beyond = abs(a.minute_residual_s) - MINUTE_BOUNDARY_S
        if beyond > 0:
            minute_ok = math.exp(-0.5 * (beyond / MINUTE_BOUNDARY_SCALE_S) ** 2)
            reasons.append("The minute hand sits between two minutes.")
    overall = base * minute_ok

    if a.second is None or a.minute_residual_s is None:
        return Confidence(overall, 0.0, (*reasons, "No seconds hand was found."))
    seconds = base
    if not a.seconds_readable:
        seconds = min(seconds, UNTRUSTED_SECONDS_CONFIDENCE)
        reasons.append("The seconds hand overlaps another hand.")
    if not twelve_from_markers:
        seconds = min(seconds, UNTRUSTED_SECONDS_CONFIDENCE)
        reasons.append("No hour markers: 12 o'clock comes only from your tap.")
    return Confidence(overall, seconds, tuple(reasons))
