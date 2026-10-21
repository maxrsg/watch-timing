"""Hand assignment and confidence (steps 7–9) under the errors real hands have.

Candidates come straight from the true hand angles plus realistic errors, without any image:
an hour hand a few degrees off (5–9 min on the real photos), a minute hand up to tens of
seconds off the seconds hand (misalignment, parallax), the seconds hand's counterweight tail
long enough to look like a short hand, and clutter (lettering, the date window). Hands closer
than the detector can separate merge into one candidate. This measures the identification
logic alone; the synthetic dials and real photos cover the detection in front of it.
"""

from dataclasses import dataclass

import numpy as np
import pytest

from tests.synthetic.truth import wrap
from watchtiming.hands import HandCandidate
from watchtiming.reading import (
    UnreadableDialError,
    angles_to_time,
    assign_hands,
    confidence,
)

TRIALS = 400
MERGE_DEG = 3.0  # the detectors can't separate hands closer than this


@dataclass(frozen=True)
class Errors:
    hour_sd_deg: float  # hour hand angle error (normal)
    minute_off_s: float  # minute hand misalignment vs the seconds hand (uniform ±)
    tail: bool  # a counterweight tail long enough to pass as a short hand
    clutter: int  # random short bars (lettering, date window edges)


CASES = {
    "ideal": Errors(hour_sd_deg=1.0, minute_off_s=0.0, tail=False, clutter=0),
    "realistic": Errors(hour_sd_deg=3.0, minute_off_s=20.0, tail=True, clutter=0),
    "realistic_clutter": Errors(hour_sd_deg=3.0, minute_off_s=20.0, tail=True, clutter=2),
    "bad_minute": Errors(hour_sd_deg=3.0, minute_off_s=35.0, tail=True, clutter=2),
}


def _candidates(t: float, e: Errors, rng: np.random.Generator) -> list[HandCandidate]:
    hour = t / 120 + rng.normal(0, e.hour_sd_deg)
    minute = t / 10 + rng.uniform(-e.minute_off_s, e.minute_off_s) / 10 + rng.normal(0, 0.5)
    second = t * 6 + rng.normal(0, 0.3)
    raw = [
        HandCandidate(hour % 360, 0.55, 0.10, 1.2),
        HandCandidate(minute % 360, 0.80, 0.08, 1.8),
        HandCandidate(second % 360, 0.82, 0.015, 1.0),
    ]
    if e.tail:
        raw.append(HandCandidate((second + 180) % 360, 0.38, 0.03, 0.5))
    for _ in range(e.clutter):
        raw.append(
            HandCandidate(
                rng.uniform(0, 360), rng.uniform(0.35, 0.6), rng.uniform(0.01, 0.05),
                rng.uniform(0.2, 0.6),
            )
        )  # fmt: skip
    merged: list[HandCandidate] = []
    for c in sorted(raw, key=lambda c: -c.strength):
        for i, o in enumerate(merged):
            if abs(wrap(c.angle - o.angle, 360)) < MERGE_DEG:
                merged[i] = HandCandidate(
                    o.angle, max(o.length, c.length), max(o.width, c.width), o.strength + c.strength
                )
                break
        else:
            merged.append(c)
    return merged


@dataclass
class Tally:
    right: int = 0  # hour:minute right, and the seconds too when reported
    seconds_right: int = 0  # seconds reported and within 1 s
    seconds_wrong: int = 0  # seconds reported but off
    withheld: int = 0
    confidently_wrong: int = 0

    def line(self, n: int) -> str:
        return (
            f"right {self.right / n:4.0%}  seconds right {self.seconds_right / n:4.0%}"
            f"  withheld {self.withheld / n:4.0%}  seconds wrong {self.seconds_wrong / n:4.0%}"
            f"  confidently wrong {self.confidently_wrong / n:4.0%}"
        )


def run(e: Errors, with_prior: bool, seed: int = 0) -> Tally:
    rng = np.random.default_rng(seed)
    tally = Tally()
    for _ in range(TRIALS):
        t = rng.uniform(0, 43200)
        candidates = _candidates(t, e, rng)
        # The prior: the reference time plus the predicted deviation, off by up to 20 s.
        expected = (t + rng.uniform(-20, 20)) % 43200 if with_prior else None
        try:
            a = assign_hands(candidates)
        except UnreadableDialError:
            continue
        c = confidence(a, True, True, minute_settled=expected is not None)
        time = angles_to_time(a.hour_angle, a.minute_angle, a.second_angle, expected_s=expected)
        if c.seconds < 0.5 or time.seconds is None:
            tally.withheld += 1
            shown = time.hours * 3600 + time.minutes * 60
            right = 0 <= wrap(t - shown, 43200) < 60
        else:
            right = abs(wrap(time.seconds_into_12h() - t, 43200)) < 1.0
            if right:
                tally.seconds_right += 1
            else:
                tally.seconds_wrong += 1
        tally.right += right
        tally.confidently_wrong += not right and not c.needs_confirmation
    return tally


@pytest.mark.parametrize("with_prior", [False, True], ids=["no_prior", "prior"])
@pytest.mark.parametrize("case", list(CASES))
def test_assignment_under_real_errors(case, with_prior, accuracy_report):
    tally = run(CASES[case], with_prior)
    accuracy_report[f"stress {case} ({'prior' if with_prior else 'no prior'})"] = tally.line(TRIALS)
    if case == "bad_minute" and not with_prior:
        # A minute hand 35 s off looks like one 25 s off the other way: without the expected
        # time no logic can tell, so this case is only reported. Real minute hands stay within
        # ~25 s (MINUTE_BOUNDARY_S).
        return
    # The hard rule: never confidently wrong.
    assert tally.confidently_wrong == 0, tally.line(TRIALS)
    if case in ("ideal", "realistic", "realistic_clutter"):
        assert tally.right >= 0.97 * TRIALS, tally.line(TRIALS)
        assert tally.seconds_right >= 0.90 * TRIALS, tally.line(TRIALS)
    if with_prior:  # a minute hand off by up to 35 s is settled by the prior
        assert tally.right >= 0.97 * TRIALS, tally.line(TRIALS)
