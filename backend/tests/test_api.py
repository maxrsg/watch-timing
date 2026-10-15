import hashlib

from fastapi.testclient import TestClient

from tests.helpers import make_image
from watchtiming.api import app

client = TestClient(app)


def test_probe_reports_exif_and_hash():
    data = make_image(
        DateTimeOriginal="2026:10:14 20:15:30",
        SubsecTimeOriginal="25",
        OffsetTimeOriginal="+02:00",
    )
    r = client.post("/api/probe", files={"file": ("a.jpg", data, "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["reference_time_utc"] == "2026-10-14T18:15:30.250Z"
    assert body["error"] is None


def test_probe_missing_timestamp_reports_error():
    r = client.post("/api/probe", files={"file": ("a.jpg", make_image(), "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["reference_time_utc"] is None
    assert "no capture timestamp" in r.json()["error"]


def test_probe_rejects_non_image():
    r = client.post("/api/probe", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422


FRAME = ("frame.jpg", make_image(), "image/jpeg")
IOS_CAPTURE = {
    "device_capture_time": "2026-10-14T18:15:30.250Z",
    "frame_timing": "capture_time",
    "platform": "ios",
}


def test_probe_uses_device_time_without_exif():
    r = client.post("/api/probe", files={"file": FRAME}, data=IOS_CAPTURE)
    body = r.json()
    assert body["reference_source"] == "device_clock"
    assert body["frame_timing"] == "capture_time"
    assert body["platform"] == "ios"
    assert body["latency_correction_ms"] == 132
    # 18:15:30.250 minus the in-app camera latency correction (132 ms).
    assert body["reference_time_utc"] == "2026-10-14T18:15:30.118Z"
    assert body["ignored_device_time"] is False
    assert body["error"] is None


def test_probe_flags_uncalibrated_platform():
    r = client.post(
        "/api/probe", files={"file": FRAME}, data={**IOS_CAPTURE, "platform": "android"}
    )
    body = r.json()
    assert body["reference_time_utc"] == "2026-10-14T18:15:30.250Z"
    assert body["latency_correction_ms"] is None


def test_probe_flags_device_time_ignored_for_exif():
    data = make_image(
        DateTimeOriginal="2026:10:14 20:15:30",
        SubsecTimeOriginal="25",
        OffsetTimeOriginal="+02:00",
    )
    r = client.post("/api/probe", files={"file": ("a.jpg", data, "image/jpeg")}, data=IOS_CAPTURE)
    body = r.json()
    assert body["reference_source"] == "exif"
    assert body["ignored_device_time"] is True


def test_probe_rejects_partial_device_fields():
    r = client.post("/api/probe", files={"file": FRAME}, data={"frame_timing": "capture_time"})
    assert "together" in r.json()["error"]


def test_probe_rejects_implausible_device_time():
    r = client.post(
        "/api/probe",
        files={"file": FRAME},
        data={**IOS_CAPTURE, "device_capture_time": "0001-01-01T00:00:00Z"},
    )
    assert r.status_code == 200
    assert "implausible" in r.json()["error"]


def test_server_time_has_milliseconds():
    r = client.get("/api/time")
    assert r.status_code == 200
    value = r.json()["server_time_utc"]
    assert len(value) == len("2026-10-14T18:15:30.250Z") and value.endswith("Z")
