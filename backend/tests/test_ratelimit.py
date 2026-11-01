"""Per-client rate limits, on a small app with a fake clock, and wired into the real one."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import make_image
from watchtiming import api
from watchtiming.ratelimit import QUERY, READ, WRITE, RateLimit, RateLimiter, limit_for


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(trust_fly_ip: bool = False) -> tuple[TestClient, Clock]:
    clock = Clock()
    app = FastAPI()
    app.add_middleware(RateLimit, limiter=RateLimiter(clock), trust_fly_ip=trust_fly_ip)

    @app.post("/api/read")
    def read() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/index.html")
    def page() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app), clock


def test_which_limit_applies():
    assert limit_for("POST", "/api/read") is READ
    assert limit_for("POST", "/api/probe") is READ
    assert limit_for("GET", "/api/watches") is QUERY
    assert limit_for("GET", "/api/time") is QUERY
    assert limit_for("POST", "/api/watches") is WRITE
    assert limit_for("DELETE", "/api/watches/1") is WRITE
    assert limit_for("GET", "/api/health") is None
    assert limit_for("GET", "/") is None
    assert limit_for("GET", "/assets/index.js") is None


def test_a_burst_then_429_with_retry_after():
    client, _ = make_client()
    for _ in range(READ.per_minute):
        assert client.post("/api/read").status_code == 200
    r = client.post("/api/read")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "3"  # 20 a minute: one every 3 s
    assert r.json() == {"detail": "Too many requests. Try again in 3 s."}


def test_tokens_come_back_over_time():
    client, clock = make_client()
    for _ in range(READ.per_minute):
        client.post("/api/read")
    clock.now += 2.9
    assert client.post("/api/read").status_code == 429
    clock.now += 0.2  # 3.1 s: one token back
    assert client.post("/api/read").status_code == 200
    assert client.post("/api/read").status_code == 429
    clock.now += 60
    for _ in range(READ.per_minute):  # a full bucket, never more
        assert client.post("/api/read").status_code == 200
    assert client.post("/api/read").status_code == 429


def test_health_and_static_files_are_never_limited():
    client, _ = make_client()
    for _ in range(QUERY.per_minute + 10):
        assert client.get("/api/health").status_code == 200
        assert client.get("/index.html").status_code == 200


def test_clients_are_limited_separately_by_fly_client_ip():
    client, _ = make_client(trust_fly_ip=True)
    a, b = {"Fly-Client-IP": "203.0.113.1"}, {"Fly-Client-IP": "203.0.113.2"}
    for _ in range(READ.per_minute):
        client.post("/api/read", headers=a)
    assert client.post("/api/read", headers=a).status_code == 429
    assert client.post("/api/read", headers=b).status_code == 200


def test_fly_client_ip_is_ignored_unless_trusted():
    client, _ = make_client(trust_fly_ip=False)
    for i in range(READ.per_minute):
        client.post("/api/read", headers={"Fly-Client-IP": f"203.0.113.{i}"})
    # A made-up header doesn't buy a fresh bucket.
    r = client.post("/api/read", headers={"Fly-Client-IP": "203.0.113.99"})
    assert r.status_code == 429


def test_idle_clients_are_forgotten():
    clock = Clock()
    limiter = RateLimiter(clock)
    for i in range(100):
        limiter.take(f"client-{i}", READ)
    clock.now += 61
    limiter.take("new", READ)
    assert len(limiter._buckets) == 1


def test_the_app_limits_reads():
    client = TestClient(api.app)
    data = make_image()  # no timestamp, no dial: still a read the server has to decode
    for _ in range(READ.per_minute):
        r = client.post("/api/probe", files={"file": ("a.jpg", data, "image/jpeg")})
        assert r.status_code == 200
    r = client.post("/api/probe", files={"file": ("a.jpg", data, "image/jpeg")})
    assert r.status_code == 429
