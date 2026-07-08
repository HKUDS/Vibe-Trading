from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cli.alpha_genesis import render_report_file
from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def test_api_cli_markdown_exports_preserve_same_research_decision_and_redaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = build_alpha_genesis_report(
        report_id="consistency",
        candidate_id="candidate-consistency",
        source_config={"token": "secret-token"},
        limitations=["<script>alert(1)</script>", "[click](javascript:alert(1))"],
    )
    path = tmp_path / "consistency.json"
    path.write_text(report.to_json(), encoding="utf-8")

    cli_json = json.loads(render_report_file(path))
    cli_markdown = render_report_file(path, markdown=True)

    report_root = tmp_path / "api"
    report_root.mkdir()
    (report_root / "consistency.json").write_text(report.to_json(), encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR", str(report_root))
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    api_json = TestClient(app).get("/api/alpha-genesis/reports/consistency").json()

    assert cli_json["decision"] == api_json["decision"] == "research_only"
    assert cli_json["non_goals"] == api_json["non_goals"]
    assert "secret-token" not in json.dumps(cli_json)
    assert "secret-token" not in json.dumps(api_json)
    assert "<script>" not in cli_markdown
    assert "javascript:" not in cli_markdown.lower()
