"""Watches, sessions and measurements in SQLite (stdlib sqlite3).

There's no login yet: every watch belongs to an anonymous owner ID the browser generates and
keeps. Every query that starts from a watch filters by its owner, so another owner's watch
is simply not found. Images are never stored, only what was read from them.
"""

import os
import sqlite3
from dataclasses import astuple, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "watchtiming.sqlite"

# Anyone can make up an owner ID, so these only bound one owner; the database size bounds all
# of them (the volume is small and SQLite stops working when it's full).
MAX_WATCHES_PER_OWNER = 50
MAX_SESSIONS_PER_WATCH = 200
MAX_MEASUREMENTS_PER_WATCH = 5000
DEFAULT_DB_MAX_MB = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS watches_owner ON watches (owner_id);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    watch_id INTEGER NOT NULL REFERENCES watches (id) ON DELETE CASCADE,
    started_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_watch ON sessions (watch_id);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    reference_time_utc TEXT NOT NULL,
    reference_utc_offset_minutes INTEGER NOT NULL,
    reference_source TEXT NOT NULL,
    platform TEXT,
    frame_timing TEXT,
    latency_correction_ms REAL,
    clock_offset_ms REAL,
    dial_hours INTEGER NOT NULL,
    dial_minutes INTEGER NOT NULL,
    dial_seconds REAL NOT NULL,
    deviation_s REAL NOT NULL,
    confidence REAL NOT NULL,
    seconds_confidence REAL NOT NULL,
    correction TEXT,
    geometry_json TEXT,
    image_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS measurements_session ON measurements (session_id);
"""


def db_path() -> Path:
    """`WATCHTIMING_DB`, else backend/data/watchtiming.sqlite."""
    return Path(os.environ.get("WATCHTIMING_DB") or DEFAULT_DB)


def db_max_bytes() -> int:
    """`WATCHTIMING_DB_MAX_MB`, else 500 MB: past it, nothing new is stored."""
    return int(os.environ.get("WATCHTIMING_DB_MAX_MB") or DEFAULT_DB_MAX_MB) * 1024 * 1024


class LimitReached(Exception):
    """One owner's or watch's cap is reached. The message is for the user."""


class StorageFull(Exception):
    """The database has reached its size limit."""


def _count(conn: sqlite3.Connection, sql: str, *args: object) -> int:
    return conn.execute(sql, args).fetchone()[0]


def _check_room(conn: sqlite3.Connection) -> None:
    size = _count(conn, "PRAGMA page_count") * _count(conn, "PRAGMA page_size")
    if size >= db_max_bytes():
        raise StorageFull


def connect(path: Path) -> sqlite3.Connection:
    """Open (and if needed create) the database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run a request's dependency and handler on different threads.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="milliseconds")


def _time(s: str) -> datetime:
    return datetime.fromisoformat(s)


@dataclass(frozen=True)
class Watch:
    id: int
    name: str
    created_at: datetime


@dataclass(frozen=True)
class Session:
    id: int
    watch_id: int
    started_at: datetime


@dataclass(frozen=True)
class MeasurementData:
    """What a measurement records (the columns after id, session_id and created_at)."""

    reference_time_utc: datetime
    reference_utc_offset_minutes: int
    reference_source: str
    platform: str | None
    frame_timing: str | None
    latency_correction_ms: float | None
    clock_offset_ms: float | None
    dial_hours: int  # 1–12 as the dial shows it
    dial_minutes: int
    dial_seconds: float
    deviation_s: float  # dial − reference, positive = fast
    confidence: float
    seconds_confidence: float
    correction: str | None  # None (detected), "hands" or "typed"
    geometry_json: str | None  # the detected geometry and the tap, in photo pixels
    image_sha256: str


@dataclass(frozen=True)
class SavedMeasurement:
    id: int
    session_id: int
    created_at: datetime
    data: MeasurementData


_DATA_COLUMNS = [f.name for f in fields(MeasurementData)]


def _watch(row: sqlite3.Row) -> Watch:
    return Watch(row["id"], row["name"], _time(row["created_at"]))


def _session(row: sqlite3.Row) -> Session:
    return Session(row["id"], row["watch_id"], _time(row["started_at"]))


def _measurement(row: sqlite3.Row) -> SavedMeasurement:
    values = {c: row[c] for c in _DATA_COLUMNS}
    values["reference_time_utc"] = _time(values["reference_time_utc"])
    return SavedMeasurement(
        row["id"], row["session_id"], _time(row["created_at"]), MeasurementData(**values)
    )


def create_watch(conn: sqlite3.Connection, owner: str, name: str, now: datetime) -> Watch:
    """A new watch with its first session (starting now)."""
    _check_room(conn)
    if _count(conn, "SELECT COUNT(*) FROM watches WHERE owner_id = ?", owner) >= (
        MAX_WATCHES_PER_OWNER
    ):
        raise LimitReached(f"You can track at most {MAX_WATCHES_PER_OWNER} watches.")
    with conn:
        cur = conn.execute(
            "INSERT INTO watches (owner_id, name, created_at) VALUES (?, ?, ?)",
            (owner, name, _iso(now)),
        )
        watch_id = cur.lastrowid
        assert watch_id is not None
        conn.execute(
            "INSERT INTO sessions (watch_id, started_at) VALUES (?, ?)", (watch_id, _iso(now))
        )
    return Watch(watch_id, name, _time(_iso(now)))


def list_watches(conn: sqlite3.Connection, owner: str) -> list[Watch]:
    rows = conn.execute(
        "SELECT * FROM watches WHERE owner_id = ? ORDER BY created_at, id", (owner,)
    )
    return [_watch(r) for r in rows]


def get_watch(conn: sqlite3.Connection, owner: str, watch_id: int) -> Watch | None:
    row = conn.execute(
        "SELECT * FROM watches WHERE id = ? AND owner_id = ?", (watch_id, owner)
    ).fetchone()
    return _watch(row) if row else None


def rename_watch(conn: sqlite3.Connection, owner: str, watch_id: int, name: str) -> bool:
    with conn:
        cur = conn.execute(
            "UPDATE watches SET name = ? WHERE id = ? AND owner_id = ?", (name, watch_id, owner)
        )
    return cur.rowcount > 0


def delete_watch(conn: sqlite3.Connection, owner: str, watch_id: int) -> bool:
    """Deletes its sessions and measurements too."""
    with conn:
        cur = conn.execute("DELETE FROM watches WHERE id = ? AND owner_id = ?", (watch_id, owner))
    return cur.rowcount > 0


def start_session(conn: sqlite3.Connection, watch: Watch, now: datetime) -> Session:
    """The watch was set: later measurements go to this new session."""
    _check_room(conn)
    if _count(conn, "SELECT COUNT(*) FROM sessions WHERE watch_id = ?", watch.id) >= (
        MAX_SESSIONS_PER_WATCH
    ):
        raise LimitReached(f"A watch can have at most {MAX_SESSIONS_PER_WATCH} sessions.")
    with conn:
        cur = conn.execute(
            "INSERT INTO sessions (watch_id, started_at) VALUES (?, ?)", (watch.id, _iso(now))
        )
    assert cur.lastrowid is not None
    return Session(cur.lastrowid, watch.id, _time(_iso(now)))


def sessions(conn: sqlite3.Connection, watch: Watch) -> list[Session]:
    """Newest first."""
    rows = conn.execute(
        "SELECT * FROM sessions WHERE watch_id = ? ORDER BY started_at DESC, id DESC", (watch.id,)
    )
    return [_session(r) for r in rows]


def current_session(conn: sqlite3.Connection, watch: Watch) -> Session:
    return sessions(conn, watch)[0]


def add_measurement(
    conn: sqlite3.Connection, session: Session, data: MeasurementData, now: datetime
) -> SavedMeasurement:
    _check_room(conn)
    count = _count(
        conn,
        "SELECT COUNT(*) FROM measurements WHERE session_id IN "
        "(SELECT id FROM sessions WHERE watch_id = ?)",
        session.watch_id,
    )
    if count >= MAX_MEASUREMENTS_PER_WATCH:
        raise LimitReached(f"A watch can have at most {MAX_MEASUREMENTS_PER_WATCH} measurements.")
    values = list(astuple(data))
    values[0] = _iso(data.reference_time_utc)
    columns = ", ".join(["session_id", "created_at", *_DATA_COLUMNS])
    marks = ", ".join("?" * (len(_DATA_COLUMNS) + 2))
    with conn:
        cur = conn.execute(
            f"INSERT INTO measurements ({columns}) VALUES ({marks})",
            (session.id, _iso(now), *values),
        )
    assert cur.lastrowid is not None
    return SavedMeasurement(cur.lastrowid, session.id, _time(_iso(now)), data)


def measurements(conn: sqlite3.Connection, session: Session) -> list[SavedMeasurement]:
    """In order of reference time."""
    rows = conn.execute(
        "SELECT * FROM measurements WHERE session_id = ? ORDER BY reference_time_utc, id",
        (session.id,),
    )
    return [_measurement(r) for r in rows]


def delete_measurement(conn: sqlite3.Connection, watch: Watch, measurement_id: int) -> bool:
    with conn:
        cur = conn.execute(
            "DELETE FROM measurements WHERE id = ? AND session_id IN "
            "(SELECT id FROM sessions WHERE watch_id = ?)",
            (measurement_id, watch.id),
        )
    return cur.rowcount > 0
