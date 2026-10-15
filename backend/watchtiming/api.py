import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel, PlainSerializer

from watchtiming.exif import InvalidImageError, InvalidTimestampError, read_capture_exif
from watchtiming.limits import BodySizeLimit
from watchtiming.reference import (
    FrameTiming,
    Platform,
    ReferenceSource,
    device_capture,
    reference_time,
)

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


class ServerTime(BaseModel):
    server_time_utc: UtcMillis


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
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is too large.")
    try:
        exif = read_capture_exif(data)
    except InvalidImageError as e:
        raise HTTPException(422, str(e)) from e

    ref, error, device = None, None, None
    try:
        device = device_capture(device_capture_time, frame_timing, platform)
        ref = reference_time(exif, device, now=datetime.now(UTC))
    except InvalidTimestampError as e:
        error = str(e)

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
        latency_correction_ms=(
            ref.latency_correction.total_seconds() * 1000
            if ref and ref.latency_correction is not None
            else None
        ),
        ignored_device_time=(
            device is not None and ref is not None and ref.source == ReferenceSource.EXIF
        ),
        error=error,
    )
