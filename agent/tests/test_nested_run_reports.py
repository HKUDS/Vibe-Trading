"""Regression coverage for nested backtest reports in agent run directories."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(api_server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _write_nested_report(runs_dir: Path) -> Path:
    parent = runs_dir / "20260728_135942_02_5e8bb3"
    parent.mkdir()
    (parent / "state.json").write_text('{"status": "success"}\n', encoding="utf-8")
    child = parent / "backtests" / "hk21_123"
    artifacts = child / "artifacts"
    artifacts.mkdir(parents=True)
    (child / "state.json").write_text('{"status": "success"}\n', encoding="utf-8")
    (child / "config.json").write_text(
        json.dumps(
            {
                "codes": ["00700.HK", "03690.HK"],
                "start_date": "2021-07-28",
                "end_date": "2026-07-27",
                "source": "longbridge",
            }
        ),
        encoding="utf-8",
    )
    (child / "run_card.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "backtest": {
                    "codes": ["00700.HK", "03690.HK"],
                    "start_date": "2021-07-28",
                    "end_date": "2026-07-27",
                },
                "metrics": {"total_return": 0.1, "sharpe": 1.2},
            }
        ),
        encoding="utf-8",
    )
    with (artifacts / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["final_value", "total_return", "annual_return", "max_drawdown", "sharpe", "win_rate", "trade_count"])
        writer.writeheader()
        writer.writerow({"final_value": 110000, "total_return": 0.1, "annual_return": 0.05, "max_drawdown": -0.1, "sharpe": 1.2, "win_rate": 0.5, "trade_count": 2})
    (child / "code").mkdir()
    (child / "code" / "signal_engine.py").write_text("class SignalEngine: pass\n", encoding="utf-8")
    (artifacts / "strategy.pine").write_text("//@version=6\n", encoding="utf-8")
    return child


def test_nested_backtest_is_listed_and_opened_via_safe_report_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _write_nested_report(tmp_path / "runs")

    listed = client.get("/runs?limit=20")

    assert listed.status_code == 200
    rows = listed.json()
    report = next(row for row in rows if row["codes"] == ["00700.HK", "03690.HK"])
    report_id = report["run_id"]
    assert "/" not in report_id
    assert report["total_return"] == 0.1

    detail = client.get(f"/runs/{report_id}?chart_payload=summary")

    assert detail.status_code == 200
    assert detail.json()["status"] == "success"
    assert detail.json()["run_card"]["backtest"]["codes"] == ["00700.HK", "03690.HK"]
    assert client.get(f"/runs/{report_id}/code").json() == {"signal_engine.py": "class SignalEngine: pass\n"}
    assert client.get(f"/runs/{report_id}/pine").json() == {"exists": True, "content": "//@version=6\n"}


def test_nested_report_rejects_encoded_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/nested_Li4vZXNjYXBl")

    assert response.status_code == 400


def test_single_symbol_chart_reads_only_its_ohlcv_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import ui_services

    run_dir = tmp_path / "run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "ohlcv_00700.HK.csv").write_text(
        "trade_date,open,high,low,close,volume\n2026-01-01,1,2,1,2,10\n",
        encoding="utf-8",
    )
    (artifacts / "ohlcv_03690.HK.csv").write_text(
        "trade_date,open,high,low,close,volume\n2026-01-01,3,4,3,4,20\n",
        encoding="utf-8",
    )
    reads: list[str] = []
    real_load = ui_services.load_csv_records

    def tracked_load(path: Path):
        reads.append(path.name)
        return real_load(path)

    monkeypatch.setattr(ui_services, "load_csv_records", tracked_load)

    payload = ui_services.build_run_analysis(run_dir, symbols=["00700.HK"], include_symbol_list=True)

    assert set(payload["price_series"]) == {"00700.HK"}
    assert "ohlcv_00700.HK.csv" in reads
    assert "ohlcv_03690.HK.csv" not in reads


def test_missing_selected_ohlcv_does_not_reconstruct_entire_portfolio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import ui_services

    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    called = False

    def fail_reconstruct(path: Path):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(ui_services, "reconstruct_price_series", fail_reconstruct)

    assert ui_services.load_price_series(run_dir, {"MISSING"}) == []
    assert called is False
