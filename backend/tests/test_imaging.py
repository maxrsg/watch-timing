"""The pixel limit: checked from the header, before anything is decoded."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.helpers import make_image
from watchtiming import imaging
from watchtiming.api import app
from watchtiming.imaging import InvalidImageError, open_image

client = TestClient(app)
# Pillow warns above 50 MP before our check rejects the image: expected here.
pytestmark = pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")


def png(width: int, height: int) -> bytes:
    """A 1-bit PNG: tens of megapixels in a few KB."""
    buf = io.BytesIO()
    Image.new("1", (width, height)).save(buf, "PNG")
    return buf.getvalue()


# 60 MP: under Pillow's own error threshold (2 × 50 MP), so only the explicit check stops it.
TOO_MANY = png(10_000, 6_000)


def test_over_the_limit_is_rejected():
    with pytest.raises(InvalidImageError, match="50 megapixels"):
        open_image(TOO_MANY)


def test_just_under_the_limit_opens():
    with open_image(png(7_000, 7_000)) as img:  # 49 MP
        assert img.size == (7_000, 7_000)


def test_heic_is_checked_too(monkeypatch):
    monkeypatch.setattr(imaging, "MAX_PIXELS", 100)  # 16×16 = 256
    with pytest.raises(InvalidImageError, match="50 megapixels"):
        open_image(make_image("HEIF"))


@pytest.mark.parametrize("path", ["/api/read", "/api/probe"])
def test_endpoints_reject_it(path):
    r = client.post(
        path,
        files={"file": ("big.png", TOO_MANY, "image/png")},
        data={"tap_x": 10, "tap_y": 10},
    )
    assert r.status_code == 422
    assert "50 megapixels" in r.json()["detail"]
