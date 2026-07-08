from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def test_alpha_genesis_artifact_responses_are_not_cacheable(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "report.json").write_text(
        '{"schema_version":"alpha_genesis_report.v1","report_id":"report"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)

    response = TestClient(app).get("/api/alpha-genesis/reports/report")

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_alpha_genesis_has_no_thumbnail_or_ocr_endpoints() -> None:
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)

    joined = "\n".join(app.openapi()["paths"])

    assert "thumbnail" not in joined
    assert "ocr" not in joined
    assert "preview" not in joined
