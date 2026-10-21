"""Write the pipeline's intermediate images, to look at before changing any thresholds.

    uv run python -m watchtiming.debug <image> [--tap X,Y] [-o OUT_DIR]

`--tap` is the 12 o'clock marker in the (upright) photo's pixel coordinates, as the user would
tap it; within ~20 px is plenty (the hour markers fix the exact angle). Without it, only the
stages before dial detection run, and `00_grid.png` shows the photo with a labelled coordinate
grid to read the tap from. Images go to
`debug-out/<image name>/` by default, numbered in pipeline order.
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.dial import Preprocessed, dial_rings, edge_map, preprocess
from watchtiming.geometry import Point, clock_point
from watchtiming.imaging import InvalidImageError
from watchtiming.measure import Measurement, measure
from watchtiming.pipeline import DialReading, rectified_chroma
from watchtiming.polar import ANGLE_BINS, contrast, unwrap
from watchtiming.segments import hand_groups, line_segments

Image = npt.NDArray[np.uint8]
Stage = tuple[str, Image]

# BGR colors for the overlays.
HOUR, MINUTE, SECOND, OTHER = (60, 60, 230), (230, 140, 40), (40, 200, 40), (160, 160, 160)
ROLE_COLORS = {"hour": HOUR, "minute": MINUTE, "second": SECOND, "other": OTHER}


def _color(gray: Image) -> Image:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _pt(p) -> tuple[int, int]:
    return int(round(p[0])), int(round(p[1]))


def _draw_ellipse(img: Image, e, color, thickness: int) -> None:
    axes = (int(round(e.semi_major)), int(round(e.semi_minor)))
    cv2.ellipse(img, _pt(e.center), axes, e.angle_deg, 0, 360, color, thickness, cv2.LINE_AA)


def _rectified_overlay(reading: DialReading) -> Image:
    g = reading.geometry
    rect = g.rectified
    img = _color(rect.image)
    cv2.circle(img, _pt(rect.center), int(rect.radius), OTHER, 1, cv2.LINE_AA)
    pivot = g.pivot.pivot
    for role, c in reading.roles():
        tip = reading.tip_in_rectified(c)
        cv2.line(img, _pt(pivot), _pt(tip), ROLE_COLORS[role], 2, cv2.LINE_AA)
    top = clock_point(rect.center, g.twelve.offset_deg, rect.radius)
    cv2.drawMarker(img, _pt(top), SECOND, cv2.MARKER_TRIANGLE_DOWN, 18, 2)
    cv2.drawMarker(img, _pt(pivot), (0, 0, 255), cv2.MARKER_CROSS, 16, 1)
    return img


def _normalized(polar: npt.NDArray[np.float32]) -> Image:
    top = float(np.percentile(polar, 99.5)) or 1.0
    return np.clip(polar / top * 255, 0, 255).astype(np.uint8)


def _segments_overlay(reading: DialReading, segs, groups) -> Image:
    """Every line segment on the rectified dial (thin), the hand groups (thick, yellow; blocked
    ones orange), over the chosen hands."""
    img = _rectified_overlay(reading)
    for x1, y1, x2, y2 in segs:
        cv2.line(img, _pt((x1, y1)), _pt((x2, y2)), (90, 90, 90), 1, cv2.LINE_AA)
    for g in groups:
        color = (0, 140, 255) if g.blocked else (0, 220, 255)
        for x1, y1, x2, y2 in g.segments:
            cv2.line(img, _pt((x1, y1)), _pt((x2, y2)), color, 2, cv2.LINE_AA)
    return img


def _grid(gray: Image, scale: float) -> Image:
    """The image with grid lines labelled in original-photo pixels, to read a tap from."""
    img = _color(gray)
    h, w = gray.shape
    step = 100 if max(h, w) / scale <= 2500 else 250  # in original pixels
    for value in range(0, int(max(w, h) / scale) + 1, step):
        p = int(round(value * scale))
        major = value % (step * 5) == 0
        color = (0, 200, 255) if major else (0, 140, 200)
        if p < w:
            cv2.line(img, (p, 0), (p, h - 1), color, 1)
            cv2.putText(img, str(value), (p + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        if p < h:
            cv2.line(img, (0, p), (w - 1, p), color, 1)
            cv2.putText(img, str(value), (2, p - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    return img


def debug_stages(data: bytes, tap: Point | None) -> tuple[list[Stage], list[str]]:
    """Run the pipeline on image bytes; return (named images, info lines). Pure. `tap` is in
    the upright photo's pixels; without it, only the stages before dial detection run."""
    pre = preprocess(data)
    if tap is not None:
        return draw_stages(pre, measure(pre, tap, ref=None))
    stages, info = _image_stages(pre)
    stages.insert(0, ("00_grid", _grid(pre.gray, pre.scale)))
    stages.append(("03_dial", _color(pre.gray)))
    info.append(
        "no --tap given: stopping before dial detection. Read the 12 o'clock marker's X,Y "
        "from 00_grid.png and rerun with --tap X,Y"
    )
    return stages, info


def _image_stages(pre: Preprocessed) -> tuple[list[Stage], list[str]]:
    height, width = pre.gray.shape
    info = [
        f"original (upright): {pre.original_size[0]}×{pre.original_size[1]}",
        f"preprocessed: {width}×{height}, scale {pre.scale:.4f}",
    ]
    return [("01_preprocessed", pre.gray), ("02_edges", edge_map(pre.gray))], info


def draw_stages(pre: Preprocessed, m: Measurement) -> tuple[list[Stage], list[str]]:
    """The stage images and info lines of a measurement that has been made (the same one the
    app was sent, for kept uploads). Pure."""
    stages, info = _image_stages(pre)
    color = pre.color
    dial_view = _color(pre.gray)
    tap_px = m.tap
    rings = dial_rings(pre.gray, tap_px)
    for ring in rings:
        _draw_ellipse(dial_view, ring.ellipse, OTHER, 1)
    info.append(
        f"concentric rings: {len(rings)}"
        + (f" (best: {rings[0].support} points, coverage {rings[0].coverage:.2f})" if rings else "")
    )
    cv2.drawMarker(dial_view, _pt(tap_px), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
    reading = m.reading
    if reading is None:
        stages.append(("03_dial", dial_view))
        info.append(f"stopped: {m.reading_error}")
        return stages, info

    g = reading.geometry
    _draw_ellipse(dial_view, g.ellipse, SECOND, 2)
    pivot_photo = g.rectified.to_photo(g.pivot.pivot)
    cv2.drawMarker(dial_view, _pt(pivot_photo), (0, 0, 255), cv2.MARKER_CROSS, 14, 1)
    stages.append(("03_dial", dial_view))
    stages.append(("04_rectified", _rectified_overlay(reading)))

    rect = g.rectified
    chroma = rectified_chroma(color, rect)
    pivot = g.pivot.pivot
    # Polar image (rows: clock angle, columns: radius from the pivot): contrast with the dial,
    # with color. The hands are the bright rows; their widths are measured across them here.
    polar_chroma = None if chroma is None else unwrap(chroma, pivot, rect.radius, ANGLE_BINS)
    polar = contrast(unwrap(rect.image, pivot, rect.radius, ANGLE_BINS), polar_chroma)
    stages.append(("05_polar", _normalized(polar)))
    segs = line_segments(rect.image, chroma)
    stages.append(
        ("06_segments", _segments_overlay(reading, segs, hand_groups(segs, pivot, rect.radius)))
    )

    a, c = reading.assignment, reading.confidence
    info += [
        f"pivot: {'from hand edges' if g.pivot.well_determined else 'hands parallel'}"
        f" ({len(g.pivot.lines)} segments)",
        "rectified from: "
        + (
            f"{len(g.marker_fit.inliers)} hour markers (fit error {g.marker_fit.rms_error:.1%})"
            if g.marker_fit
            else "ring + pivot"
        ),
        f"12 o'clock: {'markers' if g.twelve.from_markers else 'tap only'},"
        f" offset {g.twelve.offset_deg:+.2f}°, periodicity {g.twelve.periodicity:.1f}",
        "candidates: "
        + ", ".join(
            f"{h.angle:.2f}° len {h.length:.2f}{'+' if h.blocked else ''} w {h.width:.3f}"
            for h in reading.candidates
        ),
        f"hands: hour {a.hour_angle:.2f}°, minute {a.minute_angle:.2f}°, second "
        + (f"{a.second_angle:.2f}°" if a.second_angle is not None else "none"),
        f"residuals: minute vs seconds {a.minute_residual_s or 0:+.1f} s,"
        f" hour vs minute {a.hour_residual_min:+.1f} min",
        f"time: {reading.time}   confidence {c.overall:.2f} / seconds {c.seconds:.2f}"
        + ("   (needs confirmation)" if reading.needs_confirmation else "")
        + ("   (hands placed by the user)" if reading.corrected else ""),
        *(f"  · {r}" for r in c.reasons),
    ]
    if m.deviation_s is not None:
        info.append(f"deviation: {m.deviation_s:+.2f} s")
    return stages, info


def _parse_tap(text: str) -> Point:
    x, y = text.split(",")
    return float(x), float(y)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--tap", type=_parse_tap, help="12 o'clock as X,Y in photo pixels")
    parser.add_argument("-o", "--out", type=Path, help="default: debug-out/<image name>/")
    args = parser.parse_args(argv)

    try:
        stages, info = debug_stages(args.image.read_bytes(), args.tap)
    except (OSError, InvalidImageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out = args.out or Path("debug-out") / args.image.stem
    out.mkdir(parents=True, exist_ok=True)
    for line in info:
        print(line)
    for name, image in stages:
        path = out / f"{name}.png"
        if not cv2.imwrite(str(path), image):
            print(f"error: could not write {path}", file=sys.stderr)
            return 1
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
