"""The built frontend served next to the API (the Docker image sets WATCHTIMING_STATIC_DIR)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from watchtiming.api import app, mount_frontend


def test_frontend_is_served_beside_the_api(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Watch Timing</title>")
    (tmp_path / "sw.js").write_text("self.addEventListener('install', () => {})")
    site = FastAPI()

    @site.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(site, tmp_path)
    client = TestClient(site)

    assert "Watch Timing" in client.get("/").text
    assert client.get("/sw.js").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/missing.js").status_code == 404


def test_frontend_not_mounted_in_dev():
    assert all(getattr(route, "name", None) != "frontend" for route in app.routes)
