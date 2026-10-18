"""The renderer is the ground truth for the CV tests, so it gets tested itself."""

import math

import cv2
import numpy as np
import pytest

from tests.synthetic.render import DialSpec, hand_angles, render
from tests.synthetic.scenarios import SCENARIOS


def sample(image, origin, angle_deg: float, distance: float) -> int:
    """Gray value at `distance` px from `origin` along a clock angle (photo coordinates)."""
    a = math.radians(angle_deg)
    x = origin[0] + distance * math.sin(a)
    y = origin[1] - distance * math.cos(a)
    return int(image[round(y), round(x)])


def radius(spec: DialSpec) -> float:
    return spec.dial_radius * spec.size


def test_hand_angles():
    a = hand_angles(3, 0, 0)
    assert (a.hour, a.minute, a.second) == (90, 0, 0)
    a = hand_angles(10, 8, 37)
    assert a.hour == pytest.approx((10 + 8 / 60 + 37 / 3600) * 30)
    assert a.minute == pytest.approx(48 + 37 / 10)
    assert a.second == pytest.approx(222)
    assert hand_angles(12, 0, 0).hour == 0


def test_deterministic_for_a_seed():
    spec = DialSpec(noise_sigma=8, glare=0.3, tilt_deg=20)
    assert np.array_equal(render(spec).image, render(spec).image)
    other = render(DialSpec(noise_sigma=8, glare=0.3, tilt_deg=20, seed=1)).image
    assert not np.array_equal(render(spec).image, other)


@pytest.mark.parametrize("rotation", [0, 40, -115])
def test_hands_are_at_their_angles(rotation):
    spec = DialSpec(rotation_deg=rotation)
    dial = render(spec)
    r, pivot, a = radius(spec), dial.truth.pivot, dial.truth.angles
    # Each hand at ~60% of its length is ink-colored; 15° to the side is dial-colored.
    for angle, length in ((a.hour, 0.5), (a.minute, 0.82), (a.second, 0.9)):
        assert sample(dial.image, pivot, angle + rotation, 0.6 * length * r) < 60
        assert sample(dial.image, pivot, angle + rotation + 15, 0.6 * length * r) > 200


def test_untilted_geometry():
    spec = DialSpec()
    truth = render(spec).truth
    assert truth.pivot == pytest.approx((500, 500))
    assert truth.twelve == pytest.approx((500, 500 - 0.9 * radius(spec)))


def test_rotation_moves_twelve_clockwise():
    truth = render(DialSpec(rotation_deg=90)).truth
    assert truth.twelve[0] > truth.pivot[0] + 300
    assert truth.twelve[1] == pytest.approx(truth.pivot[1], abs=0.5)


def test_dark_dial_inverts_polarity():
    spec = DialSpec(dark_dial=True)
    dial = render(spec)
    a, pivot, r = dial.truth.angles, dial.truth.pivot, radius(spec)
    assert sample(dial.image, pivot, a.minute, 0.5 * r) > 200  # light hand
    assert sample(dial.image, pivot, a.minute + 15, 0.5 * r) < 60  # dark dial


def test_seconds_tail_points_backwards():
    spec = DialSpec()
    with_tail, without = render(spec), render(DialSpec(seconds_tail=0))
    behind = spec.dial_radius * spec.size * 0.15
    angle = with_tail.truth.angles.second + 180
    assert sample(with_tail.image, with_tail.truth.pivot, angle, behind) < 60
    assert sample(without.image, without.truth.pivot, angle, behind) > 200


def test_pivot_offset_moves_pivot_not_dial():
    spec = DialSpec(pivot_offset=(0.0, 0.3))
    truth = render(spec).truth
    assert truth.dial_center == pytest.approx((500, 500))
    assert truth.pivot == pytest.approx((500, 500 + 0.3 * radius(spec)))


@pytest.mark.parametrize("tilt,axis", [(25, 0), (40, 60)])
def test_tilt_turns_the_dial_into_an_ellipse(tilt, axis):
    dial = render(DialSpec(tilt_deg=tilt, tilt_axis_deg=axis, markers=False))
    # Light dial (235) on a darker case (150): the dial is the largest bright region.
    mask = (dial.image > 200).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    _, (d1, d2), _ = cv2.fitEllipse(max(contours, key=cv2.contourArea))
    # Perspective makes it not exactly cos(tilt), but close at this camera distance.
    assert min(d1, d2) / max(d1, d2) == pytest.approx(math.cos(math.radians(tilt)), abs=0.03)
    x, y = dial.truth.twelve
    assert mask[round(y), round(x)] or dial.image[round(y), round(x)] < 60  # on the dial


def test_effects_keep_the_image_valid():
    dial = render(DialSpec(glare=0.6, blur_sigma=1.5, noise_sigma=12))
    assert dial.image.dtype == np.uint8 and dial.image.shape == (1000, 1000)
    gx, gy = 350, 300
    assert dial.image[gy - 5 : gy + 5, gx - 5 : gx + 5].mean() > 245  # glare saturates


@pytest.mark.parametrize("name,spec", SCENARIOS.items())
def test_every_scenario_renders(name, spec):
    dial = render(spec)
    assert dial.image.shape == (spec.size, spec.size)
    x, y = dial.truth.pivot
    assert 0 < x < spec.size and 0 < y < spec.size


def test_overlap_scenarios_really_overlap():
    a = render(SCENARIOS["overlap_hour_minute"]).truth.angles
    assert abs(a.hour - a.minute) < 2
    a = render(SCENARIOS["overlap_minute_second"]).truth.angles
    assert abs(a.minute - a.second) < 2
