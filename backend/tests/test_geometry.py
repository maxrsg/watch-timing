import math

import numpy as np
import pytest

from watchtiming.geometry import (
    angle_diff,
    apply_homography,
    circ_mean,
    clock_angle,
    clock_angles,
    clock_direction,
    clock_point,
    wrap,
)


@pytest.mark.parametrize(
    ("deg", "expected"),
    [(0, (0, -1)), (90, (1, 0)), (180, (0, 1)), (270, (-1, 0))],
)
def test_clock_direction_is_clockwise_from_12_with_y_down(deg, expected):
    assert clock_direction(deg) == pytest.approx(expected, abs=1e-12)


def test_clock_point_and_angle_round_trip():
    origin = (100.0, 50.0)
    for deg in np.arange(0, 360, 7.5):
        x, y = clock_point(origin, deg, 30)
        assert math.hypot(x - origin[0], y - origin[1]) == pytest.approx(30)
        assert angle_diff(clock_angle(x - origin[0], y - origin[1]), deg) < 1e-9


def test_clock_angle_is_in_0_to_360():
    assert clock_angle(-1, 0) == pytest.approx(270)
    rng = np.random.default_rng(0)
    for x, y in rng.normal(size=(200, 2)):
        assert 0 <= clock_angle(x, y) < 360


def test_clock_angles_matches_clock_angle():
    v = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0], [0.3, -2.0]])
    assert clock_angles(v) == pytest.approx([clock_angle(x, y) for x, y in v])


@pytest.mark.parametrize(
    ("value", "period", "expected"),
    [(190, 360, -170), (-190, 360, 170), (180, 360, -180), (43000, 43200, -200), (5, 360, 5)],
)
def test_wrap(value, period, expected):
    assert wrap(value, period) == pytest.approx(expected)


def test_angle_diff_is_symmetric_and_wraps():
    assert angle_diff(359, 1) == pytest.approx(2)
    assert angle_diff(1, 359) == pytest.approx(2)
    assert angle_diff(10, 190) == pytest.approx(180)


def test_circ_mean_across_12():
    assert angle_diff(circ_mean(np.array([350.0, 10.0]), np.array([1.0, 1.0])), 0) < 1e-9
    assert circ_mean(np.array([350.0, 10.0]), np.array([3.0, 1.0])) == pytest.approx(355, abs=0.1)


def test_apply_homography_divides_by_w():
    h = np.array([[2.0, 0, 1], [0, 2.0, 0], [0, 0, 2.0]])
    assert apply_homography(h, (3, 4)) == pytest.approx((3.5, 4))
