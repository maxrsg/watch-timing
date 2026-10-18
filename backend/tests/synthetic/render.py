"""Synthetic watch dials with exactly known hand angles, for test-driving the CV pipeline.

The dial is drawn flat and upright ("dial frame": 12 o'clock up, centered), then mapped into
the photo by one homography: an in-plane rotation of the watch plus a perspective camera tilt.
Camera effects (glare, blur, noise) are applied after that, in photo space.

CLI: `uv run python -m tests.synthetic.render 10:08:37 --tilt 25 --rotation 30 -o dial.png`
"""

import argparse
import math
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.dial import GrayImage

Point = tuple[float, float]

# Gray levels. Light dial with dark hands, or the inverse when `dark_dial` is set.
BACKGROUND = 90
CASE = 150
LIGHT, DARK = 235, 25

# Geometry as fractions of the dial radius R.
CASE_RADIUS = 1.12
MARKER_INNER, MARKER_OUTER, MARKER_WIDTH = 0.84, 0.96, 0.035
TWELVE_MARKER_RADIUS = (MARKER_INNER + MARKER_OUTER) / 2
CAP_RADIUS = 0.05


@dataclass(frozen=True)
class Hand:
    length: float  # tip distance from the pivot
    width: float  # width at the pivot
    taper: float  # tip width / base width
    tail: float  # length behind the pivot


HOUR_HAND = Hand(length=0.50, width=0.075, taper=0.5, tail=0.06)
MINUTE_HAND = Hand(length=0.82, width=0.05, taper=0.4, tail=0.06)
SECOND_HAND = Hand(length=0.90, width=0.015, taper=0.6, tail=0.0)  # tail set by DialSpec


@dataclass(frozen=True)
class DialSpec:
    hours: int = 10
    minutes: int = 8
    seconds: float = 37.0
    size: int = 1000  # output is size × size pixels
    dial_radius: float = 0.38  # fraction of `size`
    rotation_deg: float = 0.0  # watch rotated clockwise in the photo (where 12 o'clock points)
    tilt_deg: float = 0.0  # camera tilt away from straight-on
    tilt_axis_deg: float = 0.0  # direction of the tilt axis in the photo
    camera_distance: float = 2.5  # in units of `size`; smaller = stronger perspective
    pivot_offset: Point = (0.0, 0.0)  # pivot vs dial center, fraction of R (dial frame)
    dark_dial: bool = False
    seconds_tail: float = 0.22  # counterweight length (fraction of R); 0 = none
    markers: bool = True
    glare: float = 0.0  # 0..1 strength of a soft highlight
    glare_center: Point = (0.35, 0.30)  # fraction of the image
    blur_sigma: float = 0.0  # pixels
    noise_sigma: float = 0.0  # gray levels
    seed: int = 0


@dataclass(frozen=True)
class Angles:
    """Hand angles in degrees, clockwise from 12 o'clock, in the dial frame."""

    hour: float
    minute: float
    second: float


@dataclass(frozen=True)
class GroundTruth:
    angles: Angles
    pivot: Point  # in the photo
    dial_center: Point  # in the photo (the projected center, not the ellipse's center)
    twelve: Point  # 12 o'clock marker in the photo: what the user taps
    homography: npt.NDArray[np.float64]  # dial frame → photo


@dataclass(frozen=True)
class RenderedDial:
    image: GrayImage
    truth: GroundTruth


def hand_angles(hours: int, minutes: int, seconds: float) -> Angles:
    """Mechanical watch: minute and hour hands move continuously with the seconds."""
    return Angles(
        hour=((hours % 12) + minutes / 60 + seconds / 3600) * 30,
        minute=(minutes + seconds / 60) * 6,
        second=seconds * 6 % 360,
    )


def _direction(angle_deg: float) -> npt.NDArray[np.float64]:
    """Unit vector for a clock angle in image coordinates (y points down)."""
    a = math.radians(angle_deg)
    return np.array([math.sin(a), -math.cos(a)])


def _fill(canvas: GrayImage, points: npt.NDArray[np.float64], value: int) -> None:
    # Fixed-point coordinates (shift=4) keep sub-pixel accuracy for the exact hand angles.
    pts = np.round(points * 16).astype(np.int32)
    cv2.fillPoly(canvas, [pts], value, cv2.LINE_AA, 4)


def _circle(canvas: GrayImage, center: npt.NDArray[np.float64], radius: float, value: int):
    c = tuple(int(v) for v in np.round(center * 16))
    cv2.circle(canvas, c, int(round(radius * 16)), value, -1, cv2.LINE_AA, 4)


def _hand(
    pivot: npt.NDArray[np.float64], angle_deg: float, hand: Hand, radius: float
) -> npt.NDArray[np.float64]:
    u = _direction(angle_deg)
    n = np.array([-u[1], u[0]])  # perpendicular
    base, tip = hand.width * radius / 2, hand.width * hand.taper * radius / 2
    back = pivot - u * hand.tail * radius
    front = pivot + u * hand.length * radius
    return np.array([back + n * base, front + n * tip, front - n * tip, back - n * base])


def _draw_dial_frame(spec: DialSpec, angles: Angles) -> tuple[GrayImage, npt.NDArray, float]:
    size = spec.size
    radius = spec.dial_radius * size
    center = np.array([size / 2, size / 2])
    pivot = center + np.array(spec.pivot_offset) * radius
    dial, ink = (DARK, LIGHT) if spec.dark_dial else (LIGHT, DARK)

    canvas = np.full((size, size), BACKGROUND, np.uint8)
    _circle(canvas, center, CASE_RADIUS * radius, CASE)
    _circle(canvas, center, radius, dial)
    if spec.markers:
        for hour in range(12):
            u = _direction(hour * 30)
            n = np.array([-u[1], u[0]])
            half = MARKER_WIDTH * radius * (1.5 if hour == 0 else 0.5)  # 12 is a double marker
            inner, outer = center + u * MARKER_INNER * radius, center + u * MARKER_OUTER * radius
            _fill(
                canvas,
                np.array([inner + n * half, outer + n * half, outer - n * half, inner - n * half]),
                ink,
            )

    second_hand = replace(SECOND_HAND, tail=spec.seconds_tail)
    for angle, hand in (
        (angles.hour, HOUR_HAND),
        (angles.minute, MINUTE_HAND),
        (angles.second, second_hand),
    ):
        _fill(canvas, _hand(pivot, angle, hand, radius), ink)
    _circle(canvas, pivot, CAP_RADIUS * radius, ink)
    return canvas, pivot, radius


def _rotation_matrix(axis: npt.NDArray[np.float64], angle: float) -> npt.NDArray[np.float64]:
    """Rodrigues: rotation by `angle` (radians) about the unit vector `axis`."""
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def _camera_homography(spec: DialSpec) -> npt.NDArray[np.float64]:
    """Dial frame → photo: rotate the watch in its plane, then view the plane tilted."""
    size = spec.size
    c = np.array([size / 2, size / 2])
    rot = math.radians(spec.rotation_deg)
    in_plane = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    axis_angle = math.radians(spec.tilt_axis_deg)
    tilt = _rotation_matrix(
        np.array([math.cos(axis_angle), math.sin(axis_angle), 0.0]), math.radians(spec.tilt_deg)
    )
    distance = spec.camera_distance * size

    def project(point: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        q = in_plane @ (point - c)
        p = tilt @ np.array([q[0], q[1], 0.0]) + np.array([0.0, 0.0, distance])
        return c + distance * p[:2] / p[2]  # focal length = distance: untilted maps 1:1

    corners = np.array([[0, 0], [size, 0], [size, size], [0, size]], np.float64)
    projected = np.array([project(p) for p in corners])
    return cv2.getPerspectiveTransform(corners.astype(np.float32), projected.astype(np.float32))


def _apply(h: npt.NDArray[np.float64], point: npt.NDArray[np.float64]) -> Point:
    x, y = cv2.perspectiveTransform(point.reshape(1, 1, 2).astype(np.float64), h)[0, 0]
    return float(x), float(y)


def render(spec: DialSpec) -> RenderedDial:
    """Draw a dial for `spec`, deterministic for a given `seed`."""
    angles = hand_angles(spec.hours, spec.minutes, spec.seconds)
    flat, pivot, radius = _draw_dial_frame(spec, angles)
    h = _camera_homography(spec)
    size = spec.size
    photo = cv2.warpPerspective(
        flat, h, (size, size), flags=cv2.INTER_LINEAR, borderValue=BACKGROUND
    ).astype(np.float32)

    if spec.glare > 0:
        ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
        gx, gy = spec.glare_center[0] * size, spec.glare_center[1] * size
        sigma = 0.18 * size
        photo += spec.glare * 255 * np.exp(-((xs - gx) ** 2 + (ys - gy) ** 2) / (2 * sigma**2))
    if spec.blur_sigma > 0:
        photo = cv2.GaussianBlur(photo, (0, 0), spec.blur_sigma)
    if spec.noise_sigma > 0:
        photo += np.random.default_rng(spec.seed).normal(0, spec.noise_sigma, photo.shape)

    center = np.array([size / 2, size / 2])
    twelve = center + _direction(0) * TWELVE_MARKER_RADIUS * radius
    truth = GroundTruth(
        angles=angles,
        pivot=_apply(h, pivot),
        dial_center=_apply(h, center),
        twelve=_apply(h, twelve),
        homography=h,
    )
    return RenderedDial(np.clip(photo, 0, 255).astype(np.uint8), truth)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a synthetic dial with a known time.")
    parser.add_argument("time", help="h:m:s, e.g. 10:08:37.5")
    parser.add_argument("-o", "--out", type=Path, default=Path("dial.png"))
    parser.add_argument("--rotation", type=float, default=0.0)
    parser.add_argument("--tilt", type=float, default=0.0)
    parser.add_argument("--tilt-axis", type=float, default=0.0)
    parser.add_argument("--dark", action="store_true", help="dark dial with light hands")
    parser.add_argument("--glare", type=float, default=0.0)
    parser.add_argument("--blur", type=float, default=0.0)
    parser.add_argument("--noise", type=float, default=0.0)
    parser.add_argument("--no-tail", action="store_true")
    args = parser.parse_args()

    h, m, s = args.time.split(":")
    spec = DialSpec(
        hours=int(h),
        minutes=int(m),
        seconds=float(s),
        rotation_deg=args.rotation,
        tilt_deg=args.tilt,
        tilt_axis_deg=args.tilt_axis,
        dark_dial=args.dark,
        glare=args.glare,
        blur_sigma=args.blur,
        noise_sigma=args.noise,
        seconds_tail=0.0 if args.no_tail else DialSpec.seconds_tail,
    )
    dial = render(spec)
    cv2.imwrite(str(args.out), dial.image)
    t = dial.truth
    print(f"wrote {args.out}")
    print(
        f"angles: hour {t.angles.hour:.3f}°  minute {t.angles.minute:.3f}°  "
        f"second {t.angles.second:.3f}°"
    )
    print(f"pivot {t.pivot[0]:.1f},{t.pivot[1]:.1f}  twelve {t.twelve[0]:.1f},{t.twelve[1]:.1f}")


if __name__ == "__main__":
    main()
