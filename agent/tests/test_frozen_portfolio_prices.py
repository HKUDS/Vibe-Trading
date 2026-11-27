"""Frozen portfolio prices must give the strategy the same inputs on replay."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.mark.parametrize(
    "crop_window", [False, True], ids=["same-window", "narrow-window"]
)
def test_frozen_trial_preserves_prices_at_strategy_threshold(
    tmp_path, monkeypatch, crop_window
):
    import dotenv

    from backtest import runner
    from backtest.loaders.local_loader import DataLoader
    from src.research_lab.execution import freeze_run, trial

    symbol = "AAPL.US"
    dates = pd.bdate_range("2026-01-05", periods=10, name="date")
    closes = np.r_[np.full(5, np.nextafter(100.0, 0.0)), np.full(5, 101.5)]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": 100_000,
        },
        index=dates,
    )
    root = tmp_path / "threshold-run"
    (root / "code").mkdir(parents=True)
    (root / "code/signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: frame['close'].lt(100.0).astype(float) for code, frame in data_map.items()}\n",
        encoding="utf-8",
    )
    (root / "config.json").write_text(
        json.dumps(
            {
                "codes": [f"local:{symbol}"],
                "source": "local",
                "benchmark": symbol,
                "start_date": str(dates[0].date()),
                "end_date": str(dates[-1].date()),
                "initial_cash": 10_000,
                "slippage_us": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    with monkeypatch.context() as source:
        source.setattr(DataLoader, "is_available", lambda self: True)
        source.setattr(
            DataLoader, "fetch", lambda self, *args, **kwargs: {symbol: frame.copy()}
        )
        runner.main(root)

    prices_path = Path(f"artifacts/ohlcv_{symbol}.csv")
    recorded = pd.read_csv(
        root / prices_path, index_col=0, float_precision="round_trip"
    )
    np.testing.assert_array_equal(recorded["close"], frame["close"])
    trades = json.loads((root / "run_card.json").read_text())["metrics"]["trade_count"]
    assert trades > 0

    study = tmp_path / "threshold-study"
    config, manifest, _, _ = freeze_run(root, study)
    expected = frame
    if crop_window:
        config.update(start_date=str(dates[1].date()), end_date=str(dates[-2].date()))
        expected = frame.iloc[1:-1]
    result = trial(study, "threshold", config, manifest)
    trial_dir = Path(result["run_dir"])
    saved = pd.read_csv(
        trial_dir / "snapshot/frame-0.csv", index_col=0, float_precision="round_trip"
    )
    np.testing.assert_array_equal(saved["close"], expected["close"])
    replayed = pd.read_csv(
        trial_dir / prices_path, index_col=0, float_precision="round_trip"
    )
    np.testing.assert_array_equal(replayed["close"], expected["close"])
    assert result["metrics"]["trade_count"] == trades
