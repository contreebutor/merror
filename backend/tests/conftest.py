"""Shared test fixtures.

Every test runs against a throwaway Chroma directory so the real memory store
is never touched.
"""

import pytest

from app import store


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Point the vector store at a fresh directory for every test."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(store, "_collection", None)
    yield
    store._client = None
    store._collection = None


@pytest.fixture
def client():
    """FastAPI test client bound to the temporary store."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
