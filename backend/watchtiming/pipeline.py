"""The dial-reading pipeline: grayscale photo + tapped 12 o'clock → hand angles and time.

Pure functions. Wires the steps in dial.py, hands.py and reading.py together, and keeps the
intermediate results for the debug CLI and for drawing the detected hands over the photo.
"""

import math
from dataclasses import dataclass, replace

import cv2

from watchtiming.dial import (
    MARKER_RADIUS,
    RECTIFIED_RADIUS,
    ColorImage,
    Ellipse,
    GrayImage,
    Point,
    Rectified,
    apply_homography,
    find_dial,
    plausible_center,
    rectified_frame,
    rectify,
    warp_rectified,
)
from watchtiming.hands import (
    MARKER_INNER,
    MARKER_OUTER,
    HandCandidate,
    PivotSearch,
    TwelveRefinement,
    find_pivot,
    measure_hands,
    refine_twelve,
)
from watchtiming.markers import MarkerFit, find_markers, fit_markers
from watchtiming.reading import (
    SECONDS_CONFIDENCE_THRESHOLD,
    Assignment,
    Confidence,
    DialTime,
    UnreadableDialError,
    angles_to_time,
    assign_hands,
    confidence,
    hour_residual_min,
    minute_residual_s,
)

# How far off a tapped 12 o'clock can plausibly be, as an angle (about 20 px on a dial of
# 300 px radius).
TAP_UNCERTAINTY_DEG = 4.0
# The hour markers are trusted for the rectification when they fit their ideal positions this
# well (RMS, as a fraction of the marker radius; marker shapes differ, so not exactly 0).
MAX_MARKER_FIT_ERROR = 0.03
# Markers this clean (sideways RMS, degrees) are used without comparing against the ring-based
# reading; less clean fits (e.g. glare biasing centroids) are compared by confidence.
TRUSTED_MARKER_ANGLE_DEG = 0.3
# How far the hand lines may move the pivot from the marker center (fraction of R).
MAX_PIVOT_SHIFT = 0.04


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
        return (math.degrees(math.atan2(x - px, py - y)) - self.twelve.offset_deg) % 360

    def distance_of(self, photo_point: Point) -> float:
        """Distance from the pivot to a point in the photo, as a fraction of R."""
        x, y = apply_homography(self.rectified.homography, photo_point)
        px, py = self.pivot.pivot
        return math.hypot(x - px, y - py) / self.rectified.radius


@dataclass(frozen=True)
class DialReading:
    ellipse: Ellipse
    marker_fit: MarkerFit | None
    rectified: Rectified
    pivot: PivotSearch
    twelve: TwelveRefinement
    candidates: list[HandCandidate]
    assignment: Assignment
    time: DialTime  # seconds is None when they can't be trusted (never guessed)
    confidence: Confidence
    corrected: bool = False  # the hands were placed by the user

    @property
    def geometry(self) -> DialGeometry:
        return DialGeometry(self.ellipse, self.marker_fit, self.rectified, self.pivot, self.twelve)


class HandsNotFoundError(UnreadableDialError):
    """The dial was located, but its hands couldn't be read. Carries the geometry, so the user
    can still place the hands themselves."""

    def __init__(self, message: str, geometry: DialGeometry):
        super().__init__(message)
        self.geometry = geometry


Rectification = tuple[Rectified, PivotSearch, TwelveRefinement, MarkerFit | None]


def _from_markers(
    gray: GrayImage, ellipse: Ellipse, tap: Point, color: ColorImage | None = None
) -> Rectification | None:
    """Perspective, center and 12 o'clock from the hour markers, if they fit well."""
    center, _ = rectified_frame()
    fit = fit_markers(find_markers(gray, ellipse, tap), center, MARKER_RADIUS * RECTIFIED_RADIUS)
    if fit is None or fit.rms_error > MAX_MARKER_FIT_ERROR:
        return None
    rectified = warp_rectified(gray, fit.homography)
    # The markers fix the dial's center (to a few pixels: marker shapes differ); the hand lines
    # refine it.
    found = find_pivot(
        rectified.image, rectified.center, rectified.radius, rectified_chroma(color, rectified)
    )
    shift = math.hypot(found.pivot[0] - rectified.center[0], found.pivot[1] - rectified.center[1])
    pivot = (
        found
        if found.well_determined and shift <= MAX_PIVOT_SHIFT * rectified.radius
        else PivotSearch(rectified.center, found.lines, well_determined=True)
    )
    return rectified, pivot, TwelveRefinement(0.0, 0.0, True), fit


def _from_ring(
    gray: GrayImage, ellipse: Ellipse, tap: Point, color: ColorImage | None = None
) -> Rectification:
    """Perspective from a ring of the dial plus the pivot (as its center); 12 o'clock from the
    tap, refined by the markers' 12-fold pattern."""
    # Rough pass: correct only the affine part, find the pivot, then use it as the dial
    # center to remove the perspective exactly.
    rough = rectify(gray, ellipse, ellipse.center, tap)
    rough_pivot = find_pivot(
        rough.image, rough.center, rough.radius, rectified_chroma(color, rough)
    )
    center = plausible_center(ellipse, rough.to_photo(rough_pivot.pivot))
    rectified = rectify(gray, ellipse, center, tap)
    pivot = find_pivot(
        rectified.image, rectified.center, rectified.radius, rectified_chroma(color, rectified)
    )
    twelve = refine_twelve(rectified.image, rectified.center, rectified.radius)
    return rectified, pivot, twelve, None


def rectified_chroma(color: ColorImage | None, rectified: Rectified):
    """The rectified dial's color without its brightness (Lab a and b), or None."""
    if color is None:
        return None
    height, width = rectified.image.shape
    warped = cv2.warpPerspective(
        color, rectified.homography, (width, height), flags=cv2.INTER_LINEAR
    )
    return cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)[..., 1:]


def _read(ellipse: Ellipse, r: Rectification, color: ColorImage | None) -> DialReading:
    rectified, pivot, twelve, marker_fit = r
    found = measure_hands(
        rectified.image,
        rectified.center,
        pivot.pivot,
        rectified.radius,
        rectified_chroma(color, rectified),
    )
    candidates = [replace(c, angle=(c.angle - twelve.offset_deg) % 360) for c in found]
    # Without markers, 12 o'clock comes only from the tap, which can be a few degrees off.
    uncertainty = 0.0 if twelve.from_markers else TAP_UNCERTAINTY_DEG
    assignment = assign_hands(candidates, twelve_uncertainty_deg=uncertainty)
    conf = confidence(assignment, pivot.well_determined, twelve.from_markers)
    time = angles_to_time(assignment.hour_angle, assignment.minute_angle, assignment.second_angle)
    if conf.seconds < SECONDS_CONFIDENCE_THRESHOLD:
        # The seconds hand still placed the minute boundary, but its value isn't reported.
        time = replace(time, seconds=None)
    return DialReading(
        ellipse, marker_fit, rectified, pivot, twelve, candidates, assignment, time, conf
    )


def read_dial(gray: GrayImage, tap: Point, color: ColorImage | None = None) -> DialReading:
    """Read the time on a dial. `tap` is the 12 o'clock marker in `gray`'s coordinates. `color`
    (the same image in color, optional) makes colored hands stand out.

    Two ways to undo the perspective: from the hour markers (exact when they're clean; best on
    real dials, whose bezel and case sit above the dial) and from a ring of the dial plus the
    pivot. Clean markers are used directly. When they fit less cleanly (glare can bias their
    centroids), both are read and the more confident reading wins.
    """
    ellipse = find_dial(gray, tap)
    from_markers = _from_markers(gray, ellipse, tap, color)
    trusted = (
        from_markers is not None and from_markers[3].angular_rms_deg <= TRUSTED_MARKER_ANGLE_DEG
    )
    options = [from_markers] if trusted else [from_markers, _from_ring(gray, ellipse, tap, color)]
    rectifications = [r for r in options if r is not None]
    readings: list[DialReading] = []
    error: UnreadableDialError | None = None
    for rectification in rectifications:
        try:
            readings.append(_read(ellipse, rectification, color))
        except UnreadableDialError as e:
            error = e
    if not readings:
        rectified, pivot, twelve, marker_fit = rectifications[0]
        geometry = DialGeometry(ellipse, marker_fit, rectified, pivot, twelve)
        raise HandsNotFoundError(str(error or "No hands were found on the dial."), geometry)
    return max(readings, key=lambda r: (r.confidence.seconds, r.confidence.overall))


def locate_dial(gray: GrayImage, tap: Point, color: ColorImage | None = None) -> DialGeometry:
    """The dial's geometry without reading hands: from the markers when they fit, else a ring."""
    ellipse = find_dial(gray, tap)
    rectification = _from_markers(gray, ellipse, tap, color) or _from_ring(
        gray, ellipse, tap, color
    )
    rectified, pivot, twelve, marker_fit = rectification
    return DialGeometry(ellipse, marker_fit, rectified, pivot, twelve)


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
    time = angles_to_time(h.angle, m.angle, s.angle if s else None)
    g = geometry
    return DialReading(
        g.ellipse, g.marker_fit, g.rectified, g.pivot, g.twelve,
        [c for c in (h, m, s) if c is not None], assignment, time, conf, corrected=True,
    )  # fmt: skip


# --- Overlay: the detected geometry in the photo's coordinates ---------------------------------


@dataclass(frozen=True)
class HandOverlay:
    role: str  # "hour", "minute", "second" or "other" (a candidate that isn't a hand)
    tip: Point


@dataclass(frozen=True)
class Overlay:
    """What the frontend draws over the photo, in the upright original photo's pixels."""

    dial_center: Point
    dial_axes: tuple[float, float]  # semi-major, semi-minor
    dial_angle_deg: float
    pivot: Point
    twelve: Point
    hands: list[HandOverlay]


def photo_overlay(reading: DialReading | DialGeometry, scale: float) -> Overlay:
    """Map the geometry (and the reading's hands, if any) back to the original photo. `scale` is
    processed pixels per original pixel (`Preprocessed.scale`)."""
    geometry = reading.geometry if isinstance(reading, DialReading) else reading
    rect = geometry.rectified

    def to_photo(point: Point) -> Point:
        x, y = rect.to_photo(point)
        return x / scale, y / scale

    def rect_point(origin: Point, angle_deg: float, fraction: float) -> Point:
        a = math.radians(angle_deg)
        r = fraction * rect.radius
        return origin[0] + r * math.sin(a), origin[1] - r * math.cos(a)

    pivot = geometry.pivot.pivot
    hands: list[HandOverlay] = []
    if isinstance(reading, DialReading):
        a = reading.assignment
        roles = {id(a.hour): "hour", id(a.minute): "minute"}
        if a.second is not None:
            roles[id(a.second)] = "second"
        # Candidate angles include the 12 o'clock correction; undo it to draw in the image's frame.
        frame_offset = geometry.twelve.offset_deg + a.rotation_deg
        hands = [
            HandOverlay(
                roles.get(id(c), "other"),
                to_photo(rect_point(pivot, c.angle + frame_offset, c.length)),
            )
            for c in reading.candidates
        ]
    e = geometry.ellipse
    return Overlay(
        dial_center=(e.center[0] / scale, e.center[1] / scale),
        dial_axes=(e.semi_major / scale, e.semi_minor / scale),
        dial_angle_deg=e.angle_deg,
        pivot=to_photo(pivot),
        # Middle of the marker ring, where the user tapped.
        twelve=to_photo(
            rect_point(rect.center, geometry.twelve.offset_deg, (MARKER_INNER + MARKER_OUTER) / 2)
        ),
        hands=hands,
    )
