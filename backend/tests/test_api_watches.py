"""Watches, sessions and measurements over the API, owned by an anonymous owner ID."""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.test_api_read import DIAL, photo
from watchtiming.api import app

client = TestClient(app)


def owner() -> dict[str, str]:
    return {"X-Owner-Id": str(uuid.uuid4())}


ME = owner()
SHA = "ab" * 32
# A recent reference time (the server rejects implausible ones), on a whole second.
REF = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)


def new_watch(headers=ME, name="Orient Ray") -> int:
    res = client.post("/api/watches", json={"name": name}, headers=headers)
    assert res.status_code == 201
    return res.json()["id"]


def reading(ref: datetime, deviation_s: float, offset_minutes: int = 120, **extra) -> dict:
    """A reading whose dial shows `ref` + `deviation_s` in the watch's zone."""
    zone = timezone(timedelta(minutes=offset_minutes))
    local = (ref + timedelta(seconds=deviation_s)).astimezone(zone)
    return {
        "reference_time_utc": ref.isoformat(),
        "reference_utc_offset_minutes": offset_minutes,
        "reference_source": "exif",
        "hours": local.hour % 12 or 12,
        "minutes": local.minute,
        "seconds": local.second + local.microsecond / 1e6,
        "confidence": 0.9,
        "seconds_confidence": 0.8,
        "image_sha256": SHA,
        **extra,
    }


def save(watch_id: int, body: dict, headers=ME):
    return client.post(f"/api/watches/{watch_id}/measurements", json=body, headers=headers)


def test_create_list_rename_delete():
    me = owner()
    watch_id = new_watch(me, "  Seiko 5  ")
    watches = client.get("/api/watches", headers=me).json()
    assert [(w["id"], w["name"]) for w in watches] == [(watch_id, "Seiko 5")]
    assert watches[0]["measurement_count"] == 0
    assert watches[0]["rate"] is None

    res = client.patch(f"/api/watches/{watch_id}", json={"name": "Seiko 5 Sports"}, headers=me)
    assert res.json()["name"] == "Seiko 5 Sports"

    assert client.delete(f"/api/watches/{watch_id}", headers=me).status_code == 204
    assert client.get("/api/watches", headers=me).json() == []


def test_names_must_not_be_empty():
    res = client.post("/api/watches", json={"name": "   "}, headers=ME)
    assert res.status_code == 422


def test_owner_header_is_required_and_must_be_a_uuid():
    assert client.get("/api/watches").status_code == 422
    assert client.get("/api/watches", headers={"X-Owner-Id": "me"}).status_code == 422


def test_other_owners_watches_are_not_found():
    watch_id = new_watch()
    other = owner()
    assert client.get("/api/watches", headers=other).json() == []
    assert client.get(f"/api/watches/{watch_id}", headers=other).status_code == 404
    res = client.patch(f"/api/watches/{watch_id}", json={"name": "Mine"}, headers=other)
    assert res.status_code == 404
    assert client.delete(f"/api/watches/{watch_id}", headers=other).status_code == 404
    assert save(watch_id, reading(REF, 1.0), headers=other).status_code == 404
    assert client.post(f"/api/watches/{watch_id}/sessions", headers=other).status_code == 404


def test_saved_measurements_give_the_rate():
    watch_id = new_watch()
    for days, deviation in [(0, 1.0), (1, 4.0), (2, 7.0)]:
        res = save(watch_id, reading(REF - timedelta(days=2 - days), deviation))
        assert res.status_code == 201
        assert res.json()["deviation_s"] == pytest.approx(deviation)

    detail = client.get(f"/api/watches/{watch_id}", headers=ME).json()
    (session,) = detail["sessions"]
    assert [m["deviation_s"] for m in session["measurements"]] == pytest.approx([1, 4, 7])
    assert session["rate"]["rate_s_per_day"] == pytest.approx(3.0)
    assert not session["rate"]["short_span"]

    (summary,) = [w for w in client.get("/api/watches", headers=ME).json() if w["id"] == watch_id]
    assert summary["measurement_count"] == 3
    assert summary["latest_deviation_s"] == pytest.approx(7.0)
    assert summary["rate"]["rate_s_per_day"] == pytest.approx(3.0)


def test_the_deviation_is_recomputed_not_taken_from_the_client():
    watch_id = new_watch()
    # The dial shows 2.5 s ahead; a client claiming another deviation has no say.
    body = reading(REF, 2.5) | {"deviation_s": 99.0}
    assert save(watch_id, body).json()["deviation_s"] == pytest.approx(2.5)


def test_am_pm_and_the_watchs_zone_are_resolved_like_a_reading():
    watch_id = new_watch()
    # UTC−5: the dial shows the local 12-hour time, the deviation is still −1.5 s.
    body = reading(REF, -1.5, offset_minutes=-300)
    assert save(watch_id, body).json()["deviation_s"] == pytest.approx(-1.5)


def test_invalid_measurements_are_rejected():
    watch_id = new_watch()
    future = datetime.now(UTC) + timedelta(hours=1)
    assert save(watch_id, reading(future, 0.0)).status_code == 422
    # Device-clock references need their platform and frame timing; EXIF ones have none.
    assert save(watch_id, reading(REF, 0.0, reference_source="device_clock")).status_code == 422
    assert save(watch_id, reading(REF, 0.0, platform="ios")).status_code == 422
    device = reading(REF, 0.0, reference_source="device_clock", platform="ios")
    assert save(watch_id, device | {"frame_timing": "capture_time"}).status_code == 201
    # No seconds, no measurement.
    assert save(watch_id, reading(REF, 0.0) | {"seconds": None}).status_code == 422
    assert save(watch_id, reading(REF, 0.0) | {"image_sha256": "x"}).status_code == 422


def test_setting_the_watch_starts_a_new_session():
    watch_id = new_watch()
    save(watch_id, reading(REF - timedelta(days=1), 5.0))
    save(watch_id, reading(REF, 8.0))
    res = client.post(f"/api/watches/{watch_id}/sessions", headers=ME)
    assert res.status_code == 201
    current, previous = res.json()["sessions"]
    assert current["measurements"] == []
    assert current["rate"] is None
    assert previous["rate"]["rate_s_per_day"] == pytest.approx(3.0)

    save(watch_id, reading(REF + timedelta(minutes=1), 0.2))
    (summary,) = [w for w in client.get("/api/watches", headers=ME).json() if w["id"] == watch_id]
    assert summary["measurement_count"] == 1
    assert summary["rate"] is None  # never across sessions


def test_delete_a_measurement():
    watch_id = new_watch()
    mid = save(watch_id, reading(REF, 1.0)).json()["id"]
    other_watch = new_watch()
    assert (
        client.delete(f"/api/watches/{other_watch}/measurements/{mid}", headers=ME).status_code
        == 404
    )
    assert (
        client.delete(f"/api/watches/{watch_id}/measurements/{mid}", headers=ME).status_code == 204
    )
    detail = client.get(f"/api/watches/{watch_id}", headers=ME).json()
    assert detail["sessions"][0]["measurements"] == []


def read_with_watch(watch_id: int | None, headers=ME):
    data = {"tap_x": DIAL.truth.twelve[0], "tap_y": DIAL.truth.twelve[1]}
    if watch_id is not None:
        data["watch_id"] = watch_id
    return client.post(
        "/api/read",
        files={"file": ("dial.jpg", photo("2026:10:18 10:08:34", "5"), "image/jpeg")},
        data=data,
        headers=headers,
    )


def test_a_read_for_a_watch_is_steered_by_its_session():
    watch_id = new_watch()
    assert read_with_watch(watch_id).json()["expected_deviation_s"] is None
    save(watch_id, reading(REF, 2.0))
    body = read_with_watch(watch_id).json()
    assert body["expected_deviation_s"] == pytest.approx(2.0)  # no rate yet: the last one
    assert body["deviation_s"] == pytest.approx(2.5, abs=0.05)
    assert body["image_sha256"] and len(body["image_sha256"]) == 64


def test_a_read_for_someone_elses_watch_is_rejected():
    watch_id = new_watch()
    assert read_with_watch(watch_id, headers=owner()).status_code == 404
    assert read_with_watch(watch_id, headers={}).status_code == 422
    assert read_with_watch(None, headers={}).status_code == 200
