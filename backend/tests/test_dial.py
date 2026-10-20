import cv2
import numpy as np
import pytest

from tests.synthetic.render import DialSpec, render
from tests.synthetic.scenarios import SCENARIOS
from tests.synthetic.truth import dial_point, rectification_error_deg
from watchtiming.dial import (
    MARKER_RADIUS,
    DialNotFoundError,
    Ellipse,
    apply_homography,
    dial_rings,
    find_dial,
    plausible_center,
    rectify,
    rectifying_homography,
)


def rim(dial, spec: DialSpec, fraction: float = 1.0):
    return [
        apply_homography(dial.truth.homography, dial_point(spec, d, fraction))
        for d in range(0, 360, 5)
    ]


@pytest.mark.parametrize("name,spec", SCENARIOS.items())
def test_a_ring_of_the_dial_gives_an_exact_rectification(name, spec):
    """The chosen ring may be the dial edge or the case around it: any circle in the dial's
    plane, concentric with it, fixes the perspective (with the true center)."""
    dial = render(spec)
    ellipse = find_dial(dial.image, dial.truth.twelve)
    h, miss = rectifying_homography(ellipse, dial.truth.dial_center, dial.truth.twelve)
    assert rectification_error_deg(h, dial, spec) < 0.1
    assert miss < 1e-6


def test_the_dial_edge_is_one_of_the_rings():
    spec = SCENARIOS["flat"]
    dial = render(spec)
    rings = dial_rings(dial.image, dial.truth.twelve)
    assert any(
        np.abs(r.ellipse.normalized_radius(rim(dial, spec)) - 1).max() < 0.005 for r in rings
    )


def test_rings_survive_ticks_touching_the_edge():
    """Real dials: a minute track and the rehaut touch the dial edge, so no contour is a clean
    ellipse (the old single-contour detector found nothing on real photos)."""
    spec = SCENARIOS["tilt_mild"]
    dial = render(spec)
    image = dial.image.copy()
    for inner, outer in zip(rim(dial, spec, 0.96), rim(dial, spec, 1.05), strict=True):
        cv2.line(image, tuple(map(round, inner)), tuple(map(round, outer)), 30, 3, cv2.LINE_AA)
    ellipse = find_dial(image, dial.truth.twelve)
    h, _ = rectifying_homography(ellipse, dial.truth.dial_center, dial.truth.twelve)
    assert rectification_error_deg(h, dial, spec) < 0.1


def test_ellipse_center_alone_leaves_perspective_error():
    """Why the pivot matters: under strong tilt the affine-only correction is degrees off."""
    spec = SCENARIOS["tilt_strong"]
    dial = render(spec)
    ellipse = find_dial(dial.image, dial.truth.twelve)
    h, _ = rectifying_homography(ellipse, ellipse.center, dial.truth.twelve)
    assert rectification_error_deg(h, dial, spec) > 2


def test_twelve_is_up_and_scaled_by_the_tap():
    dial = render(DialSpec(rotation_deg=130))
    ellipse = find_dial(dial.image, dial.truth.twelve)
    rect = rectify(dial.image, ellipse, dial.truth.dial_center, dial.truth.twelve)
    x, y = apply_homography(rect.homography, dial.truth.twelve)
    assert x == pytest.approx(rect.center[0], abs=0.5)
    assert rect.center[1] - y == pytest.approx(MARKER_RADIUS * rect.radius, abs=0.5)


def test_round_trip_to_photo():
    dial = render(DialSpec(tilt_deg=30))
    ellipse = find_dial(dial.image, dial.truth.twelve)
    rect = rectify(dial.image, ellipse, dial.truth.dial_center, dial.truth.twelve)
    back = rect.to_photo(apply_homography(rect.homography, (321.0, 456.0)))
    assert back == pytest.approx((321, 456))


def test_tap_outside_any_dial_is_rejected():
    dial = render(DialSpec())
    with pytest.raises(DialNotFoundError):
        find_dial(dial.image, (5.0, 5.0))


def test_blank_image_is_rejected():
    with pytest.raises(DialNotFoundError):
        find_dial(np.full((600, 800), 128, np.uint8), (400.0, 300.0))


def test_plausible_center_allows_no_offset_on_a_head_on_dial():
    circle = Ellipse((100.0, 100.0), 50.0, 50.0, 0.0)
    assert plausible_center(circle, (110.0, 100.0)) == pytest.approx((100, 100))
    tilted = Ellipse((100.0, 100.0), 50.0, 40.0, 0.0)  # √(50²−40²)·0.4 = 12 px allowed
    assert plausible_center(tilted, (105.0, 100.0)) == pytest.approx((105, 100))
    assert plausible_center(tilted, (130.0, 100.0)) == pytest.approx((112, 100))
