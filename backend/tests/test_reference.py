from datetime import UTC, datetime, timedelta, timezone

import pytest

from tests.helpers import capture
from watchtiming.exif import InvalidTimestampError
from watchtiming.reference import (
    EARLIEST_CAPTURE,
    FRAME_LATENCY,
    MAX_CLOCK_AHEAD,
    DeviceCapture,
    FrameTiming,
    Platform,
    ReferenceSource,
    device_capture,
    reference_time,
)

DEVICE_TIME = datetime(2026, 10, 14, 20, 0, 0, 123_000, tzinfo=timezone(timedelta(hours=2)))
DEVICE_UTC = datetime(2026, 10, 14, 18, 0, 0, 123_000, tzinfo=UTC)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def device(
    time: datetime = DEVICE_TIME,
    timing: FrameTiming = FrameTiming.CAPTURE_TIME,
    platform: Platform = Platform.IOS,
) -> DeviceCapture:
    return DeviceCapture(time, timing, platform)


def test_exif_is_used_when_present():
    ref = reference_time(capture("2026:10:14 20:15:30", "5", "+02:00"), device(), NOW)
    assert ref.source == ReferenceSource.EXIF
    assert ref.time == datetime(2026, 10, 14, 18, 15, 30, 500_000, tzinfo=UTC)
    assert ref.device is None


def test_ios_capture_time_is_utc_and_corrected_for_camera_latency():
    ref = reference_time(capture(), device(), NOW)
    latency = FRAME_LATENCY[(Platform.IOS, FrameTiming.CAPTURE_TIME)]
    assert ref.source == ReferenceSource.DEVICE_CLOCK
    assert ref.device == device()
    assert ref.latency_correction == latency
    assert ref.time == DEVICE_UTC - latency
    assert ref.time.tzinfo == UTC


@pytest.mark.parametrize(
    "timing,platform",
    [
        (FrameTiming.CAPTURE_TIME, Platform.ANDROID),
        (FrameTiming.CAPTURE_TIME, Platform.OTHER),
        (FrameTiming.PRESENTATION_TIME, Platform.IOS),
        (FrameTiming.TAP, Platform.IOS),
    ],
)
def test_unmeasured_combinations_are_uncorrected_and_flagged(timing, platform):
    ref = reference_time(capture(), device(timing=timing, platform=platform), NOW)
    assert ref.time == DEVICE_UTC
    assert ref.latency_correction is None


def test_broken_exif_does_not_fall_back_to_device_clock():
    with pytest.raises(InvalidTimestampError, match="time zone"):
        reference_time(capture("2026:10:14 20:15:30", None, None), device(), NOW)


def test_nothing_is_rejected():
    with pytest.raises(InvalidTimestampError, match="in-app camera"):
        reference_time(capture(), None, NOW)


# --- plausibility (both sources) ---


def test_bounds_are_inclusive():
    assert reference_time(capture(), device(time=EARLIEST_CAPTURE), NOW)
    assert reference_time(capture(), device(time=NOW + MAX_CLOCK_AHEAD), NOW)


@pytest.mark.parametrize(
    "time",
    [
        EARLIEST_CAPTURE - timedelta(seconds=1),
        NOW + MAX_CLOCK_AHEAD + timedelta(seconds=1),
        datetime(9999, 12, 31, 23, 0, tzinfo=UTC),
    ],
)
def test_implausible_device_time_is_rejected(time):
    with pytest.raises(InvalidTimestampError, match="implausible"):
        reference_time(capture(), device(time=time), NOW)


def test_device_time_that_overflows_is_rejected():
    year_one = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(InvalidTimestampError, match="out of range"):
        reference_time(capture(), device(time=year_one), NOW)


@pytest.mark.parametrize(
    "dt,offset",
    [
        ("2019:12:31 23:00:00", "+00:00"),
        ("0001:01:01 00:00:00", "+02:00"),
        ("9999:12:31 23:00:00", "-05:00"),
    ],
)
def test_implausible_or_overflowing_exif_is_rejected(dt, offset):
    with pytest.raises(InvalidTimestampError):
        reference_time(capture(dt, None, offset), None, NOW)


# --- device_capture: the upload's in-app camera fields ---


def test_no_device_fields_means_no_device_capture():
    assert device_capture(None, None, None) is None


@pytest.mark.parametrize(
    "time,timing,platform",
    [
        (DEVICE_TIME, None, None),
        (None, FrameTiming.CAPTURE_TIME, None),
        (None, None, Platform.IOS),
        (DEVICE_TIME, FrameTiming.CAPTURE_TIME, None),
    ],
)
def test_partial_device_fields_are_rejected(time, timing, platform):
    with pytest.raises(InvalidTimestampError, match="together"):
        device_capture(time, timing, platform)


def test_naive_device_time_is_rejected():
    with pytest.raises(InvalidTimestampError, match="time zone"):
        device_capture(datetime(2026, 10, 14, 20, 0), FrameTiming.TAP, Platform.IOS)
