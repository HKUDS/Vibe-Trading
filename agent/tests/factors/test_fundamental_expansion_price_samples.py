"""Sample tests for the Tier-1 fundamental expansion factors.

Covers the four price-dependent / derived-field factors added per
``research/fundamental_factor_expansion_proposal.md`` §4 Tier 1 (#1, #5, #6, #8):

- ``fund_book_to_market`` (real FF HML characteristic)
- ``fund_fcf_yield`` (CFO - capex over market cap)
- ``fund_revenue_growth`` (schema derived field ``revenue_growth``)
- ``fund_earnings_growth`` (schema derived field ``earnings_growth``)

All compute-level tests pass hand-built panel dicts directly to ``compute()``
— never through the loader/schema — so they are independent of when the
concurrent schema change adding ``revenue_growth``/``earnings_growth`` lands.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.base import zscore
from src.factors.registry import AlphaMeta
from src.factors.registry import get_default_registry
from src.factors.zoo.fundamental import book_to_market
from src.factors.zoo.fundamental import earnings_growth
from src.factors.zoo.fundamental import fcf_yield
from src.factors.zoo.fundamental import revenue_growth

_DATES = pd.to_datetime(["2024-01-02", "2024-01-03"])
_CODES = ["A", "B", "C"]

_PRICE_FACTORS = [book_to_market, fcf_yield]
_GROWTH_FACTORS = [revenue_growth, earnings_growth]
_ALL_FACTORS = _PRICE_FACTORS + _GROWTH_FACTORS


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    """Build a 2-date x 3-symbol frame from per-date row values."""
    return pd.DataFrame(rows, index=_DATES, columns=_CODES, dtype=np.float64)


def _book_to_market_panel() -> dict[str, pd.DataFrame]:
    # market cap: A=1000, B=2000, C=5000; equity 500/250/100
    # -> b/m: A=0.50, B=0.125, C=0.02 (strictly decreasing)
    return {
        "close": _frame([[10.0, 20.0, 50.0], [10.0, 20.0, 50.0]]),
        "fund:total_equity": _frame([[500.0, 250.0, 100.0], [500.0, 250.0, 100.0]]),
        "fund:shares_diluted": _frame([[100.0, 100.0, 100.0], [100.0, 100.0, 100.0]]),
    }


def _fcf_yield_panel() -> dict[str, pd.DataFrame]:
    # A: cfo=100, capex=30 -> fcf=70, mcap=10*10=100 -> yield 0.70
    # B: cfo=50,  capex=15 -> fcf=35, mcap=20*10=200 -> yield 0.175
    # C: cfo=20,  capex=25 -> fcf=-5, mcap=50*10=500  -> yield -0.01
    return {
        "close": _frame([[10.0, 20.0, 50.0], [10.0, 20.0, 50.0]]),
        "fund:cfo": _frame([[100.0, 50.0, 20.0], [100.0, 50.0, 20.0]]),
        "fund:capex": _frame([[30.0, 15.0, 25.0], [30.0, 15.0, 25.0]]),
        "fund:shares_diluted": _frame([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]]),
    }


def _growth_panel(field: str) -> dict[str, pd.DataFrame]:
    return {field: _frame([[0.30, 0.10, -0.20], [0.30, 0.10, -0.20]])}


def _valid_panel(module) -> dict[str, pd.DataFrame]:
    if module is book_to_market:
        return _book_to_market_panel()
    if module is fcf_yield:
        return _fcf_yield_panel()
    if module is revenue_growth:
        return _growth_panel("fund:revenue_growth")
    return _growth_panel("fund:earnings_growth")


# ---------------------------------------------------------------------------
# (a) AlphaMeta gate accepts each factor's declared columns_required
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", _ALL_FACTORS, ids=lambda m: m.__alpha_meta__["id"])
def test_alpha_meta_gate_accepts_declared_columns(module) -> None:
    meta = AlphaMeta(**module.__alpha_meta__)

    assert meta.columns_required == module.__alpha_meta__["columns_required"]
    assert meta.decay_horizon == 252
    assert meta.min_warmup_bars == 1
    assert meta.universe == ["equity_us", "equity_cn", "equity_hk"]
    assert meta.frequency == ["1d"]


def test_alpha_meta_themes_match_proposal() -> None:
    assert book_to_market.__alpha_meta__["theme"] == ["value"]
    assert fcf_yield.__alpha_meta__["theme"] == ["value"]
    assert revenue_growth.__alpha_meta__["theme"] == ["growth"]
    assert earnings_growth.__alpha_meta__["theme"] == ["growth"]


# ---------------------------------------------------------------------------
# (b) compute() numeric correctness on hand-built panels
# ---------------------------------------------------------------------------


def test_book_to_market_matches_hand_computed_ratios() -> None:
    panel = _book_to_market_panel()
    expected_ratios = _frame([[0.50, 0.125, 0.02], [0.50, 0.125, 0.02]])

    result = book_to_market.compute(panel)

    pd.testing.assert_frame_equal(result, zscore(expected_ratios))


def test_book_to_market_direction_higher_equity_to_mcap_scores_higher() -> None:
    panel = _book_to_market_panel()

    result = book_to_market.compute(panel)

    row = result.iloc[0]
    assert row["A"] > row["B"] > row["C"]


def test_fcf_yield_subtracts_capex_from_cfo() -> None:
    # A: cfo 100, capex 30 -> fcf 70 over mcap 100 -> yield 0.70
    panel = _fcf_yield_panel()
    expected_ratios = _frame([[0.70, 0.175, -0.01], [0.70, 0.175, -0.01]])

    result = fcf_yield.compute(panel)

    pd.testing.assert_frame_equal(result, zscore(expected_ratios))


@pytest.mark.parametrize(
    ("module", "field"),
    [(revenue_growth, "fund:revenue_growth"), (earnings_growth, "fund:earnings_growth")],
    ids=["fund_revenue_growth", "fund_earnings_growth"],
)
def test_growth_factors_zscore_declared_field(module, field: str) -> None:
    panel = _growth_panel(field)

    result = module.compute(panel)

    pd.testing.assert_frame_equal(result, zscore(panel[field]))
    row = result.iloc[0]
    assert row["A"] > row["B"] > row["C"]


# ---------------------------------------------------------------------------
# (c) NaN contract: NaN in any declared dependency -> NaN output at that cell
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", _ALL_FACTORS, ids=lambda m: m.__alpha_meta__["id"])
def test_nan_in_any_declared_dependency_produces_nan_output(module) -> None:
    for column in module.__alpha_meta__["columns_required"]:
        panel = _valid_panel(module)
        panel[column] = panel[column].copy()
        panel[column].iloc[0, 1] = np.nan  # symbol B on date 0

        result = module.compute(panel)

        assert np.isnan(result.iloc[0, 1]), f"{module.__alpha_meta__['id']}: {column}"
        assert np.isfinite(result.iloc[0, 0]), f"{module.__alpha_meta__['id']}: {column}"
        assert np.isfinite(result.iloc[0, 2]), f"{module.__alpha_meta__['id']}: {column}"


# ---------------------------------------------------------------------------
# (d) Zero market cap / zero denominator -> NaN, never inf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", _PRICE_FACTORS, ids=lambda m: m.__alpha_meta__["id"])
def test_zero_close_produces_nan_not_inf(module) -> None:
    panel = _valid_panel(module)
    panel["close"] = panel["close"].copy()
    panel["close"].iloc[0, 1] = 0.0  # zero market cap for B on date 0

    result = module.compute(panel)

    assert np.isnan(result.iloc[0, 1])
    assert not np.isinf(result.to_numpy(dtype=np.float64)).any()


@pytest.mark.parametrize("module", _PRICE_FACTORS, ids=lambda m: m.__alpha_meta__["id"])
def test_zero_shares_produces_nan_not_inf(module) -> None:
    panel = _valid_panel(module)
    panel["fund:shares_diluted"] = panel["fund:shares_diluted"].copy()
    panel["fund:shares_diluted"].iloc[1, 2] = 0.0  # zero share count for C on date 1

    result = module.compute(panel)

    assert np.isnan(result.iloc[1, 2])
    assert not np.isinf(result.to_numpy(dtype=np.float64)).any()


# ---------------------------------------------------------------------------
# Registry load: the four ids are discoverable from the default registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alpha_id",
    ["fund_book_to_market", "fund_fcf_yield", "fund_revenue_growth", "fund_earnings_growth"],
)
def test_factor_is_loadable_from_default_registry(alpha_id: str) -> None:
    registry = get_default_registry()

    alpha = registry.get(alpha_id)

    assert alpha.id == alpha_id
