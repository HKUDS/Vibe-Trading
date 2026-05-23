"""Live signal generator — same logic as backtest signal engine.

Loads ``code/signal_engine.py`` from a run directory, fetches recent OHLCV
via ccxt, and returns the latest signal value for the symbol.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "4H": "4h", "1D": "1d",
}


def _load_signal_engine(run_dir: Path):
    """Load SignalEngine class from run_dir/code/signal_engine.py."""
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        raise FileNotFoundError(f"signal_engine.py not found in {run_dir}/code/")
    spec = importlib.util.spec_from_file_location("_trader_signal_engine", signal_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine_cls = getattr(module, "SignalEngine", None)
    if engine_cls is None:
        raise AttributeError(f"SignalEngine class not found in {signal_path}")
    return engine_cls


def _fetch_ohlcv(
    exchange,
    symbol: str,
    interval: str,
    lookback: int,
) -> pd.DataFrame:
    """Fetch recent OHLCV bars from the exchange.

    Returns DataFrame with columns [open, high, low, close, volume],
    indexed by UTC timestamp.
    """
    ccxt_tf = _INTERVAL_MAP.get(interval)
    if ccxt_tf is None:
        raise ValueError(f"Unsupported interval: {interval}")

    raw = exchange.fetch_ohlcv(symbol, ccxt_tf, limit=lookback)
    if not raw:
        raise RuntimeError(f"No OHLCV data returned for {symbol}")

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df.index = df.index.tz_localize(None)  # strip tz for compatibility with backtest engine
    return df


def compute_signal(
    run_dir: Path,
    exchange,
    symbol: str,
    interval: str = "1H",
    lookback: int = 200,
) -> int:
    """Compute the current signal for *symbol* using the run's signal engine.

    Args:
        run_dir: Backtest run directory containing code/signal_engine.py.
        exchange: ccxt exchange instance (authenticated for private, or public).
        symbol: Exchange symbol, e.g. "BTC/USDT:USDT".
        interval: OHLCV bar interval.
        lookback: Number of bars to fetch (must cover signal's lookback window).

    Returns:
        Signal as integer: 1 (long), -1 (short), 0 (flat).
    """
    engine_cls = _load_signal_engine(run_dir)
    engine = engine_cls()

    df = _fetch_ohlcv(exchange, symbol, interval, lookback)
    data_map = {symbol: df}

    signal_map = engine.generate(data_map)
    series: Optional[pd.Series] = signal_map.get(symbol)
    if series is None or series.empty:
        return 0

    raw = float(series.iloc[-1])
    if raw > 1e-9:
        return 1
    if raw < -1e-9:
        return -1
    return 0
