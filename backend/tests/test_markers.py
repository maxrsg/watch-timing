import cv2
import pytest

from tests.synthetic.render import DialSpec, render
from tests.synthetic.scenarios import SCENARIOS
from tests.synthetic.truth import rectification_error_deg
from watchtiming.dial import MARKER_RADIUS, RECTIFIED_RADIUS, find_dial, rectified_frame
from watchtiming.markers import find_markers, fit_markers

CENTER, _ = rectified_frame()
MARKER_PX = MARKER_RADIUS * RECTIFIED_RADIUS


def markers_of(spec: DialSpec):
    dial = render(spec)
    ellipse = find_dial(dial.image, dial.truth.twelve)
    return dial, find_markers(dial.image, ellipse, dial.truth.twelve)


@pytest.mark.parametrize("name", ["flat", "rotated", "tilt_strong", "close_camera", "noise"])
def test_markers_give_an_exact_rectification(name):
    """Perspective, center and 12 o'clock from the markers alone (no pivot, no ring). Under
    strong tilt some markers are too squashed to pass the size filter; six are enough."""
    spec = SCENARIOS[name]
    dial, markers = markers_of(spec)
    fit = fit_markers(markers, CENTER, MARKER_PX)
    assert fit is not None and len(fit.inliers) >= 6
    # rectification_error_deg measures angles around the homography's origin.
    shift = [[1, 0, -CENTER[0]], [0, 1, -CENTER[1]], [0, 0, 1]]
    assert rectification_error_deg(shift @ fit.homography, dial, spec) < 0.1


def test_glare_biases_markers_and_the_reading_falls_back():
    """Glare shifts marker centroids; the pipeline then prefers the ring-based reading."""
    from watchtiming.pipeline import read_dial

    dial = render(SCENARIOS["glare"])
    reading = read_dial(dial.image, dial.truth.twelve)
    assert reading.marker_fit is None
    assert reading.time.seconds == pytest.approx(37.0, abs=0.05)


def test_a_hand_covering_the_tapped_marker():
    """At about :00 the minute hand lies over the 12 and merges with it into one hand-shaped
    blob (a real photo at 15:01). The other markers still fix the dial; the tap only gives
    the direction of 12."""
    spec = DialSpec(hours=3, minutes=0, seconds=20, tilt_deg=20)
    dial = render(spec)
    image = dial.image.copy()
    ink = int(image[round(dial.truth.twelve[1]), round(dial.truth.twelve[0])])
    pivot, twelve = (tuple(map(round, p)) for p in (dial.truth.pivot, dial.truth.twelve))
    cv2.line(image, pivot, twelve, ink, 25)
    ellipse = find_dial(image, dial.truth.twelve)
    markers = find_markers(image, ellipse, dial.truth.twelve)
    hours = [m.hour for m in markers]
    assert 0 not in hours and len(hours) >= 9  # the seconds hand (at 4) may cover one more
    assert set(hours) <= set(range(1, 12))
    fit = fit_markers(markers, CENTER, MARKER_PX)
    assert fit is not None
    shift = [[1, 0, -CENTER[0]], [0, 1, -CENTER[1]], [0, 0, 1]]
    assert rectification_error_deg(shift @ fit.homography, dial, spec) < 0.1


def test_hours_are_numbered_from_the_tapped_marker():
    _, markers = markers_of(DialSpec(rotation_deg=100))
    assert [m.hour for m in markers] == list(range(12))


def test_no_markers_means_no_fit():
    _, markers = markers_of(SCENARIOS["no_markers"])
    assert fit_markers(markers, CENTER, MARKER_PX) is None


def test_tap_away_from_any_marker():
    dial = render(DialSpec())
    ellipse = find_dial(dial.image, dial.truth.twelve)
    assert find_markers(dial.image, ellipse, (500.0, 330.0)) == []  # empty dial area
