import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, PlainSerializer, StringConstraints
from starlette.concurrency import run_in_threadpool

from watchtiming import store
from watchtiming.accuracy import RateFit, RatePoint, expected_deviation, fit_rate, source_key
from watchtiming.dial import preprocess
from watchtiming.exif import CaptureExif, InvalidTimestampError, read_capture_exif
from watchtiming.geometry import Point
from watchtiming.imaging import InvalidImageError
from watchtiming.limits import BodySizeLimit
from watchtiming.measure import HandTips, Measurement, measure, measure_typed
from watchtiming.pipeline import OverlayGeometry
from watchtiming.reading import DialTime, deviation_seconds
from watchtiming.reference import (
    EARLIEST_CAPTURE,
    MAX_CLOCK_AHEAD,
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
    frame_timing: FrameTiming | None  # device clock only
    platform: Platform | None  # device clock only
    latency_correction_ms: float | None
    timestamp_error: str | None
    image_sha256: str
    # The deviation the reading was steered with: sent, or predicted from the watch's session.
    expected_deviation_s: float | None
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
        frame_timing=ref.device.timing if ref and ref.device else None,
        platform=ref.device.platform if ref and ref.device else None,
        latency_correction_ms=_latency_ms(ref),
        timestamp_error=timestamp_error,
    )


def _typed_result(
    size: tuple[int, int],
    sha256: str,
    typed: DialTime,
    ref: Reference | None,
    timestamp_error: str | None,
) -> ReadResult:
    """A typed time: the user's reading is taken as is, the dial isn't read."""
    width, height = size
    return ReadResult(
        image_width=width,
        image_height=height,
        **_reference_fields(ref, timestamp_error),
        image_sha256=sha256,
        expected_deviation_s=None,
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


# --- Watches: owner and database -----------------------------------------------------------


def get_db() -> Iterator[sqlite3.Connection]:
    conn = store.connect(store.db_path())
    try:
        yield conn
    finally:
        conn.close()


def _owner_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as e:
        raise HTTPException(422, "X-Owner-Id must be a UUID.") from e


def require_owner(x_owner_id: Annotated[str, Header()]) -> str:
    """No login yet: the browser generates an anonymous owner ID, keeps it and sends it."""
    return _owner_id(x_owner_id)


def optional_owner(x_owner_id: Annotated[str | None, Header()] = None) -> str | None:
    return _owner_id(x_owner_id) if x_owner_id is not None else None


Db = Annotated[sqlite3.Connection, Depends(get_db)]
Owner = Annotated[str, Depends(require_owner)]


def _watch_or_404(db: sqlite3.Connection, owner: str, watch_id: int) -> store.Watch:
    watch = store.get_watch(db, owner, watch_id)
    if watch is None:
        raise HTTPException(404, "Watch not found.")
    return watch


def _rate_points(measurements: list[store.SavedMeasurement]) -> list[RatePoint]:
    return [
        RatePoint(
            m.data.reference_time_utc,
            m.data.deviation_s,
            source_key(m.data.reference_source, m.data.platform, m.data.frame_timing),
        )
        for m in measurements
    ]


def _predicted_deviation(
    db: sqlite3.Connection, owner: str | None, watch_id: int, ref: Reference | None
) -> float | None:
    """The deviation the watch's current session predicts for this photo."""
    if owner is None:
        raise HTTPException(422, "Send X-Owner-Id with watch_id.")
    watch = _watch_or_404(db, owner, watch_id)
    if ref is None:
        return None
    points = _rate_points(store.measurements(db, store.current_session(db, watch)))
    platform = ref.device.platform if ref.device else None
    timing = ref.device.timing if ref.device else None
    return expected_deviation(points, ref.time, source_key(ref.source, platform, timing))


@app.post("/api/read")
async def read(
    file: UploadFile,
    tips: Annotated[HandTips | None, Depends(_hand_tips)],
    typed: Annotated[DialTime | None, Depends(_typed_time)],
    db: Db,
    owner: Annotated[str | None, Depends(optional_owner)],
    tap_x: Annotated[float | None, Form()] = None,
    tap_y: Annotated[float | None, Form()] = None,
    device_capture_time: Annotated[datetime | None, Form()] = None,
    frame_timing: Annotated[FrameTiming | None, Form()] = None,
    platform: Annotated[Platform | None, Form()] = None,
    expected_deviation_s: Annotated[float | None, Form(allow_inf_nan=False)] = None,
    watch_id: Annotated[int | None, Form()] = None,
) -> ReadResult:
    """Read the dial and compute the deviation from the capture time. Persists nothing (unless
    the dev-only WATCHTIMING_SAVE_UPLOADS is set, see upload_log.py); a reading is saved to a
    watch with POST /api/watches/{id}/measurements.

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

    `watch_id` (with the X-Owner-Id header): the watch being measured. Without an
    `expected_deviation_s`, its current session predicts one.
    """
    if typed is not None and tips is not None:
        raise HTTPException(422, "Send either a typed time or hand tips, not both.")
    data, exif = await _read_upload(file)
    sha256 = hashlib.sha256(data).hexdigest()
    ref, _, timestamp_error = _reference(exif, device_capture_time, frame_timing, platform)
    if watch_id is not None and expected_deviation_s is None:
        expected_deviation_s = _predicted_deviation(db, owner, watch_id, ref)
    try:
        pre = await run_in_threadpool(preprocess, data)
    except InvalidImageError as e:
        raise HTTPException(422, str(e)) from e
    width, height = pre.original_size
    if typed is not None:
        return _typed_result((width, height), sha256, typed, ref, timestamp_error)
    if tap_x is None or tap_y is None:
        raise HTTPException(422, "Tap the 12 o'clock marker (or type the time).")
    if not (0 <= tap_x < width and 0 <= tap_y < height):
        raise HTTPException(422, "The tapped point is outside the photo.")

    m = await run_in_threadpool(measure, pre, (tap_x, tap_y), ref, tips, expected_deviation_s)
    result = ReadResult(
        image_width=width,
        image_height=height,
        **_reference_fields(ref, timestamp_error),
        image_sha256=sha256,
        expected_deviation_s=expected_deviation_s,
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
            "watch_id": watch_id,
            "filename": file.filename,
        }
        result_json = result.model_dump_json(indent=2)
        await run_in_threadpool(
            save_upload, root, data, file.content_type, request, pre, m, result_json
        )
    return result


# --- Watches: endpoints ---------------------------------------------------------------------

WatchName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class WatchIn(BaseModel):
    name: WatchName


class RateOut(BaseModel):
    """The session's rate: one slope, a separate intercept per reference source."""

    rate_s_per_day: float  # positive = gains time
    intercepts: dict[str, float]  # each source's deviation at `epoch`
    epoch: UtcMillis
    n: int
    span_hours: float
    residual_std_s: float | None
    short_span: bool  # under 24 h: shown, but not trustworthy yet
    mixed_sources: bool


class MeasurementOut(BaseModel):
    id: int
    created_at: UtcMillis
    reference_time_utc: UtcMillis
    reference_utc_offset_minutes: int
    reference_source: ReferenceSource
    platform: Platform | None
    frame_timing: FrameTiming | None
    source_key: str  # the group its constant offset belongs to (see RateOut.intercepts)
    latency_correction_ms: float | None
    hours: int  # 1–12 as shown on the dial
    minutes: int
    seconds: float
    deviation_s: float  # dial − reference, positive = fast
    confidence: float
    seconds_confidence: float
    correction: Literal["hands", "typed"] | None


class SessionOut(BaseModel):
    id: int
    started_at: UtcMillis
    measurements: list[MeasurementOut]  # by reference time
    rate: RateOut | None  # None until two measurements at different times


class WatchSummary(BaseModel):
    id: int
    name: str
    created_at: UtcMillis
    # The current session (since the watch was last set):
    measurement_count: int
    latest_deviation_s: float | None
    rate: RateOut | None


class WatchDetail(BaseModel):
    id: int
    name: str
    created_at: UtcMillis
    sessions: list[SessionOut]  # newest (current) first


class MeasurementIn(BaseModel):
    """A reading to save, as /api/read returned it (or as the user corrected or typed it). The
    deviation is recomputed here from the dial time and the reference."""

    reference_time_utc: datetime
    reference_utc_offset_minutes: int = Field(ge=-14 * 60, le=14 * 60)
    reference_source: ReferenceSource
    platform: Platform | None = None
    frame_timing: FrameTiming | None = None
    latency_correction_ms: float | None = Field(default=None, allow_inf_nan=False)
    clock_offset_ms: float | None = Field(default=None, allow_inf_nan=False)
    hours: int = Field(ge=1, le=12)
    minutes: int = Field(ge=0, le=59)
    seconds: float = Field(ge=0, lt=60, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1)
    seconds_confidence: float = Field(ge=0, le=1)
    correction: Literal["hands", "typed"] | None = None
    overlay: Overlay | None = None
    tap: PhotoPoint | None = None
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _rate_out(fit: RateFit | None) -> RateOut | None:
    return RateOut(**asdict(fit)) if fit is not None else None


def _measurement_out(m: store.SavedMeasurement) -> MeasurementOut:
    d = m.data
    return MeasurementOut(
        id=m.id,
        created_at=m.created_at,
        reference_time_utc=d.reference_time_utc,
        reference_utc_offset_minutes=d.reference_utc_offset_minutes,
        reference_source=ReferenceSource(d.reference_source),
        platform=Platform(d.platform) if d.platform else None,
        frame_timing=FrameTiming(d.frame_timing) if d.frame_timing else None,
        source_key=source_key(d.reference_source, d.platform, d.frame_timing),
        latency_correction_ms=d.latency_correction_ms,
        hours=d.dial_hours,
        minutes=d.dial_minutes,
        seconds=d.dial_seconds,
        deviation_s=d.deviation_s,
        confidence=d.confidence,
        seconds_confidence=d.seconds_confidence,
        correction=d.correction,  # type: ignore[arg-type]  # only ever stored from MeasurementIn
    )


def _summary(db: sqlite3.Connection, watch: store.Watch) -> WatchSummary:
    ms = store.measurements(db, store.current_session(db, watch))
    latest = max(ms, key=lambda m: m.data.reference_time_utc) if ms else None
    return WatchSummary(
        id=watch.id,
        name=watch.name,
        created_at=watch.created_at,
        measurement_count=len(ms),
        latest_deviation_s=latest.data.deviation_s if latest else None,
        rate=_rate_out(fit_rate(_rate_points(ms))),
    )


def _detail(db: sqlite3.Connection, watch: store.Watch) -> WatchDetail:
    sessions = []
    for s in store.sessions(db, watch):
        ms = store.measurements(db, s)
        sessions.append(
            SessionOut(
                id=s.id,
                started_at=s.started_at,
                measurements=[_measurement_out(m) for m in ms],
                rate=_rate_out(fit_rate(_rate_points(ms))),
            )
        )
    return WatchDetail(id=watch.id, name=watch.name, created_at=watch.created_at, sessions=sessions)


@app.get("/api/watches")
def list_watches(db: Db, owner: Owner) -> list[WatchSummary]:
    """The owner's watches, oldest first, with their current session's rate."""
    return [_summary(db, w) for w in store.list_watches(db, owner)]


@app.post("/api/watches", status_code=201)
def create_watch(body: WatchIn, db: Db, owner: Owner) -> WatchSummary:
    """A new watch; its first session starts now."""
    return _summary(db, store.create_watch(db, owner, body.name, datetime.now(UTC)))


@app.get("/api/watches/{watch_id}")
def get_watch(watch_id: int, db: Db, owner: Owner) -> WatchDetail:
    """The watch with all its sessions (newest first), their measurements and rates."""
    return _detail(db, _watch_or_404(db, owner, watch_id))


@app.patch("/api/watches/{watch_id}")
def rename_watch(watch_id: int, body: WatchIn, db: Db, owner: Owner) -> WatchSummary:
    if not store.rename_watch(db, owner, watch_id, body.name):
        raise HTTPException(404, "Watch not found.")
    return _summary(db, _watch_or_404(db, owner, watch_id))


@app.delete("/api/watches/{watch_id}", status_code=204)
def delete_watch(watch_id: int, db: Db, owner: Owner) -> Response:
    """Deletes the watch with all its sessions and measurements."""
    if not store.delete_watch(db, owner, watch_id):
        raise HTTPException(404, "Watch not found.")
    return Response(status_code=204)


@app.post("/api/watches/{watch_id}/sessions", status_code=201)
def start_session(watch_id: int, db: Db, owner: Owner) -> WatchDetail:
    """The watch was set: a new session starts, and the rate starts over. Rates are never
    computed across sessions."""
    watch = _watch_or_404(db, owner, watch_id)
    store.start_session(db, watch, datetime.now(UTC))
    return _detail(db, watch)


def _measurement_data(body: MeasurementIn, now: datetime) -> store.MeasurementData:
    """Check a reading to save and recompute its deviation."""
    if body.reference_time_utc.tzinfo is None:
        raise HTTPException(422, "reference_time_utc must include a time zone.")
    ref_utc = body.reference_time_utc.astimezone(UTC)
    if not EARLIEST_CAPTURE <= ref_utc <= now + MAX_CLOCK_AHEAD:
        raise HTTPException(422, "The reference time is implausible.")
    device_fields = (body.platform, body.frame_timing)
    if body.reference_source == ReferenceSource.DEVICE_CLOCK:
        device_fields_ok = all(f is not None for f in device_fields)
    else:
        device_fields_ok = all(f is None for f in device_fields)
    if not device_fields_ok:
        raise HTTPException(
            422, "Platform and frame timing are sent for device-clock references only."
        )
    local = ref_utc.astimezone(timezone(timedelta(minutes=body.reference_utc_offset_minutes)))
    deviation = deviation_seconds(DialTime(body.hours % 12, body.minutes, body.seconds), local)
    geometry = (
        json.dumps(
            {
                "overlay": body.overlay.model_dump() if body.overlay else None,
                "tap": body.tap.model_dump() if body.tap else None,
            }
        )
        if body.overlay or body.tap
        else None
    )
    return store.MeasurementData(
        reference_time_utc=ref_utc,
        reference_utc_offset_minutes=body.reference_utc_offset_minutes,
        reference_source=body.reference_source.value,
        platform=body.platform.value if body.platform else None,
        frame_timing=body.frame_timing.value if body.frame_timing else None,
        latency_correction_ms=body.latency_correction_ms,
        clock_offset_ms=body.clock_offset_ms,
        dial_hours=body.hours,
        dial_minutes=body.minutes,
        dial_seconds=body.seconds,
        deviation_s=deviation,
        confidence=body.confidence,
        seconds_confidence=body.seconds_confidence,
        correction=body.correction,
        geometry_json=geometry,
        image_sha256=body.image_sha256,
    )


@app.post("/api/watches/{watch_id}/measurements", status_code=201)
def save_measurement(watch_id: int, body: MeasurementIn, db: Db, owner: Owner) -> MeasurementOut:
    """Save a reading to the watch's current session. Saving is the user's confirmation, so the
    measurement counts toward the rate."""
    watch = _watch_or_404(db, owner, watch_id)
    now = datetime.now(UTC)
    data = _measurement_data(body, now)
    return _measurement_out(store.add_measurement(db, store.current_session(db, watch), data, now))


@app.delete("/api/watches/{watch_id}/measurements/{measurement_id}", status_code=204)
def delete_measurement(watch_id: int, measurement_id: int, db: Db, owner: Owner) -> Response:
    watch = _watch_or_404(db, owner, watch_id)
    if not store.delete_measurement(db, watch, measurement_id):
        raise HTTPException(404, "Measurement not found.")
    return Response(status_code=204)


def mount_frontend(target: FastAPI, folder: Path) -> None:
    """Serve the built PWA (`frontend/dist`) at `/`. Mounted last, so the /api routes win.
    Navigation is by location hash, so `/` → index.html is the only page needed."""
    target.mount("/", StaticFiles(directory=folder, html=True), name="frontend")


# Production (the Docker image) serves the frontend from the same origin; dev uses Vite.
if static_dir := os.environ.get("WATCHTIMING_STATIC_DIR"):
    mount_frontend(app, Path(static_dir))
