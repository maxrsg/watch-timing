"""Dial detection. Step 1 so far: preprocessing (orientation, grayscale, downscale).

Pure functions: image in, result out. No file system, no framework code.
"""

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from watchtiming.imaging import (
    TRANSPOSED_ORIENTATIONS,
    open_image,
    orientation,
    read_exif,
    upright_gray,
)

# Long side of the image the CV pipeline works on. Enough for ±0.2 s seconds-hand precision
# on a dial that fills a good part of the frame, and keeps every stage fast.
PROCESS_LONG_SIDE = 1000

GrayImage = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Preprocessed:
    gray: GrayImage
    # Processed pixels per pixel of the upright original. Maps points the user tapped on the
    # (upright) photo into processed coordinates: processed = original * scale.
    scale: float
    # (width, height) of the upright original, after EXIF orientation.
    original_size: tuple[int, int]


def preprocess(data: bytes, long_side: int = PROCESS_LONG_SIDE) -> Preprocessed:
    """Decode image bytes → upright grayscale, downscaled to `long_side` (never upscaled)."""
    with open_image(data) as img:
        turn = orientation(read_exif(img))
        width, height = img.size
        if turn in TRANSPOSED_ORIENTATIONS:
            width, height = height, width
        if img.format == "JPEG":
            # Let the JPEG decoder skip detail we would throw away anyway (scales by 1/2^n,
            # never below the requested size).
            img.draft("L", (long_side, long_side))
        upright = upright_gray(img, turn)

    gray = np.asarray(upright, dtype=np.uint8)
    factor = long_side / max(gray.shape)
    if factor < 1:
        size = (round(gray.shape[1] * factor), round(gray.shape[0] * factor))
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    return Preprocessed(gray=gray, scale=gray.shape[1] / width, original_size=(width, height))
