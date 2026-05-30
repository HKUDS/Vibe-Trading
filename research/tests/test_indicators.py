"""
Unit tests for research/lib/indicators.py

Covers:
  (a) Returned dict keys match the enabled indicator pool from config.
  (b) Every returned Series has the same index as input candles and same length.
  (c) The module can be imported without TA-Lib installed (uses pure-Python ta library).
  (d) Empty indicator_pool returns empty dict.
  (e) Unknown indicator name triggers a warning and is skipped.

All tests are network-free (synthetic candle data only).

Run from research/ as:
    python -m pytest tests/test_indicators.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Bootstrap: ensure research/ is on sys.path so lib.* and pipeline.* are importable.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from lib.indicators import compute_indicator_pool, _INDICATOR_DISPATCH
from pipeline.config import ResearchConfig, SymbolConfig, FeesConfig


# ─── Synthetic candle fixture ─────────────────────────────────────────────────

def make_candles(n: int = 500) -> pd.DataFrame:
    """Generate n rows of synthetic OHLCV data with a UTC DatetimeIndex."""
    np.random.seed(42)
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(np.cumsum(np.random.randn(n)) + 30000, index=idx)
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.abs(np.random.randn(n)) * 100 + 50,
        },
        index=idx,
    )


def make_config(**overrides) -> ResearchConfig:
    """Build a minimal ResearchConfig for testing."""
    base = dict(
        symbols=(
            SymbolConfig(name="btc", okx_swap="BTC-USDT-SWAP", ccxt_bybit="BTC/USDT:USDT"),
        ),
        period=365,
        interval="1H",
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.0005, slippage=0.001),
        horizons_h=(1, 4, 24),
    )
    base.update(overrides)
    return ResearchConfig(**base)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestImportWithoutTaLib:
    """Verify the module imports cleanly without TA-Lib (uses pure-Python ta)."""

    def test_import_succeeds(self):
        # If we reached this line, the import at the top of this file already succeeded.
        from lib.indicators import compute_indicator_pool as fn  # noqa: F401
        assert callable(fn)

    def test_no_talib_dependency(self):
        """indicators.py must NOT import talib (TA-Lib C extension)."""
        import lib.indicators as mod
        import inspect
        src = inspect.getsource(mod)
        assert "import talib" not in src
        assert "from talib" not in src


class TestIndicatorPoolKeys:
    """Returned dict keys must match config.indicator_pool."""

    def test_full_default_pool_keys(self):
        candles = make_candles()
        cfg = make_config()  # uses default indicator_pool (all 13)
        pool = compute_indicator_pool(candles, cfg)
        assert set(pool.keys()) == set(cfg.indicator_pool)

    def test_subset_pool_keys(self):
        candles = make_candles()
        subset = ("rsi_14", "obv", "rolling_std_20")
        cfg = make_config(indicator_pool=subset)
        pool = compute_indicator_pool(candles, cfg)
        assert set(pool.keys()) == set(subset)

    def test_single_indicator(self):
        candles = make_candles()
        cfg = make_config(indicator_pool=("atr_14",))
        pool = compute_indicator_pool(candles, cfg)
        assert list(pool.keys()) == ["atr_14"]


class TestSeriesAlignmentAndLength:
    """Every returned Series must have the same index and length as input candles."""

    def test_index_equals_candles_index(self):
        candles = make_candles()
        cfg = make_config()
        pool = compute_indicator_pool(candles, cfg)
        for name, series in pool.items():
            assert series.index.equals(candles.index), (
                f"Indicator '{name}': series index does not match candles index"
            )

    def test_length_equals_candles_length(self):
        candles = make_candles()
        cfg = make_config()
        pool = compute_indicator_pool(candles, cfg)
        n = len(candles)
        for name, series in pool.items():
            assert len(series) == n, (
                f"Indicator '{name}': expected length {n}, got {len(series)}"
            )

    def test_returns_pd_series(self):
        candles = make_candles()
        cfg = make_config()
        pool = compute_indicator_pool(candles, cfg)
        for name, series in pool.items():
            assert isinstance(series, pd.Series), (
                f"Indicator '{name}': expected pd.Series, got {type(series).__name__}"
            )


class TestEdgeCases:
    """Edge-case behaviour."""

    def test_empty_pool_returns_empty_dict(self):
        candles = make_candles()
        cfg = make_config(indicator_pool=())
        pool = compute_indicator_pool(candles, cfg)
        assert pool == {}

    def test_unknown_indicator_skipped_with_warning(self, capsys):
        candles = make_candles()
        cfg = make_config(indicator_pool=("rsi_14", "nonexistent_indicator"))
        pool = compute_indicator_pool(candles, cfg)
        # Only the known indicator should appear
        assert "rsi_14" in pool
        assert "nonexistent_indicator" not in pool
        captured = capsys.readouterr()
        assert "nonexistent_indicator" in captured.out

    def test_all_known_short_names_are_in_dispatch_table(self):
        """Every short name listed in the spec is covered by the dispatch table."""
        expected = {
            "rsi_14", "macd_diff", "roc_10", "stoch_k",
            "ema_cross_9_21", "sma_cross_10_30", "adx_14",
            "atr_14", "bb_width_20", "rolling_std_20",
            "obv", "mfi_14", "volume_zscore_20",
        }
        assert expected <= set(_INDICATOR_DISPATCH.keys())

    def test_indicator_series_name_attribute(self):
        """Each Series should have its short name as its .name attribute."""
        candles = make_candles()
        cfg = make_config(indicator_pool=("rsi_14", "obv"))
        pool = compute_indicator_pool(candles, cfg)
        for key, series in pool.items():
            assert series.name == key
