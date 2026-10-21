"""Hour markers: exact perspective, center and 12 o'clock from the markers themselves, and the
direction of 12 o'clock from the markers' 12-fold pattern when they can't be fitted one by one.

Pure functions: image in, result out. No file system, no framework code.

The markers lie in the dial's own plane, exactly 30° apart around its center. Mapping them to
those positions fixes the perspective, the center, the scale and the direction of 12 o'clock
in one go, without relying on the bezel or case rings (which sit above the dial and shift
against it under an angle: parallax).
"""

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.dial import Ellipse, ransac_ellipse
from watchtiming.geometry import (
    GrayImage,
    Matrix,
    Point,
    angle_diff,
    clock_angle,
    clock_point,
)
from watchtiming.polar import ANGLE_BINS, contrast, unwrap

# Blob areas, as fractions of the dial ring's semi-major axis squared: big enough to exclude
# minute-track ticks and lettering, small enough to exclude the date window.
MIN_AREA, MAX_AREA = 0.003, 0.05
# Markers are searched inside this multiple of the dial ring. Their contrast is taken against
# a median background over this fraction of the ring's semi-major axis (larger than a marker).
SEARCH_EXTENT = 1.3
BACKGROUND_SIZE = 0.3
# RANSAC over blob centroids: the ellipse of markers, and how close a blob must be to it.
RING_ITERATIONS = 400
RING_BAND = 0.05
# The marker ring is concentric with the dial ring: axis ratios within this of each other, and
# centers within this fraction of the dial ring's radius. Looser than the rings' own check
# (dial._concentric): blob centroids are noisier than edge points, and perspective shifts the
# marker ring's center against a bezel ring that sits above the dial.
MAX_RATIO_DIFF = 0.15
MARKER_RING_MAX_SHIFT = 0.15
# The marker ring's size relative to the dial ring, which may be the minute track, the bezel
# or the case.
MARKER_RING_SIZE = (0.3, 1.2)
# A blob counts as the hour it's nearest to only within this angle of it.
ANGLE_TOLERANCE_DEG = 10.0
# When a hand covers the tapped marker (it merges into a hand-shaped blob), the marker ring is
# found without it, but must still pass this close to the tap (fraction of its radius).
TAP_BAND = 0.15
# A blob counts as the tapped marker within this fraction of the dial ring of the tap.
TAP_DISTANCE = 0.12
# Final fit: a marker is an inlier when it lands within this fraction of the marker radius of
# its ideal position. Marker shapes differ (the 12 is often bigger), so this can't be tiny.
INLIER_TOLERANCE = 0.04
MIN_MARKERS = 6


@dataclass(frozen=True)
class Marker:
    hour: int  # 0 = 12 o'clock … 11
    centroid: Point  # in the photo
    area: float


@dataclass(frozen=True)
class MarkerFit:
    homography: Matrix  # photo → rectified (the markers on their ideal circle)
    inliers: list[Marker]
    rms_error: float  # of the inliers after the fit, as a fraction of the marker radius
    # The sideways (angular) part of that error, in degrees. Marker shapes differ in where their
    # centroid sits along the radius (dots, batons, a bigger 12), which is harmless; sideways
    # errors (glare biasing a centroid) rotate the hands' reference.
    angular_rms_deg: float


def ideal_position(center: Point, radius: float, hour: int) -> Point:
    return clock_point(center, hour * 30, radius)


def _blobs(gray: GrayImage, ring: Ellipse) -> list[tuple[Point, float]]:
    """Compact features that stand out from their surroundings (bright or dark), inside the
    dial area: (centroid, area)."""
    a = ring.semi_major
    k = min(255, int(BACKGROUND_SIZE * a) | 1)  # odd (medianBlur), at most 255
    contrast = cv2.absdiff(gray, cv2.medianBlur(gray, k))
    h, w = gray.shape
    ys, xs = np.mgrid[0:h, 0:w]
    inside = (
        ring.normalized_radius(np.column_stack([xs.ravel(), ys.ravel()])).reshape(h, w)
        < SEARCH_EXTENT
    )
    if not inside.any():
        return []
    threshold, _ = cv2.threshold(
        contrast[inside].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    binary = ((contrast > threshold) & inside).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(binary)
    lo, hi = MIN_AREA * a * a, MAX_AREA * a * a
    return [
        ((float(centroids[i][0]), float(centroids[i][1])), float(stats[i, cv2.CC_STAT_AREA]))
        for i in range(1, count)
        if lo <= stats[i, cv2.CC_STAT_AREA] <= hi
    ]


def _concentric_with(e: Ellipse, ring: Ellipse) -> bool:
    """Whether `e` can be a circle of the dial inside `ring`: in the same plane and around the
    same center, so about as elliptic and centered nearby (perspective shifts it a little)."""
    shift = np.hypot(*(np.array(e.center) - np.array(ring.center)))
    return (
        MARKER_RING_SIZE[0] * ring.semi_major < e.semi_major < MARKER_RING_SIZE[1] * ring.semi_major
        and abs(e.semi_minor / e.semi_major - ring.semi_minor / ring.semi_major) < MAX_RATIO_DIFF
        and shift < MARKER_RING_MAX_SHIFT * ring.semi_major
    )


def _marker_ring(
    points: npt.NDArray[np.float64], tap_index: int | None, tap: Point, ring: Ellipse
) -> Ellipse | None:
    """The ellipse through the most blob centroids (RANSAC): through the tapped one, or, when
    no blob is at the tap (a hand covers that marker), passing close to the tap."""
    if tap_index is None:
        # Sample only blobs about as far out as the tap (measured against the dial ring, which
        # has the markers' shape): random picks from all blobs rarely hit five markers.
        tap_radius = ring.normalized_radius(np.array([tap]))[0]
        near = np.abs(ring.normalized_radius(points) - tap_radius) < TAP_BAND * tap_radius
        others = np.flatnonzero(near)
    else:
        others = np.delete(np.arange(len(points)), tap_index)
    if len(others) < 5:
        return None

    def sample(rng: np.random.Generator) -> npt.NDArray[np.intp]:
        if tap_index is None:
            return rng.choice(others, 5, replace=False)
        return np.append(rng.choice(others, 4, replace=False), tap_index)

    def accept(e: Ellipse) -> bool:
        if not _concentric_with(e, ring):
            return False
        return tap_index is not None or abs(e.normalized_radius(np.array([tap]))[0] - 1) <= TAP_BAND

    best, best_count = ransac_ellipse(points, sample, accept, RING_BAND, RING_ITERATIONS)
    if best is None or best_count < MIN_MARKERS:
        return None
    inliers = points[np.abs(best.normalized_radius(points) - 1) < RING_BAND]
    return Ellipse.from_cv(cv2.fitEllipse(inliers.astype(np.float32)))


def _circle_angle(e: Ellipse, point: Point) -> float:
    """Clock-style angle of a point around the ellipse, after squashing the ellipse to a circle
    (an affine approximation; good enough to number the hours)."""
    u = np.array([np.cos(np.radians(e.angle_deg)), np.sin(np.radians(e.angle_deg))])
    v = np.array([-u[1], u[0]])
    d = np.array(point) - e.center
    x, y = (d @ u) / e.semi_major, (d @ v) / e.semi_minor
    # Back to image orientation with equal axes, then clock angle (clockwise from up).
    px, py = x * u + y * v
    return clock_angle(px, py)


def find_markers(gray: GrayImage, ring: Ellipse, tap: Point) -> list[Marker]:
    """The hour markers, numbered from the tapped one (12 o'clock). `ring` is any ellipse
    roughly around the dial; it only sets the search area and the expected marker size.

    A hand often lies over the 12 (at about :00 the minute hand does): then that marker merges
    into the hand's blob and is left out, and the tap itself gives the direction of 12."""
    blobs = _blobs(gray, ring)
    if len(blobs) < MIN_MARKERS:
        return []
    points = np.array([b[0] for b in blobs], np.float64)
    nearest = int(np.argmin(np.hypot(points[:, 0] - tap[0], points[:, 1] - tap[1])))
    tapped = np.hypot(*(points[nearest] - tap)) <= TAP_DISTANCE * ring.semi_major
    tap_index = nearest if tapped else None
    marker_ring = _marker_ring(points, tap_index, tap, ring)
    if marker_ring is None:
        return []

    twelve = _circle_angle(marker_ring, blobs[nearest][0] if tapped else tap)
    by_hour: dict[int, tuple[float, Marker]] = {}
    for (xy, area), p in zip(blobs, points, strict=True):
        if abs(marker_ring.normalized_radius(p)[0] - 1) >= RING_BAND:
            continue
        offset = (_circle_angle(marker_ring, xy) - twelve) % 360
        hour = round(offset / 30) % 12
        miss = angle_diff(offset, hour * 30)
        if miss < ANGLE_TOLERANCE_DEG and (hour not in by_hour or miss < by_hour[hour][0]):
            by_hour[hour] = (miss, Marker(hour, xy, area))
    return [m for _, m in sorted(by_hour.values(), key=lambda t: t[1].hour)]


def fit_markers(markers: list[Marker], center: Point, marker_radius: float) -> MarkerFit | None:
    """The photo → rectified homography putting each marker at its hour on a circle of
    `marker_radius` around `center`, or None without enough consistent markers around the dial."""
    if len(markers) < MIN_MARKERS:
        return None
    src = np.array([m.centroid for m in markers], np.float64)
    dst = np.array([ideal_position(center, marker_radius, m.hour) for m in markers], np.float64)
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, INLIER_TOLERANCE * marker_radius)
    if h is None or mask is None:
        return None
    inliers = [m for m, ok in zip(markers, mask.ravel(), strict=True) if ok]
    if len(inliers) < MIN_MARKERS or len({m.hour // 3 for m in inliers}) < 3:
        return None
    projected = cv2.perspectiveTransform(
        np.array([m.centroid for m in inliers], np.float64).reshape(-1, 1, 2), h
    ).reshape(-1, 2)
    ideal = np.array([ideal_position(center, marker_radius, m.hour) for m in inliers])
    rms = float(np.sqrt(((projected - ideal) ** 2).sum(axis=1).mean()) / marker_radius)
    outward = (ideal - center) / marker_radius
    sideways = np.column_stack([-outward[:, 1], outward[:, 0]])
    angular = np.degrees(((projected - ideal) * sideways).sum(axis=1) / marker_radius)
    return MarkerFit(h, inliers, rms, float(np.sqrt((angular**2).mean())))


# --- 12 o'clock from the markers' 12-fold pattern ----------------------------------------------

# Ring (fraction of R) where hour markers usually sit, outside the hands area.
MARKER_INNER, MARKER_OUTER = 0.84, 0.98
# How much stronger the 12-fold pattern must be than its neighboring frequencies (10, 11, 13 and
# 14 per turn) to trust the markers over the tap. Markers: much stronger. One isolated feature
# (a hand tip): about equal, because a single spike has every frequency. Neighbors rather than
# all lower frequencies, so uneven lighting (low frequencies) doesn't mask the markers.
MIN_MARKER_PERIODICITY = 3.0


@dataclass(frozen=True)
class TwelveRefinement:
    offset_deg: float  # where the markers put 12 o'clock, relative to the tap's direction
    periodicity: float  # 12-fold strength / mean strength of frequencies 10, 11, 13, 14
    from_markers: bool  # False: no clear markers, the tap's direction is used as-is


def refine_twelve(image: GrayImage, dial_center: Point, radius: float) -> TwelveRefinement:
    """Exact direction of 12 o'clock from the hour markers.

    The tap only picks which marker is 12; its exact angle comes from all 12 markers at once:
    the phase of the ring's 12-fold pattern (circular mean of 12·θ). Assumes the markers sit
    every 30°, as on almost all dials.
    """
    bins = ANGLE_BINS
    polar = contrast(unwrap(image, dial_center, MARKER_OUTER * radius, bins))
    profile = polar[:, int(MARKER_INNER * radius) :].sum(axis=1, dtype=np.float64)
    spectrum = np.fft.fft(profile)
    harmonic = np.conj(spectrum[12])  # Σ p(θ)·e^{+12iθ}
    others = float(np.abs(spectrum[[10, 11, 13, 14]]).mean())
    periodicity = float(abs(harmonic) / others) if others > 0 else 0.0
    if periodicity < MIN_MARKER_PERIODICITY:
        return TwelveRefinement(0.0, periodicity, False)
    offset = float(np.degrees(np.angle(harmonic)) / 12)  # in (−15°, 15°]
    return TwelveRefinement(offset, periodicity, True)
