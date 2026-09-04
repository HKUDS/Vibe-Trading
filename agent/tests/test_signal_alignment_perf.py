"""Signal alignment optimization regression tests.

Verifies:
1. Optimized _align() produces identical results to reference implementation
2. Performance target: 5000 bars x 50 symbols < 50ms (CI-safe; dev target 15-35ms)
3. End-to-end backtest equity curve unchanged (tolerance 1e-6)
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import (
    BaseEngine,
    _align,
    _detect_market_for_align,
    _ffill_1d,
    _ffill_2d,
)
from backtest.engines.china_a import ChinaAEngine


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

def _make_ohlcv(n_bars: int, seed: int = 0, nan_ratio: float = 0.05) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with random walk close prices.

    Args:
        n_bars: Number of bars.
        seed: RNG seed offset (combined with base seed 42).
        nan_ratio: Fraction of close values replaced with NaN (simulates halts).
    """
    rng = np.random.default_rng(42 + seed)
    # Random walk for close
    returns = rng.normal(0.001, 0.02, n_bars)
    close_raw = 100.0 * np.exp(np.cumsum(returns))
    # Build OHLCV from clean prices (open/high/low always valid for execution)
    open_prices = np.roll(close_raw, 1)
    open_prices[0] = close_raw[0]
    high = np.fmax(close_raw, open_prices) * (1 + rng.uniform(0, 0.01, n_bars))
    low = np.fmin(close_raw, open_prices) * (1 - rng.uniform(0, 0.01, n_bars))
    volume = rng.integers(1000, 100000, n_bars).astype(float)
    # Inject NaN gaps into close only (simulates missing close price / halt)
    close = close_raw.copy()
    if nan_ratio > 0:
        nan_positions = rng.choice(n_bars, size=int(n_bars * nan_ratio), replace=False)
        close[nan_positions] = np.nan
    dates = pd.bdate_range("2020-01-01", periods=n_bars)
    return pd.DataFrame(
        {"open": open_prices, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_signal(index: pd.DatetimeIndex, seed: int = 0) -> pd.Series:
    """Generate random signal in {-1, 0, 1}."""
    rng = np.random.default_rng(42 + seed)
    values = rng.choice([-1.0, 0.0, 1.0], size=len(index))
    return pd.Series(values, index=index)


def _build_synthetic_dataset(n_bars: int, n_symbols: int, nan_ratio: float = 0.05):
    """Build data_map, signal_map, codes for testing."""
    codes = [f"SYM{i:03d}.SZ" for i in range(n_symbols)]
    data_map = {}
    signal_map = {}
    for i, code in enumerate(codes):
        df = _make_ohlcv(n_bars, seed=i, nan_ratio=nan_ratio)
        data_map[code] = df
        signal_map[code] = _make_signal(df.index, seed=i + 1000)
    return data_map, signal_map, codes


# ---------------------------------------------------------------------------
# Gold standard reference: pre-vectorization pandas scalar path
# Source: main branch base.py lines 98-157 (commit 86f6012)
# ---------------------------------------------------------------------------


def _align_pandas_reference(
    data_map: dict,
    signal_map: dict,
    codes: list,
    optimizer=None,
) -> tuple:
    """Reference implementation of _align() using pure pandas operations.

    This replicates the original scalar reindex+ffill logic from before
    the vectorization optimization (commit fff6c16). Used as gold standard
    to validate that the optimized path produces identical results.
    """
    all_dates: set = set()
    for c in codes:
        all_dates.update(data_map[c].index)
    dates = pd.DatetimeIndex(sorted(all_dates))

    close = pd.DataFrame(index=dates, columns=codes, dtype=float)
    for c in codes:
        close[c] = data_map[c]["close"].reindex(dates)

    # ffill with limit to avoid masking long suspensions
    ffill_limit = (
        10 if len({_detect_market_for_align(c) for c in codes}) > 1 else 5
    )
    close = close.ffill(limit=ffill_limit)

    # Drop symbols that are entirely NaN
    all_nan_cols = [c for c in codes if close[c].isna().all()]
    if all_nan_cols:
        codes = [c for c in codes if c not in all_nan_cols]
        if not codes:
            raise ValueError("All symbols have no data in the requested date range")
        close = close[codes]

    pos = pd.DataFrame(0.0, index=dates, columns=codes)
    for c in codes:
        own_dates = data_map[c].index
        raw = signal_map[c].reindex(own_dates).fillna(0.0).clip(-1.0, 1.0)
        shifted = raw.shift(1).fillna(0.0)
        pos[c] = shifted.reindex(dates).ffill(limit=ffill_limit).fillna(0.0)

    ret = close.pct_change().fillna(0.0)

    if optimizer is not None:
        pos = optimizer(ret, pos, dates)

    scale = pos.abs().sum(axis=1).clip(lower=1.0)
    pos = pos.div(scale, axis=0)

    return dates, close, pos, ret


class TestAlignGoldStandard:
    """Gold standard regression: old pandas scalar path vs. new vectorized path.

    Ensures any optimization to _align() produces element-wise identical results
    to the original pandas reindex implementation across all edge cases.
    """

    @pytest.mark.parametrize("n_bars,n_symbols", [
        (100, 3),
        (500, 10),
        (2000, 30),
    ])
    def test_basic_equivalence(self, n_bars: int, n_symbols: int) -> None:
        """Vectorized _align() matches reference on clean synthetic data."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars, n_symbols, nan_ratio=0.05
        )

        dates_ref, close_ref, pos_ref, ret_ref = _align_pandas_reference(
            data_map, signal_map, list(codes)
        )
        dates_opt, close_opt, _, pos_opt, ret_opt = _align(
            data_map, signal_map, list(codes)
        )

        assert (dates_ref == dates_opt).all(), "Date indices must match exactly"
        pd.testing.assert_frame_equal(close_ref, close_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_ref, pos_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(ret_ref, ret_opt, rtol=1e-10, atol=1e-12)

    def test_nan_gaps_equivalence(self) -> None:
        """Both paths handle high NaN ratio (trading halts) identically."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=500, n_symbols=5, nan_ratio=0.20
        )

        dates_ref, close_ref, pos_ref, ret_ref = _align_pandas_reference(
            data_map, signal_map, list(codes)
        )
        dates_opt, close_opt, _, pos_opt, ret_opt = _align(
            data_map, signal_map, list(codes)
        )

        assert (dates_ref == dates_opt).all()
        pd.testing.assert_frame_equal(close_ref, close_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_ref, pos_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(ret_ref, ret_opt, rtol=1e-10, atol=1e-12)

    def test_cross_market_equivalence(self) -> None:
        """Both paths use ffill_limit=10 for cross-market scenarios."""
        dates = pd.bdate_range("2025-01-01", periods=300)
        rng = np.random.default_rng(42)

        # Equity symbols
        codes_eq = ["000001.SZ", "600519.SH", "000858.SZ"]
        # Crypto symbols (triggers multi-market ffill_limit=10)
        codes_crypto = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
        codes = codes_eq + codes_crypto

        data_map = {}
        signal_map = {}
        for i, code in enumerate(codes):
            close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 300)))
            # Inject NaN gaps
            nan_pos = rng.choice(300, size=15, replace=False)
            close[nan_pos] = np.nan
            df = pd.DataFrame({"close": close, "open": np.roll(close, 1)}, index=dates)
            data_map[code] = df
            signal_map[code] = pd.Series(
                rng.choice([-1.0, 0.0, 1.0], size=300), index=dates
            )

        dates_ref, close_ref, pos_ref, ret_ref = _align_pandas_reference(
            data_map, signal_map, list(codes)
        )
        dates_opt, close_opt, _, pos_opt, ret_opt = _align(
            data_map, signal_map, list(codes)
        )

        assert (dates_ref == dates_opt).all()
        pd.testing.assert_frame_equal(close_ref, close_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_ref, pos_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(ret_ref, ret_opt, rtol=1e-10, atol=1e-12)

    def test_all_nan_column_drop(self) -> None:
        """Both paths drop all-NaN symbols identically."""
        dates = pd.bdate_range("2025-01-01", periods=200)
        rng = np.random.default_rng(42)

        codes = ["VALID1.SZ", "VALID2.SZ", "ALLNAN.SZ", "VALID3.SZ"]
        data_map = {}
        signal_map = {}
        for code in codes:
            if code == "ALLNAN.SZ":
                close = np.full(200, np.nan)
            else:
                close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 200)))
            df = pd.DataFrame({"close": close, "open": close.copy()}, index=dates)
            data_map[code] = df
            signal_map[code] = pd.Series(
                rng.choice([-1.0, 0.0, 1.0], size=200), index=dates
            )

        dates_ref, close_ref, pos_ref, ret_ref = _align_pandas_reference(
            data_map, signal_map, list(codes)
        )
        dates_opt, close_opt, _, pos_opt, ret_opt = _align(
            data_map, signal_map, list(codes)
        )

        # Both should have dropped ALLNAN.SZ
        assert "ALLNAN.SZ" not in close_ref.columns
        assert "ALLNAN.SZ" not in close_opt.columns
        assert (dates_ref == dates_opt).all()
        pd.testing.assert_frame_equal(close_ref, close_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_ref, pos_opt, rtol=1e-10, atol=1e-12)

    def test_with_optimizer(self) -> None:
        """Both paths produce identical results when optimizer is applied."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=100, n_symbols=3, nan_ratio=0.05
        )

        def scale_optimizer(ret, pos, dates_arg):
            """Simple scaling optimizer for testing."""
            return pos * 0.5

        dates_ref, close_ref, pos_ref, ret_ref = _align_pandas_reference(
            data_map, signal_map, list(codes), optimizer=scale_optimizer
        )
        dates_opt, close_opt, _, pos_opt, ret_opt = _align(
            data_map, signal_map, list(codes), optimizer=scale_optimizer
        )

        assert (dates_ref == dates_opt).all()
        pd.testing.assert_frame_equal(close_ref, close_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_ref, pos_opt, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(ret_ref, ret_opt, rtol=1e-10, atol=1e-12)

    def test_end_to_end_equity_curve(self) -> None:
        """End-to-end backtest equity curve matches between old and new path."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=500, n_symbols=10, nan_ratio=0.05
        )

        # New (optimized) path
        dates_opt, close_opt, _, pos_opt, _ = _align(data_map, signal_map, list(codes))
        codes_opt = list(pos_opt.columns)
        engine_opt = ChinaAEngine({"initial_cash": 1_000_000})
        engine_opt._execute_bars(dates_opt, data_map, close_opt, pos_opt, codes_opt)
        equity_opt = pd.Series(
            [s.equity for s in engine_opt.equity_snapshots],
            index=[s.timestamp for s in engine_opt.equity_snapshots],
        )

        # Old (reference pandas) path
        dates_ref, close_ref, pos_ref, _ = _align_pandas_reference(
            data_map, signal_map, list(codes)
        )
        codes_ref = list(pos_ref.columns)
        engine_ref = ChinaAEngine({"initial_cash": 1_000_000})
        engine_ref._execute_bars(dates_ref, data_map, close_ref, pos_ref, codes_ref)
        equity_ref = pd.Series(
            [s.equity for s in engine_ref.equity_snapshots],
            index=[s.timestamp for s in engine_ref.equity_snapshots],
        )

        pd.testing.assert_series_equal(
            equity_ref, equity_opt, rtol=1e-6, atol=1e-8,
            check_names=False,
        )


# ---------------------------------------------------------------------------
# TestAlignConsistency: verify _align() output correctness
# ---------------------------------------------------------------------------


class TestAlignConsistency:
    """Verify _align() correctness with synthetic data containing NaN gaps."""

    def test_close_matrix_values(self) -> None:
        """Close matrix values match source data after alignment and ffill."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=150, n_symbols=5, nan_ratio=0.03
        )
        dates, close_df, _, _, _ = _align(data_map, signal_map, codes)

        # For each symbol, non-NaN source values should appear at correct positions
        for code in codes:
            src = data_map[code]["close"]
            for ts in src.index:
                if pd.notna(src[ts]) and ts in close_df.index:
                    assert close_df.at[ts, code] == pytest.approx(src[ts], rel=1e-10), (
                        f"Mismatch at {ts} for {code}"
                    )

    def test_position_matrix_shift(self) -> None:
        """position[t] = signal[t-1] — next-bar-open semantics."""
        dates = pd.bdate_range("2025-01-01", periods=20)
        df = pd.DataFrame(
            {"close": np.linspace(10, 30, 20), "open": np.linspace(10, 30, 20)},
            index=dates,
        )
        # Signal goes to 1.0 at bar index 5
        sig = pd.Series(0.0, index=dates)
        sig.iloc[5] = 1.0

        _, _, _, pos_df, _ = _align({"X": df}, {"X": sig}, ["X"])

        # At bar 5 position should still be 0 (signal not yet effective)
        assert pos_df.at[dates[5], "X"] == 0.0
        # At bar 6 position should reflect signal from bar 5
        assert pos_df.at[dates[6], "X"] > 0.0

    def test_ffill_limit_respected(self) -> None:
        """Consecutive NaN > ffill_limit should NOT be forward-filled."""
        n_bars = 30
        dates = pd.bdate_range("2025-01-01", periods=n_bars)
        close_vals = np.full(n_bars, np.nan)
        # Set value at bar 0, then leave bars 1-20 as NaN (gap > 5 default limit)
        close_vals[0] = 100.0
        close_vals[25] = 110.0
        df = pd.DataFrame(
            {"close": close_vals, "open": close_vals.copy()},
            index=dates,
        )
        sig = pd.Series(0.0, index=dates)
        data_map = {"X": df}
        signal_map = {"X": sig}

        _, close_df, _, _, _ = _align(data_map, signal_map, ["X"])

        # Bar 0 filled, bars 1-5 should be ffilled from bar 0
        for i in range(1, 6):
            assert close_df.at[dates[i], "X"] == pytest.approx(100.0)
        # Bars beyond ffill_limit=5 should remain NaN
        assert np.isnan(close_df.at[dates[6], "X"])
        assert np.isnan(close_df.at[dates[10], "X"])

    def test_all_nan_column_dropped(self) -> None:
        """A symbol with entirely NaN close should be dropped from output."""
        dates = pd.bdate_range("2025-01-01", periods=10)
        df_good = pd.DataFrame(
            {"close": np.linspace(10, 20, 10), "open": np.linspace(10, 20, 10)},
            index=dates,
        )
        df_bad = pd.DataFrame(
            {"close": [np.nan] * 10, "open": [np.nan] * 10},
            index=dates,
        )
        sig = pd.Series(1.0, index=dates)
        data_map = {"GOOD": df_good, "BAD": df_bad}
        signal_map = {"GOOD": sig, "BAD": sig}

        _, close_df, _, pos_df, _ = _align(data_map, signal_map, ["GOOD", "BAD"])

        assert "GOOD" in close_df.columns
        assert "BAD" not in close_df.columns
        assert "BAD" not in pos_df.columns

    def test_multi_market_ffill_limit(self) -> None:
        """Cross-market scenario uses ffill_limit=10."""
        n_bars = 30
        dates = pd.bdate_range("2025-01-01", periods=n_bars)
        # Equity symbol
        close_equity = np.full(n_bars, np.nan)
        close_equity[0] = 50.0
        close_equity[20] = 55.0
        df_equity = pd.DataFrame({"close": close_equity, "open": close_equity.copy()}, index=dates)
        # Crypto symbol (triggers multi-market detection -> ffill_limit=10)
        close_crypto = np.linspace(1000, 1100, n_bars)
        df_crypto = pd.DataFrame({"close": close_crypto, "open": close_crypto.copy()}, index=dates)

        sig = pd.Series(0.0, index=dates)
        data_map = {"000001.SZ": df_equity, "BTC-USDT": df_crypto}
        signal_map = {"000001.SZ": sig, "BTC-USDT": sig}

        _, close_df, _, _, _ = _align(data_map, signal_map, ["000001.SZ", "BTC-USDT"])

        # With ffill_limit=10, bars 1-10 should be ffilled from bar 0
        for i in range(1, 11):
            assert close_df.at[dates[i], "000001.SZ"] == pytest.approx(50.0)
        # Bar 11 should be NaN (exceeded limit=10)
        assert np.isnan(close_df.at[dates[11], "000001.SZ"])


# ---------------------------------------------------------------------------
# TestAlignPerformance: verify performance targets
# ---------------------------------------------------------------------------


class TestAlignPerformance:
    """Verify _align() performance meets target thresholds."""

    def test_5000bars_50symbols_under_35ms(self) -> None:
        """5000 bars x 50 symbols should complete in < 50ms (median of 7 runs).

        Design target is 15-35ms on developer machines; CI runners are slower
        due to shared resources, so the gate is relaxed to 50ms which still
        guarantees >40x improvement over the pre-optimization 2-2.5s baseline.
        """
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=5000, n_symbols=50, nan_ratio=0.02
        )

        # Warmup run (JIT, caching effects)
        _align(data_map, signal_map, codes)

        timings = []
        for _ in range(7):
            start = time.perf_counter()
            _align(data_map, signal_map, codes)
            elapsed = time.perf_counter() - start
            timings.append(elapsed)

        median_ms = sorted(timings)[len(timings) // 2] * 1000
        print(f"\n  _align 5000x50 median: {median_ms:.2f} ms")
        # Performance gate: median < 50ms (accommodates CI runner variance)
        # Ref: design doc specifies 15-35ms on dev machines; 50ms guarantees
        # >40x improvement over pre-optimization 2-2.5s baseline.
        assert median_ms < 50.0, (
            f"Performance regression: median {median_ms:.2f}ms exceeds 50ms target. "
            f"All timings (ms): {[f'{t*1000:.2f}' for t in timings]}"
        )

    @pytest.mark.skip(reason="Baseline comparison - enable manually if needed")
    def test_speedup_ratio(self) -> None:
        """Compare optimized vs naive reindex-based implementation."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=5000, n_symbols=50, nan_ratio=0.02
        )

        # Optimized path
        start = time.perf_counter()
        _align(data_map, signal_map, codes)
        opt_time = time.perf_counter() - start

        # Naive reference: per-symbol reindex
        all_dates = sorted(set().union(*(df.index for df in data_map.values())))
        unified_idx = pd.DatetimeIndex(all_dates)
        start = time.perf_counter()
        for code in codes:
            data_map[code]["close"].reindex(unified_idx).ffill(limit=5)
        naive_time = time.perf_counter() - start

        ratio = naive_time / opt_time if opt_time > 0 else float("inf")
        print(f"\n  Speedup ratio: {ratio:.2f}x (naive={naive_time*1000:.1f}ms, opt={opt_time*1000:.1f}ms)")
        assert ratio > 1.0, "Optimized path should be faster than naive reindex"


# ---------------------------------------------------------------------------
# TestExecuteBarsOptimization: verify _execute_bars correctness
# ---------------------------------------------------------------------------


class TestExecuteBarsOptimization:
    """Verify _execute_bars optimization preserves correctness."""

    def _run_small_backtest(self):
        """Run a minimal backtest with 200 bars x 3 symbols."""
        data_map, signal_map, codes = _build_synthetic_dataset(
            n_bars=200, n_symbols=3, nan_ratio=0.01
        )
        dates, close_df, _, target_pos, _ = _align(data_map, signal_map, codes)
        # Sync codes after potential all-NaN drops
        codes = [c for c in codes if c in target_pos.columns]

        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._execute_bars(dates, data_map, close_df, target_pos, codes)
        return engine, dates, close_df, target_pos, codes

    def test_basic_backtest_runs(self) -> None:
        """Full backtest with synthetic data completes without error."""
        engine, dates, close_df, target_pos, codes = self._run_small_backtest()

        # Should have equity snapshots for every bar
        assert len(engine.equity_snapshots) == len(dates)
        # Final equity should be positive (started at 1M, mild random walk)
        assert engine.equity_snapshots[-1].equity > 0
        # Should have generated some trades
        assert len(engine.trades) > 0

    def test_safe_price_fast_path(self) -> None:
        """Fast path (_arr/_row/_col) returns same result as slow path."""
        dates = pd.DatetimeIndex(pd.bdate_range("2025-01-01", periods=10))
        close_data = np.array([[10.0, 20.0], [11.0, 21.0], [12.0, np.nan],
                               [13.0, 23.0], [14.0, 24.0], [15.0, 25.0],
                               [16.0, 26.0], [17.0, 27.0], [18.0, 28.0],
                               [19.0, 29.0]])
        close_df = pd.DataFrame(close_data, index=dates, columns=["A", "B"])
        arr = close_data.copy()

        for row_idx in range(len(dates)):
            for col_idx, sym in enumerate(["A", "B"]):
                ts = dates[row_idx]
                fallback = 999.0
                slow = BaseEngine._safe_price(close_df, ts, sym, fallback)
                fast = BaseEngine._safe_price(
                    close_df, ts, sym, fallback,
                    _arr=arr, _row=row_idx, _col=col_idx,
                )
                assert slow == fast, (
                    f"Mismatch at row={row_idx}, col={col_idx}: slow={slow}, fast={fast}"
                )

    def test_instance_attrs_cleaned(self) -> None:
        """After _execute_bars, _close_arr and _code_to_col are set to None."""
        engine, _, _, _, _ = self._run_small_backtest()
        assert engine._close_arr is None
        assert engine._code_to_col is None


# ---------------------------------------------------------------------------
# TestFfillHelpers: verify numpy ffill correctness
# ---------------------------------------------------------------------------


class TestFfillHelpers:
    """Verify numpy-based forward-fill helpers."""

    def test_ffill_1d_basic(self) -> None:
        arr = np.array([1.0, np.nan, np.nan, 4.0, np.nan])
        _ffill_1d(arr, limit=2)
        expected = np.array([1.0, 1.0, 1.0, 4.0, 4.0])
        np.testing.assert_array_equal(arr, expected)

    def test_ffill_1d_limit_exceeded(self) -> None:
        arr = np.array([1.0, np.nan, np.nan, np.nan, 5.0])
        _ffill_1d(arr, limit=1)
        expected = np.array([1.0, 1.0, np.nan, np.nan, 5.0])
        np.testing.assert_array_equal(arr, expected)

    def test_ffill_2d_column_wise(self) -> None:
        arr = np.array([[1.0, 10.0], [np.nan, np.nan], [3.0, np.nan], [np.nan, 40.0]])
        result = _ffill_2d(arr, limit=2)
        # Column 0: [1, 1, 3, 3]
        # Column 1: [10, 10, 10, 40]
        assert result[1, 0] == 1.0
        assert result[3, 0] == 3.0
        assert result[1, 1] == 10.0
        assert result[2, 1] == 10.0

    def test_ffill_1d_leading_nan(self) -> None:
        """Leading NaN with no valid predecessor stays NaN."""
        arr = np.array([np.nan, np.nan, 3.0, np.nan])
        _ffill_1d(arr, limit=5)
        assert np.isnan(arr[0])
        assert np.isnan(arr[1])
        assert arr[2] == 3.0
        assert arr[3] == 3.0


# ---------------------------------------------------------------------------
# TestDetectMarket: verify market detection helper
# ---------------------------------------------------------------------------


class TestDetectMarket:
    """Verify _detect_market_for_align classification."""

    def test_equity_codes(self) -> None:
        assert _detect_market_for_align("000001.SZ") == "equity"
        assert _detect_market_for_align("600519.SH") == "equity"

    def test_crypto_codes(self) -> None:
        assert _detect_market_for_align("BTC-USDT") == "crypto"
        assert _detect_market_for_align("ETH-USDT") == "crypto"

    def test_forex_codes(self) -> None:
        assert _detect_market_for_align("EUR/USD") == "forex"
        assert _detect_market_for_align("EURUSD.FX") == "forex"


# ---------------------------------------------------------------------------
# TestFundPanelCompatibility: E2E verify vectorized _align() ignores fund:*
# ---------------------------------------------------------------------------


def _make_data_map_with_fund(n_dates=200, n_codes=5, fund_cols=None):
    """Create synthetic data_map with OHLCV + optional fund:* columns."""
    if fund_cols is None:
        fund_cols = ["fund:revenue", "fund:roe", "fund:net_profit"]

    np.random.seed(42)
    dates = pd.bdate_range("2023-01-01", periods=n_dates)
    data_map = {}
    signal_map = {}
    codes = [f"SYM{i:03d}.SZ" for i in range(n_codes)]

    for c in codes:
        price = 100 + np.cumsum(np.random.randn(n_dates) * 0.5)
        df = pd.DataFrame(
            {
                "open": price * 0.99,
                "high": price * 1.01,
                "low": price * 0.98,
                "close": price,
                "volume": np.random.randint(1000, 10000, n_dates).astype(float),
            },
            index=dates,
        )

        # Inject fund:* enrichment columns
        for fc in fund_cols:
            df[fc] = np.random.rand(n_dates) * 100

        data_map[c] = df
        # Simple alternating signal
        signal_map[c] = pd.Series(
            np.where(np.random.rand(n_dates) > 0.5, 1.0, 0.0),
            index=dates,
        )

    return data_map, signal_map, codes


class TestFundPanelCompatibility:
    """E2E: verify vectorized _align() ignores fund:* enrichment columns."""

    def test_align_output_excludes_fund_columns(self) -> None:
        """Returned close_df and target_pos columns contain only symbol codes."""
        data_map, signal_map, codes = _make_data_map_with_fund(
            n_dates=200, n_codes=5
        )

        _, close_df, _, pos_df, ret_df = _align(data_map, signal_map, list(codes))

        # Columns must only be symbol codes, no fund:* leakage
        for col in close_df.columns:
            assert not col.startswith("fund:"), (
                f"fund column '{col}' leaked into close_df"
            )
        for col in pos_df.columns:
            assert not col.startswith("fund:"), (
                f"fund column '{col}' leaked into target_pos"
            )
        for col in ret_df.columns:
            assert not col.startswith("fund:"), (
                f"fund column '{col}' leaked into ret_df"
            )
        # All original codes should be present
        assert set(close_df.columns) == set(codes)
        assert set(pos_df.columns) == set(codes)

    def test_align_equivalence_with_and_without_fund_columns(self) -> None:
        """_align() output is identical whether fund:* columns are present or not."""
        np.random.seed(42)
        n_dates, n_codes = 200, 5
        dates = pd.bdate_range("2023-01-01", periods=n_dates)
        codes = [f"SYM{i:03d}.SZ" for i in range(n_codes)]

        data_map_clean = {}
        data_map_fund = {}
        signal_map = {}

        for c in codes:
            price = 100 + np.cumsum(np.random.randn(n_dates) * 0.5)
            base_df = pd.DataFrame(
                {
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": np.random.randint(1000, 10000, n_dates).astype(float),
                },
                index=dates,
            )
            data_map_clean[c] = base_df.copy()

            fund_df = base_df.copy()
            fund_df["fund:revenue"] = np.random.rand(n_dates) * 1e6
            fund_df["fund:roe"] = np.random.rand(n_dates) * 0.3
            fund_df["fund:net_profit"] = np.random.rand(n_dates) * 5e5
            data_map_fund[c] = fund_df

            signal_map[c] = pd.Series(
                np.where(np.random.rand(n_dates) > 0.5, 1.0, 0.0),
                index=dates,
            )

        _, close_clean, _, pos_clean, ret_clean = _align(
            data_map_clean, signal_map, list(codes)
        )
        _, close_fund, _, pos_fund, ret_fund = _align(
            data_map_fund, signal_map, list(codes)
        )

        pd.testing.assert_frame_equal(close_clean, close_fund, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(pos_clean, pos_fund, rtol=1e-10, atol=1e-12)
        pd.testing.assert_frame_equal(ret_clean, ret_fund, rtol=1e-10, atol=1e-12)

    def test_heterogeneous_fund_columns(self) -> None:
        """_align() works when different symbols have different fund:* columns."""
        np.random.seed(99)
        n_dates = 150
        dates = pd.bdate_range("2023-01-01", periods=n_dates)
        codes = ["AAA.SZ", "BBB.SZ", "CCC.SZ"]

        data_map = {}
        signal_map = {}

        for i, c in enumerate(codes):
            price = 50 + np.cumsum(np.random.randn(n_dates) * 0.3)
            df = pd.DataFrame(
                {
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": np.random.randint(500, 5000, n_dates).astype(float),
                },
                index=dates,
            )
            # Different fund:* columns per symbol
            if i == 0:
                df["fund:roe"] = np.random.rand(n_dates) * 0.2
                df["fund:revenue"] = np.random.rand(n_dates) * 1e6
            elif i == 1:
                df["fund:roe"] = np.random.rand(n_dates) * 0.15
            else:
                df["fund:net_profit"] = np.random.rand(n_dates) * 3e5
                df["fund:eps"] = np.random.rand(n_dates) * 5.0

            data_map[c] = df
            signal_map[c] = pd.Series(
                np.where(np.random.rand(n_dates) > 0.5, 1.0, 0.0),
                index=dates,
            )

        # Should not raise
        _, close_df, _, pos_df, ret_df = _align(data_map, signal_map, list(codes))

        assert set(close_df.columns) == set(codes)
        assert set(pos_df.columns) == set(codes)
        assert close_df.shape == (n_dates, len(codes))
        assert pos_df.shape == (n_dates, len(codes))
        assert ret_df.shape == (n_dates, len(codes))

    def test_full_backtest_with_fund_columns(self) -> None:
        """Full E2E: BaseEngine.run through _align with fund:* columns."""
        data_map, signal_map, codes = _make_data_map_with_fund(
            n_dates=200, n_codes=4
        )

        dates, close_df, _, target_pos, _ = _align(data_map, signal_map, list(codes))
        valid_codes = [c for c in codes if c in target_pos.columns]

        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._execute_bars(dates, data_map, close_df, target_pos, valid_codes)

        # Should complete with equity snapshots for every bar
        assert len(engine.equity_snapshots) == len(dates)
        # Final equity should be positive
        assert engine.equity_snapshots[-1].equity > 0
        # Should have executed trades
        assert len(engine.trades) > 0

    def test_fund_columns_do_not_leak_to_close_matrix(self) -> None:
        """fund:* columns with sentinel value 999.0 must not appear in close_df."""
        np.random.seed(7)
        n_dates = 100
        sentinel = 999.0
        dates = pd.bdate_range("2023-06-01", periods=n_dates)
        codes = ["X.SZ", "Y.SZ"]

        data_map = {}
        signal_map = {}

        for c in codes:
            price = 30 + np.cumsum(np.random.randn(n_dates) * 0.2)
            # Ensure no price naturally equals sentinel
            price = np.where(np.abs(price - sentinel) < 1.0, price + 5.0, price)
            df = pd.DataFrame(
                {
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": np.random.randint(100, 1000, n_dates).astype(float),
                },
                index=dates,
            )
            # All fund columns filled with sentinel
            df["fund:revenue"] = sentinel
            df["fund:roe"] = sentinel
            df["fund:net_profit"] = sentinel

            data_map[c] = df
            signal_map[c] = pd.Series(1.0, index=dates)

        _, close_df, _, _, _ = _align(data_map, signal_map, list(codes))

        # No cell in close_df should contain the sentinel value
        assert not (close_df == sentinel).any().any(), (
            "Sentinel 999.0 from fund:* columns leaked into close matrix"
        )
