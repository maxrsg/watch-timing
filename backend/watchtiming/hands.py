"""Shared hand types: the hands' centerlines, the pivot search result and the hand candidate.

The hands themselves are found from their straight edges in segments.py and assigned in
reading.py. Angles are clock angles: degrees clockwise from 12 o'clock in the rectified dial.
"""

from dataclasses import dataclass

from watchtiming.geometry import FloatArray, Point

# Hands whose directions differ less than this (mod 180°) can't locate the pivot together.
MIN_LINE_SPREAD_DEG = 8.0


@dataclass(frozen=True)
class HandLine:
    point: FloatArray  # a point on the line (image coordinates)
    direction: FloatArray  # unit vector
    weight: float


@dataclass(frozen=True)
class PivotSearch:
    pivot: Point
    lines: list[HandLine]  # the hands' centerlines that located it
    # False when the hands lie along a single line: the pivot is then only located across it.
    well_determined: bool


# Candidates shorter than this (fraction of R) are tails (e.g. the seconds hand's
# counterweight) or noise.
MIN_HAND_LENGTH = 0.3


@dataclass(frozen=True)
class HandCandidate:
    angle: float  # clock degrees, of the hand's direction
    length: float  # fraction of R
    width: float  # fraction of R, measured across the hand
    strength: float  # evidence (edge length); relative between candidates of one photo
    blocked: bool = False  # ran into something (a date window): its length is a lower bound
    # Angle of the outer part only (None: same as `angle`). Where two hands overlap near the
    # pivot, the longer one's outer part is itself alone.
    outer_angle: float | None = None

    @property
    def is_tail(self) -> bool:
        # A hand cut short by a date window is no tail: its length is only a lower bound.
        return self.length < MIN_HAND_LENGTH and not self.blocked
