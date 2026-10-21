"""Hands from their straight edges: the pivot and the hand candidates (steps 4–6).

Pure functions: image in, result out. No file system, no framework code.

Hands are straight and point at the pivot, so their outlines show up as long line segments
(LSD) whose lines pass close to the pivot. That only relies on hands having straight edges, not
on them contrasting with the dial all the way to the hub: real hands are often dark metal near
the pivot and luminous further out, cross lettering, or run into a date window. Markers and
the date window also give radial edges, but they start far from the hub.

- The pivot is a small round cap where the hands' edges converge: candidates from a circle
  detector are ranked by how well the long segments point at them, and the winner is sharpened
  by fitting its rim.
- Segments pointing at the pivot are grouped by direction and chained outward from the hub (a
  marker in line with a hand is separated from it by a radial gap); each group is a hand
  candidate, or several overlapping hands. The two edges of a tapered hand are joined.

Adapted from watch-time (tempgrejs/watch-time, backend/app/vision/center.py and hands.py). Its
radius-relative constants are rescaled to this pipeline's R (the hour markers sit at 0.9 R
here, at about 0.78 of watch-time's radius).

Angles are clock angles: degrees clockwise from 12 o'clock in the rectified dial.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.geometry import (
    FloatArray,
    GrayImage,
    Point,
    angle_diff,
    circ_mean,
    clock_angles,
    clock_direction,
)
from watchtiming.hands import MIN_LINE_SPREAD_DEG, HandCandidate, HandLine, PivotSearch
from watchtiming.polar import ANGLE_BINS, contrast, unwrap

Segments = npt.NDArray[np.float64]  # (n, 4): x1, y1, x2, y2

# Smoothing (pixels) before the segment detector: noise breaks a hand's edges into pieces too
# short to count (σ = 15 gray levels lost the hour and minute hands). Then contrast
# equalization (uneven light, dark hands on a dark dial).
LSD_SMOOTH_PX = 2.0
CLAHE_CLIP = 2.0
CLAHE_TILE = 8


def line_segments(image: GrayImage, chroma: npt.NDArray[np.uint8] | None = None) -> Segments:
    """LSD segments in the image, and in the Lab a channel when there's color (a red seconds
    hand on a black dial is faint in gray)."""
    lsd = cv2.createLineSegmentDetector()
    smooth = cv2.GaussianBlur(image, (0, 0), LSD_SMOOTH_PX)
    channels = [cv2.createCLAHE(CLAHE_CLIP, (CLAHE_TILE, CLAHE_TILE)).apply(smooth)]
    if chroma is not None:
        a = cv2.GaussianBlur(np.ascontiguousarray(chroma[..., 0]), (0, 0), LSD_SMOOTH_PX)
        channels.append(a)
    found = [lsd.detect(c)[0] for c in channels]
    parts = [s.reshape(-1, 4) for s in found if s is not None]
    return np.concatenate(parts).astype(np.float64) if parts else np.zeros((0, 4))


# --- Shared by the pivot search and the hand candidates ----------------------------------------

# Fractions of R. A hand reaches at least this close to the pivot (the edges of a date window
# also point at the pivot, but start further out: 0.33–0.5 R on the real photos; hands start
# within 0.27 R), and no further out than MAX_REACH.
MAX_INNER = 0.3
MAX_REACH = 1.15
# Segments within this direction difference belong together (degrees).
GROUP_DEG = 5.0


@dataclass(frozen=True)
class _Oriented:
    """Segments relative to a pivot, each turned to point outward."""

    p_in: FloatArray  # (n, 2) the end nearer the pivot, relative to it
    v: FloatArray  # (n, 2) from the inner to the outer end
    length: FloatArray
    r_in: FloatArray  # distances of the inner and outer ends from the pivot
    r_out: FloatArray
    offset: FloatArray  # signed distance of each segment's line from the pivot


def _orient(segs: Segments, pivot: FloatArray) -> _Oriented:
    p1, p2 = segs[:, :2] - pivot, segs[:, 2:] - pivot
    r1, r2 = np.linalg.norm(p1, axis=1), np.linalg.norm(p2, axis=1)
    swap = (r1 > r2)[:, None]
    p_in, p_out = np.where(swap, p2, p1), np.where(swap, p1, p2)
    v = p_out - p_in
    length = np.linalg.norm(v, axis=1)
    offset = (p_in[:, 0] * v[:, 1] - p_in[:, 1] * v[:, 0]) / np.maximum(length, 1e-9)
    return _Oriented(p_in, v, length, np.minimum(r1, r2), np.maximum(r1, r2), offset)


def _group_by_direction(
    phi: FloatArray, weights: FloatArray
) -> tuple[list[list[int]], list[float]]:
    """Greedy grouping of directions (degrees) within GROUP_DEG, heaviest first so long edges
    seed the groups: (member indices per group, each group's weighted circular mean)."""
    groups: list[list[int]] = []
    centers: list[float] = []
    for k in np.argsort(-weights):
        for gi, center in enumerate(centers):
            if angle_diff(phi[k], center) < GROUP_DEG:
                groups[gi].append(int(k))
                centers[gi] = circ_mean(phi[groups[gi]], weights[groups[gi]])
                break
        else:
            groups.append([int(k)])
            centers.append(float(phi[k]))
    return groups, centers


# --- Step 4: the pivot -------------------------------------------------------------------------
#
# A hand's two edges pass half its width beside the pivot, on either side, so edges alone
# don't point at it. Their middle does: per direction, the centerline lies halfway between the
# edges on the left and on the right. The pivot is where the centerlines meet (iterated, since
# which segments belong to a hand depends on where the pivot is), sharpened by the cap's rim
# when there is one.

# Fractions of R. The shortest segment used, the search window around the start, the cap's
# radius range, how far the cap may lie from the centerlines' meeting point, and how far a
# centerline may miss it before it's dropped (lettering, a dial edge).
PIVOT_MIN_SEGMENT = 0.1
PIVOT_SEARCH = 0.2
CAP_RADII = (0.025, 0.1)
CAP_SNAP = 0.02
PIVOT_OUTLIER = 0.01
# The largest distance from the pivot estimate to a hand's edge, per iteration: loose while the
# estimate may be far off (a rough, affine-only rectification under strong tilt), then tight.
PIVOT_OFFSETS = (0.2, 0.12, 0.08, 0.08)
# Each side of a hand needs at least this much edge length (fraction of R) for a centerline.
PIVOT_MIN_SIDE = 0.1
# Only centerlines at least this fraction of the strongest one's weight count for their spread
# (a faint line in another direction doesn't make the pivot well determined).
SPREAD_MIN_WEIGHT = 0.3
# Misses larger than this multiple of the median miss drop a centerline (and PIVOT_OUTLIER).
PIVOT_OUTLIER_FACTOR = 2.0
# The cap's rim: sampled along RIM_RAYS rays at RIM_SAMPLES radii between RIM_RANGE times the
# detected radius; rays whose strongest edge lies more than RIM_TRIM of it from the median are
# a hand crossing the rim. A fitted center moving more than RIM_MAX_SHIFT of it is rejected.
RIM_RAYS = 90
RIM_SAMPLES = 40
RIM_RANGE = (0.5, 1.5)
RIM_TRIM = 0.15
RIM_MAX_SHIFT = 0.5
# Hough circle detector for the cap (OpenCV's HOUGH_GRADIENT_ALT: edge threshold, and how
# circular the edge must be, 0–1).
CAP_HOUGH_EDGE = 60
CAP_HOUGH_ROUNDNESS = 0.6


def _centerlines(
    segs: Segments, pivot: FloatArray, radius: float, max_offset: float
) -> list[HandLine]:
    """Hands' centerlines: segments passing within `max_offset` (fraction of R) of `pivot`,
    grouped by direction, halfway between the edges on either side of each group."""
    o = _orient(segs, pivot)
    ok = (
        (o.length > PIVOT_MIN_SEGMENT * radius)
        & (np.abs(o.offset) < max_offset * radius)
        & (o.r_in < 2 * MAX_INNER * radius)
        & (o.r_out < MAX_REACH * radius)
    )
    idx = np.flatnonzero(ok)
    groups, centers = _group_by_direction(clock_angles(o.v[idx]), o.length[idx])

    lines = []
    for members, center in zip(groups, centers, strict=True):
        i = idx[np.array(members)]
        offset, length = o.offset[i], o.length[i]
        left, right = offset > 0, offset < 0
        w_left, w_right = length[left].sum(), length[right].sum()
        if min(w_left, w_right) < PIVOT_MIN_SIDE * radius:
            continue  # one edge only: its offset from the centerline is unknown
        middle = (
            np.average(offset[left], weights=length[left])
            + np.average(offset[right], weights=length[right])
        ) / 2
        direction = clock_direction(center)
        normal = np.array([direction[1], -direction[0]])  # offset = cross(point − pivot, dir)
        lines.append(HandLine(pivot + middle * normal, direction, float(w_left + w_right)))
    return lines


def _intersect(lines: list[HandLine]) -> FloatArray:
    """Point minimizing the weighted squared distances to all lines."""
    a, b = np.zeros((2, 2)), np.zeros(2)
    for line in lines:
        n = np.array([-line.direction[1], line.direction[0]])
        a += line.weight * np.outer(n, n)
        b += line.weight * np.outer(n, n) @ line.point
    return np.linalg.solve(a, b)


def _distance(line: HandLine, point: FloatArray) -> float:
    n = np.array([-line.direction[1], line.direction[0]])
    return abs(float(n @ (point - line.point)))


def _spread_deg(lines: list[HandLine]) -> float:
    """Largest angle between two strong lines' directions, mod 180°."""
    if len(lines) < 2:
        return 0.0
    top = max(line.weight for line in lines)
    a = [
        np.degrees(np.arctan2(line.direction[1], line.direction[0])) % 180
        for line in lines
        if line.weight >= SPREAD_MIN_WEIGHT * top
    ]
    return max((min(abs(x - y), 180 - abs(x - y)) for x in a for y in a), default=0.0)


def _fit_rim(gray: GrayImage, c: FloatArray, r: float) -> FloatArray:
    """Least-squares circle through the strongest edge along each ray around a cap. Hands
    crossing the rim give outlier rays; a median-based trim drops them."""
    n_rays = RIM_RAYS
    radii = np.linspace(RIM_RANGE[0] * r, RIM_RANGE[1] * r, RIM_SAMPLES)
    ang = np.linspace(0, 2 * np.pi, n_rays, endpoint=False)
    xs = c[0] + np.cos(ang)[:, None] * radii
    ys = c[1] + np.sin(ang)[:, None] * radii
    g = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    vals = cv2.remap(g, xs.astype(np.float32), ys.astype(np.float32), cv2.INTER_LINEAR)
    k = np.argmax(np.abs(np.diff(vals, axis=1)), axis=1)
    rr = (radii[k] + radii[k + 1]) / 2
    keep = np.abs(rr - np.median(rr)) < RIM_TRIM * r
    if keep.sum() < n_rays // 3:
        return c
    px = c[0] + np.cos(ang[keep]) * rr[keep]
    py = c[1] + np.sin(ang[keep]) * rr[keep]
    # Algebraic circle fit: x² + y² + D·x + E·y + F = 0
    a = np.stack([px, py, np.ones_like(px)], 1)
    (d, e, _), *_ = np.linalg.lstsq(a, -(px**2 + py**2), rcond=None)
    fitted = np.array([-d / 2, -e / 2])
    return fitted if np.linalg.norm(fitted - c) < RIM_MAX_SHIFT * r else c


def _cap(image: GrayImage, near: FloatArray, radius: float) -> FloatArray | None:
    """The center of the hub cap nearest `near`, sharpened by its rim, or None."""
    h = int(PIVOT_SEARCH * radius)
    x0, y0 = max(int(near[0]) - h, 0), max(int(near[1]) - h, 0)
    crop = cv2.GaussianBlur(image[y0 : y0 + 2 * h, x0 : x0 + 2 * h], (5, 5), 1.5)
    circles = cv2.HoughCircles(
        crop, cv2.HOUGH_GRADIENT_ALT, dp=1, minDist=3,
        param1=CAP_HOUGH_EDGE, param2=CAP_HOUGH_ROUNDNESS,
        minRadius=max(int(CAP_RADII[0] * radius), 3), maxRadius=int(CAP_RADII[1] * radius),
    )  # fmt: skip
    if circles is None:
        return None
    caps = [(c[:2] + (x0, y0), float(c[2])) for c in circles[0]]
    center, r = min(caps, key=lambda cap: np.linalg.norm(cap[0] - near))
    return _fit_rim(image, center, r)


def find_pivot(image: GrayImage, start: Point, radius: float, segs: Segments) -> PivotSearch:
    """Where the hands' centerlines meet, near `start` (the dial center of the rectified image).

    When the hands lie along one line (overlapping, or opposite), they only locate the pivot
    across that line (`well_determined` False); along it, the hub cap does if there's one, else
    the point closest to `start`.
    """
    c0 = np.asarray(start, np.float64)
    pivot = c0.copy()
    lines: list[HandLine] = []
    well_determined = False
    for max_offset in PIVOT_OFFSETS:
        lines = _centerlines(segs, pivot, radius, max_offset)
        well_determined = len(lines) >= 2 and _spread_deg(lines) >= MIN_LINE_SPREAD_DEG
        if not well_determined:
            break
        estimate = _intersect(lines)
        misses = [_distance(line, estimate) for line in lines]
        limit = max(PIVOT_OUTLIER * radius, PIVOT_OUTLIER_FACTOR * float(np.median(misses)))
        kept = [line for line, miss in zip(lines, misses, strict=True) if miss <= limit]
        if len(kept) >= 2 and _spread_deg(kept) >= MIN_LINE_SPREAD_DEG:
            lines, estimate = kept, _intersect(kept)
        if np.linalg.norm(estimate - c0) > PIVOT_SEARCH * radius:
            well_determined = False
            break
        pivot = estimate
    if not well_determined:
        pivot = c0.copy()
        if lines:
            line = max(lines, key=lambda line: line.weight)
            pivot = line.point + ((c0 - line.point) @ line.direction) * line.direction

    cap = _cap(image, pivot, radius)
    if cap is not None:
        if well_determined and np.linalg.norm(cap - pivot) < CAP_SNAP * radius:
            pivot = cap
        elif not well_determined and lines:
            line = max(lines, key=lambda line: line.weight)
            if _distance(line, cap) < CAP_SNAP * radius:
                pivot = cap  # the cap places it along the hands' line
    return PivotSearch((float(pivot[0]), float(pivot[1])), lines, well_determined)


# --- Steps 5–6: hand candidates ----------------------------------------------------------------

# Fractions of R. The shortest segment considered, the largest distance from the pivot to a
# segment's line, and the least total segment length of a hand (see also MAX_INNER, MAX_REACH
# and GROUP_DEG above).
MIN_SEGMENT = 0.07
MAX_OFFSET = 0.08
MIN_EVIDENCE = 0.17
# A long edge across a hand's ray, between these radii (fractions of R), is something the hand
# runs into (a date window's near side): the hand ends there and its length is only a lower
# bound. Hour markers sit further out; lettering strokes are shorter.
BLOCK_FROM, BLOCK_TO = 0.4, 0.75
BLOCK_MIN_LENGTH = 0.08
BLOCK_ACROSS_DEG = 25.0  # how far from perpendicular to the ray the edge may be
# A hand's segments form a chain from the hub; a larger radial gap means a marker.
MAX_GAP = 0.23
# Two groups this close (degrees) and equally long (fraction of R), both starting near the
# pivot, are the two edges of one tapered hand.
MERGE_DEG = 9.0
MERGE_LENGTH = 0.09
MERGE_INNER = 0.29
# The outer angle comes from segments reaching past this fraction of the group's length.
OUTER_FRACTION = 0.75
# Width: across the hand in the polar contrast image, between these fractions of its length (and
# at most WIDTH_MAX_RADIUS of R, clear of where long hands thin to a point), where the contrast
# stays above half of the hand's own.
WIDTH_FROM, WIDTH_TO, WIDTH_MAX_RADIUS = 0.3, 0.7, 0.6
WIDTH_SEARCH_DEG = 12.0


@dataclass
class HandGroup:
    """Segments that point at the pivot in one direction: one hand, or overlapping hands."""

    angle: float  # from all segments of the group (length-weighted circular mean)
    outer_angle: float  # from the segments reaching furthest out
    r_in: float  # fractions of R
    r_out: float
    evidence: float  # total segment length, fraction of R
    blocked: bool = False  # ran into something (a date window): may be longer
    segments: list[FloatArray] = field(default_factory=list, repr=False)


def _blocked_at(segs: Segments, pivot: FloatArray, angle: float, radius: float) -> float | None:
    """Radius (pixels) where a long edge crosses the ray at `angle` between BLOCK_FROM and
    BLOCK_TO of R, or None."""
    ray = clock_direction(angle)
    p1, p2 = segs[:, :2] - pivot, segs[:, 2:] - pivot
    v = p2 - p1
    length = np.linalg.norm(v, axis=1)
    across = np.abs(v @ ray) / np.maximum(length, 1e-9) < np.sin(np.radians(BLOCK_ACROSS_DEG))
    # Where each segment's line meets the ray: p1 + t·v = s·ray.
    det = v[:, 0] * -ray[1] - v[:, 1] * -ray[0]
    ok = across & (length > BLOCK_MIN_LENGTH * radius) & (np.abs(det) > 1e-9)
    if not ok.any():
        return None
    p1, v, det = p1[ok], v[ok], det[ok]
    t = (-p1[:, 0] * -ray[1] + p1[:, 1] * -ray[0]) / det
    r = (v[:, 0] * -p1[:, 1] + v[:, 1] * p1[:, 0]) / det
    hits = (t >= 0) & (t <= 1) & (r > BLOCK_FROM * radius) & (r < BLOCK_TO * radius)
    return float(r[hits].min()) if hits.any() else None


def hand_groups(segs: Segments, pivot: Point, radius: float) -> list[HandGroup]:
    """Group the segments pointing at the pivot into hand candidates, strongest first."""
    if len(segs) == 0:
        return []
    c = np.asarray(pivot, np.float64)
    o = _orient(segs, c)
    r_in, r_out, length = o.r_in, o.r_out, o.length
    ok = (
        (length > MIN_SEGMENT * radius)
        & (np.abs(o.offset) < MAX_OFFSET * radius)
        & (r_out < MAX_REACH * radius)
    )
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return []
    phi = clock_angles(o.v[idx])  # direction of each segment, pointing outward
    groups, _ = _group_by_direction(phi, length[idx])

    out: list[HandGroup] = []
    for members in groups:
        m = np.array(members)
        # Keep only the chain of segments connected to the innermost one: a marker in line with
        # a hand is separated from it by a radial gap.
        m = m[np.argsort(r_in[idx[m]])]
        reach = r_out[idx[m[0]]]
        chain = [m[0]]
        for k in m[1:]:
            if r_in[idx[k]] > reach + MAX_GAP * radius:
                break
            chain.append(k)
            reach = max(reach, r_out[idx[k]])
        m = np.array(chain)
        # A hand that runs into a date window ends where it meets the window's near side.
        block = _blocked_at(segs, c, circ_mean(phi[m], length[idx[m]]), radius)
        blocked = block is not None and r_out[idx[m]].max() > block
        if blocked:
            m = m[r_in[idx[m]] < block]
            if len(m) == 0:
                continue
        i = idx[m]
        rin, rout = r_in[i].min() / radius, r_out[i].max() / radius
        if blocked:
            rout = min(rout, block / radius)
        evidence = length[i].sum() / radius
        if rin > MAX_INNER or evidence < MIN_EVIDENCE:
            continue
        outer = m[r_out[i] >= OUTER_FRACTION * r_out[i].max()]
        out.append(
            HandGroup(
                angle=circ_mean(phi[m], length[i]),
                outer_angle=circ_mean(phi[outer], length[idx[outer]]),
                r_in=float(rin),
                r_out=float(rout),
                evidence=float(evidence),
                blocked=bool(blocked),
                segments=[segs[j] for j in i],
            )
        )
    return sorted(_merge_edges(out), key=lambda g: -g.evidence)


def _merge_edges(groups: list[HandGroup]) -> list[HandGroup]:
    """Join groups that are the two diverging edges of one tapered hand."""
    out: list[HandGroup] = []
    for g in sorted(groups, key=lambda g: -g.evidence):
        for o in out:
            if (
                angle_diff(g.angle, o.angle) < MERGE_DEG
                and abs(g.r_out - o.r_out) < MERGE_LENGTH
                and max(g.r_in, o.r_in) < MERGE_INNER
            ):
                w = np.array([o.evidence, g.evidence])
                o.angle = circ_mean(np.array([o.angle, g.angle]), w)
                o.outer_angle = circ_mean(np.array([o.outer_angle, g.outer_angle]), w)
                o.r_in, o.r_out = min(o.r_in, g.r_in), max(o.r_out, g.r_out)
                o.evidence += g.evidence
                o.blocked = o.blocked or g.blocked
                o.segments += g.segments
                break
        else:
            out.append(g)
    return out


def _widths(
    image: GrayImage,
    pivot: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None,
    groups: list[HandGroup],
) -> list[float]:
    """Each hand's width (fraction of R), measured across it in the polar contrast image: the
    run around its angle where the contrast stays above half of its peak, median over radii."""
    polar = unwrap(image, pivot, radius, ANGLE_BINS)
    polar_chroma = None if chroma is None else unwrap(chroma, pivot, radius, ANGLE_BINS)
    c = contrast(polar, polar_chroma)
    per_deg = ANGLE_BINS / 360
    search = int(WIDTH_SEARCH_DEG * per_deg)
    widths = []
    for g in groups:
        lo = int(WIDTH_FROM * g.r_out * radius)
        hi = int(min(WIDTH_TO * g.r_out, WIDTH_MAX_RADIUS) * radius)
        row = int(round(g.angle * per_deg))
        rows = np.arange(row - search, row + search + 1) % ANGLE_BINS
        measured = []
        for r in range(max(lo, 2), max(hi, lo + 1)):
            bins = _half_max_width(c[rows, r], search)
            if bins:
                measured.append(np.radians(bins / per_deg) * r / radius)  # arc length / R
        widths.append(float(np.median(measured)) if measured else 0.0)
    return widths


def _half_max_width(profile: npt.NDArray[np.float32], search: int) -> int:
    """Width (in bins) of the run around the profile's peak where it stays above half the peak;
    0 without a peak. The peak is looked for in the middle half of the profile, which spans
    ±`search` bins around the hand's angle, so a neighboring hand at the edge isn't taken."""
    margin = search // 2
    peak = margin + int(np.argmax(profile[margin : len(profile) - margin]))
    half = profile[peak] / 2
    if half <= 0:
        return 0
    left = peak
    while left > 0 and profile[left - 1] > half:
        left -= 1
    right = peak
    while right < len(profile) - 1 and profile[right + 1] > half:
        right += 1
    return right - left + 1


def measure_hands(
    image: GrayImage,
    pivot: Point,
    radius: float,
    chroma: npt.NDArray[np.uint8] | None = None,
    segs: Segments | None = None,
) -> list[HandCandidate]:
    """Hand candidates around the pivot of a rectified dial, strongest first. `chroma`: the
    rectified Lab a and b channels, if the photo has color."""
    if segs is None:
        segs = line_segments(image, chroma)
    groups = hand_groups(segs, pivot, radius)
    widths = _widths(image, pivot, radius, chroma, groups)
    return [
        HandCandidate(
            angle=g.angle,
            length=g.r_out,
            width=w,
            strength=g.evidence,
            blocked=g.blocked,
            outer_angle=g.outer_angle,
        )
        for g, w in zip(groups, widths, strict=True)
    ]
