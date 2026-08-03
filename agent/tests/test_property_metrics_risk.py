"""Property-based invariants for the metrics / risk-metrics / risk-overlay cores.

The assertion-style tests elsewhere prove *specific* inputs behave; these
hypothesis tests stress the numeric cores with adversarial-but-valid inputs so
invariants hold for *any* series:

- ``observed_sharpe``  — scale / sign invariance, zero-mean -> ~0, finite.
- ``probabilistic_sharpe_ratio`` — SR=0 -> 0.5; monotone in SR.
- ``deflated_sharpe_ratio`` — never above the corresponding PSR; n_trials gate.
- ``expected_shortfall`` — monotone in alpha; bounded below by the tail
  quantile; invalid alpha raises; short series -> NaN.
- ``_max_drawdown_from_returns`` — never positive.
- ``buy_and_hold_return`` — telescopes to ``P_end / P_start - 1``.
- ``rank_trials_risk_adjusted`` — best has the max score; gates reject.
- ``apply_risk_overlay`` — the gross-leverage cap is never violated (bar proxy).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402 — guarded by importorskip
from hypothesis import strategies as st  # noqa: E402

from backtest.metrics import buy_and_hold_return
from backtest.risk_metrics import (
    _max_drawdown_from_returns,
    deflated_sharpe_ratio,
    expected_shortfall,
    observed_sharpe,
    probabilistic_sharpe_ratio,
    rank_trials_risk_adjusted,
)
from backtest.risk_overlay import apply_risk_overlay, load_risk_overlay

# Keep the property suite fast enough for the 10-minute CI budget.
settings.register_profile("vibe-trading", max_examples=50, deadline=None)
settings.load_profile("vibe-trading")

# Arbitrary-but-valid per-bar returns (realistic range, always finite).
_returns = st.lists(
    st.floats(min_value=-0.25, max_value=0.25, allow_nan=False, allow_infinity=False),
    min_size=10,
    max_size=300,
).map(lambda xs: np.asarray(xs, dtype=float))


# ---------------------------------------------------------------------------
# observed_sharpe
# ---------------------------------------------------------------------------


@given(_returns, st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False))
def test_observed_sharpe_scale_invariance(returns, scale):
    """Sharpe is scale-invariant: multiplying returns by c>0 leaves it unchanged."""
    base = observed_sharpe(returns)
    scaled = observed_sharpe(returns * scale)
    assert base == pytest.approx(scaled, rel=1e-6, abs=1e-9)


@given(_returns)
def test_observed_sharpe_sign_flip(returns):
    """Flipping the sign of every return flips the sign of Sharpe."""
    assert observed_sharpe(-returns) == pytest.approx(-observed_sharpe(returns), rel=1e-6, abs=1e-9)


@given(_returns)
def test_observed_sharpe_zero_mean_is_zero(returns):
    """A demeaned series has Sharpe ~0 (no drift, only noise)."""
    demeaned = returns - np.mean(returns)
    assert abs(observed_sharpe(demeaned)) <= 1e-6


@given(_returns, st.integers(min_value=52, max_value=756))
def test_observed_sharpe_always_finite(returns, bars_per_year):
    """No adversarial finite input may produce NaN/inf Sharpe."""
    value = observed_sharpe(returns, bars_per_year=bars_per_year)
    assert np.isfinite(value)


# ---------------------------------------------------------------------------
# probabilistic_sharpe_ratio / deflated_sharpe_ratio
# ---------------------------------------------------------------------------


@given(st.integers(min_value=5, max_value=10_000))
def test_psr_zero_sharpe_is_half(n_obs):
    """A zero-Sharpe strategy is 50% likely to beat a zero benchmark."""
    out = probabilistic_sharpe_ratio(0.0, n_obs)
    assert out["psr"] == pytest.approx(0.5, abs=1e-9)


@given(
    st.floats(min_value=-3.0, max_value=2.9, allow_nan=False, allow_infinity=False),
    st.integers(min_value=5, max_value=2000),
)
def test_psr_monotone_in_sharpe(low, n_obs):
    """PSR is non-decreasing in the observed (annualised) Sharpe."""
    out_low = probabilistic_sharpe_ratio(low, n_obs)
    out_high = probabilistic_sharpe_ratio(low + 0.05, n_obs)
    assert out_low["psr"] <= out_high["psr"] + 1e-12


@given(
    st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=5, max_value=2000),
)
def test_dsr_never_exceeds_psr(sharpe, n_obs):
    """Multiple-trial deflation cannot raise the confidence above the PSR."""
    psr = probabilistic_sharpe_ratio(sharpe, n_obs)["psr"]
    dsr = deflated_sharpe_ratio(sharpe, n_obs, n_trials=20)["dsr"]
    assert dsr <= psr + 1e-9


def test_dsr_rejects_invalid_trial_count():
    """n_trials < 1 (or a bool) is a documented error, not a crash."""
    out = deflated_sharpe_ratio(0.5, 100, n_trials=0)
    assert "error" in out
    out_bool = deflated_sharpe_ratio(0.5, 100, n_trials=True)
    assert "error" in out_bool


# ---------------------------------------------------------------------------
# expected_shortfall (CVaR)
# ---------------------------------------------------------------------------


@given(
    st.floats(min_value=0.51, max_value=0.99, allow_nan=False, allow_infinity=False),
    _returns,
)
def test_expected_shortfall_bounds_tail_quantile(alpha, returns):
    """ES(alpha) is the mean of the tail, so it can never sit below its own
    tail quantile (VaR) — the worst-case estimate must dominate the cutoff."""
    es = expected_shortfall(returns, alpha=alpha)
    losses = -returns[np.isfinite(returns)]
    var = float(np.quantile(losses, alpha))
    assert es >= var - 1e-9


@given(
    st.floats(min_value=0.51, max_value=0.98, allow_nan=False, allow_infinity=False),
    _returns,
)
def test_expected_shortfall_monotone_in_alpha(alpha, returns):
    """A deeper tail (larger alpha) can only raise the expected loss magnitude."""
    es_a = expected_shortfall(returns, alpha=alpha)
    es_b = expected_shortfall(returns, alpha=alpha + 0.01)
    assert es_a <= es_b + 1e-9


def test_expected_shortfall_invalid_alpha_raises():
    with pytest.raises(ValueError):
        expected_shortfall(np.array([0.01, -0.02, 0.0, 0.03, -0.01, 0.02, 0.0, 0.01, -0.01, 0.0]), alpha=0.5)
    with pytest.raises(ValueError):
        expected_shortfall(np.array([0.01, -0.02, 0.0, 0.03, -0.01, 0.02, 0.0, 0.01, -0.01, 0.0]), alpha=1.0)


def test_expected_shortfall_short_series_is_nan():
    """Fewer than 5 observations yields NaN (insufficient tail evidence)."""
    assert np.isnan(expected_shortfall(np.array([0.01, -0.02, 0.0, 0.03])))


# ---------------------------------------------------------------------------
# drawdown
# ---------------------------------------------------------------------------


@given(_returns)
def test_max_drawdown_never_positive(returns):
    """A drawdown is a loss relative to a running peak: it can never be > 0."""
    assert _max_drawdown_from_returns(returns) <= 1e-12


# ---------------------------------------------------------------------------
# buy_and_hold_return
# ---------------------------------------------------------------------------


@given(
    st.lists(
        st.floats(min_value=1e-3, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=30,
    )
)
def test_buy_and_hold_telescopes_to_price_relative(prices):
    """With positive prices the total return is exactly P_end / P_start - 1."""
    series = pd.Series(prices)
    assert buy_and_hold_return(series) == pytest.approx(prices[-1] / prices[0] - 1.0, rel=1e-9)


def test_buy_and_hold_rejects_nonpositive_entry():
    """A zero or negative entry price has no honest percentage return."""
    assert buy_and_hold_return(pd.Series([0.0, 1.0, 2.0])) is None
    assert buy_and_hold_return(pd.Series([-1.0, 1.0])) is None
    assert buy_and_hold_return(pd.Series([1.0])) is None  # fewer than 2 obs


# ---------------------------------------------------------------------------
# rank_trials_risk_adjusted
# ---------------------------------------------------------------------------

_trial_matrix = st.integers(min_value=20, max_value=60).flatmap(
    lambda n: st.lists(
        st.lists(
            st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        ),
        min_size=1,
        max_size=6,
    )
).map(lambda cols: np.asarray(cols, dtype=float).T)  # (T, N)


@given(_trial_matrix)
def test_rank_trials_best_is_max_score(mat):
    """The reported best trial must be the highest-scoring accepted trial, and
    the ranking must be sorted descending by score."""
    out = rank_trials_risk_adjusted(mat, max_dd_limit=1.0, min_psr=0.0)
    assert out["n_trials"] == mat.shape[1]
    ranking = out["ranking"]
    assert ranking == sorted(ranking, key=lambda s: s["score"], reverse=True)
    if ranking:
        assert out["best"]["trial_index"] == ranking[0]["trial_index"]
    # Every entry is either accepted or rejected, never both.
    assert out["n_accepted"] + out["n_rejected"] == mat.shape[1]


@given(_trial_matrix)
def test_rank_trials_hard_gates_reject(mat):
    """Impossible gates (zero DD tolerance + zero CVaR budget) reject every
    trial that ever loses money, leaving no best candidate."""
    # Force at least one losing bar per column so the zero-DD / zero-CVaR
    # gates provably have something to reject (an all-gain column would pass).
    mat[0, :] = -0.05
    out = rank_trials_risk_adjusted(mat, max_dd_limit=0.0, min_psr=0.99, max_cvar=0.0)
    assert out["n_accepted"] == 0
    assert out["best"] is None
    assert out["n_rejected"] == mat.shape[1]


# ---------------------------------------------------------------------------
# risk_overlay — gross leverage cap
# ---------------------------------------------------------------------------

_overlay_weights = st.integers(min_value=2, max_value=5).flatmap(
    lambda n_names: st.lists(
        st.lists(
            st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
            min_size=n_names,
            max_size=n_names,
        ),
        min_size=20,
        max_size=60,
    )
)


@given(_overlay_weights, st.floats(min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False))
def test_overlay_gross_leverage_cap(rows, cap):
    """The causal overlay must never leave gross leverage above its cap, no
    matter how the raw target weights are distributed across names/bars."""
    rng = np.random.default_rng(42)
    n_bars = len(rows)
    n_names = len(rows[0])
    index = pd.date_range("2025-01-01", periods=n_bars, freq="D")
    columns = [f"C{i}" for i in range(n_names)]
    positions = pd.DataFrame(rows, index=index, columns=columns)
    returns = pd.DataFrame(
        rng.normal(0.0, 0.02, size=(n_bars, n_names)),
        index=index,
        columns=columns,
    )
    cfg = load_risk_overlay({"risk_overlay": {"max_gross_leverage": cap}})
    assert cfg is not None and cfg.active()

    adjusted, diagnostics = apply_risk_overlay(positions, returns, config=cfg)
    assert diagnostics["applied"] is True

    gross = adjusted.abs().sum(axis=1)
    assert float(gross.max()) <= cap + 1e-6
