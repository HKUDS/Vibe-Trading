from __future__ import annotations

import json

import pandas as pd

from src.tools import build_registry
from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine
from src.ztrade_autoresearch.protocol import BASELINE_ID, DEFAULT_V47_PARAMS
from src.ztrade_autoresearch.runner import (
    discover_ztrade_csv_universe,
    run_synthetic_research,
    run_ztrade_csv_research,
)


def _sample_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=90)
    close = pd.Series([20 + i * 0.06 for i in range(90)], index=dates)
    close.iloc[35:40] -= [1.5, 1.2, 0.9, 0.4, 0.0]
    open_ = close.shift(1).fillna(close.iloc[0]) * 0.995
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
    volume = pd.Series(1_000_000.0, index=dates)
    volume.iloc[40] = 2_500_000.0
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_candidate_strategy_generates_long_only_signals() -> None:
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)
    signals = engine.generate({"000001.SZ": _sample_frame()})

    series = signals["000001.SZ"]
    assert set(series.unique()).issubset({0.0, 1.0})
    assert series.index.equals(_sample_frame().index)


def test_synthetic_research_writes_evidence(tmp_path) -> None:
    summary = run_synthetic_research(tmp_path / "research", max_iterations=2)

    assert summary["status"] == "ok"
    assert summary["baseline_id"] == BASELINE_ID
    assert len(summary["iterations"]) == 2
    assert (tmp_path / "research" / "summary.json").exists()
    assert (tmp_path / "research" / "metrics_rows.json").exists()
    assert list((tmp_path / "research").glob("*/rw_*/*run_card.json"))


def test_tool_registry_discovers_ztrade_autoresearch() -> None:
    registry = build_registry()
    assert "ztrade_autoresearch" in registry.tool_names

    payload = json.loads(
        registry.execute(
            "ztrade_autoresearch",
            {"run_dir": "/tmp/vibe_ztrade_autoresearch_tool_test", "max_iterations": 1},
        )
    )
    assert payload["status"] == "ok"


def test_ztrade_csv_research_uses_local_csv_data(tmp_path) -> None:
    data_dir = tmp_path / "ztrade_data"
    data_dir.mkdir()
    _write_csv(data_dir / "000001.csv", offset=0.0)
    _write_csv(data_dir / "600000.csv", offset=8.0)
    _write_csv(data_dir / "300750.csv", offset=20.0)

    universe = discover_ztrade_csv_universe(
        data_dir,
        start_date="2026-01-01",
        end_date="2026-03-31",
        max_symbols=2,
        min_rows=15,
    )
    assert len(universe) == 2
    assert all("." in code for code in universe)

    summary = run_ztrade_csv_research(
        tmp_path / "csv_research",
        data_dir=data_dir,
        max_iterations=1,
        max_symbols=2,
        windows=[
            {"id": "rw_fixture", "type": "rolling", "regime": "fixture", "start": "2026-01-01", "end": "2026-03-31"}
        ],
    )
    assert summary["status"] == "ok"
    assert summary["mode"] == "ztrade_csv"
    assert summary["universe_by_window"]["rw_fixture"]
    assert (tmp_path / "csv_research" / "candidate_volume_110" / "rw_fixture" / "run_card.json").exists()


def _write_csv(path, *, offset: float) -> None:
    dates = pd.bdate_range("2025-12-01", periods=100)
    close = pd.Series([20 + offset + i * 0.08 for i in range(100)], index=dates)
    close.iloc[35:39] -= [1.2, 1.0, 0.5, 0.0]
    frame = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close.shift(1).fillna(close.iloc[0]) * 0.997,
            "close": close,
            "high": close * 1.015,
            "low": close * 0.985,
            "volume": 1_000_000 + offset * 10_000,
        }
    )
    frame.to_csv(path, index=False)
