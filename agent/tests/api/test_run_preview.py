"""Tests for GET /runs/{run_id}/preview.

The chat history asks for a preview of every assistant turn, and every turn
owns a run directory, so the route must stay cheap for plain replies and must
never pull chart payloads for backtests.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src import ui_services
from src.api import run_artifacts, runs_routes

BACKTEST_RUN = "run_backtest"
CHAT_RUN = "run_chat"
METRICS_CSV = (
    "final_value,total_return,annual_return,max_drawdown,sharpe,win_rate,trade_count\n"
    "112000,0.12,0.05,-0.08,1.3,0.55,42\n"
)


def _write_backtest_run(
    run_dir: Path, symbols: int, bars: int, equity_rows: int
) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (run_dir / "state.json").write_text('{"status": "success"}\n', encoding="utf-8")
    (artifacts / "metrics.csv").write_text(METRICS_CSV, encoding="utf-8")
    start = date(2020, 1, 1)
    days = [
        (start + timedelta(days=i)).isoformat() for i in range(max(bars, equity_rows))
    ]
    for n in range(symbols):
        rows = ["trade_date,open,high,low,close,volume"]
        rows += [f"{day},10,11,9,10.5,1000" for day in days[:bars]]
        (artifacts / f"ohlcv_S{n:03d}.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )
    equity = ["timestamp,equity,drawdown"]
    equity += [f"{day},{100000 + i},0" for i, day in enumerate(days[:equity_rows])]
    (artifacts / "equity.csv").write_text("\n".join(equity) + "\n", encoding="utf-8")
    (artifacts / "trades.csv").write_text(
        "timestamp,code,side,price,qty\n2020-01-02,S000,BUY,10,100\n", encoding="utf-8"
    )


def _write_chat_run(run_dir: Path) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (run_dir / "state.json").write_text('{"status": "success"}\n', encoding="utf-8")
    (run_dir / "llm_usage.json").write_text('{"input_tokens": 10}\n', encoding="utf-8")
    (artifacts / "grounding_evidence.json").write_text(
        '{"items": []}\n', encoding="utf-8"
    )


@pytest.fixture(scope="module")
def runs_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("preview") / "runs"
    _write_backtest_run(root / BACKTEST_RUN, symbols=40, bars=500, equity_rows=1200)
    _write_chat_run(root / CHAT_RUN)
    return root


@pytest.fixture
def client(runs_root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", runs_root)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_backtest_preview_matches_full_response(
    client: TestClient, runs_root: Path
) -> None:
    full = api_server._build_response_from_run_dir(
        runs_root / BACKTEST_RUN, elapsed=0.0
    ).model_dump(mode="json")

    response = client.get(f"/runs/{BACKTEST_RUN}/preview")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"metrics", "equity_curve", "report_worthy"}
    assert payload["report_worthy"] is True
    assert payload["metrics"] == full["metrics"]
    assert payload["equity_curve"] == full["equity_curve"]
    assert len(payload["equity_curve"]) == run_artifacts.EQUITY_CURVE_MAX_POINTS


def test_backtest_preview_is_a_small_fraction_of_the_full_response(
    client: TestClient,
) -> None:
    full = client.get(f"/runs/{BACKTEST_RUN}")
    preview = client.get(f"/runs/{BACKTEST_RUN}/preview")

    assert full.status_code == preview.status_code == 200
    assert len(preview.content) < 64 * 1024
    assert len(preview.content) * 50 < len(full.content)


def test_preview_never_builds_chart_payloads(client: TestClient, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("preview loaded chart payloads")

    monkeypatch.setattr(ui_services, "build_run_analysis", fail)
    monkeypatch.setattr(ui_services, "load_price_series", fail)
    monkeypatch.setattr(ui_services, "reconstruct_price_series", fail)

    response = client.get(f"/runs/{BACKTEST_RUN}/preview")

    assert response.status_code == 200
    assert response.json()["report_worthy"] is True


def test_chat_turn_preview_reads_no_csv(client: TestClient, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("chat-turn preview opened a CSV")

    monkeypatch.setattr(run_artifacts, "load_csv_records", fail)

    response = client.get(f"/runs/{CHAT_RUN}/preview")

    assert response.status_code == 200
    assert response.json() == {
        "metrics": None,
        "equity_curve": [],
        "report_worthy": False,
    }


def test_preview_is_rendered_in_threadpool(client: TestClient, offloaded: list) -> None:
    response = client.get(f"/runs/{CHAT_RUN}/preview")

    assert response.status_code == 200
    assert runs_routes._render_run_preview in offloaded


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (
            lambda d: (d / "run_card.json").write_text(
                json.dumps({"metrics": {"sharpe": 1}})
            ),
            True,
        ),
        (lambda d: (d / "run_card.json").write_text("{}"), False),
        (
            lambda d: (d / "artifacts" / "ohlcv_AAPL.csv").write_text(
                "trade_date,close\n"
            ),
            True,
        ),
        (
            lambda d: (d / "artifacts" / "price_series.csv").write_text(
                "timestamp,code\n"
            ),
            True,
        ),
        (lambda d: (d / "artifacts" / "strategy.pine").write_text("//"), True),
        (lambda d: (d / "artifacts" / "VALIDATION.JSON").write_text("{}"), True),
        (lambda d: (d / "artifacts" / "notes.txt").write_text("x"), False),
    ],
)
def test_report_worthy_rules(tmp_path: Path, setup, expected: bool) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    setup(run_dir)

    assert run_artifacts.build_run_preview(run_dir)["report_worthy"] is expected


def test_metrics_without_required_fields_stay_empty(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "metrics.csv").write_text(
        "final_value\n100\n", encoding="utf-8"
    )

    preview = run_artifacts.build_run_preview(run_dir)

    assert preview["metrics"] is None
    assert preview["report_worthy"] is True


def test_preview_missing_run_is_404(client: TestClient) -> None:
    response = client.get("/runs/run_missing/preview")

    assert response.status_code == 404


def test_preview_rejects_invalid_run_id(client: TestClient) -> None:
    response = client.get("/runs/foo.bar/preview")

    assert response.status_code == 400
