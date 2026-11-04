import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.main import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SYNC_RUNS", "1")
    monkeypatch.setenv("STAGE_DELAY_MS", "0")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    return tmp_path


@pytest.fixture
def client(env):
    with TestClient(create_app(get_settings())) as c:
        yield c
