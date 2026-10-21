"""Shared types and the clock-angle convention used throughout the pipeline.

Pure functions. Clock angles are degrees clockwise from 12 o'clock, in image coordinates
(x right, y down): the direction of clock angle θ is (sin θ, −cos θ). Every module converts
between angles and points through these helpers, so the convention lives in one place.
"""

import math

import numpy as np
import numpy.typing as npt

Point = tuple[float, float]
Matrix = npt.NDArray[np.float64]
GrayImage = npt.NDArray[np.uint8]
ColorImage = npt.NDArray[np.uint8]  # BGR (OpenCV's channel order)
FloatArray = npt.NDArray[np.float64]


def wrap(value: float, period: float) -> float:
    """Into [−period/2, period/2)."""
    return (value + period / 2) % period - period / 2


def angle_diff(a: float, b: float) -> float:
    """Unsigned difference between two angles in degrees, 0–180."""
    return abs(wrap(a - b, 360))


def clock_direction(deg: float) -> FloatArray:
    """Unit vector of a clock angle, in image coordinates."""
    a = math.radians(deg)
    return np.array([math.sin(a), -math.cos(a)])


def clock_point(origin: Point, deg: float, distance: float) -> Point:
    """The point `distance` pixels from `origin` at a clock angle."""
    a = math.radians(deg)
    return origin[0] + distance * math.sin(a), origin[1] - distance * math.cos(a)


def clock_angle(dx: float, dy: float) -> float:
    """Clock angle (degrees, 0–360) of an image-space vector."""
    return math.degrees(math.atan2(dx, -dy)) % 360


def clock_angles(v: FloatArray) -> FloatArray:
    """`clock_angle` of each vector in an (…, 2) array."""
    return np.degrees(np.arctan2(v[..., 0], -v[..., 1])) % 360


def circ_mean(deg: FloatArray, weights: FloatArray) -> float:
    """Weighted circular mean of angles in degrees, 0–360."""
    a = np.radians(deg)
    s, c = (weights * np.sin(a)).sum(), (weights * np.cos(a)).sum()
    return float(np.degrees(np.arctan2(s, c)) % 360)


def apply_homography(h: Matrix, point: Point) -> Point:
    x, y, w = h @ np.array([point[0], point[1], 1.0])
    return float(x / w), float(y / w)
