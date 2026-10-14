"""GET /runs/{run_id} builds and encodes its payload off the event loop."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from src.api import runs_routes

RUN_ID = "run_20250101_000000"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _make_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / RUN_ID
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (run_dir / "state.json").write_text('{"status": "success"}\n', encoding="utf-8")
    (run_dir / "req.json").write_text(
        json.dumps(
            {
                "context": {
                    "codes": ["AAPL"],
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-02",
                }
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "price_series.csv").write_text(
        "timestamp,code,open,high,low,close,volume\n2025-01-01,AAPL,1,2,1,2,100\n",
        encoding="utf-8",
    )
    (artifacts / "equity.csv").write_text(
        "timestamp,equity,drawdown\n2025-01-01,100000,0\n2025-01-02,101000,0\n",
        encoding="utf-8",
    )
    return run_dir


def test_full_run_detail_is_rendered_in_threadpool(
    tmp_path: Path, monkeypatch, offloaded: list
) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = _make_run(tmp_path)

    response = client.get(f"/runs/{RUN_ID}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert runs_routes._render_run_result in offloaded
    expected = api_server._build_response_from_run_dir(
        run_dir, elapsed=0.0, include_analysis=True
    )
    assert response.json() == expected.model_dump(mode="json")


def test_chart_payload_variant_is_rendered_in_threadpool(
    tmp_path: Path, monkeypatch, offloaded: list
) -> None:
    client = _client(tmp_path, monkeypatch)
    _make_run(tmp_path)

    response = client.get(f"/runs/{RUN_ID}", params={"chart_payload": "summary"})

    assert response.status_code == 200
    assert runs_routes._render_run_result in offloaded
    payload = response.json()
    assert payload["chart_symbols"] == ["AAPL"]
    assert payload["price_series"] == {}
