"""Ground-truth helpers for comparing pipeline results with a rendered dial.

The clock-angle convention (sin, −cos) is written out here and in render.py on purpose instead
of importing watchtiming.geometry: the ground truth stays an independent check of it.
"""

import math

import numpy as np

from tests.synthetic.render import DialSpec, RenderedDial
from watchtiming.geometry import Point, apply_homography


def wrap(value: float, period: float) -> float:
    """Into [−period/2, period/2)."""
    return (value + period / 2) % period - period / 2


def true_seconds_into_12h(spec: DialSpec) -> float:
    return (spec.hours % 12) * 3600 + spec.minutes * 60 + spec.seconds


def dial_point(spec: DialSpec, clock_deg: float, fraction: float) -> Point:
    """A point in the flat dial frame: `fraction` of R from the center at a clock angle."""
    r = spec.dial_radius * spec.size * fraction
    a = math.radians(clock_deg)
    return (spec.size / 2 + r * math.sin(a), spec.size / 2 - r * math.cos(a))


def rectification_error_deg(h_photo_to_rect: np.ndarray, dial: RenderedDial, spec: DialSpec):
    """Largest clock-angle error of dial points mapped photo → rectified, around the
    rectified center (the origin of `h_photo_to_rect`)."""
    worst = 0.0
    for deg in range(0, 360, 10):
        photo = apply_homography(dial.truth.homography, dial_point(spec, deg, 0.9))
        x, y = apply_homography(h_photo_to_rect, photo)
        worst = max(worst, abs(wrap(math.degrees(math.atan2(x, -y)) - deg, 360)))
    return worst


def tap_with_error(dial: RenderedDial, pixels: float) -> Point:
    """The true 12 o'clock point, moved `pixels` sideways (tangentially), like a sloppy tap."""
    (tx, ty), (cx, cy) = dial.truth.twelve, dial.truth.pivot
    angle = math.atan2(ty - cy, tx - cx) + math.pi / 2
    return tx + pixels * math.cos(angle), ty + pixels * math.sin(angle)
