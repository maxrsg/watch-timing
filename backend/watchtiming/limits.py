"""Reject oversized request bodies before they are parsed or spooled to disk."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimit:
    """ASGI middleware: 413 on a too-large `Content-Length`, or once streamed bytes exceed it."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            # Same JSON shape as the HTTPException below and FastAPI's own errors.
            response = JSONResponse({"detail": "Request body is too large."}, 413)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised while the body is being read, before any response has started;
                    # FastAPI re-raises HTTPException from body parsing as-is.
                    raise HTTPException(413, "Request body is too large.")
            return message

        await self.app(scope, limited_receive, send)
