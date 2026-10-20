import os

import pytest

from watchtiming import devserver
from watchtiming.upload_log import ENV_VAR


@pytest.fixture
def runs(monkeypatch):
    calls = []
    monkeypatch.setattr(devserver.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.delenv(ENV_VAR, raising=False)
    return calls


def test_plain_start_keeps_saving_off(runs):
    devserver.main([])
    assert ENV_VAR not in os.environ
    ((args, kwargs),) = runs
    assert args == ("watchtiming.api:app",)
    assert kwargs["reload"] is True and kwargs["port"] == 8000


def test_save_uploads_default_dir(runs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    devserver.main(["--save-uploads"])
    assert os.environ[ENV_VAR] == str(tmp_path / "debug-out" / "uploads")


def test_save_uploads_custom_dir(runs, tmp_path):
    devserver.main(["--save-uploads", str(tmp_path / "mine")])
    assert os.environ[ENV_VAR] == str(tmp_path / "mine")
