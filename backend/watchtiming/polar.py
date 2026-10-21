"""The polar unwrap of a rectified dial and its contrast with the dial.

Pure functions: image in, result out. No file system, no framework code. Rows are clock angles
(degrees clockwise from 12 o'clock), columns the radius in pixels.
"""

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.geometry import GrayImage, Point

# Angular resolution of the polar unwrap: 0.25° per row (the seconds hand moves 6°/s).
ANGLE_BINS = 1440


def unwrap(
    image: npt.NDArray[np.uint8], center: Point, max_radius: float, angle_bins: int = ANGLE_BINS
) -> npt.NDArray[np.uint8]:
    """Polar image: row i = clock angle i·360/angle_bins, column j = radius j (pixels)."""
    radial_bins = max(1, int(round(max_radius)))
    polar = cv2.warpPolar(
        image, (radial_bins, angle_bins), center, max_radius,
        cv2.INTER_LINEAR + cv2.WARP_POLAR_LINEAR,
    )  # fmt: skip
    # OpenCV's row 0 points along +x (3 o'clock); clock angle 0 is 12 o'clock, 90° earlier.
    return np.roll(polar, angle_bins // 4, axis=0)


# Weight of color differences (Lab a, b) against brightness differences in `contrast`.
CHROMA_WEIGHT = 1.0


def contrast(
    polar: GrayImage, chroma: npt.NDArray[np.uint8] | None = None
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
