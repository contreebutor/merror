"""Shared test fixtures.

Every test runs against a throwaway Chroma directory so the real memory store
is never touched.
"""

import pytest

from app import store


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Point the vector store and uploads directory at fresh paths.

    Applied to every test, so the suite can never read or write the real
    memory store or the real uploaded images.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(store, "_collection", None)
    yield
    store._client = None
    store._collection = None


@pytest.fixture
def fake_vision(monkeypatch):
    """Replace the Anthropic client with a scripted stand-in.

    Returns a factory: call it with a response (or an exception to raise) and
    it returns the fake client, whose `.messages.calls` records every request.
    """
    from tests.helpers import FakeAnthropic

    def install(response):
        client = FakeAnthropic(response)
        monkeypatch.setattr("app.vision._client", lambda: client)
        return client

    return install


@pytest.fixture
def client():
    """FastAPI test client bound to the temporary store."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
