"""The dial-reading pipeline: grayscale photo + tapped 12 o'clock → hand angles and time.

Pure functions. Wires the steps in dial.py, markers.py, segments.py and reading.py together,
and keeps the intermediate results for the debug CLI and for drawing the detected hands over
the photo.
"""

import math
from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.dial import (
    MARKER_RADIUS,
    RECTIFIED_RADIUS,
    Ellipse,
    Rectified,
    find_dial,
    plausible_center,
    rectified_frame,
    rectify,
    warp_rectified,
)
from watchtiming.geometry import (
    ColorImage,
    GrayImage,
    Point,
    apply_homography,
    clock_angle,
    clock_point,
)
from watchtiming.hands import HandCandidate, PivotSearch
from watchtiming.markers import (
    MARKER_INNER,
    MARKER_OUTER,
    MarkerFit,
    TwelveRefinement,
    find_markers,
    fit_markers,
    refine_twelve,
)
from watchtiming.reading import (
    Assignment,
    Confidence,
    DialTime,
    UnreadableDialError,
    assign_hands,
    confidence,
    hour_residual_min,
    minute_residual_s,
    reported_time,
)
from watchtiming.segments import Segments, find_pivot, line_segments, measure_hands

# How far off a tapped 12 o'clock can plausibly be, as an angle (about 20 px on a dial of
# 300 px radius).
TAP_UNCERTAINTY_DEG = 4.0
# The hour markers are trusted for the rectification when they fit their ideal positions this
# well (RMS, as a fraction of the marker radius; marker shapes differ, so not exactly 0).
MAX_MARKER_FIT_ERROR = 0.03
# Markers this clean (sideways RMS, degrees) are used without comparing against the ring-based
# reading; less clean fits (e.g. glare biasing centroids) are compared by confidence.
TRUSTED_MARKER_ANGLE_DEG = 0.3
# A homography has 8 unknowns: from fewer markers than this it bends to fit their centroids'
# noise. Such a fit is only used when it's clean (6 markers on a small real dial, 0.45° off,
# put the minute hand 4° off; the ring + pivot fallback was right).
FEW_MARKERS = 8
# How far the hands' edges may move the pivot from the marker center (fraction of R).
MAX_PIVOT_SHIFT = 0.04

Chroma = npt.NDArray[np.uint8]  # Lab a and b of the rectified dial
HandRole = Literal["hour", "minute", "second", "other"]


@dataclass(frozen=True)
class DialGeometry:
    """Where the dial is, before any hands are read: enough to draw it and to turn points the
    user drags on the photo into hand angles."""

    ellipse: Ellipse
    # How the dial was rectified: from the hour markers (None: from a ring and the pivot).
    marker_fit: MarkerFit | None
    rectified: Rectified  # perspective-corrected, 12 o'clock up
    pivot: PivotSearch  # in rectified coordinates
    twelve: TwelveRefinement  # hand angles are corrected by its offset

    def angle_of(self, photo_point: Point) -> float:
        """Clock angle (degrees) of the direction from the pivot to a point in the photo."""
        x, y = apply_homography(self.rectified.homography, photo_point)
        px, py = self.pivot.pivot
        return (clock_angle(x - px, y - py) - self.twelve.offset_deg) % 360

    def distance_of(self, photo_point: Point) -> float:
        """Distance from the pivot to a point in the photo, as a fraction of R."""
        x, y = apply_homography(self.rectified.homography, photo_point)
        px, py = self.pivot.pivot
        return math.hypot(x - px, y - py) / self.rectified.radius


@dataclass(frozen=True)
class DialReading:
    geometry: DialGeometry
    candidates: list[HandCandidate]
    assignment: Assignment
    time: DialTime  # seconds is None when they can't be trusted (never guessed)
    confidence: Confidence
    corrected: bool = False  # the hands were placed by the user

    @property
    def needs_confirmation(self) -> bool:
        """Hands the user placed are their confirmation."""
        return self.confidence.needs_confirmation and not self.corrected

    def roles(self) -> list[tuple[HandRole, HandCandidate]]:
        """Each candidate with the hand it was assigned to ("other": not a hand)."""
        a = self.assignment
        # Overlapping hands share a candidate: the finer hand names it (minute over hour,
        # seconds over both).
        by_id: dict[int, HandRole] = {id(a.hour): "hour", id(a.minute): "minute"}
        if a.second is not None:
            by_id[id(a.second)] = "second"
        return [(by_id.get(id(c), "other"), c) for c in self.candidates]

    def tip_in_rectified(self, c: HandCandidate) -> Point:
        """A candidate's tip in the rectified image. Candidate angles include the 12 o'clock
        correction and the assignment's rotation; this undoes both."""
        g = self.geometry
        angle = c.angle + g.twelve.offset_deg + self.assignment.rotation_deg
        return clock_point(g.pivot.pivot, angle, c.length * g.rectified.radius)


class HandsNotFoundError(UnreadableDialError):
    """The dial was located, but its hands couldn't be read. Carries the geometry, so the user
    can still place the hands themselves."""

    def __init__(self, message: str, geometry: DialGeometry):
        super().__init__(message)
        self.geometry = geometry


@dataclass(frozen=True)
class _Rectification:
    """A located dial, plus the rectified image's features that reading the hands reuses."""

    geometry: DialGeometry
    chroma: Chroma | None
    segments: Segments


@dataclass(frozen=True)
class _Features:
    pivot: PivotSearch
    chroma: Chroma | None
    segments: Segments


def rectified_chroma(color: ColorImage | None, rectified: Rectified) -> Chroma | None:
    """The rectified dial's color without its brightness (Lab a and b), or None."""
    if color is None:
        return None
    height, width = rectified.image.shape
    warped = cv2.warpPerspective(
        color, rectified.homography, (width, height), flags=cv2.INTER_LINEAR
    )
    return cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)[..., 1:]


def _features(rectified: Rectified, color: ColorImage | None) -> _Features:
    """The line segments of a rectified dial and where the hands' edges converge, starting
    from its center."""
    chroma = rectified_chroma(color, rectified)
    segs = line_segments(rectified.image, chroma)
    pivot = find_pivot(rectified.image, rectified.center, rectified.radius, segs)
    return _Features(pivot, chroma, segs)


def _from_markers(
    gray: GrayImage, ellipse: Ellipse, tap: Point, color: ColorImage | None = None
) -> _Rectification | None:
    """Perspective, center and 12 o'clock from the hour markers, if they fit well."""
    center, _ = rectified_frame()
    fit = fit_markers(find_markers(gray, ellipse, tap), center, MARKER_RADIUS * RECTIFIED_RADIUS)
    if fit is None or fit.rms_error > MAX_MARKER_FIT_ERROR:
        return None
    if len(fit.inliers) < FEW_MARKERS and fit.angular_rms_deg > TRUSTED_MARKER_ANGLE_DEG:
        return None
    rectified = warp_rectified(gray, fit.homography)
    # The markers fix the dial's center (to a few pixels: marker shapes differ); the hand lines
    # refine it.
    f = _features(rectified, color)
    found = f.pivot
    shift = math.hypot(found.pivot[0] - rectified.center[0], found.pivot[1] - rectified.center[1])
    pivot = (
        found
        if found.well_determined and shift <= MAX_PIVOT_SHIFT * rectified.radius
        else PivotSearch(rectified.center, found.lines, well_determined=True)
    )
    geometry = DialGeometry(ellipse, fit, rectified, pivot, TwelveRefinement(0.0, 0.0, True))
    return _Rectification(geometry, f.chroma, f.segments)


def _from_ring(
    gray: GrayImage, ellipse: Ellipse, tap: Point, color: ColorImage | None = None
) -> _Rectification:
    """Perspective from a ring of the dial plus the pivot (as its center); 12 o'clock from the
    tap, refined by the markers' 12-fold pattern."""
    # Rough pass: correct only the affine part, find the pivot, then use it as the dial
    # center to remove the perspective exactly.
    rough = rectify(gray, ellipse, ellipse.center, tap)
    rough_pivot = _features(rough, color).pivot
    center = plausible_center(ellipse, rough.to_photo(rough_pivot.pivot))
    rectified = rectify(gray, ellipse, center, tap)
    f = _features(rectified, color)
    twelve = refine_twelve(rectified.image, rectified.center, rectified.radius)
    geometry = DialGeometry(ellipse, None, rectified, f.pivot, twelve)
    return _Rectification(geometry, f.chroma, f.segments)


def _turned(c: HandCandidate, degrees: float) -> HandCandidate:
    outer = None if c.outer_angle is None else (c.outer_angle + degrees) % 360
    return replace(c, angle=(c.angle + degrees) % 360, outer_angle=outer)


def _read(r: _Rectification, expected_s: float | None) -> DialReading:
    g = r.geometry
    rect = g.rectified
    found = measure_hands(rect.image, g.pivot.pivot, rect.radius, r.chroma, r.segments)
    candidates = [_turned(c, -g.twelve.offset_deg) for c in found]
    # Without markers, 12 o'clock comes only from the tap, which can be a few degrees off.
    uncertainty = 0.0 if g.twelve.from_markers else TAP_UNCERTAINTY_DEG
    assignment = assign_hands(candidates, uncertainty, expected_s)
    conf = confidence(
        assignment, g.pivot.well_determined, g.twelve.from_markers, expected_s is not None
    )
    time = reported_time(assignment, conf, expected_s)
    return DialReading(g, candidates, assignment, time, conf)


def read_dial(
    gray: GrayImage,
    tap: Point,
    color: ColorImage | None = None,
    expected_s: float | None = None,
) -> DialReading:
    """Read the time on a dial. `tap` is the 12 o'clock marker in `gray`'s coordinates. `color`
    (the same image in color, optional) makes colored hands stand out. `expected_s` (seconds
    into the 12 hours: the reference time plus the watch's predicted deviation) only picks the
    minute when the minute hand sits near a minute boundary; see `angles_to_time`.

    Two ways to undo the perspective: from the hour markers (exact when they're clean; best on
    real dials, whose bezel and case sit above the dial) and from a ring of the dial plus the
    pivot. Clean markers are used directly. When they fit less cleanly (glare can bias their
    centroids), both are read and the reading whose hands agree best wins.
    """
    ellipse = find_dial(gray, tap)
    from_markers = _from_markers(gray, ellipse, tap, color)
    fit = from_markers.geometry.marker_fit if from_markers is not None else None
    trusted = fit is not None and fit.angular_rms_deg <= TRUSTED_MARKER_ANGLE_DEG
    options = [from_markers] if trusted else [from_markers, _from_ring(gray, ellipse, tap, color)]
    rectifications = [r for r in options if r is not None]
    readings: list[DialReading] = []
    error: UnreadableDialError | None = None
    for rectification in rectifications:
        try:
            readings.append(_read(rectification, expected_s))
        except UnreadableDialError as e:
            error = e
    if not readings:
        message = str(error or "No hands were found on the dial.")
        raise HandsNotFoundError(message, rectifications[0].geometry)
    # Two readings of the same photo: prefer one that needs no confirmation, then the one whose
    # hands agree best (a rectification rotated by glare-biased markers fits them worse).
    return min(readings, key=lambda r: (r.confidence.needs_confirmation, r.assignment.cost))


def locate_dial(
    gray: GrayImage, tap: Point, color: ColorImage | None = None, expected_s: float | None = None
) -> DialGeometry:
    """The geometry `read_dial` reads the dial in (same arguments, same choice of rectification),
    so hands the user placed on its overlay are measured from the pivot they were shown."""
    try:
        return read_dial(gray, tap, color, expected_s).geometry
    except HandsNotFoundError as e:
        return e.geometry


def read_with_hands(
    geometry: DialGeometry, hour: Point, minute: Point, second: Point | None
) -> DialReading:
    """A reading from hand tips the user placed on the photo (`gray`'s coordinates).

    The angles go through the same rectification as a detected reading. The hands' consistency
    is still checked: its reasons warn about a hand that was probably misplaced.
    """

    def hand(tip: Point) -> HandCandidate:
        return HandCandidate(geometry.angle_of(tip), geometry.distance_of(tip), 0.0, 1.0)

    h, m = hand(hour), hand(minute)
    s = hand(second) if second is not None else None
    assignment = Assignment(
        hour=h, minute=m, second=s, rotation_deg=0.0,
        minute_residual_s=minute_residual_s(m.angle, s.angle) if s else None,
        hour_residual_min=hour_residual_min(h.angle, m.angle),
        cost=0.0, seconds_shared=False, hour_minute_shared=False,
    )  # fmt: skip
    conf = confidence(assignment, pivot_well_determined=True, twelve_from_markers=True)
    time = reported_time(assignment, conf, placed=True)
    candidates = [c for c in (h, m, s) if c is not None]
    return DialReading(geometry, candidates, assignment, time, conf, corrected=True)


# --- Overlay: the detected geometry in the photo's coordinates ---------------------------------


@dataclass(frozen=True)
class HandTip:
    role: HandRole
    tip: Point


@dataclass(frozen=True)
class OverlayGeometry:
    """What the frontend draws over the photo, in the upright original photo's pixels."""

    dial_center: Point
    dial_axes: tuple[float, float]  # semi-major, semi-minor
    dial_angle_deg: float
    pivot: Point
    twelve: Point
    hands: list[HandTip]


def photo_overlay(reading: DialReading | DialGeometry, scale: float) -> OverlayGeometry:
    """Map the geometry (and the reading's hands, if any) back to the original photo. `scale` is
    processed pixels per original pixel (`Preprocessed.scale`)."""
    geometry = reading.geometry if isinstance(reading, DialReading) else reading
    rect = geometry.rectified

    def to_photo(point: Point) -> Point:
        x, y = rect.to_photo(point)
        return x / scale, y / scale

    hands: list[HandTip] = []
    if isinstance(reading, DialReading):
        hands = [
            HandTip(role, to_photo(reading.tip_in_rectified(c))) for role, c in reading.roles()
        ]
    e = geometry.ellipse
    # Middle of the marker ring, where the user tapped.
    twelve = clock_point(
        rect.center, geometry.twelve.offset_deg, (MARKER_INNER + MARKER_OUTER) / 2 * rect.radius
    )
    return OverlayGeometry(
        dial_center=(e.center[0] / scale, e.center[1] / scale),
        dial_axes=(e.semi_major / scale, e.semi_minor / scale),
        dial_angle_deg=e.angle_deg,
        pivot=to_photo(geometry.pivot.pivot),
        twelve=to_photo(twelve),
        hands=hands,
    )
