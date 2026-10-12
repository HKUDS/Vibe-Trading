"""Regression: after-close SEC filings must not leak into the IC one bar early.

SEC ``filed`` has no acceptance time. A filing on a trading date may be
published after its close. Same-day IC alignment can therefore include a
market reaction that preceded availability of the factor.

The known-answer check below plants a factor equal to the next day's return
(the strongest possible leak). Before the fix the bench reports a near-perfect
IC; with the filed-on-t value made first visible on bar t+1 the IC collapses
to ~0. These tests are offline: the loader is mocked, exactly like
``test_fundamental_factor_dependencies_are_loaded_at_filing_time``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd

from src.factors.factor_analysis_core import compute_ic_series
from src.tools.alpha_bench_tool import _compute_forward_returns, _prepare_bench_panel

_DATES = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"])


def _close_panel() -> pd.DataFrame:
    """Eight deterministic closes; cross-sectional IC needs >= 5 symbols.

    The series is the seed-73 draw from ``default_rng(73).normal(0, 0.02)``
    compounded from 100 — chosen so consecutive-day cross-sectional return
    ranks are uncorrelated (|lag-IC| <= 0.12 every day), keeping the
    known-answer test about the filing lag, not about the fixture.
    """
    return pd.DataFrame(
        {
            "AAPL.US": [100.00, 97.81, 95.38, 98.83, 99.43, 96.99],
            "MSFT.US": [100.00, 101.56, 103.82, 102.25, 99.69, 98.64],
            "NVDA.US": [100.00, 99.24, 96.04, 92.59, 93.58, 91.74],
            "AMZN.US": [100.00, 100.59, 97.40, 98.70, 99.25, 98.15],
            "GOOG.US": [100.00, 100.67, 98.98, 99.41, 102.24, 104.99],
            "META.US": [100.00, 96.11, 98.81, 99.49, 98.70, 100.09],
            "TSLA.US": [100.00, 101.00, 102.87, 100.62, 101.13, 101.96],
            "AMD.US": [100.00, 98.07, 97.74, 98.84, 100.68, 101.34],
        },
        index=_DATES,
    )


def _leak_frame(close: pd.DataFrame) -> pd.DataFrame:
    """A fundamental whose value on bar t is exactly the t->t+1 return.

    This is what a same-day ``filed`` value looks like when the filing is
    accepted after the close: the value encodes information the market has
    not priced in yet at close(t).
    """
    return close.pct_change(fill_method=None).shift(-1)


def _registry(columns: list[str]) -> SimpleNamespace:
    return SimpleNamespace(get=lambda _aid: SimpleNamespace(meta={"columns_required": columns}))


def _ic(factor: pd.DataFrame, close: pd.DataFrame) -> float:
    """Mean cross-sectional Spearman IC between the factor and forward returns."""
    returns = _compute_forward_returns({"close": close})
    ic_series = compute_ic_series(factor, returns)
    assert not ic_series.empty
    return float(ic_series.mean())


def test_unshifted_pit_panel_would_report_a_perfect_ic() -> None:
    """The known-answer sanity check: without the lag the leak is real.

    Guards against someone removing the shift in ``_prepare_bench_panel``
    without noticing it re-opens issue #1790.
    """
    close = _close_panel()

    ic = _ic(_leak_frame(close), close)

    assert abs(ic) > 0.9


def test_pit_panel_shifts_filing_one_bar_later(monkeypatch) -> None:
    """A filed-on-t value must first appear on bar t+1 in the bench panel."""
    close = _close_panel()
    # What the loader hands back for a filing anchored on bar 2: NaN before
    # the filing, forward-filled after it (fundamentals_loader L194 ffills).
    frame = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    frame.iloc[2] = 5.0
    frame = frame.ffill()
    loader = Mock(return_value={"net_income": frame})
    monkeypatch.setattr("backtest.loaders.fundamentals_loader.load_fundamental_panel", loader)

    result = _prepare_bench_panel(_registry(["close", "fund:net_income"]), ["aid"], {"close": close}, "sp500", "2026-2026")

    column = result["fund:net_income"]
    # Before the filing bar and on it: NaN. From t+1 on: the filed value.
    assert column.iloc[2].isna().all()
    assert (column.iloc[3:] == 5.0).all().all()
    # The lag is recorded so downstream consumers can see the semantics.
    assert result["_meta"]["fundamental_pit_lag_bars"] == 1


def test_after_close_filing_does_not_leak_into_the_ic(monkeypatch) -> None:
    """Known-answer: a factor equal to next-day returns must not produce IC.

    This is the reproduce step from the issue, planted offline: the loader
    returns a value anchored on the filed date (as for an after-close
    filing); after the fix the bench must not report a signal.
    """
    close = _close_panel()
    loader = Mock(return_value={"net_income": _leak_frame(close)})
    monkeypatch.setattr("backtest.loaders.fundamentals_loader.load_fundamental_panel", loader)

    result = _prepare_bench_panel(_registry(["close", "fund:net_income"]), ["aid"], {"close": close}, "sp500", "2026-2026")

    assert abs(_ic(result["fund:net_income"], close)) < 0.1
