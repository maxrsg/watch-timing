"""One measurement: a preprocessed photo, its tap and reference time → reading and deviation.

Pure functions, no framework code: the API parses the upload and serializes the result, the
debug tools call this the same way. Points are in the upright original photo's pixels (the
frame the user tapped in); they're scaled into the processed image here.
"""

from dataclasses import dataclass

from watchtiming.dial import DialNotFoundError, Preprocessed
from watchtiming.geometry import Point
from watchtiming.pipeline import (
    DialReading,
    HandsNotFoundError,
    OverlayGeometry,
    locate_dial,
    photo_overlay,
    read_dial,
    read_with_hands,
)
from watchtiming.reading import UnreadableDialError, deviation_seconds, seconds_into_12h
from watchtiming.reference import Reference

TWELVE_HOURS_S = 12 * 3600


@dataclass(frozen=True)
class HandTips:
    """Hand tips the user placed on the photo; `second` None: no seconds hand."""

    hour: Point
    minute: Point
    second: Point | None


@dataclass(frozen=True)
class Measurement:
    reading: DialReading | None
    overlay: OverlayGeometry | None  # also without a reading, when the dial was found
    reading_error: str | None
    # Dial − reference in seconds, positive = fast. Needs the reference and the dial's seconds.
    deviation_s: float | None
    tap: Point  # in the processed image


def expected_dial_seconds(
    ref: Reference | None, expected_deviation_s: float | None
) -> float | None:
    """What the dial should show (seconds into its 12 hours): the reference time in the watch's
    zone plus the predicted deviation. None without either."""
    if ref is None or expected_deviation_s is None:
        return None
    return (seconds_into_12h(ref.local_time) + expected_deviation_s) % TWELVE_HOURS_S


def measure(
    pre: Preprocessed,
    tap: Point,
    ref: Reference | None,
    tips: HandTips | None = None,
    expected_deviation_s: float | None = None,
) -> Measurement:
    """Read the dial (or take the hands the user placed) and compare it with the reference.

    `tap`: the 12 o'clock marker. `tips`: hands the user placed, used instead of detecting
    them. `expected_deviation_s`: the watch's predicted deviation; with a reference it settles
    which minute a minute hand near a boundary means (see `read_dial`).
    """

    def scaled(p: Point) -> Point:
        return p[0] * pre.scale, p[1] * pre.scale

    tap_px = scaled(tap)
    expected = expected_dial_seconds(ref, expected_deviation_s)
    try:
        if tips is None:
            reading = read_dial(pre.gray, tap_px, pre.color, expected)
        else:
            geometry = locate_dial(pre.gray, tap_px, pre.color, expected)
            second = scaled(tips.second) if tips.second is not None else None
            reading = read_with_hands(geometry, scaled(tips.hour), scaled(tips.minute), second)
    except HandsNotFoundError as e:
        # The dial was found: its geometry lets the user place the hands.
        return Measurement(None, photo_overlay(e.geometry, pre.scale), str(e), None, tap_px)
    except (DialNotFoundError, UnreadableDialError) as e:
        return Measurement(None, None, str(e), None, tap_px)

    deviation = None
    if ref is not None and reading.time.seconds is not None:
        deviation = deviation_seconds(reading.time, ref.local_time)
    return Measurement(reading, photo_overlay(reading, pre.scale), None, deviation, tap_px)
