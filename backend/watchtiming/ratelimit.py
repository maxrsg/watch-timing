"""Per-client rate limits for the API (ASGI middleware), kept in memory.

The app runs as one process on one machine (fly.toml, `--workers 1`), so memory is the right
place for the counts; they start over on a restart, which is fine for abuse protection.
Each client gets a token bucket per kind of request: a burst of `per_minute` at once, then
`per_minute` spread over each minute.
"""

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Behind Fly's proxy every request comes from the proxy; it puts the real client in this header.
# Only trusted when WATCHTIMING_TRUST_FLY_IP=1 (the Docker image): anywhere else, anyone could
# send it and pick their own bucket.
FLY_CLIENT_IP = b"fly-client-ip"
TRUST_FLY_IP_ENV = "WATCHTIMING_TRUST_FLY_IP"


@dataclass(frozen=True)
class Limit:
    name: str
    per_minute: int


READ = Limit("read", 20)  # decoding a photo of up to 50 MP: the expensive one
WRITE = Limit("write", 60)
QUERY = Limit("query", 300)

# Unlimited: the health check (Fly's own) and everything outside /api (the static PWA).
_UNLIMITED = {"/api/health"}
_READS = {"/api/read", "/api/probe"}


def limit_for(method: str, path: str) -> Limit | None:
    if not path.startswith("/api/") or path in _UNLIMITED:
        return None
    if path in _READS:
        return READ
    if method in ("GET", "HEAD", "OPTIONS"):
        return QUERY
    return WRITE


class RateLimiter:
    """The buckets: (client, limit name) → (tokens left, when they were counted)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._pruned = clock()

    def take(self, client: str, limit: Limit) -> float | None:
        """Use one token: None if allowed, else the seconds until the next one."""
        now = self.clock()
        self._prune(now)
        rate = limit.per_minute / 60
        key = (client, limit.name)
        tokens, then = self._buckets.get(key, (limit.per_minute, now))
        tokens = min(limit.per_minute, tokens + (now - then) * rate)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / rate
        self._buckets[key] = (tokens - 1, now)
        return None

    def reset(self) -> None:
        self._buckets.clear()

    def _prune(self, now: float) -> None:
        """Once a minute, forget clients idle for a minute: every bucket is full again by
        then, the same as a new one."""
        if now - self._pruned < 60:
            return
        self._pruned = now
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 60}


def client_key(scope: Scope, trust_fly_ip: bool) -> str:
    if trust_fly_ip:
        for name, value in scope["headers"]:
            if name == FLY_CLIENT_IP:
                return value.decode("latin-1")
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimit:
    """ASGI middleware: 429 with Retry-After once a client's bucket for the request is empty."""

    def __init__(
        self, app: ASGIApp, limiter: RateLimiter, trust_fly_ip: bool | None = None
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.trust_fly_ip = (
            os.environ.get(TRUST_FLY_IP_ENV) == "1" if trust_fly_ip is None else trust_fly_ip
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = limit_for(scope["method"], scope["path"]) if scope["type"] == "http" else None
        if limit is not None:
            wait = self.limiter.take(client_key(scope, self.trust_fly_ip), limit)
            if wait is not None:
                seconds = math.ceil(wait)
                # Same JSON shape as FastAPI's errors: the frontend shows `detail`.
                response = JSONResponse(
                    {"detail": f"Too many requests. Try again in {seconds} s."},
                    429,
                    headers={"Retry-After": str(seconds)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
