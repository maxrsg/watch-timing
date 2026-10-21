"""Steps 1–2 of the pipeline: preprocessing (orientation, grayscale, downscale), the dial's
concentric rings, and the ring-based perspective rectification.

Pure functions: image in, result out. No file system, no framework code.
"""

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.geometry import (
    ColorImage,
    GrayImage,
    Matrix,
    Point,
    apply_homography,
    clock_angle,
)
from watchtiming.imaging import (
    TRANSPOSED_ORIENTATIONS,
    open_image,
    orientation,
    read_exif,
    upright_rgb,
)

# Long side of the image the CV pipeline works on. Enough for ±0.2 s seconds-hand precision
# on a dial that fills a good part of the frame, and keeps every stage fast.
PROCESS_LONG_SIDE = 1000


@dataclass(frozen=True)
class Preprocessed:
    gray: GrayImage
    color: ColorImage  # the same pixels in color: colored hands can be faint in gray
    # Processed pixels per pixel of the upright original. Maps points the user tapped on the
    # (upright) photo into processed coordinates: processed = original * scale.
    scale: float
    # (width, height) of the upright original, after EXIF orientation.
    original_size: tuple[int, int]


def preprocess(data: bytes, long_side: int = PROCESS_LONG_SIDE) -> Preprocessed:
    """Decode image bytes → upright grayscale and color, downscaled to `long_side` (never
    upscaled)."""
    with open_image(data) as img:
        turn = orientation(read_exif(img))
        width, height = img.size
        if turn in TRANSPOSED_ORIENTATIONS:
            width, height = height, width
        if img.format == "JPEG":
            # Let the JPEG decoder skip detail we would throw away anyway (scales by 1/2^n,
            # never below the requested size).
            img.draft("RGB", (long_side, long_side))
        upright = upright_rgb(img, turn)

    color = cv2.cvtColor(np.asarray(upright, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    factor = long_side / max(color.shape[:2])
    if factor < 1:
        size = (round(color.shape[1] * factor), round(color.shape[0] * factor))
        color = cv2.resize(color, size, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    return Preprocessed(
        gray=gray, color=color, scale=gray.shape[1] / width, original_size=(width, height)
    )


# --- Step 2: dial edge as an ellipse ---------------------------------------------------------

# Minor/major axis ratio: below this the dial is tilted more than ~65° and unreadable anyway.
MIN_AXIS_RATIO = 0.4
# The rough circle (Hough) must have a radius of at least this fraction of the image's short
# side, and at most this fraction.
MIN_DIAL_FRACTION, MAX_DIAL_FRACTION = 0.15, 0.75
# Concentric rings: histogram resolution and the band of normalized radii searched around the
# rough circle (dial edge, minute track, rehaut, bezel, case all show up as rings).
RING_BIN = 0.004
RING_RANGE = (0.4, 1.5)
# A ring's edge points must lie within this fraction of its radius, cover this share of its
# circumference, and number at least this many.
RING_INLIER_BAND = 0.006
MIN_RING_COVERAGE = 0.55
MIN_RING_POINTS = 60
# The seed shape (`_seed_shape`): edge radii between these multiples of the rough circle's, in
# sectors of SEED_SECTOR_DEG, the SEED_PEAKS strongest 1-px radii per sector that have at least
# SEED_MIN_VOTES edge points; at least SEED_MIN_CANDIDATES candidates overall, and a RANSAC
# inlier band of SEED_BAND (normalized radius) over them.
SEED_RANGE = (0.6, 1.4)
SEED_SECTOR_DEG = 5
SEED_PEAKS = 3
SEED_MIN_VOTES = 3
SEED_MIN_CANDIDATES = 12
SEED_BAND = 0.015
# Rings of one dial share the seed shape's center (within this fraction of its semi-major
# axis) and axis ratio (within this); two rings whose sizes differ less than RING_SAME are one.
CONCENTRIC_SHIFT = 0.03
CONCENTRIC_RATIO = 0.03
RING_SAME = 0.01


class DialNotFoundError(ValueError):
    """No dial edge could be found around the tapped 12 o'clock point."""


@dataclass(frozen=True)
class Ellipse:
    center: Point
    semi_major: float
    semi_minor: float
    angle_deg: float  # direction of the major axis, image coordinates

    @classmethod
    def from_cv(cls, box: tuple[Point, Point, float]) -> "Ellipse":
        (cx, cy), (w, h), angle = box
        if w >= h:
            return cls((cx, cy), w / 2, h / 2, angle)
        return cls((cx, cy), h / 2, w / 2, angle + 90)

    def _axes(self) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        a = np.radians(self.angle_deg)
        return np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])

    def normalized_radius(self, points: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """1 on the ellipse, < 1 inside, > 1 outside."""
        d = np.asarray(points, np.float64).reshape(-1, 2) - self.center
        u, v = self._axes()
        return np.hypot(d @ u / self.semi_major, d @ v / self.semi_minor)

    def conic(self) -> Matrix:
        """Symmetric 3×3 C with xᵀ C x = 0 on the ellipse (homogeneous x)."""
        u, v = self._axes()
        m = np.outer(u, u) / self.semi_major**2 + np.outer(v, v) / self.semi_minor**2
        c = np.array(self.center)
        conic = np.zeros((3, 3))
        conic[:2, :2] = m
        conic[:2, 2] = conic[2, :2] = -m @ c
        conic[2, 2] = c @ m @ c - 1
        return conic


def edge_map(gray: GrayImage) -> GrayImage:
    """Canny with thresholds from the image's own edge strengths (not its brightness), so blur
    and low contrast lower the thresholds along with the edges."""
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.5)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1)
    strongest = float(np.percentile(cv2.magnitude(gx, gy), 99))
    high = max(20.0, 0.5 * strongest)
    return cv2.Canny(blurred, 0.4 * high, high, L2gradient=True)


def _arc_coverage(ellipse: Ellipse, points: npt.NDArray[np.float64], bins: int = 36) -> float:
    d = points - ellipse.center
    u, v = ellipse._axes()
    t = np.arctan2(d @ v / ellipse.semi_minor, d @ u / ellipse.semi_major)
    filled = np.unique(((t + np.pi) / (2 * np.pi) * bins).astype(int) % bins)
    return len(filled) / bins


@dataclass(frozen=True)
class Ring:
    """One elliptical edge concentric with the dial (dial edge, minute track, bezel, case…)."""

    ellipse: Ellipse
    support: int  # edge points on it
    coverage: float  # 0–1 share of its circumference with edge points


def _robust_ellipse(
    points: npt.NDArray[np.float64], band: float, start: Ellipse | None = None, rounds: int = 4
) -> Ellipse | None:
    """Keep the points near the current ellipse, refit, tightening the band each round. Starts
    from `start`, or from a plain fit of all points."""
    if len(points) < 5:
        return None
    ellipse = start or Ellipse.from_cv(cv2.fitEllipse(points.astype(np.float32)))
    for _ in range(rounds):
        keep = points[np.abs(ellipse.normalized_radius(points) - 1) < band]
        if len(keep) < MIN_RING_POINTS:
            return None
        ellipse = Ellipse.from_cv(cv2.fitEllipse(keep.astype(np.float32)))
        band = max(band * 0.6, RING_INLIER_BAND)
    return ellipse


def ransac_ellipse(
    pool: npt.NDArray[np.float64],
    sample: Callable[[np.random.Generator], npt.NDArray[np.intp]],
    accept: Callable[[Ellipse], bool],
    band: float,
    iterations: int,
) -> tuple[Ellipse | None, int]:
    """The ellipse through the most points of `pool` (within `band` of normalized radius 1):
    fitted to `sample(rng)` indices each round, skipping ellipses `accept` rejects. Returns the
    best and its inlier count. Deterministic: the random sampling is seeded."""
    rng = np.random.default_rng(0)
    best, best_count = None, 0
    for _ in range(iterations):
        try:
            e = Ellipse.from_cv(cv2.fitEllipse(pool[sample(rng)].astype(np.float32)))
        except cv2.error:
            continue
        if not accept(e):
            continue
        count = int((np.abs(e.normalized_radius(pool) - 1) < band).sum())
        if count > best_count:
            best, best_count = e, count
    return best, best_count


def _rough_circle(gray: GrayImage, tap: Point) -> tuple[Point, float] | None:
    """Median of the strongest Hough circles that have the tap inside: a rough dial center and
    radius. Robust to the many concentric edges of a real watch."""
    short = min(gray.shape)
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(gray, (0, 0), 2), cv2.HOUGH_GRADIENT, dp=1.5, minDist=10,
        param1=80, param2=40,
        minRadius=int(MIN_DIAL_FRACTION * short), maxRadius=int(MAX_DIAL_FRACTION * short),
    )  # fmt: skip
    if circles is None:
        return None
    around_tap = [
        c for c in circles[0][:15] if 0.3 < np.hypot(tap[0] - c[0], tap[1] - c[1]) / c[2] < 1.0
    ]
    if not around_tap:
        return None
    cx, cy, r = np.median(np.array(around_tap), axis=0)
    return (float(cx), float(cy)), float(r)


def _seed_shape(
    points: npt.NDArray[np.float64], center: Point, r0: float, iterations: int = 400
) -> Ellipse | None:
    """One ring's ellipse, robustly: in every sector the strongest edge radii around the rough
    center, then RANSAC over those few candidates (most sectors agree on the dominant ring).
    Deterministic: the random sampling is seeded."""
    d = points - center
    r = np.hypot(d[:, 0], d[:, 1])
    theta = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 360  # math angle: only bins sectors
    lo, hi = SEED_RANGE[0] * r0, SEED_RANGE[1] * r0
    in_band = (r > lo) & (r < hi)
    candidates = []
    for sector in range(0, 360, SEED_SECTOR_DEG):
        mask = in_band & (theta >= sector) & (theta < sector + SEED_SECTOR_DEG)
        if mask.sum() < SEED_MIN_VOTES:
            continue
        hist, edges = np.histogram(r[mask], bins=np.arange(lo, hi, 1.0))
        for i in np.argsort(hist)[::-1][:SEED_PEAKS]:
            if hist[i] < SEED_MIN_VOTES:
                break
            rho = (edges[i] + edges[i + 1]) / 2
            a = np.radians(sector + SEED_SECTOR_DEG / 2)
            candidates.append((center[0] + rho * np.cos(a), center[1] + rho * np.sin(a)))
    if len(candidates) < SEED_MIN_CANDIDATES:
        return None
    pool = np.array(candidates, np.float64)

    def plausible(e: Ellipse) -> bool:
        return 0.5 * r0 < e.semi_major < 1.5 * r0 and e.semi_minor / e.semi_major >= MIN_AXIS_RATIO

    best, _ = ransac_ellipse(
        pool,
        lambda rng: rng.choice(len(pool), 5, replace=False),
        plausible,
        band=SEED_BAND,
        iterations=iterations,
    )
    if best is None:
        return None
    return _robust_ellipse(points, band=0.02, start=best)


def dial_rings(gray: GrayImage, tap: Point) -> list[Ring]:
    """Elliptical edges concentric with the dial around the tap, best supported first.

    Real dials rarely have one clean closed edge: ticks, the rehaut and the bezel touch it, so
    contours break up. Instead: a rough circle (Hough), one ring's shape found robustly
    (`_seed_shape`), then the edge points' radii under that shape separate the concentric
    rings, and each is fitted starting from a scaled copy of the shape.
    """
    rough = _rough_circle(gray, tap)
    if rough is None:
        return []
    center, r0 = rough
    ys, xs = np.nonzero(edge_map(gray))
    points = np.column_stack([xs, ys]).astype(np.float64)
    shape = _seed_shape(points, center, r0)
    if shape is None:
        return []

    # Under the shape's (tilted) metric, concentric rings have constant normalized radius.
    radius = shape.normalized_radius(points)
    bins = np.arange(RING_RANGE[0], RING_RANGE[1], RING_BIN)
    hist, _ = np.histogram(radius, bins=bins)
    smooth = np.convolve(hist, np.ones(3) / 3, mode="same")
    rings: list[Ring] = []
    for i in range(1, len(smooth) - 1):
        is_peak = smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1]
        if not is_peak or smooth[i] < 0.25 * smooth.max():
            continue
        rho = (bins[i] + bins[i + 1]) / 2
        seed = Ellipse(
            shape.center, shape.semi_major * rho, shape.semi_minor * rho, shape.angle_deg
        )
        ellipse = _robust_ellipse(points[np.abs(radius - rho) < 0.02], band=0.01, start=seed)
        if ellipse is None or not _concentric(ellipse, shape):
            continue
        inliers = points[np.abs(ellipse.normalized_radius(points) - 1) < RING_INLIER_BAND]
        coverage = _arc_coverage(ellipse, inliers)
        if coverage >= MIN_RING_COVERAGE and not any(_same_ring(ellipse, r.ellipse) for r in rings):
            rings.append(Ring(ellipse, len(inliers), coverage))
    return sorted(rings, key=lambda ring: ring.support * ring.coverage, reverse=True)


def _concentric(e: Ellipse, shape: Ellipse) -> bool:
    """Same center and the same tilt (axis ratio) as the shape: a ring of the same dial."""
    offset = np.hypot(e.center[0] - shape.center[0], e.center[1] - shape.center[1])
    ratio = (e.semi_minor / e.semi_major) - (shape.semi_minor / shape.semi_major)
    return offset < CONCENTRIC_SHIFT * shape.semi_major and abs(ratio) < CONCENTRIC_RATIO


def _same_ring(a: Ellipse, b: Ellipse) -> bool:
    return abs(a.semi_major / b.semi_major - 1) < RING_SAME


def find_dial(gray: GrayImage, tap: Point) -> Ellipse:
    """An ellipse concentric with the dial, for the perspective correction: the best-supported
    ring around the tapped 12 o'clock. Which ring (dial edge, minute track, bezel) doesn't
    matter for the perspective; the scale comes from the tap (see `Rectified.marker_radius`)."""
    rings = dial_rings(gray, tap)
    if not rings:
        raise DialNotFoundError(
            "Couldn't find the dial's edge around the tapped 12 o'clock. Fill more of the "
            "frame with the watch and avoid strong reflections."
        )
    return rings[0].ellipse


# --- Step 2b: perspective rectification ------------------------------------------------------

# Radius of the dial in the rectified image, in pixels. 400 px puts one second of the seconds
# hand (6°) at ~40 px along the rim.
RECTIFIED_RADIUS = 400
RECTIFIED_MARGIN = 1.15
# The scale of the rectified dial comes from the tapped 12 o'clock marker, not from the ellipse
# (which may be the bezel or the minute track): the marker lands at this fraction of the
# nominal dial radius. Hand and marker bands downstream are fractions of that radius.
MARKER_RADIUS = 0.9


@dataclass(frozen=True)
class Rectified:
    image: GrayImage
    homography: Matrix  # photo → rectified
    center: Point  # dial center in the rectified image
    radius: float  # dial radius in the rectified image

    def to_photo(self, point: Point) -> Point:
        return apply_homography(np.linalg.inv(self.homography), point)


def _rotate_clockwise(angle: float) -> Matrix:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def rectifying_homography(
    ellipse: Ellipse, center: Point, tap: Point, radius: float = RECTIFIED_RADIUS
) -> tuple[Matrix, float]:
    """Photo → rectified dial: a circle of `radius` around the origin, 12 o'clock at the top.

    `center` is where the dial's center appears in the photo. Under perspective that is not the
    ellipse's center; its polar line with respect to the ellipse is the image of the line at
    infinity, so mapping that line back to infinity removes the perspective exactly. With the
    ellipse center instead, only the affine part is corrected.
    Returns (homography, how far `center` lands from the circle's center, in rectified pixels).
    """
    # Normalize coordinates for conditioning: ellipse center at the origin, semi-major = 1.
    s = 1 / ellipse.semi_major
    cx, cy = ellipse.center
    norm = np.array([[s, 0, -s * cx], [0, s, -s * cy], [0, 0, 1]])
    norm_inv = np.linalg.inv(norm)
    conic = norm_inv.T @ ellipse.conic() @ norm_inv
    c = norm @ np.array([center[0], center[1], 1.0])

    # Projective part: send the polar of the center (image of the line at infinity) to infinity.
    line = conic @ c
    line = line / line[2]
    projective = np.array([[1, 0, 0], [0, 1, 0], [line[0], line[1], 1.0]])
    p_inv = np.linalg.inv(projective)
    conic = p_inv.T @ conic @ p_inv

    # Affine part: the conic is now an ellipse (x−x0)ᵀ M (x−x0) = 1; M^½ maps it to the unit circle.
    a, b, k = conic[:2, :2], conic[:2, 2], conic[2, 2]
    x0 = -np.linalg.solve(a, b)
    # (x−x0)ᵀ A (x−x0) = −(b·x0 + k), so M = A / −(b·x0 + k); any overall sign of the conic cancels.
    scale = float(b @ x0 + k)
    m = a / -scale
    evals, evecs = np.linalg.eigh(m)
    root = evecs @ np.diag(np.sqrt(evals)) @ evecs.T
    affine = np.eye(3)
    affine[:2, :2] = radius * root
    affine[:2, 2] = -radius * root @ x0

    to_circle = affine @ projective @ norm
    # Rotate so the tapped 12 o'clock is straight up.
    tap_r = apply_homography(to_circle, tap)
    h = _rotate_clockwise(-np.radians(clock_angle(*tap_r))) @ to_circle
    h = h / h[2, 2]
    miss = float(np.hypot(*apply_homography(h, center)))
    return h, miss


# Under perspective, the dial center's image moves away from the ellipse center by at most about
# this fraction of sqrt(semi_major² − semi_minor²) (measured: ≤ 0.3 for a phone held at one dial
# diameter). A head-on dial (circle) allows no offset at all.
MAX_CENTER_SHIFT = 0.4


def plausible_center(ellipse: Ellipse, center: Point) -> Point:
    """Clamp a dial-center estimate (e.g. the pivot) to the offset the dial's tilt allows.

    One ellipse and one point can't tell a tilted dial with a centered pivot from a head-on dial
    with an off-center pivot. Watch pivots are centered, so the pivot is used as the dial
    center, but only as far as the ellipse's shape makes that offset possible.
    """
    a, b = ellipse.semi_major, ellipse.semi_minor
    limit = MAX_CENTER_SHIFT * float(np.sqrt(max(a * a - b * b, 0.0)))
    offset = np.array(center) - ellipse.center
    length = float(np.hypot(*offset))
    if length <= limit:
        return center
    clamped = np.array(ellipse.center) + offset * (limit / length)
    return float(clamped[0]), float(clamped[1])


def rectify(
    gray: GrayImage, ellipse: Ellipse, center: Point, tap: Point, radius: float = RECTIFIED_RADIUS
) -> Rectified:
    """Warp the dial upright and round, scaled so the tapped marker is at MARKER_RADIUS."""
    unit, _ = rectifying_homography(ellipse, center, tap, 1.0)
    tap_distance = float(np.hypot(*apply_homography(unit, tap)))  # in ellipse radii
    if tap_distance <= 0:
        raise DialNotFoundError("The tapped 12 o'clock is at the dial's center.")
    scale = MARKER_RADIUS * radius / tap_distance
    h = np.diag([scale, scale, 1.0]) @ unit
    half = radius * RECTIFIED_MARGIN
    shift = np.array([[1, 0, half], [0, 1, half], [0, 0, 1.0]])
    size = int(round(2 * half))
    h = shift @ h
    image = cv2.warpPerspective(gray, h, (size, size), flags=cv2.INTER_LINEAR)
    return Rectified(image=image, homography=h, center=(half, half), radius=radius)


def rectified_frame(radius: float = RECTIFIED_RADIUS) -> tuple[Point, int]:
    """Center and size of the rectified image for a dial of `radius`."""
    half = radius * RECTIFIED_MARGIN
    return (half, half), int(round(2 * half))


def warp_rectified(gray: GrayImage, h: Matrix, radius: float = RECTIFIED_RADIUS) -> Rectified:
    """A Rectified from a photo → rectified homography that already targets `rectified_frame`."""
    center, size = rectified_frame(radius)
    image = cv2.warpPerspective(gray, h, (size, size), flags=cv2.INTER_LINEAR)
    return Rectified(image=image, homography=h, center=center, radius=radius)
