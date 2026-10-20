import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel, PlainSerializer
from starlette.concurrency import run_in_threadpool

from watchtiming.dial import DialNotFoundError, preprocess
from watchtiming.exif import CaptureExif, InvalidTimestampError, read_capture_exif
from watchtiming.imaging import InvalidImageError
from watchtiming.limits import BodySizeLimit
from watchtiming.pipeline import (
    HandsNotFoundError,
    locate_dial,
    photo_overlay,
    read_dial,
    read_with_hands,
)
from watchtiming.reading import UnreadableDialError, deviation_seconds
from watchtiming.reference import (
    FrameTiming,
    Platform,
    Reference,
    ReferenceSource,
    device_capture,
    reference_time,
)
from watchtiming.upload_log import save_upload, upload_dir

MAX_UPLOAD_BYTES = 30 * 1024 * 1024

app = FastAPI(title="watch-timing")
# Checked before parsing, so oversized uploads never reach disk. Room for multipart overhead;
# the per-file check in the handler stays as a second layer.
app.add_middleware(BodySizeLimit, max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024)


def _utc_millis(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# "2026-10-14T18:15:30.250Z": ECMAScript only guarantees Date.parse for 3 fractional digits.
UtcMillis = Annotated[datetime, PlainSerializer(_utc_millis, return_type=str, when_used="json")]


class ExifTags(BaseModel):
    make: str | None
    model: str | None
    orientation: int | None
    datetime_original: str | None
    subsec_time_original: str | None
    offset_time_original: str | None


class ProbeResult(BaseModel):
    sha256: str
    size: int
    content_type: str | None
    format: str | None
    exif: ExifTags
    reference_time_utc: UtcMillis | None
    reference_source: ReferenceSource | None
    frame_timing: FrameTiming | None
    platform: Platform | None
    # Milliseconds subtracted for camera latency; null = uncalibrated platform/timing.
    latency_correction_ms: float | None
    # A device time was sent, but the image's EXIF took precedence (likely a client bug).
    ignored_device_time: bool
    error: str | None


class PhotoPoint(BaseModel):
    x: float
    y: float


class HandOverlay(BaseModel):
    role: Literal["hour", "minute", "second", "other"]
    tip: PhotoPoint


class Overlay(BaseModel):
    """The detected geometry, in the upright photo's pixels (the coordinates of the tap)."""

    dial_center: PhotoPoint
    dial_semi_major: float
    dial_semi_minor: float
    dial_angle_deg: float
    pivot: PhotoPoint
    twelve: PhotoPoint
    hands: list[HandOverlay]


class DialReadingOut(BaseModel):
    hours: int  # 1–12 as shown on the dial
    minutes: int
    seconds: float | None  # null: withheld, not trustworthy enough
    confidence: float
    seconds_confidence: float
    needs_confirmation: bool
    reasons: list[str]
    corrected: bool  # the hands were placed by the user, not detected


class ReadResult(BaseModel):
    image_width: int  # upright photo, after EXIF orientation
    image_height: int
    reference_time_utc: UtcMillis | None
    reference_utc_offset_minutes: int | None  # the phone's local zone at capture
    reference_source: ReferenceSource | None
    latency_correction_ms: float | None
    timestamp_error: str | None
    reading: DialReadingOut | None
    overlay: Overlay | None
    reading_error: str | None
    # Dial − reference in seconds, positive = fast. Needs both and the dial's seconds.
    deviation_s: float | None


class ServerTime(BaseModel):
    server_time_utc: UtcMillis


async def _read_upload(file: UploadFile) -> tuple[bytes, CaptureExif]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is too large.")
    try:
        return data, read_capture_exif(data)
    except InvalidImageError as e:
        raise HTTPException(422, str(e)) from e


def _reference(exif, device_capture_time, frame_timing, platform):
    """(reference, device capture, error message)."""
    device = None
    try:
        device = device_capture(device_capture_time, frame_timing, platform)
        return reference_time(exif, device, now=datetime.now(UTC)), device, None
    except InvalidTimestampError as e:
        return None, device, str(e)


def _latency_ms(ref: Reference | None) -> float | None:
    if ref is None or ref.latency_correction is None:
        return None
    return ref.latency_correction.total_seconds() * 1000


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/time")
def server_time() -> ServerTime:
    """For measuring the device clock's offset (NTP-style round trip)."""
    return ServerTime(server_time_utc=datetime.now(UTC))


@app.post("/api/probe")
async def probe(
    file: UploadFile,
    device_capture_time: Annotated[datetime | None, Form()] = None,
    frame_timing: Annotated[FrameTiming | None, Form()] = None,
    platform: Annotated[Platform | None, Form()] = None,
) -> ProbeResult:
    """Report which reference time an upload would get. Persists nothing.

    `device_capture_time`, `frame_timing` and `platform` are sent together for frames from
    the in-app camera, which have no EXIF.
    """
    data, exif = await _read_upload(file)
    ref, device, error = _reference(exif, device_capture_time, frame_timing, platform)

    return ProbeResult(
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        content_type=file.content_type,
        format=exif.format,
        exif=ExifTags(
            make=exif.make,
            model=exif.model,
            orientation=exif.orientation,
            datetime_original=exif.datetime_original,
            subsec_time_original=exif.subsec_time_original,
            offset_time_original=exif.offset_time_original,
        ),
        reference_time_utc=ref.time if ref else None,
        reference_source=ref.source if ref else None,
        frame_timing=ref.device.timing if ref and ref.device else None,
        platform=ref.device.platform if ref and ref.device else None,
        latency_correction_ms=_latency_ms(ref),
        ignored_device_time=(
            device is not None and ref is not None and ref.source == ReferenceSource.EXIF
        ),
        error=error,
    )


def _point(p: tuple[float, float]) -> PhotoPoint:
    return PhotoPoint(x=p[0], y=p[1])


def _overlay(o) -> Overlay:
    return Overlay(
        dial_center=_point(o.dial_center),
        dial_semi_major=o.dial_axes[0],
        dial_semi_minor=o.dial_axes[1],
        dial_angle_deg=o.dial_angle_deg,
        pivot=_point(o.pivot),
        twelve=_point(o.twelve),
        hands=[HandOverlay(role=h.role, tip=_point(h.tip)) for h in o.hands],
    )


def _hand_tips(scale: float, *coords: float | None):
    """User-placed tips (photo pixels → processed): (hour, minute, second or None), or None
    when no hands were placed. Hour and minute are required together; seconds are optional."""
    hx, hy, mx, my, sx, sy = coords
    if all(c is None for c in coords):
        return None
    if None in (hx, hy, mx, my) or (sx is None) != (sy is None):
        raise HTTPException(422, "Send the hour and minute hand tips (and optionally seconds).")

    def tip(x, y):
        return (x * scale, y * scale)

    return tip(hx, hy), tip(mx, my), (tip(sx, sy) if sx is not None else None)


@app.post("/api/read")
async def read(
    file: UploadFile,
    tap_x: Annotated[float, Form()],
    tap_y: Annotated[float, Form()],
    device_capture_time: Annotated[datetime | None, Form()] = None,
    frame_timing: Annotated[FrameTiming | None, Form()] = None,
    platform: Annotated[Platform | None, Form()] = None,
    hour_x: Annotated[float | None, Form()] = None,
    hour_y: Annotated[float | None, Form()] = None,
    minute_x: Annotated[float | None, Form()] = None,
    minute_y: Annotated[float | None, Form()] = None,
    second_x: Annotated[float | None, Form()] = None,
    second_y: Annotated[float | None, Form()] = None,
) -> ReadResult:
    """Read the dial and compute the deviation from the capture time. Persists nothing (unless
    the dev-only WATCHTIMING_SAVE_UPLOADS is set, see upload_log.py).

    `tap_x`, `tap_y`: the 12 o'clock marker in the upright photo's pixels. The device fields are
    as for /api/probe; `device_capture_time` should carry the phone's local UTC offset.

    `hour_*`, `minute_*` (and optionally `second_*`): hand tips the user placed on the photo,
    in the same pixels. When given, they're used instead of detecting the hands.
    """
    data, exif = await _read_upload(file)
    ref, _, timestamp_error = _reference(exif, device_capture_time, frame_timing, platform)
    try:
        pre = await run_in_threadpool(preprocess, data)
    except InvalidImageError as e:
        raise HTTPException(422, str(e)) from e
    width, height = pre.original_size
    if not (0 <= tap_x < width and 0 <= tap_y < height):
        raise HTTPException(422, "The tapped point is outside the photo.")

    tap = (tap_x * pre.scale, tap_y * pre.scale)
    tips = _hand_tips(pre.scale, hour_x, hour_y, minute_x, minute_y, second_x, second_y)
    reading_out = overlay = reading_error = deviation = None
    try:
        if tips is None:
            reading = await run_in_threadpool(read_dial, pre.gray, tap, pre.color)
        else:
            geometry = await run_in_threadpool(locate_dial, pre.gray, tap, pre.color)
            reading = read_with_hands(geometry, *tips)
    except HandsNotFoundError as e:
        # The dial was found: return its geometry so the user can place the hands.
        reading_error = str(e)
        overlay = _overlay(photo_overlay(e.geometry, pre.scale))
    except (DialNotFoundError, UnreadableDialError) as e:
        reading_error = str(e)
    else:
        t, c = reading.time, reading.confidence
        reading_out = DialReadingOut(
            hours=t.hours or 12, minutes=t.minutes, seconds=t.seconds,
            confidence=c.overall, seconds_confidence=c.seconds,
            needs_confirmation=c.needs_confirmation and not reading.corrected,
            reasons=list(c.reasons), corrected=reading.corrected,
        )  # fmt: skip
        overlay = _overlay(photo_overlay(reading, pre.scale))
        if ref is not None and t.seconds is not None:
            deviation = deviation_seconds(t, ref.local_time)

    offset = ref.local_time.utcoffset() if ref else None
    result = ReadResult(
        image_width=width,
        image_height=height,
        reference_time_utc=ref.time if ref else None,
        reference_utc_offset_minutes=(
            round(offset.total_seconds() / 60) if offset is not None else None
        ),
        reference_source=ref.source if ref else None,
        latency_correction_ms=_latency_ms(ref),
        timestamp_error=timestamp_error,
        reading=reading_out,
        overlay=overlay,
        reading_error=reading_error,
        deviation_s=deviation,
    )
    if (root := upload_dir()) is not None:
        request = {
            "tap_x": tap_x,
            "tap_y": tap_y,
            "device_capture_time": device_capture_time,
            "frame_timing": frame_timing,
            "platform": platform,
            "filename": file.filename,
        }
        await run_in_threadpool(
            save_upload, root, data, file.content_type, request, result.model_dump_json(indent=2)
        )
    return result
