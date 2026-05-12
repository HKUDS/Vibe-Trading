"""Tests for Trust Layer run card generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from backtest.run_card import write_run_card
from src.core.runner import Runner


def test_config_hash_is_deterministic_independent_of_key_order(tmp_path: Path) -> None:
    config_a = {
        "codes": ["AAPL", "MSFT"],
        "start_date": "2025-01-01",
        "end_date": "2025-03-01",
        "interval": "1D",
        "engine": "global_equity",
        "initial_cash": 100000,
        "source": "auto",
        "nested": {"b": 2, "a": 1},
    }
    config_b = {
        "nested": {"a": 1, "b": 2},
        "source": "auto",
        "initial_cash": 100000,
        "engine": "global_equity",
        "interval": "1D",
        "end_date": "2025-03-01",
        "start_date": "2025-01-01",
        "codes": ["AAPL", "MSFT"],
    }

    card_a = write_run_card(tmp_path / "a", config_a, {"sharpe": 1.2})
    card_b = write_run_card(tmp_path / "b", config_b, {"sharpe": 1.2})

    assert card_a["reproducibility"]["config_hash"] == card_b["reproducibility"]["config_hash"]
    assert "nested" not in card_a["backtest"]


def test_strategy_hash_is_included_when_strategy_path_exists(tmp_path: Path) -> None:
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text("def signal():\n    return 1\n", encoding="utf-8")

    card = write_run_card(
        tmp_path / "run",
        {"codes": ["BTC-USDT"], "engine": "crypto"},
        {"return_pct": 0.15},
        strategy_path=strategy_path,
    )

    expected_hash = hashlib.sha256(strategy_path.read_bytes()).hexdigest()
    assert card["reproducibility"]["strategy_hash"] == expected_hash


def test_artifact_listing_includes_expected_existing_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "artifacts" / "nested").mkdir(parents=True)
    (run_dir / "config.json").write_text('{"ok": true}\n', encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text("SIGNAL = 1\n", encoding="utf-8")
    (run_dir / "artifacts" / "equity.csv").write_text("date,equity\n", encoding="utf-8")
    (run_dir / "artifacts" / "nested" / "trades.csv").write_text("id,pnl\n", encoding="utf-8")

    card = write_run_card(run_dir, {"codes": ["000001.SZ"]}, {"sharpe": 1.0})

    artifacts = {artifact["path"]: artifact for artifact in card["artifacts"]}
    assert card["reproducibility"]["config_hash"] == hashlib.sha256(
        (run_dir / "config.json").read_bytes()
    ).hexdigest()
    assert list(artifacts) == [
        "artifacts/equity.csv",
        "artifacts/nested/trades.csv",
        "code/signal_engine.py",
        "config.json",
    ]
    for relative_path, artifact in artifacts.items():
        path = run_dir / relative_path
        assert artifact["size_bytes"] == path.stat().st_size
        assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_json_and_markdown_files_are_written(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    metrics = {
        "sharpe": 1.23,
        "max_drawdown": -0.08,
        "validation": {"n_windows": 5, "consistency_rate": 0.8},
        "curve": [1, 2, 3],
    }

    card = write_run_card(
        run_dir,
        {
            "codes": ["AAPL"],
            "start_date": "2025-01-01",
            "end_date": "2025-02-01",
            "interval": "1D",
            "engine": "global_equity",
            "initial_cash": 50000,
            "source": "yfinance",
            "secret": "not copied raw",
        },
        metrics,
        data_sources=["yfinance"],
        warnings=["sample warning"],
    )

    json_path = run_dir / "run_card.json"
    md_path = run_dir / "run_card.md"
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert loaded == card
    assert loaded["schema_version"] == "0.1"
    assert loaded["generated_at"].endswith("Z")
    assert loaded["metrics"] == {"max_drawdown": -0.08, "sharpe": 1.23}
    assert loaded["validation"] == {"consistency_rate": 0.8, "n_windows": 5}
    assert "secret" not in json.dumps(loaded)
    assert "# Backtest Run Card" in markdown
    assert "Validation" in markdown
    assert "sample warning" in markdown


def test_runner_artifact_spec_surfaces_run_card_paths() -> None:
    runner = Runner()

    assert runner.artifact_entries["run_card_json"]["path"] == "run_card.json"
    assert runner.artifact_entries["run_card_json"]["required"] is False
    assert runner.artifact_entries["run_card_md"]["path"] == "run_card.md"
    assert runner.artifact_entries["run_card_md"]["required"] is False


def test_options_backtest_writes_run_card(tmp_path: Path) -> None:
    from backtest.engines.options_portfolio import run_options_backtest

    dates = pd.bdate_range("2025-01-01", periods=4)
    bars = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [1000, 1100, 1200, 1300],
        },
        index=dates,
    )

    class FakeLoader:
        name = "yfinance"

        def fetch(self, codes, start_date, end_date):
            return {"SPY": bars.copy()}

    class SignalEngine:
        def generate(self, data_map):
            return [
                {
                    "date": "2025-01-01",
                    "action": "open",
                    "underlying": "SPY",
                    "legs": [{"type": "call", "strike": 101.0, "expiry": "2025-03-21", "qty": 1}],
                },
                {
                    "date": "2025-01-03",
                    "action": "close",
                    "underlying": "SPY",
                    "legs": [{"type": "call", "strike": 101.0, "expiry": "2025-03-21", "qty": 1}],
                },
            ]

    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-06",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": 100_000,
        },
        FakeLoader(),
        SignalEngine(),
        tmp_path,
    )

    card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert card["backtest"]["engine"] == "options"
    assert card["data_sources"] == ["yfinance"]
    assert "greeks.csv" in {Path(artifact["path"]).name for artifact in card["artifacts"]}
    assert (tmp_path / "run_card.md").exists()
