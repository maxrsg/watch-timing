"""Watches, sessions and measurements over the API, owned by an anonymous owner ID."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.test_api_read import DIAL, photo
from watchtiming import store
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


# --- Limits: one owner's caps, and the database size for everyone ---------------------------


def test_watches_per_owner_are_capped(monkeypatch):
    monkeypatch.setattr(store, "MAX_WATCHES_PER_OWNER", 2)
    me = owner()
    new_watch(me)
    new_watch(me)
    res = client.post("/api/watches", json={"name": "Third"}, headers=me)
    assert res.status_code == 409
    assert res.json()["detail"] == "You can track at most 2 watches."
    new_watch(owner())  # another owner has their own cap


def test_sessions_per_watch_are_capped(monkeypatch):
    monkeypatch.setattr(store, "MAX_SESSIONS_PER_WATCH", 2)
    watch_id = new_watch()  # its first session
    assert client.post(f"/api/watches/{watch_id}/sessions", headers=ME).status_code == 201
    res = client.post(f"/api/watches/{watch_id}/sessions", headers=ME)
    assert res.status_code == 409
    assert "at most 2 sessions" in res.json()["detail"]


def test_measurements_per_watch_are_capped_across_sessions(monkeypatch):
    monkeypatch.setattr(store, "MAX_MEASUREMENTS_PER_WATCH", 2)
    watch_id = new_watch()
    assert save(watch_id, reading(REF, 1.0)).status_code == 201
    client.post(f"/api/watches/{watch_id}/sessions", headers=ME)
    assert save(watch_id, reading(REF + timedelta(hours=1), 1.0)).status_code == 201
    res = save(watch_id, reading(REF + timedelta(hours=2), 1.0))
    assert res.status_code == 409
    assert "at most 2 measurements" in res.json()["detail"]
    # Deleting one makes room again.
    first = client.get(f"/api/watches/{watch_id}", headers=ME).json()["sessions"][0]
    mid = first["measurements"][0]["id"]
    res = client.delete(f"/api/watches/{watch_id}/measurements/{mid}", headers=ME)
    assert res.status_code == 204
    assert save(watch_id, reading(REF + timedelta(hours=2), 1.0)).status_code == 201


def test_a_full_database_takes_nothing_new(monkeypatch):
    watch_id = new_watch()
    monkeypatch.setenv("WATCHTIMING_DB_MAX_MB", "0")
    for res in (
        client.post("/api/watches", json={"name": "New"}, headers=ME),
        client.post(f"/api/watches/{watch_id}/sessions", headers=ME),
        save(watch_id, reading(REF, 1.0)),
    ):
        assert res.status_code == 507
        assert "storage is full" in res.json()["detail"]
    # Reading, renaming and deleting still work.
    assert client.get("/api/watches", headers=ME).status_code == 200
    assert (
        client.patch(f"/api/watches/{watch_id}", json={"name": "Renamed"}, headers=ME).status_code
        == 200
    )
    assert client.delete(f"/api/watches/{watch_id}", headers=ME).status_code == 204


def test_overlay_hands_are_bounded():
    watch_id = new_watch()
    point = {"x": 1.0, "y": 2.0}
    overlay = {
        "dial_center": point, "dial_semi_major": 10.0, "dial_semi_minor": 9.0,
        "dial_angle_deg": 0.0, "pivot": point, "twelve": point,
        "hands": [{"role": "other", "tip": point}] * 65,
    }  # fmt: skip
    assert save(watch_id, reading(REF, 1.0, overlay=overlay)).status_code == 422


def test_a_locked_database_answers_503(monkeypatch):
    import sqlite3

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "list_watches", locked)
    res = client.get("/api/watches", headers=ME)
    assert res.status_code == 503
    assert "Try again" in res.json()["detail"]


def test_an_unexpected_error_answers_with_a_sentence(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "list_watches", broken)
    res = TestClient(app, raise_server_exceptions=False).get("/api/watches", headers=ME)
    assert res.status_code == 500
    assert res.json() == {"detail": "Something went wrong on the server. Try again."}


def test_a_missing_watch_hints_at_the_owner_link():
    res = client.get("/api/watches/999999", headers=owner())
    assert res.status_code == 404
    assert "another browser" in res.json()["detail"]


def test_a_watch_without_a_session_gets_one(tmp_db):
    watch_id = new_watch()
    with store.connect(tmp_db) as conn:
        conn.execute("DELETE FROM sessions WHERE watch_id = ?", (watch_id,))
    assert save(watch_id, reading(REF, 1.0)).status_code == 201
    assert len(client.get(f"/api/watches/{watch_id}", headers=ME).json()["sessions"]) == 1


def test_non_finite_overlay_points_are_rejected():
    watch_id = new_watch()
    body = json.dumps(reading(REF, 1.0)).replace(
        '"image_sha256"', '"tap": {"x": NaN, "y": 1}, "image_sha256"'
    )
    res = client.post(
        f"/api/watches/{watch_id}/measurements",
        content=body,
        headers={**ME, "Content-Type": "application/json"},
    )
    assert res.status_code == 422


def test_the_schema_is_versioned(tmp_db):
    new_watch()
    with store.connect(tmp_db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_an_unversioned_database_is_migrated(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as old:  # as created before versioning
        old.executescript(store.SCHEMA_V1)
        old.execute(
            "INSERT INTO watches (owner_id, name, created_at) VALUES (?, ?, ?)",
            ("o", "Old", "2026-01-01T00:00:00.000+00:00"),
        )
    conn = store.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)
    assert [w.name for w in store.list_watches(conn, "o")] == ["Old"]
    conn.close()


def test_a_malformed_size_limit_is_named(monkeypatch):
    monkeypatch.setenv("WATCHTIMING_DB_MAX_MB", "lots")
    with pytest.raises(ValueError, match="WATCHTIMING_DB_MAX_MB"):
        store.db_max_bytes()
