"""Capture timestamp from EXIF → UTC, with subseconds.

Pure functions: bytes in, values out. No file system, no framework code.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from PIL import ExifTags

from watchtiming.imaging import MALFORMED_IMAGE_ERRORS, InvalidImageError, open_image, read_exif

_Tag = ExifTags.Base


class InvalidTimestampError(ValueError):
    """No usable capture time: missing, malformed or implausible."""


@dataclass(frozen=True)
class CaptureExif:
    format: str | None
    make: str | None
    model: str | None
    orientation: int | None
    datetime_original: str | None
    subsec_time_original: str | None
    offset_time_original: str | None


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    text = str(value).strip().strip("\x00").strip()
    return text or None


def read_capture_exif(data: bytes) -> CaptureExif:
    """Read the capture-related EXIF tags from JPEG or HEIC bytes."""
    with open_image(data) as img:
        fmt = img.format
        exif = read_exif(img)
    try:
        sub = exif.get_ifd(ExifTags.IFD.Exif)  # parsed lazily, so malformed data fails here
    except MALFORMED_IMAGE_ERRORS as e:
        raise InvalidImageError("The image's metadata is unreadable.") from e

    orientation = exif.get(_Tag.Orientation)
    return CaptureExif(
        format=fmt,
        make=_text(exif.get(_Tag.Make)),
        model=_text(exif.get(_Tag.Model)),
        orientation=orientation if isinstance(orientation, int) else None,
        datetime_original=_text(sub.get(_Tag.DateTimeOriginal)),
        subsec_time_original=_text(sub.get(_Tag.SubsecTimeOriginal)),
        offset_time_original=_text(sub.get(_Tag.OffsetTimeOriginal)),
    )


_SUBSEC = re.compile(r"[0-9]+")
_OFFSET = re.compile(r"([+-])([0-9]{2}):([0-9]{2})")


def _parse_subsec(subsec: str | None) -> int:
    """'05' → 50_000 µs, a decimal fraction truncated to µs. Missing → 0 (whole seconds)."""
    if subsec is None:
        return 0
    if not _SUBSEC.fullmatch(subsec):
        raise InvalidTimestampError(f"Invalid SubSecTimeOriginal: {subsec!r}")
    return int(subsec[:6].ljust(6, "0"))


def _parse_offset(offset: str) -> timezone:
    """'+02:00' → timezone(+2h). Real-world offsets are within ±14:00."""
    match = _OFFSET.fullmatch(offset)
    if not match:
        raise InvalidTimestampError(f"Invalid OffsetTimeOriginal: {offset!r}")
    sign, hours, minutes = match[1], int(match[2]), int(match[3])
    if hours > 14 or minutes > 59:
        raise InvalidTimestampError(f"Invalid OffsetTimeOriginal: {offset!r}")
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(delta if sign == "+" else -delta)


def exif_timezone(exif: CaptureExif) -> timezone:
    """The photo's local time zone (from OffsetTimeOriginal): the zone the phone, and most
    likely the watch, was set to."""
    if exif.offset_time_original is None:
        raise InvalidTimestampError("The photo's capture timestamp has no time zone offset.")
    return _parse_offset(exif.offset_time_original)


def exif_capture_time(exif: CaptureExif) -> datetime:
    """When the camera says the photo was taken, in UTC (the phone's clock).

    Use `reference.reference_time` for the measurement's reference time.
    """
    if exif.datetime_original is None:
        raise InvalidTimestampError(
            "The photo has no capture timestamp. Screenshots, images from messaging "
            "apps and edited exports can't be used; take the photo with the camera."
        )
    if exif.offset_time_original is None:
        raise InvalidTimestampError("The photo's capture timestamp has no time zone offset.")

    try:
        local = datetime.strptime(exif.datetime_original, "%Y:%m:%d %H:%M:%S")
    except ValueError as e:
        raise InvalidTimestampError(f"Invalid DateTimeOriginal: {exif.datetime_original!r}") from e

    local = local.replace(
        microsecond=_parse_subsec(exif.subsec_time_original),
        tzinfo=_parse_offset(exif.offset_time_original),
    )
    try:
        return local.astimezone(UTC)
    except OverflowError as e:  # e.g. year 1 with a positive offset
        raise InvalidTimestampError(f"Invalid DateTimeOriginal: {exif.datetime_original!r}") from e
