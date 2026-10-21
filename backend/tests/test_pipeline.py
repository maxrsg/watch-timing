"""The pipeline's wiring: the reading's shape, roles, overlay and how often it detects segments."""

import numpy as np
import pytest

from tests.synthetic.render import DialSpec, render
from tests.synthetic.scenarios import SCENARIOS
from watchtiming import pipeline
from watchtiming.geometry import angle_diff, clock_angle
from watchtiming.pipeline import locate_dial, photo_overlay, read_dial, read_with_hands


def test_roles_name_each_hand_once():
    dial = render(DialSpec())
    reading = read_dial(dial.image, dial.truth.twelve)
    roles = [role for role, _ in reading.roles()]
    assert sorted(r for r in roles if r != "other") == ["hour", "minute", "second"]
    assert len(roles) == len(reading.candidates)


def test_tips_point_along_the_true_hands():
    spec = DialSpec()
    dial = render(spec)
    reading = read_dial(dial.image, dial.truth.twelve)
    true = {"hour": dial.truth.angles.hour, "minute": dial.truth.angles.minute,
            "second": dial.truth.angles.second}  # fmt: skip
    overlay = photo_overlay(reading, scale=1.0)
    px, py = overlay.pivot
    for hand in overlay.hands:
        if hand.role != "other":
            x, y = hand.tip
            assert angle_diff(clock_angle(x - px, y - py), true[hand.role]) < 0.5


def test_a_shared_candidate_is_named_by_the_finer_hand():
    """Hour and minute hands placed on the same line: one candidate per role still, and the
    overlay draws each."""
    dial = render(DialSpec())
    geometry = locate_dial(dial.image, dial.truth.twelve)
    tip = dial.truth.twelve
    reading = read_with_hands(geometry, tip, tip, None)
    assert [role for role, _ in reading.roles()] == ["hour", "minute"]


def test_placed_hands_need_no_confirmation():
    dial = render(DialSpec())
    geometry = locate_dial(dial.image, dial.truth.twelve)
    reading = read_with_hands(geometry, dial.truth.twelve, dial.truth.twelve, None)
    assert reading.corrected
    assert reading.confidence.needs_confirmation  # no seconds hand
    assert not reading.needs_confirmation


@pytest.mark.parametrize(("name", "expected"), [("flat", 1), ("no_markers", 2)])
def test_segments_are_detected_once_per_rectification(monkeypatch, name, expected):
    """LSD is the slowest step: a marker-based read runs it once; the ring-based rectification
    runs it for its rough pass and its final one."""
    calls = []
    original = pipeline.line_segments

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "line_segments", counting)
    dial = render(SCENARIOS[name])
    read_dial(dial.image, dial.truth.twelve)
    assert len(calls) == expected


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_placed_hands_use_the_geometry_the_reading_showed(name):
    """Hands the user drags on the overlay are measured from the pivot and rectification the
    reading drew, also when it chose the ring over less clean markers."""
    dial = render(SCENARIOS[name])
    reading = read_dial(dial.image, dial.truth.twelve)
    geometry = locate_dial(dial.image, dial.truth.twelve)
    assert (geometry.marker_fit is None) == (reading.geometry.marker_fit is None)
    assert geometry.pivot.pivot == reading.geometry.pivot.pivot
    assert geometry.twelve == reading.geometry.twelve
    assert np.array_equal(geometry.rectified.homography, reading.geometry.rectified.homography)
