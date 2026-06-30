"""Equivalence tests for optimized factor operators.

Tests verify that the fast paths (bottleneck / numpy stride) produce
identical results to the original pandas rolling().apply() fallback.
"""

from __future__ import annotations

import importlib
import os
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

# ── Helpers to force fallback path ──


def _reload_base_with_bottleneck(enabled: bool):
    """Reload base.py with bottleneck enabled or disabled."""
    os.environ["VIBE_TRADING_DISABLE_BOTTLENECK"] = "0" if enabled else "1"
    # Force reimport of _backend and base
    if "src.factors._backend" in sys.modules:
        del sys.modules["src.factors._backend"]
    if "src.factors.base" in sys.modules:
        del sys.modules["src.factors.base"]
    mod = importlib.import_module("src.factors.base")
    return mod


# ── Reference implementations (original pandas path) ──


def _ref_ts_rank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    def _last_rank(arr: np.ndarray) -> float:
        if np.isnan(arr).all():
            return np.nan
        last = arr[-1]
        if np.isnan(last):
            return np.nan
        valid = arr[~np.isnan(arr)]
        if valid.size == 0:
            return np.nan
        less = (valid < last).sum()
        eq = (valid == last).sum()
        rank_avg = less + 0.5 * (eq + 1)
        return float(rank_avg / valid.size)

    return df.rolling(window=n, min_periods=n).apply(_last_rank, raw=True)


def _ref_ts_argmax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    def _argmax_last(arr: np.ndarray) -> float:
        if np.isnan(arr).all():
            return np.nan
        arr_filled = np.where(np.isnan(arr), -np.inf, arr)
        return float(np.argmax(arr_filled))

    return df.rolling(window=n, min_periods=n).apply(_argmax_last, raw=True)


def _ref_ts_argmin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    def _argmin_last(arr: np.ndarray) -> float:
        if np.isnan(arr).all():
            return np.nan
        arr_filled = np.where(np.isnan(arr), np.inf, arr)
        return float(np.argmin(arr_filled))

    return df.rolling(window=n, min_periods=n).apply(_argmin_last, raw=True)


def _ref_decay_linear(df: pd.DataFrame, n: int) -> pd.DataFrame:
    weights = np.arange(n, 0, -1, dtype=np.float64)
    weights /= weights.sum()

    def _apply(arr: np.ndarray) -> float:
        if np.isnan(arr).any():
            return np.nan
        return float(np.dot(arr, weights))

    return df.rolling(window=n, min_periods=n).apply(_apply, raw=True)


# ── Fixtures ──


@pytest.fixture
def random_df():
    """100 rows × 10 columns random DataFrame."""
    np.random.seed(42)
    return pd.DataFrame(np.random.randn(100, 10))


@pytest.fixture
def random_df_with_nan():
    """100 rows × 10 columns with scattered NaN values."""
    np.random.seed(42)
    df = pd.DataFrame(np.random.randn(100, 10))
    df.iloc[10, 2] = np.nan
    df.iloc[30, 5] = np.nan
    df.iloc[50, 0] = np.nan
    df.iloc[70, 8] = np.nan
    return df


# ── ts_rank tests ──


class TestTsRank:
    @pytest.mark.parametrize("n", [3, 5, 10, 20])
    def test_equivalence_clean(self, random_df, n):
        """Fast path matches pandas reference on clean data."""
        base = _reload_base_with_bottleneck(True)
        result = base.ts_rank(random_df, n)
        expected = _ref_ts_rank(random_df, n)
        pd.testing.assert_frame_equal(result, expected, atol=1e-12)

    @pytest.mark.parametrize("n", [5, 10])
    def test_equivalence_with_nan(self, random_df_with_nan, n):
        """Fast path matches pandas reference with NaN values."""
        base = _reload_base_with_bottleneck(True)
        result = base.ts_rank(random_df_with_nan, n)
        expected = _ref_ts_rank(random_df_with_nan, n)
        pd.testing.assert_frame_equal(result, expected, atol=1e-12)

    def test_warmup_is_nan(self, random_df):
        """First n-1 rows must be NaN."""
        base = _reload_base_with_bottleneck(True)
        n = 10
        result = base.ts_rank(random_df, n)
        assert result.iloc[: n - 1].isna().all().all()

    def test_fallback_path(self, random_df):
        """Fallback (bottleneck disabled) still works correctly."""
        base = _reload_base_with_bottleneck(False)
        result = base.ts_rank(random_df, 5)
        expected = _ref_ts_rank(random_df, 5)
        pd.testing.assert_frame_equal(result, expected, atol=1e-12)

    def test_all_nan_window_emits_no_runtime_warning(self):
        """All-NaN windows stay NaN without divide-by-zero noise."""
        base = _reload_base_with_bottleneck(True)
        df = pd.DataFrame(np.nan, index=range(12), columns=list("abc"))
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            result = base.ts_rank(df, 5)

        assert result.isna().all().all()

    def test_constant_window(self):
        """All-same values: rank should be (n+1)/(2n) for average rank."""
        base = _reload_base_with_bottleneck(True)
        df = pd.DataFrame(np.ones((20, 3)))
        result = base.ts_rank(df, 5)
        # For 5 identical values: less=0, eq=5, rank_avg=0+0.5*(5+1)=3, pct=3/5=0.6
        expected_val = 0.6
        assert np.allclose(result.iloc[4:].values, expected_val)

    def test_invalid_window(self):
        base = _reload_base_with_bottleneck(True)
        with pytest.raises(ValueError, match="window must be >= 1"):
            base.ts_rank(pd.DataFrame(), 0)


# ── ts_argmax tests ──


class TestTsArgmax:
    @pytest.mark.parametrize("n", [3, 5, 10, 20])
    def test_equivalence_clean(self, random_df, n):
        base = _reload_base_with_bottleneck(True)
        result = base.ts_argmax(random_df, n)
        expected = _ref_ts_argmax(random_df, n)
        pd.testing.assert_frame_equal(result, expected)

    def test_warmup_is_nan(self, random_df):
        base = _reload_base_with_bottleneck(True)
        n = 10
        result = base.ts_argmax(random_df, n)
        assert result.iloc[: n - 1].isna().all().all()

    def test_fallback_path(self, random_df):
        base = _reload_base_with_bottleneck(False)
        result = base.ts_argmax(random_df, 5)
        expected = _ref_ts_argmax(random_df, 5)
        pd.testing.assert_frame_equal(result, expected)

    def test_integer_output(self, random_df):
        """argmax returns integer indices (0-based), not floats."""
        base = _reload_base_with_bottleneck(True)
        result = base.ts_argmax(random_df, 5)
        valid = result.iloc[4:]
        assert (valid == valid.astype(int)).all().all()

    def test_invalid_window(self):
        base = _reload_base_with_bottleneck(True)
        with pytest.raises(ValueError, match="window must be >= 1"):
            base.ts_argmax(pd.DataFrame(), 0)


# ── ts_argmin tests ──


class TestTsArgmin:
    @pytest.mark.parametrize("n", [3, 5, 10, 20])
    def test_equivalence_clean(self, random_df, n):
        base = _reload_base_with_bottleneck(True)
        result = base.ts_argmin(random_df, n)
        expected = _ref_ts_argmin(random_df, n)
        pd.testing.assert_frame_equal(result, expected)

    def test_warmup_is_nan(self, random_df):
        base = _reload_base_with_bottleneck(True)
        n = 10
        result = base.ts_argmin(random_df, n)
        assert result.iloc[: n - 1].isna().all().all()

    def test_fallback_path(self, random_df):
        base = _reload_base_with_bottleneck(False)
        result = base.ts_argmin(random_df, 5)
        expected = _ref_ts_argmin(random_df, 5)
        pd.testing.assert_frame_equal(result, expected)

    def test_invalid_window(self):
        base = _reload_base_with_bottleneck(True)
        with pytest.raises(ValueError, match="window must be >= 1"):
            base.ts_argmin(pd.DataFrame(), 0)


# ── decay_linear tests ──


class TestDecayLinear:
    @pytest.mark.parametrize("n", [3, 5, 10, 20])
    def test_equivalence_clean(self, random_df, n):
        base = _reload_base_with_bottleneck(True)
        result = base.decay_linear(random_df, n)
        expected = _ref_decay_linear(random_df, n)
        pd.testing.assert_frame_equal(result, expected, atol=1e-10)

    @pytest.mark.parametrize("n", [5, 10])
    def test_equivalence_with_nan(self, random_df_with_nan, n):
        base = _reload_base_with_bottleneck(True)
        result = base.decay_linear(random_df_with_nan, n)
        expected = _ref_decay_linear(random_df_with_nan, n)
        pd.testing.assert_frame_equal(result, expected, atol=1e-10)

    def test_warmup_is_nan(self, random_df):
        base = _reload_base_with_bottleneck(True)
        n = 10
        result = base.decay_linear(random_df, n)
        assert result.iloc[: n - 1].isna().all().all()

    def test_no_lookahead(self, random_df):
        """Modifying future values must not change past outputs."""
        base = _reload_base_with_bottleneck(True)
        n = 10
        df_mod = random_df.copy()
        df_mod.iloc[50:] = 999.0
        result_orig = base.decay_linear(random_df, n)
        result_mod = base.decay_linear(df_mod, n)
        # Output at row 49 (index 49) should be identical
        pd.testing.assert_series_equal(
            result_orig.iloc[49], result_mod.iloc[49], atol=1e-10
        )

    def test_fallback_path(self, random_df):
        base = _reload_base_with_bottleneck(False)
        result = base.decay_linear(random_df, 5)
        expected = _ref_decay_linear(random_df, 5)
        pd.testing.assert_frame_equal(result, expected, atol=1e-10)

    def test_invalid_window(self):
        base = _reload_base_with_bottleneck(True)
        with pytest.raises(ValueError, match="window must be >= 1"):
            base.decay_linear(pd.DataFrame(), 0)


# ── Backend detection tests ──


class TestBackend:
    def test_bottleneck_available(self):
        """bottleneck should be available in test environment."""
        from src.factors._backend import HAS_BOTTLENECK

        assert HAS_BOTTLENECK is True

    def test_disable_env_var(self):
        """VIBE_TRADING_DISABLE_BOTTLENECK=1 should disable bottleneck."""
        _reload_base_with_bottleneck(False)
        from src.factors._backend import HAS_BOTTLENECK

        assert HAS_BOTTLENECK is False
        # Restore
        _reload_base_with_bottleneck(True)
