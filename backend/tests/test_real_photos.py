"""Accuracy on real photos (tests/fixtures/local/, gitignored; add with
`python -m tests.fixtures.add_local`). Skipped when there are none.

The only hard rule here: a reading is never confidently wrong. A wrong reading must ask the
user to confirm it. The errors are reported at the end of the run, to measure progress.
"""

import json
import time
from pathlib import Path

import pytest

from tests.synthetic.render import hand_angles
from tests.synthetic.truth import wrap
from watchtiming.dial import DialNotFoundError, preprocess
from watchtiming.pipeline import HandsNotFoundError, read_dial

LOCAL = Path(__file__).parent / "fixtures" / "local"
PHOTOS = sorted(p for p in LOCAL.glob("*") if (p / "truth.json").is_file())
# A reading counts as right within these errors (the seconds one is the precision target for
# the whole measurement, widened to the labels' own uncertainty: the B photos' times are read
# by eye to about ±1 s; the minute one allows for the seconds being withheld).
SECONDS_TOLERANCE_S = 1.0
MINUTE_TOLERANCE_S = 60.0
# The prior's error: the expected time as the reference plus a predicted deviation, 20 s off.
PRIOR_ERROR_S = 20.0


def _angle_errors(reading, truth) -> str:
    true = hand_angles(truth["hours"], truth["minutes"], truth["seconds"])
    a = reading.assignment
    parts = [
        f"h {wrap(a.hour_angle - true.hour, 360):+.1f}°",
        f"m {wrap(a.minute_angle - true.minute, 360):+.1f}°",
    ]
    if a.second_angle is not None:
        parts.append(f"s {wrap(a.second_angle - true.second, 360):+.1f}°")
    return " ".join(parts)


@pytest.mark.skipif(not PHOTOS, reason="no local real-photo fixtures")
@pytest.mark.parametrize("with_prior", [False, True], ids=["no_prior", "prior"])
@pytest.mark.parametrize("folder", PHOTOS, ids=[p.name for p in PHOTOS])
def test_real_photo(folder: Path, with_prior: bool, real_photo_report):
    truth = json.loads((folder / "truth.json").read_text())
    true_s = truth["hours"] * 3600 + truth["minutes"] * 60 + truth["seconds"]
    pre = preprocess((folder / "photo.jpg").read_bytes())
    tap = (truth["tap"][0] * pre.scale, truth["tap"][1] * pre.scale)
    shown = f"{truth['hours']}:{truth['minutes']:02d}:{truth['seconds']:04.1f}"
    expected = (true_s + PRIOR_ERROR_S) % 43200 if with_prior else None
    key = f"{folder.name} ({'prior' if with_prior else 'no prior'})"
    start = time.perf_counter()
    try:
        reading = read_dial(pre.gray, tap, pre.color, expected)
    except (DialNotFoundError, HandsNotFoundError) as e:
        real_photo_report[key] = f"true {shown}  no reading: {e}"
        return
    elapsed = time.perf_counter() - start

    t, c = reading.time, reading.confidence
    if t.seconds is None:
        error = wrap(t.hours * 3600 + t.minutes * 60 + 30 - true_s, 43200)
        right = abs(error) <= MINUTE_TOLERANCE_S - 30
        result = f"{t}  error {error / 60:+.1f} min (seconds withheld)"
    else:
        error = wrap(t.seconds_into_12h() - true_s, 43200)
        right = abs(error) <= SECONDS_TOLERANCE_S
        result = f"{t}  error {error:+.2f} s"
    verdict = "ok" if right else ("WRONG, flagged" if c.needs_confirmation else "WRONG")
    real_photo_report[key] = (
        f"true {shown}  read {result}  ({_angle_errors(reading, truth)})"
        f"  confidence {c.overall:.2f}/{c.seconds:.2f}  {verdict}  {elapsed:.2f} s"
    )
    assert right or c.needs_confirmation, "confidently wrong"
