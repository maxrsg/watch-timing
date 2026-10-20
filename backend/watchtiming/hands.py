"""Hands: polar unwrap, per-angle profiles and the pivot. Steps 4–6 of the pipeline.

Pure functions: image in, result out. No file system, no framework code.

Angles are clock angles: degrees clockwise from 12 o'clock in the rectified dial.
"""

import itertools
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.dial import GrayImage, Point

Profile = npt.NDArray[np.float64]

# Angular resolution of the polar unwrap: 0.25° per row (the seconds hand moves 6°/s).
ANGLE_BINS = 1440
# Radii (fraction of the dial radius) used for the hands. The outer ring with the hour
# markers starts around 0.84 R on most dials and is left out.
HANDS_INNER, HANDS_OUTER = 0.15, 0.82


def unwrap(image: GrayImage, center: Point, max_radius: float, angle_bins: int = ANGLE_BINS):
    """Polar image: row i = clock angle i·360/angle_bins, column j = radius j (pixels)."""
    radial_bins = max(1, int(round(max_radius)))
    polar = cv2.warpPolar(
        image, (radial_bins, angle_bins), center, max_radius,
        cv2.INTER_LINEAR + cv2.WARP_POLAR_LINEAR,
    )  # fmt: skip
    # OpenCV's row 0 points along +x (3 o'clock); clock angle 0 is 12 o'clock, 90° earlier.
    return np.roll(polar, angle_bins // 4, axis=0)


def inside_hands_area(image: npt.NDArray[np.uint8], dial_center: Point, radius: float):
    """Copy of `image` with everything beyond HANDS_OUTER·radius from the dial center (the
    marker ring and beyond) replaced by the dial's median gray. The ring is defined around the
    dial center, so it stays excluded when a polar unwrap is centered elsewhere (the pivot)."""
    mask = np.zeros(image.shape, np.uint8)
    c = (int(round(dial_center[0])), int(round(dial_center[1])))
    cv2.circle(mask, c, int(HANDS_OUTER * radius), 255, -1)
    out = image.copy()
    out[mask == 0] = np.median(image[mask > 0], axis=0).astype(np.uint8)  # per channel
    return out


# Weight of color differences (Lab a, b) against brightness differences in `contrast`.
CHROMA_WEIGHT = 1.0


def contrast(
    polar: npt.NDArray[np.uint8], chroma: npt.NDArray[np.uint8] | None = None
) -> npt.NDArray[np.float32]:
    """|pixel − its ring's median|: hands stand out whether they are darker or lighter than
    the dial. With `chroma` (the polar Lab a and b channels), the distance includes color, so a
    red hand on a black dial stands out although it's barely brighter."""
    p = polar.astype(np.float32)
    if chroma is None:
        return np.abs(p - np.median(p, axis=0, keepdims=True))
    q = chroma.astype(np.float32)
    squared = (p - np.median(p, axis=0, keepdims=True)) ** 2
    squared += CHROMA_WEIGHT * ((q - np.median(q, axis=0, keepdims=True)) ** 2).sum(axis=-1)
    return np.sqrt(squared)


# --- Step 4: the pivot -------------------------------------------------------------------------

# Pivot search: hands are traced with these tolerances (pixels) in turn, loose while the
# estimate may be far off. Their centerlines are fitted from PIVOT_LINE_INNER of R outward
# (clear of the cap and where hands cross), for traces at least PIVOT_MIN_LENGTH long. A line
# missing the common point by more than PIVOT_OUTLIER_PX (or twice the median miss) is dropped.
PIVOT_TOLERANCES_PX = (16.0, 8.0, 4.0)
PIVOT_LINE_INNER = 0.25
PIVOT_MIN_LENGTH = 0.35
PIVOT_OUTLIER_PX = 3.0
# Hands whose directions differ less than this (mod 180°) can't locate the pivot together.
MIN_LINE_SPREAD_DEG = 8.0


@dataclass(frozen=True)
class HandLine:
    point: npt.NDArray[np.float64]  # a point on the centerline (image coordinates)
    direction: npt.NDArray[np.float64]  # unit vector
    weight: float  # 1 / variance of the line's position across the pivot (pixels⁻²)


@dataclass(frozen=True)
class PivotSearch:
    pivot: Point
    lines: list[HandLine]
    # False when the hands lie along a single line: the pivot is then only located across it.
    well_determined: bool


def _peaks(profile: Profile, min_separation: int, min_fraction: float) -> list[int]:
    """Indices of circular local maxima (the highest point within ±min_separation), strongest
    first. A flat-topped peak (a wide hand) counts once."""
    n = len(profile)
    order = np.argsort(profile)[::-1]
    floor = min_fraction * profile[order[0]]
    peaks: list[int] = []
    for i in order:
        if profile[i] < floor:
            break
        neighborhood = profile[np.arange(i - min_separation, i + min_separation + 1) % n]
        is_local_max = profile[i] >= neighborhood.max()
        if is_local_max and all(min(abs(i - j), n - abs(i - j)) >= min_separation for j in peaks):
            peaks.append(int(i))
    return peaks


def _smooth(profile: Profile, width: int) -> Profile:
    kernel = np.ones(width) / width
    padded = np.concatenate([profile[-width:], profile, profile[:width]])
    return np.convolve(padded, kernel, mode="same")[width:-width]


def _pivot_precision(pts, wts, mean, direction, pivot: Point) -> float:
    """1 / variance of where a fitted line passes the pivot. A short hand's line, extrapolated
    far back to the pivot, is much less certain than a long one's (linear-regression variance:
    σ²·(1/n + d²/Σt²), with d the distance from the fit's center to the pivot)."""
    normal = np.array([-direction[1], direction[0]])
    t = (pts - mean) @ direction
    residual = (pts - mean) @ normal
    n_eff = wts.sum() ** 2 / (wts**2).sum()
    sigma2 = max(float(np.average(residual**2, weights=wts)), 0.05**2)
    spread = float(np.average(t**2, weights=wts)) * n_eff
    d = float((np.array(pivot) - mean) @ direction)
    return 1.0 / (sigma2 * (1 / n_eff + d * d / max(spread, 1e-9)))


def _intersect(lines: list[HandLine]) -> npt.NDArray[np.float64]:
    """Point minimizing the weighted squared distances to all lines."""
    a = np.zeros((2, 2))
    b = np.zeros(2)
    for line in lines:
        n = np.array([-line.direction[1], line.direction[0]])
        a += line.weight * np.outer(n, n)
        b += line.weight * np.outer(n, n) @ line.point
    return np.linalg.solve(a, b)


def _spread_deg(lines: list[HandLine]) -> float:
    """Largest angle between any two line directions, mod 180°."""
    angles = [np.degrees(np.arctan2(line.direction[1], line.direction[0])) % 180 for line in lines]
    return max(
        (min(abs(a - b), 180 - abs(a - b)) for i, a in enumerate(angles) for b in angles[i + 1 :]),
        default=0.0,
    )


def _hand_line(ev: "BarEvidence", t: "HandTrace", pivot: Point, radius: float) -> HandLine | None:
    """A straight centerline through a traced hand, in image coordinates."""
    per_deg = ANGLE_BINS / 360
    keep = t.radii >= PIVOT_LINE_INNER * radius
    if keep.sum() < 8:
        return None
    points, weights = [], []
    for j, r in zip(t.rows[keep], t.radii[keep], strict=True):
        angle, weight = _center_deg(ev, int(j), int(r), per_deg)
        a = np.radians(angle)
        points.append((pivot[0] + r * np.sin(a), pivot[1] - r * np.cos(a)))
        weights.append(max(weight, 1e-6))
    pts, wts = np.array(points), np.array(weights)
    mean = (pts * wts[:, None]).sum(0) / wts.sum()
    cov = ((pts - mean).T * wts) @ (pts - mean) / wts.sum()
    direction = np.linalg.eigh(cov)[1][:, 1]
    return HandLine(mean, direction, _pivot_precision(pts, wts, mean, direction, pivot))


def _distance(line: HandLine, point: npt.NDArray[np.float64]) -> float:
    normal = np.array([-line.direction[1], line.direction[0]])
    return abs(float(normal @ (point - line.point)))


def find_pivot(
    image: GrayImage,
    start: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None = None,
) -> PivotSearch:
    """Where the hand centerlines meet (step 4). `start` is the dial center of the (roughly)
    rectified image and `radius` its dial radius.

    Works in any projectively distorted view of the dial, because a homography keeps the hands
    straight lines through the pivot. The hands are traced as bars (as for the candidates),
    first loosely (the estimate can be far off), then tightly around the improving estimate.
    When the hands are (nearly) parallel, the pivot is taken as the point on their line closest
    to `start`.
    """
    pivot = np.array(start, np.float64)
    lines: list[HandLine] = []
    well_determined = False
    for tolerance in PIVOT_TOLERANCES_PX:
        p = (float(pivot[0]), float(pivot[1]))
        ev, traces = hand_traces(image, start, p, radius, chroma, tolerance)
        lines = [
            line
            for t in traces
            if t.end >= PIVOT_MIN_LENGTH * radius and (line := _hand_line(ev, t, p, radius))
        ]
        if not lines:
            break
        well_determined = len(lines) >= 2 and _spread_deg(lines) >= MIN_LINE_SPREAD_DEG
        if well_determined:
            pivot = _intersect(lines)
            # Drop lines that miss the common point (lettering, a dial edge), then refit.
            misses = [_distance(line, pivot) for line in lines]
            limit = max(PIVOT_OUTLIER_PX, 2 * float(np.median(misses)))
            kept = [line for line, miss in zip(lines, misses, strict=True) if miss <= limit]
            if len(kept) >= 2 and _spread_deg(kept) >= MIN_LINE_SPREAD_DEG:
                lines = kept
                pivot = _intersect(lines)
        else:
            line = max(lines, key=lambda line: line.weight)
            pivot = line.point + ((pivot - line.point) @ line.direction) * line.direction
    return PivotSearch((float(pivot[0]), float(pivot[1])), lines, well_determined)


# --- Steps 5–6: hand candidates ----------------------------------------------------------------
#
# A hand is a straight bar on a ray through the pivot: in the polar image around the pivot it is
# a band at one angle, with a rising edge on one side and a falling edge on the other, starting
# near the pivot and keeping a steady (or tapering) width out to its tip. Contrast summed per
# angle can't tell that from lettering or a date window, which add contrast too; bar evidence
# (both edges present, at a matching width) along an unbroken run from the pivot can.

# Peaks closer than this are one candidate (overlapping hands give fewer peaks than hands).
MIN_HAND_SEPARATION_DEG = 3.0
# Radius (fraction of R) where hand widths are compared: clear of the cap, inside the hour
# hand's length on most watches.
WIDTH_RADIUS = 0.35
# Candidates shorter than this are tails (e.g. the seconds hand's counterweight) or noise.
MIN_HAND_LENGTH = 0.3
# The image is smoothed by this much (pixels) before taking gradients.
SMOOTH_PX = 1.0
# Bar half-widths tried at every point (fractions of R): from a thin seconds hand to a wide
# sword hand.
HALF_WIDTHS = tuple(float(w) for w in np.geomspace(0.0025, 0.09, 12))
# A point is part of a bar when its evidence is NOISE_K times the ring's typical evidence and
# above MIN_EVIDENCE (gray levels per pixel; flat synthetic dials have no noise at all). Typical:
# the NOISE_PERCENTILE of the ring. Hands cover far less than a quarter of any ring, and most
# of the plain dial has no bar evidence at all (its median is 0), so a median says nothing.
NOISE_K = 4.0
NOISE_PERCENTILE = 75
MIN_EVIDENCE = 1.0
# Seeds: peaks of the evidence summed over these radii (fractions of R), down to this fraction
# of the strongest. Near the pivot (where only hands are) and further out (a thin hand whose
# inner part is covered by a wider one).
SEED_BANDS = ((HANDS_INNER, 0.35), (0.45, HANDS_OUTER))
MIN_SEED_FRACTION = 0.04
SEED_SMOOTHING_DEG = (1.0, 4.0)
# Tracing a seed outward: the bar's center may wander this far (pixels) from the seed's angle
# (pivot error bends the band at small radii) and may vanish for at most MAX_GAP of R. A wide
# hand (half-width at least WIDE_HAND of R) ends where it gets WIDEN_FACTOR wider than over the
# last WIDTH_MEMORY of R, for at least WIDEN_PERSIST of R: it ran into the date window. Thin
# hands may widen (a seconds hand's arrow or lollipop, lettering it crosses).
TRACE_TOLERANCE_PX = 4.0
MAX_GAP = 0.04
# The trace is the first run (joined across gaps) at least this long (fraction of R).
MIN_RUN = 0.08
WIDE_HAND = 0.015
WIDEN_FACTOR = 1.5
WIDTH_MEMORY = 0.1
WIDEN_PERSIST = 0.06
# Only this far out (fraction of R): date windows sit well away from the pivot, while a sword
# hand widens from its neck into its blade close to it.
WIDEN_FROM = 0.4
WIDEN_STEADY = 0.8
# Wide candidates this close (relative to touching side by side), and about as long (fraction of
# R), are two facets of one hand.
FACET_SLACK = 1.0
FACET_LENGTH = 0.05
# A hand starts near the pivot (within MAX_START of R), or further out when something else
# (another hand) covers the ray up to there. It is present over MIN_CONTINUITY of its run.
MAX_START = 0.25
MIN_CONTINUITY = 0.7
# A hand differs from the dial (contrast) more at its center than beside it, on at least one
# side, over this share of its length. The strip of plain dial between two hands also has two
# edges, but is lower than both hands beside it.
MIN_COVERED = 0.5


@dataclass(frozen=True)
class HandCandidate:
    angle: float  # clock degrees, from the hand's centerline
    length: float  # fraction of R; capped at HANDS_OUTER (the marker ring is excluded)
    width: float  # fraction of R, at WIDTH_RADIUS
    strength: float  # summed evidence; relative between candidates of one photo
    blocked: bool = False  # ran into something wider (a date window): may be longer

    @property
    def is_tail(self) -> bool:
        # A hand cut short by a date window is no tail: its length is only a lower bound.
        return self.length < MIN_HAND_LENGTH and not self.blocked


def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two clock angles, in degrees."""
    d = (a - b) % 360
    return min(d, 360 - d)


@dataclass(frozen=True)
class BarEvidence:
    """Polar maps around the pivot (rows: angle bins, columns: radius in pixels)."""

    contrast: npt.NDArray[np.float32]  # |pixel − ring median|, with color
    evidence: npt.NDArray[np.float32]  # best bar evidence over the half-widths tried
    half_width: npt.NDArray[np.float32]  # the half-width (pixels) that gave it
    present: npt.NDArray[np.bool_]  # evidence clearly above the ring's noise
    covered: npt.NDArray[np.bool_]  # contrast clearly above the ring's noise (anything there)


def bar_evidence(
    image: GrayImage,
    dial_center: Point,
    pivot: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None = None,
) -> BarEvidence:
    bins = ANGLE_BINS
    rad_per_bin = 2 * np.pi / bins
    outer = HANDS_OUTER * radius

    def polar_of(img):
        smooth = cv2.GaussianBlur(img, (0, 0), SMOOTH_PX)
        return unwrap(inside_hands_area(smooth, dial_center, radius), pivot, outer, bins)

    gray_polar = polar_of(image)
    chroma_polar = None if chroma is None else polar_of(chroma)
    c = contrast(gray_polar, chroma_polar)
    n_r = c.shape[1]
    r = np.maximum(np.arange(n_r, dtype=np.float64), 1.0)

    # Signed channels: brightness, and color (Lab a, b) when there is any. Each is searched for
    # bars of either polarity, so a dark hand over a bright date window counts like a light hand
    # on a dark dial.
    channels = [gray_polar.astype(np.float32)]
    if chroma_polar is not None:
        weight = np.float32(np.sqrt(CHROMA_WEIGHT))
        channels += [weight * chroma_polar[..., i].astype(np.float32) for i in range(2)]
    # Derivatives along the arc, per pixel (not per angle bin).
    arc = (2 * r * rad_per_bin)[None, :].astype(np.float32)
    grads = [(np.roll(ch, -1, axis=0) - np.roll(ch, 1, axis=0)) / arc for ch in channels]

    rows = np.arange(bins)[:, None]
    cols = np.arange(n_r)[None, :]
    best = np.zeros_like(c)
    best_half = np.zeros_like(c)
    for fraction in HALF_WIDTHS:
        half = fraction * radius
        k = np.maximum(1, np.rint(half / r / rad_per_bin)).astype(np.intp)[None, :]
        before, after = (rows - k) % bins, (rows + k) % bins
        squared = np.zeros_like(c)
        for g in grads:
            # Both edges of a bar: one rising and one falling, in either order.
            lit = np.minimum(g[before, cols], -g[after, cols])
            dark = np.minimum(-g[before, cols], g[after, cols])
            squared += np.maximum(np.maximum(lit, dark), 0) ** 2
        e = np.sqrt(squared)
        better = e > best
        best = np.where(better, e, best)
        best_half = np.where(better, np.float32(half), best_half)

    noise = np.percentile(best, NOISE_PERCENTILE, axis=0, keepdims=True)
    present = (best > NOISE_K * noise) & (best > MIN_EVIDENCE)
    contrast_noise = 1.4826 * np.median(c, axis=0, keepdims=True)
    covered = c > np.maximum(NOISE_K * contrast_noise, MIN_EVIDENCE)
    return BarEvidence(c, best, best_half, present, covered)


def _seeds(ev: BarEvidence, radius: float, per_deg: float) -> list[int]:
    """Directions to trace: peaks of the evidence per angle, near the pivot and further out,
    at two smoothings (the coarse one finds the middle of a hand whose outline strokes give
    peaks of their own)."""
    seeds: list[int] = []
    for lo, hi in SEED_BANDS:
        band = np.where(ev.present, ev.evidence, 0)[:, int(lo * radius) : int(hi * radius)]
        summed = band.sum(axis=1, dtype=np.float64)
        if summed.max() <= 0:
            continue
        for smoothing in SEED_SMOOTHING_DEG:
            profile = _smooth(summed, max(1, int(smoothing * per_deg)))
            separation = int(MIN_HAND_SEPARATION_DEG * per_deg)
            for peak in _peaks(profile, separation, MIN_SEED_FRACTION):
                if all(_angle_diff(peak / per_deg, s / per_deg) >= 1.0 for s in seeds):
                    seeds.append(peak)
    return seeds


@dataclass(frozen=True)
class HandTrace:
    """One bar followed outward from the pivot, in the polar maps."""

    radii: npt.NDArray[np.intp]  # where it's present
    rows: npt.NDArray[np.intp]  # angle bin of its center there
    start: int
    end: int  # last radius (pixels) where it's present
    blocked: bool  # ended where it ran into something wider: the hand may be longer


def _ray(
    ev: BarEvidence,
    seed: int,
    radius: float,
    per_deg: float,
    tolerance_px: float = TRACE_TOLERANCE_PX,
):
    """Along the seed's ray, per radius: the best row within the tolerance, and whether a bar is
    present there."""
    bins, n_r = ev.evidence.shape
    r_cap = int(HANDS_INNER * radius)
    radii = np.arange(r_cap, n_r)
    tols = np.maximum(2, np.ceil(np.degrees(tolerance_px / radii) * per_deg)).astype(int)
    rows = np.empty(len(radii), np.intp)
    for i, (r, tol) in enumerate(zip(radii, tols, strict=True)):
        window = np.arange(seed - tol, seed + tol + 1) % bins
        rows[i] = window[np.argmax(ev.evidence[window, r])]
    return radii, rows, ev.present[rows, radii]


def _runs(radii, present, gap_limit: int) -> list[tuple[int, int]]:
    """(first, last) indices of runs of presence, joined across gaps up to `gap_limit`."""
    idx = np.flatnonzero(present)
    if len(idx) == 0:
        return []
    breaks = np.flatnonzero(np.diff(radii[idx]) > gap_limit + 1)
    firsts = np.concatenate([[0], breaks + 1])
    lasts = np.concatenate([breaks, [len(idx) - 1]])
    return [(int(idx[f]), int(idx[last])) for f, last in zip(firsts, lasts, strict=True)]


def _until_widening(ev: BarEvidence, radii, rows, present, radius: float) -> int:
    """Index where a wide hand runs into something wider (a date window), else the last: the
    bar gets WIDEN_FACTOR wider than just before, and stays that wide over WIDEN_STEADY of the
    next WIDEN_PERSIST of R (lettering widens it only briefly and erratically)."""
    halves = ev.half_width[rows, radii]
    memory = max(1, int(WIDTH_MEMORY * radius))
    persist = max(1, int(WIDEN_PERSIST * radius))
    for i in range(len(radii)):
        r = radii[i]
        if not present[i] or r - radii[0] < memory or r < WIDEN_FROM * radius:
            continue
        recent = halves[(radii >= r - memory) & (radii < r) & present]
        if len(recent) == 0:
            continue
        usual = float(np.median(recent))
        if usual < WIDE_HAND * radius or halves[i] <= WIDEN_FACTOR * usual:
            continue
        ahead = (radii >= r) & (radii < r + persist) & present
        if (
            radii[-1] - r >= persist
            and np.mean(halves[ahead] > WIDEN_FACTOR * usual) >= WIDEN_STEADY
        ):
            return max(i - 1, 0)
    return len(radii) - 1


def _stands_out(ev: BarEvidence, rows, radii) -> npt.NDArray[np.bool_]:
    """Per trace point: is the center's contrast above the contrast just beside the bar on at
    least one side?"""
    bins = ev.contrast.shape[0]
    k = np.maximum(
        1, np.rint(2 * ev.half_width[rows, radii] / np.maximum(radii, 1) * bins / (2 * np.pi))
    )
    k = k.astype(np.intp)
    center = ev.contrast[rows, radii]
    beside = np.minimum(
        ev.contrast[(rows - k) % bins, radii], ev.contrast[(rows + k) % bins, radii]
    )
    return center > beside


def _trace(
    ev: BarEvidence,
    seed: int,
    radius: float,
    per_deg: float,
    tolerance_px: float = TRACE_TOLERANCE_PX,
) -> HandTrace | None:
    radii, rows, present = _ray(ev, seed, radius, per_deg, tolerance_px)
    gap_limit = max(1, int(MAX_GAP * radius))
    # The first run of some length: bits near the pivot cap, cut off from the hand by a gap
    # where two hands cross, don't end it.
    runs = [
        (f, last)
        for f, last in _runs(radii, present, gap_limit)
        if radii[last] - radii[f] >= MIN_RUN * radius
    ]
    if not runs:
        return None
    first, last = runs[0]
    radii, rows, present = (
        radii[first : last + 1],
        rows[first : last + 1],
        present[first : last + 1],
    )
    end = _until_widening(ev, radii, rows, present, radius)
    blocked = end < len(radii) - 1
    radii, rows, present = radii[: end + 1], rows[: end + 1], present[: end + 1]
    radii, rows = radii[present], rows[present]
    if len(radii) < 2:
        return None
    if np.median(ev.half_width[rows, radii]) >= 0.95 * HALF_WIDTHS[-1] * radius:
        return None  # as wide as the widest bar tried: not a bar
    start, end_r = int(radii[0]), int(radii[-1])
    if len(radii) < MIN_CONTINUITY * (end_r - start + 1):
        return None
    if _stands_out(ev, rows, radii).mean() < MIN_COVERED:
        return None  # plain dial between two hands (a dark bar between bright edges)
    if start > MAX_START * radius:
        # Allowed only when something covers this very ray between the pivot and the start: a
        # thin hand's inner part lying on a wider hand.
        r_cap = int(HANDS_INNER * radius)
        window = np.arange(rows[0] - 1, rows[0] + 2) % ev.evidence.shape[0]
        inner = ev.covered[window][:, r_cap:start].any(axis=0)
        if inner.mean() < MIN_CONTINUITY:
            return None
    return HandTrace(radii, rows, start, end_r, blocked)


def _center_deg(ev: BarEvidence, row: int, r: int, per_deg: float) -> tuple[float, float]:
    """Sub-bin center of the bar at (row, r), in degrees, and its weight: the evidence peak
    across the bar (both edges match best at its center), refined by a parabola."""
    bins = ev.evidence.shape[0]
    left, mid, right = ev.evidence[[(row - 1) % bins, row, (row + 1) % bins], r]
    curvature = left - 2 * mid + right
    shift = 0.5 * (left - right) / curvature if curvature < 0 else 0.0
    return (row + float(np.clip(shift, -0.5, 0.5))) / per_deg, float(mid)


def _candidate(ev: BarEvidence, t: HandTrace, radius: float, per_deg: float) -> HandCandidate:
    length = t.end / radius
    # Near the pivot hands overlap and a pivot error matters most; long hands are measured
    # beyond where tails reach.
    first = int(MIN_HAND_LENGTH * radius) if length >= MIN_HAND_LENGTH else 0
    keep = t.radii >= first
    centers = [
        _center_deg(ev, int(j), int(r), per_deg)
        for j, r in zip(t.rows[keep], t.radii[keep], strict=True)
    ]
    angles = np.array([c for c, _ in centers])
    weights = np.array([w for _, w in centers])
    ref = angles[0]
    unwrapped = ref + (angles - ref + 180) % 360 - 180
    angle = (
        float(np.average(unwrapped, weights=weights) if weights.sum() > 0 else unwrapped.mean())
        % 360
    )
    r_w = min(int(min(WIDTH_RADIUS, length / 2) * radius), t.end)
    i = int(np.argmin(np.abs(t.radii - r_w)))
    width = 2 * float(ev.half_width[t.rows[i], t.radii[i]]) / radius
    strength = float(ev.evidence[t.rows, t.radii].sum())
    return HandCandidate(angle, length, width, strength, t.blocked)


def hand_traces(
    image: GrayImage,
    dial_center: Point,
    pivot: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None = None,
    tolerance_px: float = TRACE_TOLERANCE_PX,
) -> tuple[BarEvidence, list[HandTrace]]:
    """The bar evidence and every hand-like trace in it (for candidates, the pivot and the
    debug CLI)."""
    ev = bar_evidence(image, dial_center, pivot, radius, chroma)
    per_deg = ANGLE_BINS / 360
    seeds = _seeds(ev, radius, per_deg)
    traces = [t for s in seeds if (t := _trace(ev, s, radius, per_deg, tolerance_px))]
    return ev, traces


def measure_hands(
    image: GrayImage,
    dial_center: Point,
    pivot: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None = None,
) -> list[HandCandidate]:
    """Hand candidates around the pivot of a rectified dial, strongest first. `chroma`: the
    rectified Lab a and b channels, if the photo has color."""
    ev, traces = hand_traces(image, dial_center, pivot, radius, chroma)
    per_deg = ANGLE_BINS / 360
    # Two traces at one angle are one hand: keep the one starting nearest the pivot (a trace
    # starting further out at the same angle is something the hand runs into), then the longest.
    traces.sort(key=lambda t: (t.start, -t.end))
    candidates: list[HandCandidate] = []
    for t in traces:
        c = _candidate(ev, t, radius, per_deg)
        if any(_angle_diff(c.angle, o.angle) < MIN_HAND_SEPARATION_DEG for o in candidates):
            continue
        candidates.append(c)
    return sorted(_merge_facets(candidates), key=lambda c: -c.strength)


def _merge_facets(candidates: list[HandCandidate]) -> list[HandCandidate]:
    """Join wide candidates whose bars touch side by side: the two facets of one faceted
    (sword) hand, lit differently, each look like a bar of their own."""
    out = list(candidates)
    merged = True
    while merged:
        merged = False
        for a, b in itertools.combinations(out, 2):
            if min(a.width, b.width) < 2 * WIDE_HAND or a.is_tail or b.is_tail:
                continue
            if abs(a.length - b.length) > FACET_LENGTH:
                continue  # two different hands (an hour and a minute hand side by side)
            touching = np.degrees((a.width + b.width) / 2 / WIDTH_RADIUS) * FACET_SLACK
            gap = _angle_diff(a.angle, b.angle)
            if gap > touching:
                continue
            total = a.strength + b.strength
            offset = ((b.angle - a.angle + 180) % 360 - 180) * b.strength / total
            joined = HandCandidate(
                (a.angle + offset) % 360,
                max(a.length, b.length),
                (a.width + b.width) / 2 + np.radians(gap) * WIDTH_RADIUS,
                total,
                a.blocked or b.blocked,
            )
            out = [c for c in out if c is not a and c is not b] + [joined]
            merged = True
            break
    return out


# --- 12 o'clock refinement from the hour markers -----------------------------------------------

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
