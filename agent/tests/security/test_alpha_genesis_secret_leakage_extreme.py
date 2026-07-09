from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cli.alpha_genesis import render_report_file
from src.alpha_foundry.reports.model import AlphaGenesisReport
from src.alpha_foundry.reports.render_markdown import render_markdown
from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def _report_with_secret_values(tmp_path: Path) -> AlphaGenesisReport:
    return AlphaGenesisReport(
        report_id="leak-check",
        candidate_id="candidate",
        limitations=["research-only evidence package"],
        non_goals=["not live trading advice"],
        metadata={
            "artifact_path": str(tmp_path / "private" / "run.json"),
            "source_config": {
                "token": "raw-token-123",
                "api_key": "sk-test-secret",
            },
            "diagnostic_line": "Authorization: Bearer bearer-secret-456",
            "nested": {
                "cache_dir": str(tmp_path / "oauth-cache"),
                "message": "api_key = semantic-secret-789",
            },
        },
    )


def test_alpha_genesis_report_outputs_redact_secret_values_and_local_paths(tmp_path: Path) -> None:
    report = _report_with_secret_values(tmp_path)
    report_path = tmp_path / "leak-check.json"
    report_path.write_text(report.to_json(), encoding="utf-8")

    outputs = [
        report.to_json(),
        render_markdown(report),
        render_report_file(report_path),
    ]

    for rendered in outputs:
        assert "raw-token-123" not in rendered
        assert "sk-test-secret" not in rendered
        assert "bearer-secret-456" not in rendered
        assert "semantic-secret-789" not in rendered
        assert str(tmp_path) not in rendered


def test_alpha_genesis_api_redacts_secret_values_and_local_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    report = _report_with_secret_values(tmp_path)
    (tmp_path / "leak-check.json").write_text(report.to_json(), encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(tmp_path))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    client = TestClient(app)

    response = client.get("/api/alpha-genesis/reports/leak-check")

    assert response.status_code == 200
    rendered = response.text
    assert "raw-token-123" not in rendered
    assert "sk-test-secret" not in rendered
    assert "bearer-secret-456" not in rendered
    assert "semantic-secret-789" not in rendered
    assert str(tmp_path) not in rendered
    assert response.json()["metadata"]["source_config"]["token"] == "[redacted]"
