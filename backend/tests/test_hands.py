import math

import numpy as np
import pytest

from tests.synthetic.render import DialSpec, render
from tests.synthetic.scenarios import SCENARIOS
from tests.synthetic.truth import wrap
from watchtiming.dial import apply_homography, find_dial, rectify
from watchtiming.hands import find_pivot, measure_hands, refine_twelve, unwrap
from watchtiming.pipeline import read_dial

# Hands that should be found as separate candidates (no overlaps in these scenarios).
SEPARATE = [n for n in SCENARIOS if "overlap" not in n]


def rectified(spec: DialSpec, center="true"):
    dial = render(spec)
    ellipse = find_dial(dial.image, dial.truth.twelve)
    c = dial.truth.dial_center if center == "true" else ellipse.center
    return dial, rectify(dial.image, ellipse, c, dial.truth.twelve)


def test_unwrap_rows_are_clock_angles():
    image = np.zeros((201, 201), np.uint8)
    image[100, 150:] = 255  # a bright ray towards 3 o'clock
    polar = unwrap(image, (100.0, 100.0), 90, angle_bins=360)
    assert int(np.argmax(polar[:, 60])) == 90


@pytest.mark.parametrize("name", SEPARATE)
def test_pivot(name):
    """Found from the hand lines, starting from a rough (affine-only) rectification: a
    homography keeps the hands straight lines through the pivot."""
    dial = render(SCENARIOS[name])
    reading = read_dial(dial.image, dial.truth.twelve, dial.color)
    true = apply_homography(reading.rectified.homography, dial.truth.pivot)
    found = reading.pivot.pivot
    error = math.hypot(found[0] - true[0], found[1] - true[1])
    limit = 6.0 if name == "everything" else 2.5  # noise + glare + blur + tilt combined
    assert error < limit, f"pivot {error:.2f} px off"


def test_parallel_hands_are_flagged():
    dial, rect = rectified(SCENARIOS["overlap_all"])
    assert not find_pivot(rect.image, rect.center, rect.radius).well_determined


@pytest.mark.parametrize("name", ["flat", "tilt_strong", "dark_dial", "glare", "noise"])
def test_hand_candidates_have_true_angles_and_shapes(name):
    spec = SCENARIOS[name]
    dial, rect = rectified(spec)
    pivot = apply_homography(rect.homography, dial.truth.pivot)
    hands = [c for c in measure_hands(rect.image, rect.center, pivot, rect.radius) if not c.is_tail]
    assert len(hands) == 3
    a = dial.truth.angles
    by_truth = {}
    for label, angle in (("hour", a.hour), ("minute", a.minute), ("second", a.second)):
        best = min(hands, key=lambda c: abs(wrap(c.angle - angle, 360)))
        assert abs(wrap(best.angle - angle, 360)) < 0.2, label
        by_truth[label] = best
    assert by_truth["hour"].length < by_truth["minute"].length
    assert by_truth["second"].width < by_truth["minute"].width < by_truth["hour"].width


@pytest.mark.parametrize("tap_error_px", [-20, 0, 20])
def test_markers_fix_a_sloppy_tap(tap_error_px):
    dial = render(DialSpec(rotation_deg=25))
    (tx, ty), (cx, cy) = dial.truth.twelve, dial.truth.pivot
    side = math.atan2(ty - cy, tx - cx) + math.pi / 2
    tap = (tx + tap_error_px * math.cos(side), ty + tap_error_px * math.sin(side))
    ellipse = find_dial(dial.image, tap)
    rect = rectify(dial.image, ellipse, dial.truth.dial_center, tap)
    twelve = refine_twelve(rect.image, rect.center, rect.radius)
    true_12 = apply_homography(rect.homography, dial.truth.twelve)
    true_offset = math.degrees(math.atan2(true_12[0] - rect.center[0], rect.center[1] - true_12[1]))
    assert twelve.from_markers
    assert twelve.offset_deg == pytest.approx(true_offset, abs=0.15)


def test_no_markers_falls_back_to_the_tap():
    dial, rect = rectified(SCENARIOS["no_markers"])
    twelve = refine_twelve(rect.image, rect.center, rect.radius)
    assert not twelve.from_markers
    assert twelve.offset_deg == 0
