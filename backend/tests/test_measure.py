"""measure(): one photo → reading, overlay and deviation, without the HTTP layer."""

from datetime import UTC, datetime, timedelta, timezone

import cv2
import numpy as np
import pytest

from tests.synthetic.render import DialSpec, render
from tests.synthetic.truth import dial_point
from watchtiming import measure as measure_module
from watchtiming.dial import preprocess
from watchtiming.geometry import apply_homography
from watchtiming.measure import HandTips, expected_dial_seconds, measure, measure_typed
from watchtiming.pipeline import HandsNotFoundError, locate_dial
from watchtiming.reading import DialTime
from watchtiming.reference import Reference, ReferenceSource

CEST = timezone(timedelta(hours=2))
# The dial shows 10:08:37.0; size 1600 so the processed image is scaled (0.625).
SPEC = DialSpec(size=1600, tilt_deg=15, rotation_deg=10)
DIAL = render(SPEC)
PRE = preprocess(cv2.imencode(".png", DIAL.image)[1].tobytes())


def reference(local: datetime) -> Reference:
    return Reference(local.astimezone(UTC), ReferenceSource.EXIF, local.tzinfo)


def tip(angle_deg: float, fraction: float):
    return apply_homography(DIAL.truth.homography, dial_point(SPEC, angle_deg, fraction))


def test_measures_the_deviation():
    ref = reference(datetime(2026, 10, 18, 10, 8, 34, 500_000, tzinfo=CEST))
    m = measure(PRE, DIAL.truth.twelve, ref)
    assert m.reading is not None and m.reading_error is None
    assert m.deviation_s == pytest.approx(2.5, abs=0.05)
    assert m.tap == pytest.approx(np.array(DIAL.truth.twelve) * PRE.scale)


def test_the_overlay_is_in_photo_pixels_not_processed_ones():
    m = measure(PRE, DIAL.truth.twelve, None)
    assert PRE.scale < 1
    assert m.overlay.pivot == pytest.approx(DIAL.truth.pivot, abs=3)


def test_without_a_reference_there_is_no_deviation():
    m = measure(PRE, DIAL.truth.twelve, None)
    assert m.reading is not None and m.deviation_s is None


def test_placed_hands_are_scaled_like_the_tap():
    a = DIAL.truth.angles
    tips = HandTips(tip(a.hour, 0.3), tip(a.minute, 0.7), tip(a.second, 0.6))
    m = measure(PRE, DIAL.truth.twelve, None, tips)
    assert m.reading.corrected
    t = m.reading.time
    assert (t.hours, t.minutes) == (10, 8)
    assert t.seconds == pytest.approx(37.0, abs=0.1)


def test_no_dial_at_the_tap():
    m = measure(PRE, (5.0, 5.0), None)
    assert m.reading is None and m.overlay is None
    assert "dial" in m.reading_error


def test_hands_not_found_still_returns_the_dial(monkeypatch):
    def no_hands(gray, tap, color=None, expected_s=None):
        raise HandsNotFoundError("No hands were found on the dial.", locate_dial(gray, tap, color))

    monkeypatch.setattr(measure_module, "read_dial", no_hands)
    m = measure(PRE, DIAL.truth.twelve, None)
    assert m.reading is None and m.reading_error is not None
    assert m.overlay is not None and m.overlay.hands == []


def test_expected_dial_seconds_wraps_at_12_hours():
    ref = reference(datetime(2026, 10, 18, 23, 59, 50, tzinfo=CEST))
    assert expected_dial_seconds(ref, 15.0) == pytest.approx(5.0)
    assert expected_dial_seconds(ref, None) is None
    assert expected_dial_seconds(None, 15.0) is None


def test_a_typed_time_is_compared_like_a_reading():
    ref = reference(datetime(2026, 10, 18, 22, 8, 34, 500_000, tzinfo=CEST))
    assert measure_typed(DialTime(10, 8, 37.0), ref) == pytest.approx(2.5)  # PM resolved
    assert measure_typed(DialTime(10, 8, 37.0), None) is None
