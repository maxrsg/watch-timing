import io

import numpy as np
import pytest
from PIL import Image

from watchtiming.dial import PROCESS_LONG_SIDE, preprocess
from watchtiming.imaging import InvalidImageError


def encode(img: Image.Image, fmt: str = "JPEG", orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, fmt, exif=exif)
    return buf.getvalue()


def test_downscales_long_side_and_reports_scale():
    result = preprocess(encode(Image.new("RGB", (3000, 2000), "gray")))
    assert result.gray.dtype == np.uint8
    assert result.gray.ndim == 2
    assert result.gray.shape == (667, PROCESS_LONG_SIDE)
    assert result.original_size == (3000, 2000)
    assert result.scale == pytest.approx(1000 / 3000)


def test_small_images_are_not_upscaled():
    result = preprocess(encode(Image.new("RGB", (400, 300), "gray")))
    assert result.gray.shape == (300, 400)
    assert result.scale == 1


def test_exif_orientation_is_applied():
    # Left third white. Orientation 6 = display rotated 90° clockwise → white ends up on top.
    img = Image.new("L", (300, 100), 0)
    img.paste(255, (0, 0, 100, 100))
    result = preprocess(encode(img, orientation=6))
    assert result.gray.shape == (300, 100)
    assert result.original_size == (100, 300)
    assert result.gray[:100].mean() > 200
    assert result.gray[200:].mean() < 50


def test_scale_maps_upright_original_coordinates():
    # A 4000×3000 photo with orientation 6 is 3000×4000 upright; its long side becomes 1000.
    result = preprocess(encode(Image.new("RGB", (4000, 3000)), orientation=6))
    assert result.original_size == (3000, 4000)
    assert result.gray.shape == (1000, 750)
    assert result.scale == pytest.approx(0.25)


@pytest.mark.parametrize("fmt", ["PNG", "HEIF"])
def test_other_formats(fmt):
    result = preprocess(encode(Image.new("RGB", (1200, 800), "white"), fmt))
    assert result.gray.shape == (667, 1000)
    assert result.gray.mean() > 250


def test_truncated_image_is_rejected():
    data = encode(Image.effect_noise((800, 800), 50).convert("RGB"))
    with pytest.raises(InvalidImageError):
        preprocess(data[: len(data) // 2])
