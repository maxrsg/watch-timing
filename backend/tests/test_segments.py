import numpy as np

from tests.synthetic.render import DialSpec, render
from tests.synthetic.scenarios import SCENARIOS
from tests.synthetic.truth import wrap
from watchtiming.dial import find_dial, rectify
from watchtiming.geometry import apply_homography
from watchtiming.segments import hand_groups, line_segments, measure_hands


def rectified(spec: DialSpec):
    dial = render(spec)
    ellipse = find_dial(dial.image, dial.truth.twelve)
    rect = rectify(dial.image, ellipse, dial.truth.dial_center, dial.truth.twelve)
    return dial, rect, apply_homography(rect.homography, dial.truth.pivot)


def test_segments_of_a_plain_dial():
    _, rect, _ = rectified(DialSpec())
    segs = line_segments(rect.image)
    assert segs.ndim == 2 and segs.shape[1] == 4 and len(segs) > 10


def test_a_hand_running_into_the_date_window_is_blocked():
    """At 3:01 the hour hand runs into the date window at 3 o'clock. The window's edges point
    at the pivot too, but start far from it: they're not a hand of their own, and the hour hand
    ends where it meets the window (its length is only a lower bound)."""
    spec = SCENARIOS["date_window"]
    dial, rect, pivot = rectified(spec)
    hands = measure_hands(rect.image, pivot, rect.radius)
    at_three = [c for c in hands if abs(wrap(c.angle - 90, 360)) < 6]
    assert len(at_three) == 1
    hour = at_three[0]
    assert abs(wrap(hour.angle - dial.truth.angles.hour, 360)) < 0.5
    assert hour.blocked


def test_the_date_window_alone_is_not_a_hand():
    spec = DialSpec(hours=10, minutes=8, seconds=37, dark_dial=True, date_window=True)
    _, rect, pivot = rectified(spec)
    groups = hand_groups(line_segments(rect.image), pivot, rect.radius)
    assert not [g for g in groups if abs(wrap(g.angle - 90, 360)) < 6]


def test_tapered_edges_are_joined_into_one_hand():
    """Each hand's two edges converge towards its tip; they're one candidate, on the hand's
    centerline."""
    dial, rect, pivot = rectified(DialSpec())
    groups = hand_groups(line_segments(rect.image), pivot, rect.radius)
    a = dial.truth.angles
    for true in (a.hour, a.minute, a.second):
        near = [g for g in groups if abs(wrap(g.angle - true, 360)) < 3]
        assert len(near) == 1
        assert abs(wrap(near[0].angle - true, 360)) < 0.2
    assert np.all([g.r_in < 0.3 for g in groups])
