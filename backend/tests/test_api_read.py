"""POST /api/read: a rendered dial with a known time, uploaded like a phone photo."""

import io
from datetime import UTC, datetime, timedelta

import cv2
import pytest
from fastapi.testclient import TestClient
from PIL import ExifTags, Image

from tests.synthetic.render import DialSpec, render
from watchtiming.api import app

client = TestClient(app)

# The dial shows 10:08:37.0 local time (CEST, UTC+2).
SPEC = DialSpec(hours=10, minutes=8, seconds=37.0, tilt_deg=15, rotation_deg=10)
DIAL = render(SPEC)


def photo(exif_local: str | None, subsec: str = "500") -> bytes:
    exif = Image.Exif()
    if exif_local is not None:
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        sub[ExifTags.Base.DateTimeOriginal] = exif_local
        sub[ExifTags.Base.SubsecTimeOriginal] = subsec
        sub[ExifTags.Base.OffsetTimeOriginal] = "+02:00"
    buf = io.BytesIO()
    Image.fromarray(cv2.cvtColor(DIAL.image, cv2.COLOR_GRAY2RGB)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def post(data: bytes, tap=DIAL.truth.twelve, **fields):
    return client.post(
        "/api/read",
        files={"file": ("dial.jpg", data, "image/jpeg")},
        data={"tap_x": tap[0], "tap_y": tap[1], **fields},
    )


def test_reads_the_dial_and_computes_the_deviation():
    # Photo taken at 10:08:34.5 local; the dial shows 10:08:37.0 → the watch is 2.5 s fast.
    body = post(photo("2026:10:18 10:08:34", "5")).json()
    r = body["reading"]
    assert (r["hours"], r["minutes"]) == (10, 8)
    assert r["seconds"] == pytest.approx(37.0, abs=0.05)
    assert not r["needs_confirmation"]
    assert body["reference_source"] == "exif"
    assert body["reference_utc_offset_minutes"] == 120
    assert body["deviation_s"] == pytest.approx(2.5, abs=0.05)
    assert (body["image_width"], body["image_height"]) == DIAL.image.shape[::-1]


def test_overlay_is_in_photo_coordinates():
    overlay = post(photo("2026:10:18 10:08:34")).json()["overlay"]
    assert overlay["pivot"]["x"] == pytest.approx(DIAL.truth.pivot[0], abs=2)
    assert overlay["pivot"]["y"] == pytest.approx(DIAL.truth.pivot[1], abs=2)
    assert overlay["twelve"]["x"] == pytest.approx(DIAL.truth.twelve[0], abs=4)
    roles = sorted(h["role"] for h in overlay["hands"] if h["role"] != "other")
    assert roles == ["hour", "minute", "second"]


def test_in_app_capture_uses_the_device_time_and_its_offset():
    # In-app frame: no EXIF. Local time with offset, as the app sends it.
    now_local = datetime.now(UTC).astimezone()  # any recent time passes the plausibility check
    captured = now_local.replace(hour=10, minute=8, second=36, microsecond=0)
    if captured > now_local:
        captured -= timedelta(days=1)
    body = post(
        photo(None),
        device_capture_time=captured.isoformat(),
        frame_timing="tap",  # uncalibrated: no latency correction, keeps the arithmetic simple
        platform="other",
    ).json()
    assert body["reference_source"] == "device_clock"
    offset = captured.utcoffset()
    assert body["reference_utc_offset_minutes"] == round(offset.total_seconds() / 60)
    assert body["deviation_s"] == pytest.approx(1.0, abs=0.05)


def test_missing_timestamp_still_reads_the_dial():
    body = post(photo(None)).json()
    assert body["reading"] is not None
    assert body["deviation_s"] is None
    assert "no capture timestamp" in body["timestamp_error"]


def test_tap_outside_the_photo():
    assert post(photo(None), tap=(5000, 10)).status_code == 422


def test_no_dial_at_the_tap():
    body = post(photo(None), tap=(5, 5)).json()
    assert body["reading"] is None and body["overlay"] is None
    assert "dial" in body["reading_error"]


def test_uploads_are_kept_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("WATCHTIMING_SAVE_UPLOADS", raising=False)
    post(photo("2026:10:18 10:08:34"))
    assert not any(tmp_path.iterdir())

    monkeypatch.setenv("WATCHTIMING_SAVE_UPLOADS", str(tmp_path))
    post(photo("2026:10:18 10:08:34"))
    (folder,) = tmp_path.iterdir()
    names = {p.name for p in folder.iterdir()}
    assert {"photo.jpg", "request.json", "result.json", "info.txt", "04_rectified.png"} <= names


def tip(angle_deg: float, fraction: float) -> dict[str, float]:
    from tests.synthetic.truth import dial_point
    from watchtiming.geometry import apply_homography

    x, y = apply_homography(DIAL.truth.homography, dial_point(SPEC, angle_deg, fraction))
    return {"x": x, "y": y}


def hand_fields(hour: dict, minute: dict, second: dict | None = None) -> dict[str, float]:
    fields = {"hour_x": hour["x"], "hour_y": hour["y"], "minute_x": minute["x"],
              "minute_y": minute["y"]}  # fmt: skip
    if second:
        fields |= {"second_x": second["x"], "second_y": second["y"]}
    return fields


def test_user_placed_hands_give_the_reading():
    a = DIAL.truth.angles
    # Tips anywhere along each hand: only the direction from the pivot counts.
    fields = hand_fields(tip(a.hour, 0.3), tip(a.minute, 0.75), tip(a.second, 0.5))
    body = post(photo("2026:10:18 10:08:34", "5"), **fields).json()
    r = body["reading"]
    assert r["corrected"] is True and r["needs_confirmation"] is False
    assert (r["hours"], r["minutes"]) == (10, 8)
    assert r["seconds"] == pytest.approx(37.0, abs=0.05)
    assert body["deviation_s"] == pytest.approx(2.5, abs=0.05)
    roles = sorted(h["role"] for h in body["overlay"]["hands"])
    assert roles == ["hour", "minute", "second"]


def test_user_placed_hands_without_seconds():
    a = DIAL.truth.angles
    body = post(
        photo("2026:10:18 10:08:34"), **hand_fields(tip(a.hour, 0.4), tip(a.minute, 0.7))
    ).json()
    r = body["reading"]
    assert (r["hours"], r["minutes"], r["seconds"]) == (10, 8, None)
    assert body["deviation_s"] is None


def test_a_misplaced_hand_is_warned_about():
    a = DIAL.truth.angles
    wrong_hour = tip(a.hour + 40, 0.4)  # more than an hour off from where the minute hand says
    body = post(
        photo(None), **hand_fields(wrong_hour, tip(a.minute, 0.7), tip(a.second, 0.7))
    ).json()
    assert any("hour hand" in reason for reason in body["reading"]["reasons"])


def test_partial_hand_tips_are_rejected():
    assert post(photo(None), hour_x=10, hour_y=10).status_code == 422


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
@pytest.mark.parametrize("field", ["hour_x", "minute_y", "second_x"])
def test_non_finite_hand_tips_are_rejected(field, value):
    tips = dict(hour_x=10, hour_y=10, minute_x=20, minute_y=20, second_x=30, second_y=30)
    assert post(photo(None), **{**tips, field: value}).status_code == 422


def test_kept_uploads_record_the_placed_hands(tmp_path, monkeypatch):
    """A kept upload replays what the app was sent: the hand tips are in the request, and the
    debug stages show the placed reading, not a fresh detection."""
    import json

    monkeypatch.setenv("WATCHTIMING_SAVE_UPLOADS", str(tmp_path))
    a = DIAL.truth.angles
    fields = hand_fields(tip(a.hour, 0.3), tip(a.minute, 0.75), tip(a.second, 0.5))
    post(photo("2026:10:18 10:08:34", "5"), **fields)
    (folder,) = tmp_path.iterdir()
    request = json.loads((folder / "request.json").read_text())
    assert request["hand_tips"]["hour"] == pytest.approx([fields["hour_x"], fields["hour_y"]])
    info = (folder / "info.txt").read_text()
    assert "hands placed by the user" in info
    assert "deviation: +2.50 s" in info


def test_the_api_does_not_load_the_debug_tools():
    import subprocess
    import sys

    code = "import sys, watchtiming.api; print('watchtiming.debug' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
