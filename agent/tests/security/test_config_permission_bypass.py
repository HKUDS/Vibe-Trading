from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    return TestClient(app)


def test_report_identifier_cannot_escape_configured_artifact_root(client: TestClient) -> None:
    for candidate in ("../secret", "..%2Fsecret", "nested/secret", "secret\\path"):
        response = client.get(f"/api/alpha-genesis/reports/{candidate}")
        assert response.status_code in {400, 404}
        assert "secret" not in response.text.lower()


def test_report_get_does_not_create_missing_artifact_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_root = tmp_path / "missing"
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(missing_root))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)

    response = TestClient(app).get("/api/alpha-genesis/reports/not-found")

    assert response.status_code == 404
    assert not missing_root.exists()
