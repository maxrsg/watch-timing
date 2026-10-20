"""The reference (true) time of a measurement.

Single source of the reference time: a shutter-delay correction belongs here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from enum import StrEnum

from watchtiming.exif import CaptureExif, InvalidTimestampError, exif_capture_time, exif_timezone


class FrameTiming(StrEnum):
    """Which timestamp the in-app camera sent, most precise first."""

    # requestVideoFrameCallback metadata.captureTime
    CAPTURE_TIME = "capture_time"
    # requestVideoFrameCallback metadata.presentationTime (display side)
    PRESENTATION_TIME = "presentation_time"
    # No requestVideoFrameCallback: the time of the tap
    TAP = "tap"


class Platform(StrEnum):
    """Coarse client platform. Camera pipeline latency depends on device and browser engine."""

    IOS = "ios"
    ANDROID = "android"
    OTHER = "other"


# How late each frame timestamp is compared to the moment light hit the sensor, per
# (platform, timing). Only measured combinations are listed; anything else is used
# uncorrected and flagged as uncalibrated.
# (ios, capture_time): measured on iPhone (Firefox/WebKit) against the reference clock page,
# 2026-10-14: 0.126, 0.132, 0.139 s, including ~17-33 ms of the test
# screen's own lag.
# The remaining error is a constant offset *per source*. It shifts deviations but leaves the
# rate unchanged only within one source; mixing sources in a session needs per-source handling.
FRAME_LATENCY: dict[tuple[Platform, FrameTiming], timedelta] = {
    (Platform.IOS, FrameTiming.CAPTURE_TIME): timedelta(milliseconds=132),
}

# Plausible capture times. The lower bound is loose because offline-queued uploads can be
# days old; the upper bound allows for small clock differences.
EARLIEST_CAPTURE = datetime(2020, 1, 1, tzinfo=UTC)
MAX_CLOCK_AHEAD = timedelta(minutes=5)


class ReferenceSource(StrEnum):
    # Photo picked from the library: the camera's EXIF timestamp.
    EXIF = "exif"
    # Frame grabbed from the in-app live camera: the device clock at that frame.
    DEVICE_CLOCK = "device_clock"


@dataclass(frozen=True)
class DeviceCapture:
    """What the in-app camera sends instead of EXIF."""

    time: datetime  # timezone-aware, in the phone's local zone (it carries the UTC offset)
    timing: FrameTiming
    platform: Platform


@dataclass(frozen=True)
class Reference:
    time: datetime  # UTC
    source: ReferenceSource
    # The phone's local time zone at capture. The dial shows local time, so AM/PM and the
    # deviation are worked out in this zone.
    timezone: tzinfo
    # Device clock only: the capture details, and the latency subtracted from the time
    # (None = no calibration for this platform and timing; the time is uncorrected).
    device: DeviceCapture | None = None
    latency_correction: timedelta | None = None

    @property
    def local_time(self) -> datetime:
        return self.time.astimezone(self.timezone)


def device_capture(
    time: datetime | None, timing: FrameTiming | None, platform: Platform | None
) -> DeviceCapture | None:
    """Validate the in-app camera fields of an upload: all three, or none."""
    if time is None and timing is None and platform is None:
        return None
    if time is None or timing is None or platform is None:
        raise InvalidTimestampError(
            "Device capture time, frame timing and platform must be sent together."
        )
    if time.tzinfo is None:
        raise InvalidTimestampError("Device capture time must include a time zone.")
    return DeviceCapture(time, timing, platform)


def _plausible_utc(time: datetime, now: datetime) -> datetime:
    try:
        utc = time.astimezone(UTC)
    except OverflowError as e:
        raise InvalidTimestampError(f"Capture time {time.isoformat()} is out of range.") from e
    if not EARLIEST_CAPTURE <= utc <= now + MAX_CLOCK_AHEAD:
        raise InvalidTimestampError(
            f"Capture time {utc.isoformat()} is implausible. Check the phone's date and time."
        )
    return utc


def reference_time(exif: CaptureExif, device: DeviceCapture | None, now: datetime) -> Reference:
    """EXIF when the image has a capture timestamp, else the in-app device-clock time.

    Never mixes the two: an image with a broken EXIF timestamp is rejected even if a
    device time was sent, because the device time would then not belong to this image.
    `now` is the server time, for the plausibility check.
    """
    if exif.datetime_original is not None:
        utc = _plausible_utc(exif_capture_time(exif), now)
        return Reference(utc, ReferenceSource.EXIF, exif_timezone(exif))
    if device is not None:
        utc = _plausible_utc(device.time, now)
        latency = FRAME_LATENCY.get((device.platform, device.timing))
        local_zone = device.time.tzinfo
        assert local_zone is not None  # device_capture() rejects naive times
        return Reference(
            utc - (latency or timedelta()),
            ReferenceSource.DEVICE_CLOCK,
            local_zone,
            device,
            latency,
        )
    raise InvalidTimestampError(
        "The photo has no capture timestamp. Use the in-app camera, or pick a photo taken "
        "with the camera app. Screenshots, images from messaging apps and edited exports "
        "can't be used."
    )
