"""Shared test helpers."""

import io

from PIL import ExifTags, Image

from watchtiming.exif import CaptureExif


def make_image(fmt: str = "JPEG", **tags: str) -> bytes:
    """Encode a tiny image with the given Exif-IFD tags (DateTimeOriginal=…)."""
    exif = Image.Exif()
    exif[0x010F] = "TestMake"
    exif[0x0112] = 6
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    for name, value in tags.items():
        sub[getattr(ExifTags.Base, name).value] = value
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, fmt, exif=exif)
    return buf.getvalue()


def capture(
    dt: str | None = None, subsec: str | None = None, offset: str | None = None
) -> CaptureExif:
    """A CaptureExif with only the timestamp tags set."""
    return CaptureExif(
        format=None,
        make=None,
        model=None,
        orientation=None,
        datetime_original=dt,
        subsec_time_original=subsec,
        offset_time_original=offset,
    )
