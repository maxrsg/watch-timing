"""Decoding uploaded image bytes. Shared by EXIF reading and the CV pipeline.

Pure functions: bytes in, values out. No file system, no framework code.
"""

import io
import struct

import pillow_heif
from PIL import ExifTags, Image, UnidentifiedImageError

pillow_heif.register_heif_opener()

# Pillow warns above this many pixels and raises DecompressionBombError above twice as many.
# 50 MP covers a 48 MP phone sensor; anything over 100 MP is rejected.
Image.MAX_IMAGE_PIXELS = 50_000_000

# What Pillow's EXIF/TIFF parser and decoders can raise on malformed files (found by fuzzing:
# struct.error, TypeError and AttributeError besides the documented OSError/ValueError).
MALFORMED_IMAGE_ERRORS = (
    OSError, ValueError, TypeError, AttributeError, KeyError, IndexError, SyntaxError,
    struct.error,
)  # fmt: skip

# EXIF orientation → the transpose that makes the image upright (1 = already upright).
_UPRIGHT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
# Orientations that swap width and height (90° rotations).
TRANSPOSED_ORIENTATIONS = frozenset({5, 6, 7, 8})


class InvalidImageError(ValueError):
    """The bytes are not an image we can open."""


def open_image(data: bytes) -> Image.Image:
    """Open JPEG/HEIC/PNG bytes lazily (header only; pixels are decoded on first use)."""
    try:
        return Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:
        raise InvalidImageError("Image dimensions are too large.") from e
    except (UnidentifiedImageError, *MALFORMED_IMAGE_ERRORS) as e:
        raise InvalidImageError("File is not a readable image.") from e


def read_exif(img: Image.Image) -> Image.Exif:
    try:
        return img.getexif()
    except MALFORMED_IMAGE_ERRORS as e:
        raise InvalidImageError("The image's metadata is unreadable.") from e


def orientation(exif: Image.Exif) -> int:
    """EXIF orientation 1–8. Missing or invalid values count as 1 (upright), as in browsers."""
    value = exif.get(ExifTags.Base.Orientation)
    return value if isinstance(value, int) and 1 <= value <= 8 else 1


def upright_rgb(img: Image.Image, image_orientation: int) -> Image.Image:
    """Decode to RGB and apply the orientation.

    Transposes directly instead of using ImageOps.exif_transpose, which re-serializes the
    EXIF block and crashes on malformed metadata.
    """
    try:
        rgb = img.convert("RGB")
    except MALFORMED_IMAGE_ERRORS as e:
        raise InvalidImageError("File is not a readable image.") from e
    method = _UPRIGHT.get(image_orientation)
    return rgb.transpose(method) if method is not None else rgb
