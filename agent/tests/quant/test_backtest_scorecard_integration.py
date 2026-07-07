from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backtest.engines.base import BaseEngine


class _DummyEngine(BaseEngine):
    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:  # noqa: ARG002
        return True

    def round_size(self, raw_size: float, price: float) -> float:  # noqa: ARG002
        return max(raw_size, 0.0)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:  # noqa: ARG002
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:  # noqa: ARG002
        return price


class _DummyLoader:
    name = "dummy"

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):  # noqa: ARG002
        return {code: self.frame.copy() for code in codes}


class _DummySignal:
    def generate(self, data_map):
        return {
            code: pd.Series(1.0, index=frame.index)
            for code, frame in data_map.items()
        }


def _price_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "open": [10, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4],
            "high": [10.1, 10.3, 10.5, 10.7, 10.9, 11.1, 11.3, 11.5],
            "low": [9.9, 10.1, 10.3, 10.5, 10.7, 10.9, 11.1, 11.3],
            "close": [10, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4],
            "volume": [1_000_000] * 8,
        },
        index=dates,
    )


def _config() -> dict:
    return {
        "codes": ["000001.SZ"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-08",
        "interval": "1D",
        "source": "dummy",
        "initial_cash": 1_000_000,
        "benchmark": "auto",
        "trial_count": 1,
        "cost_model": {"commission_bps": 1.0, "slippage_bps": 5.0},
        "oos_present": True,
        "random_control_present": True,
        "execution_timestamps": {
            "signal_time": True,
            "decision_time": True,
            "order_time": True,
            "fill_time": True,
            "price_time": True,
        },
    }


def test_backtest_completed_generates_scorecard_artifact_ref_before_run_card(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(tmp_path / "artifact_root"))
    run_dir = tmp_path / "run"
    config = _config()

    metrics = _DummyEngine(config).run_backtest(
        config,
        _DummyLoader(_price_frame()),
        _DummySignal(),
        run_dir,
    )

    run_card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    assert "scorecard_refs" in run_card
    assert run_card["scorecard_refs"][0]["artifact_type"] == "scorecard"
    assert "scorecard" not in metrics
    assert "final_value" in metrics
    assert "sharpe" in metrics


def test_reliability_mode_off_skips_backtest_scorecard_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "off")
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(tmp_path / "artifact_root"))
    run_dir = tmp_path / "run"
    config = _config()

    _DummyEngine(config).run_backtest(
        config,
        _DummyLoader(_price_frame()),
        _DummySignal(),
        run_dir,
    )

    run_card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    assert "scorecard_refs" not in run_card
    assert not (tmp_path / "artifact_root" / "objects").exists()
