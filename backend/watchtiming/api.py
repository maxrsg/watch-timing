import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel, PlainSerializer
from starlette.concurrency import run_in_threadpool

from watchtiming.dial import preprocess
from watchtiming.exif import CaptureExif, InvalidTimestampError, read_capture_exif
from watchtiming.geometry import Point
from watchtiming.imaging import InvalidImageError
from watchtiming.limits import BodySizeLimit
from watchtiming.measure import HandTips, Measurement, measure, measure_typed
from watchtiming.pipeline import OverlayGeometry
from watchtiming.reading import DialTime
from watchtiming.reference import (
    DeviceCapture,
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
    # None: detected. "hands": the user placed the hands. "typed": the user typed the time.
    correction: Literal["hands", "typed"] | None


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


def _reference(
    exif: CaptureExif,
    device_capture_time: datetime | None,
    frame_timing: FrameTiming | None,
    platform: Platform | None,
) -> tuple[Reference | None, DeviceCapture | None, str | None]:
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


def _point(p: Point) -> PhotoPoint:
    return PhotoPoint(x=p[0], y=p[1])


def _overlay(o: OverlayGeometry) -> Overlay:
    return Overlay(
        dial_center=_point(o.dial_center),
        dial_semi_major=o.dial_axes[0],
        dial_semi_minor=o.dial_axes[1],
        dial_angle_deg=o.dial_angle_deg,
        pivot=_point(o.pivot),
        twelve=_point(o.twelve),
        hands=[HandOverlay(role=h.role, tip=_point(h.tip)) for h in o.hands],
    )


# A hand-tip coordinate. Pydantic accepts "nan" and "inf" for floats by default; they would
# reach the geometry and crash the read (500), so they're rejected here (422).
TipCoord = Annotated[float | None, Form(allow_inf_nan=False)]


def _hand_tips(
    hour_x: TipCoord = None,
    hour_y: TipCoord = None,
    minute_x: TipCoord = None,
    minute_y: TipCoord = None,
    second_x: TipCoord = None,
    second_y: TipCoord = None,
) -> HandTips | None:
    """Hand tips the user placed on the photo, or None when none were sent. Hour and minute are
    required together; seconds are optional."""
    coords = (hour_x, hour_y, minute_x, minute_y, second_x, second_y)
    if all(c is None for c in coords):
        return None
    if (
        hour_x is None
        or hour_y is None
        or minute_x is None
        or minute_y is None
        or (second_x is None) != (second_y is None)
    ):
        raise HTTPException(422, "Send the hour and minute hand tips (and optionally seconds).")
    second = (second_x, second_y) if second_x is not None and second_y is not None else None
    return HandTips((hour_x, hour_y), (minute_x, minute_y), second)


def _typed_time(
    typed_hours: Annotated[int | None, Form(ge=1, le=12)] = None,
    typed_minutes: Annotated[int | None, Form(ge=0, le=59)] = None,
    typed_seconds: Annotated[float | None, Form(ge=0, lt=60, allow_inf_nan=False)] = None,
) -> DialTime | None:
    """The time the user typed (as the dial shows it, 1–12 h), or None when none was sent. All
    three are required together: a deviation needs the seconds."""
    fields = (typed_hours, typed_minutes, typed_seconds)
    if all(f is None for f in fields):
        return None
    if typed_hours is None or typed_minutes is None or typed_seconds is None:
        raise HTTPException(422, "Send the typed hours, minutes and seconds together.")
    return DialTime(typed_hours % 12, typed_minutes, typed_seconds)


def _reference_fields(ref: Reference | None, timestamp_error: str | None) -> dict:
    """The ReadResult fields that describe the reference time."""
    offset = ref.local_time.utcoffset() if ref else None
    return dict(
        reference_time_utc=ref.time if ref else None,
        reference_utc_offset_minutes=(
            round(offset.total_seconds() / 60) if offset is not None else None
        ),
        reference_source=ref.source if ref else None,
        latency_correction_ms=_latency_ms(ref),
        timestamp_error=timestamp_error,
    )


def _typed_result(
    size: tuple[int, int], typed: DialTime, ref: Reference | None, timestamp_error: str | None
) -> ReadResult:
    """A typed time: the user's reading is taken as is, the dial isn't read."""
    width, height = size
    return ReadResult(
        image_width=width,
        image_height=height,
        **_reference_fields(ref, timestamp_error),
        reading=DialReadingOut(
            hours=typed.dial_hours,
            minutes=typed.minutes,
            seconds=typed.seconds,
            # The user's word, not the CV's certainty: `correction` says so.
            confidence=1.0,
            seconds_confidence=1.0,
            needs_confirmation=False,
            reasons=[],
            correction="typed",
        ),
        overlay=None,
        reading_error=None,
        deviation_s=measure_typed(typed, ref),
    )


def _reading_out(m: Measurement) -> DialReadingOut | None:
    if m.reading is None:
        return None
    t, c = m.reading.time, m.reading.confidence
    return DialReadingOut(
        hours=t.dial_hours, minutes=t.minutes, seconds=t.seconds,
        confidence=c.overall, seconds_confidence=c.seconds,
        needs_confirmation=m.reading.needs_confirmation,
        reasons=list(c.reasons), correction="hands" if m.reading.corrected else None,
    )  # fmt: skip


@app.post("/api/read")
async def read(
    file: UploadFile,
    tips: Annotated[HandTips | None, Depends(_hand_tips)],
    typed: Annotated[DialTime | None, Depends(_typed_time)],
    tap_x: Annotated[float | None, Form()] = None,
    tap_y: Annotated[float | None, Form()] = None,
    device_capture_time: Annotated[datetime | None, Form()] = None,
    frame_timing: Annotated[FrameTiming | None, Form()] = None,
    platform: Annotated[Platform | None, Form()] = None,
    expected_deviation_s: Annotated[float | None, Form()] = None,
) -> ReadResult:
    """Read the dial and compute the deviation from the capture time. Persists nothing (unless
    the dev-only WATCHTIMING_SAVE_UPLOADS is set, see upload_log.py).

    `tap_x`, `tap_y`: the 12 o'clock marker in the upright photo's pixels (required unless the
    time is typed). The device fields are as for /api/probe; `device_capture_time` should carry
    the phone's local UTC offset.

    `hour_*`, `minute_*` (and optionally `second_*`): hand tips the user placed on the photo,
    in the same pixels. When given, they're used instead of detecting the hands.

    `typed_hours` (1–12), `typed_minutes`, `typed_seconds`: the time the user read off the dial
    and typed. When given, the dial isn't read at all (no overlay); the photo only provides the
    reference time. Typed reads aren't kept by WATCHTIMING_SAVE_UPLOADS (it saves the CV stages).

    `expected_deviation_s`: the watch's predicted deviation (dial − reference, positive = fast),
    e.g. from the last measurement and the rate. With a reference time it decides which minute
    a minute hand near a minute boundary means, and which of two hands that could be swapped
    is the hour hand. It never changes the seconds read.
    """
    if typed is not None and tips is not None:
        raise HTTPException(422, "Send either a typed time or hand tips, not both.")
    data, exif = await _read_upload(file)
    ref, _, timestamp_error = _reference(exif, device_capture_time, frame_timing, platform)
    try:
        pre = await run_in_threadpool(preprocess, data)
    except InvalidImageError as e:
        raise HTTPException(422, str(e)) from e
    width, height = pre.original_size
    if typed is not None:
        return _typed_result((width, height), typed, ref, timestamp_error)
    if tap_x is None or tap_y is None:
        raise HTTPException(422, "Tap the 12 o'clock marker (or type the time).")
    if not (0 <= tap_x < width and 0 <= tap_y < height):
        raise HTTPException(422, "The tapped point is outside the photo.")

    m = await run_in_threadpool(measure, pre, (tap_x, tap_y), ref, tips, expected_deviation_s)
    result = ReadResult(
        image_width=width,
        image_height=height,
        **_reference_fields(ref, timestamp_error),
        reading=_reading_out(m),
        overlay=_overlay(m.overlay) if m.overlay is not None else None,
        reading_error=m.reading_error,
        deviation_s=m.deviation_s,
    )
    if (root := upload_dir()) is not None:
        request = {
            "tap_x": tap_x,
            "tap_y": tap_y,
            "hand_tips": asdict(tips) if tips is not None else None,
            "device_capture_time": device_capture_time,
            "frame_timing": frame_timing,
            "platform": platform,
            "expected_deviation_s": expected_deviation_s,
            "filename": file.filename,
        }
        result_json = result.model_dump_json(indent=2)
        await run_in_threadpool(
            save_upload, root, data, file.content_type, request, pre, m, result_json
        )
    return result
