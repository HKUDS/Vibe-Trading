"""Session-level price bands and final order prices at the backtest entry point."""

import json

import pandas as pd
import pytest
import yaml

from backtest.loaders import local_loader
from backtest.runner import BacktestConfigSchema, main


@pytest.mark.parametrize("symbol,opening", [
    ("005930.KS", 12_900), ("2330.TW", 10_900), ("VIC.VN", 10_600),
])
@pytest.mark.parametrize("shock_bps", [0, 200])
def test_daily_band_uses_the_actual_fill_price(tmp_path, monkeypatch, symbol, opening, shock_bps):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    bars = tmp_path / "bars.csv"
    pd.DataFrame({
        "date": pd.bdate_range("2026-03-02", periods=5),
        "open": [10_000] + [opening] * 4,
        "high": [10_000] + [opening] * 4,
        "low": [10_000] * 5,
        "close": [10_000] * 5,
        "volume": [1_000_000] * 5,
    }).to_csv(bars, index=False)
    bridge = tmp_path / "bridge.yaml"
    bridge.write_text(yaml.safe_dump({"sources": [{"symbol": symbol, "type": "csv", "path": str(bars)}]}))
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", bridge)
    (tmp_path / "config.json").write_text(json.dumps({
        "codes": [symbol],
        "start_date": "2026-03-02",
        "end_date": "2026-03-06",
        "source": "local",
        "benchmark": symbol,
        "initial_cash": 100_000_000,
        "slippage": 0,
        "extra_slippage_bps": shock_bps,
    }))
    code = tmp_path / "code"
    code.mkdir()
    (code / "signal_engine.py").write_text(
        "import pandas as pd\n"
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: pd.Series([0.0, 0.5, 0.5, 0.5, 0.5], index=bars.index)\n"
        "                for code, bars in data_map.items()}\n"
    )

    main(tmp_path)

    trades = pd.read_csv(tmp_path / "artifacts/trades.csv")
    entries = trades.loc[trades["event"] == "entry", "price"].tolist()
    assert entries == ([opening] if shock_bps == 0 else [])


@pytest.mark.parametrize("symbol", ["local:005930.KS", "local:2330.TW", "local:6488.TWO", "local:VIC.VN"])
@pytest.mark.parametrize("interval", ["1m", "1H"])
def test_intraday_cash_equity_guard_runs_before_fetch(tmp_path, capsys, monkeypatch, symbol, interval):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({
        "codes": [symbol],
        "start_date": "2026-03-02",
        "end_date": "2026-03-06",
        "source": "local",
        "interval": interval,
    }))

    with pytest.raises(SystemExit) as error:
        main(tmp_path)

    assert error.value.code == 1
    assert f"intraday backtests are unsupported for {symbol}" in capsys.readouterr().out


@pytest.mark.parametrize("symbol,interval", [("005930.KS", "1W"), ("VIC.VN", "1M"), ("AAPL.US", "1H")])
def test_other_bar_intervals_remain_available(symbol, interval):
    config = BacktestConfigSchema(
        codes=[symbol], start_date="2026-03-02", end_date="2026-03-06", interval=interval,
    )
    assert config.interval == interval
