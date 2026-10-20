"""End to end: every scenario must read within ±0.2 s, or withhold the seconds and ask the user
to confirm. The error in seconds is reported at the end of the test run."""

import pytest

from tests.synthetic.render import render
from tests.synthetic.scenarios import SCENARIOS
from tests.synthetic.truth import tap_with_error, true_seconds_into_12h, wrap
from watchtiming.pipeline import read_dial

PRECISION_S = 0.2


@pytest.mark.parametrize("tap_error_px", [0, 15])
@pytest.mark.parametrize("name,spec", SCENARIOS.items())
def test_reading_accuracy(name, spec, tap_error_px, accuracy_report):
    dial = render(spec)
    reading = read_dial(dial.image, tap_with_error(dial, tap_error_px), dial.color)
    true = true_seconds_into_12h(spec)
    c = reading.confidence
    key = f"{name} (tap {tap_error_px:+d} px)"

    if reading.time.seconds is None:
        accuracy_report[key] = (
            f"{reading.time}  seconds withheld  confidence {c.overall:.2f}/{c.seconds:.2f}"
        )
        assert c.needs_confirmation
        shown = reading.time.hours * 3600 + reading.time.minutes * 60
        assert -1 <= wrap(true - shown, 43200) < 61, "wrong hour or minute"
        return

    error = wrap(reading.time.seconds_into_12h() - true, 43200)
    accuracy_report[key] = (
        f"{reading.time}  error {error:+.3f} s  confidence {c.overall:.2f}/{c.seconds:.2f}"
    )
    assert abs(error) <= PRECISION_S
