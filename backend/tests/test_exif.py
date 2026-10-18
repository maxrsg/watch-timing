import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from tests.helpers import capture, make_image
from watchtiming.exif import InvalidTimestampError, exif_capture_time, read_capture_exif
from watchtiming.imaging import InvalidImageError


def test_full_tags_to_utc_with_subseconds():
    data = make_image(
        DateTimeOriginal="2026:10:14 20:15:30",
        SubsecTimeOriginal="457",
        OffsetTimeOriginal="+02:00",
    )
    exif = read_capture_exif(data)
    assert exif.make == "TestMake"
    assert exif.orientation == 6
    assert exif_capture_time(exif) == datetime(2026, 10, 14, 18, 15, 30, 457_000, tzinfo=UTC)


def test_subsec_is_a_decimal_fraction():
    assert exif_capture_time(capture("2026:01:01 00:00:00", "05", "+00:00")).microsecond == 50_000


def test_missing_subsec_gives_whole_seconds():
    t = exif_capture_time(capture("2026:01:01 12:00:00", None, "-05:30"))
    assert t == datetime(2026, 1, 1, 17, 30, 0, tzinfo=UTC)


def test_offset_crossing_midnight():
    t = exif_capture_time(capture("2026:01:01 00:30:00", None, "+01:00"))
    assert t == datetime(2025, 12, 31, 23, 30, tzinfo=UTC)


def test_missing_offset_is_rejected():
    with pytest.raises(InvalidTimestampError, match="time zone"):
        exif_capture_time(capture("2026:01:01 12:00:00", "1", None))


def test_no_exif_is_rejected():
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "JPEG")
    exif = read_capture_exif(buf.getvalue())
    with pytest.raises(InvalidTimestampError, match="no capture timestamp"):
        exif_capture_time(exif)


@pytest.mark.parametrize(
    "dt,subsec,offset",
    [
        ("garbage", None, "+00:00"),
        ("2026:01:01 00:00:00", "x1", "+00:00"),
        ("2026:01:01 00:00:00", None, "02:00"),
        ("2026:01:01 00:00:00", "²", "+00:00"),
        ("2026:01:01 00:00:00", None, "+02:60"),
        ("2026:01:01 00:00:00", None, "+-1:00"),
        ("2026:01:01 00:00:00", None, "+25:00"),
        ("2026:01:01 00:00:00", None, "+2:00"),
    ],
)
def test_malformed_tags_are_rejected(dt, subsec, offset):
    with pytest.raises(InvalidTimestampError):
        exif_capture_time(capture(dt, subsec, offset))


def test_long_subsec_is_truncated_not_rounded():
    # Rounding would give 1_000_000 µs and crash datetime.replace.
    t = exif_capture_time(capture("2026:01:01 00:00:00", "9999999", "+00:00"))
    assert t.microsecond == 999_999
    assert t.second == 0


def test_negative_offset():
    t = exif_capture_time(capture("2026:01:01 12:00:00", None, "-03:30"))
    assert t == datetime(2026, 1, 1, 15, 30, tzinfo=UTC)


def test_decompression_bomb_is_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # 16×16 is > 2× this → error
    with pytest.raises(InvalidImageError, match="too large"):
        read_capture_exif(make_image())


def test_not_an_image():
    with pytest.raises(InvalidImageError):
        read_capture_exif(b"definitely not an image")


def test_heic_round_trip():
    data = make_image(
        "HEIF",
        DateTimeOriginal="2026:10:14 20:15:30",
        SubsecTimeOriginal="9",
        OffsetTimeOriginal="+02:00",
    )
    exif = read_capture_exif(data)
    assert exif.format == "HEIF"
    assert exif_capture_time(exif) == datetime(2026, 10, 14, 18, 15, 30, 900_000, tzinfo=UTC)
