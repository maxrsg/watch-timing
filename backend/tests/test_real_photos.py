"""Accuracy on real photos (tests/fixtures/local/, gitignored; add with
`python -m tests.fixtures.add_local`). Skipped when there are none.

The only hard rule here: a reading is never confidently wrong. A wrong reading must ask the
user to confirm it. The errors are reported at the end of the run, to measure progress.
"""

import json
from pathlib import Path

import pytest

from tests.synthetic.render import hand_angles
from tests.synthetic.truth import wrap
from watchtiming.dial import DialNotFoundError, preprocess
from watchtiming.pipeline import HandsNotFoundError, read_dial

LOCAL = Path(__file__).parent / "fixtures" / "local"
PHOTOS = sorted(p for p in LOCAL.glob("*") if (p / "truth.json").is_file())
# A reading counts as right within these errors (the seconds one is the precision target for
# the whole measurement; the minute one allows for the seconds being withheld).
SECONDS_TOLERANCE_S = 0.5
MINUTE_TOLERANCE_S = 60.0


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
@pytest.mark.parametrize("folder", PHOTOS, ids=[p.name for p in PHOTOS])
def test_real_photo(folder: Path, real_photo_report):
    truth = json.loads((folder / "truth.json").read_text())
    true_s = truth["hours"] * 3600 + truth["minutes"] * 60 + truth["seconds"]
    pre = preprocess((folder / "photo.jpg").read_bytes())
    tap = (truth["tap"][0] * pre.scale, truth["tap"][1] * pre.scale)
    shown = f"{truth['hours']}:{truth['minutes']:02d}:{truth['seconds']:04.1f}"
    try:
        reading = read_dial(pre.gray, tap, pre.color)
    except (DialNotFoundError, HandsNotFoundError) as e:
        real_photo_report[folder.name] = f"true {shown}  no reading: {e}"
        return

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
    real_photo_report[folder.name] = (
        f"true {shown}  read {result}  ({_angle_errors(reading, truth)})"
        f"  confidence {c.overall:.2f}/{c.seconds:.2f}  {verdict}"
    )
    assert right or c.needs_confirmation, "confidently wrong"
