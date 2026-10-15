from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from watchtiming.limits import BodySizeLimit

app = FastAPI()
app.add_middleware(BodySizeLimit, max_bytes=100)


@app.post("/echo")
async def echo(request: Request) -> dict[str, int]:
    return {"size": len(await request.body())}


client = TestClient(app)


def test_small_body_passes():
    assert client.post("/echo", content=b"x" * 100).json() == {"size": 100}


def test_large_content_length_is_rejected_before_reading():
    r = client.post("/echo", content=b"x" * 101)
    assert r.status_code == 413
    assert r.json() == {"detail": "Request body is too large."}


def test_streamed_body_without_length_is_cut_off():
    chunks = (b"x" * 40 for _ in range(5))  # chunked, no Content-Length
    r = client.post("/echo", content=chunks)
    assert r.status_code == 413
    assert r.json() == {"detail": "Request body is too large."}


def test_bad_content_length_is_rejected():
    r = client.post("/echo", content=b"x", headers={"content-length": "abc"})
    assert r.status_code == 413
