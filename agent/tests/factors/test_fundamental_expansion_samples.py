"""Registration + numeric regression for the six Tier-1 fundamental factors.

Covers ``fund_accruals``, ``fund_roa``, ``fund_leverage``, ``fund_cfo_yield``,
``fund_operating_margin`` and ``fund_cash_to_assets`` in ``zoo/fundamental/``
(research/fundamental_factor_expansion_proposal.md §4 Tier 1 #2/#3/#4/#7/#9/#10).

Assertions are membership-based, never an exact registry total: the zoo grows
concurrently. Expected values are recomputed here with an independent numpy
formula (mean / sample-std z-score, plain division) rather than reusing
``src.factors.base`` operators, so a regression in the shared operator does not
silently validate itself.
"""
from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import Registry

_DATES = pd.to_datetime(["2024-01-01", "2024-01-02"])
_CODES = ["AAA", "BBB", "CCC"]

# alpha_id -> (theme, columns_required, module stem under zoo/fundamental/)
_EXPECTED_META: dict[str, tuple[list[str], list[str], str]] = {
    "fund_accruals": (["quality"], ["fund:accruals"], "accruals"),
    "fund_roa": (["quality"], ["fund:roa"], "roa"),
    "fund_leverage": (["leverage"], ["fund:leverage"], "leverage"),
    "fund_cfo_yield": (["quality"], ["fund:cfo", "fund:total_assets"], "cfo_yield"),
    "fund_operating_margin": (
        ["quality"],
        ["fund:operating_income", "fund:revenue"],
        "operating_margin",
    ),
    "fund_cash_to_assets": (["quality"], ["fund:cash", "fund:total_assets"], "cash_to_assets"),
}

# One declared dependency per alpha, blanked wholesale in the NaN-contract test.
_BLANKED_DEPENDENCY: dict[str, str] = {
    "fund_accruals": "fund:accruals",
    "fund_roa": "fund:roa",
    "fund_leverage": "fund:leverage",
    "fund_cfo_yield": "fund:cfo",
    "fund_operating_margin": "fund:operating_income",
    "fund_cash_to_assets": "fund:cash",
}

# safe_div-based alphas and the denominator column driven to exactly zero.
_ZERO_DENOMINATOR: dict[str, str] = {
    "fund_cfo_yield": "fund:total_assets",
    "fund_operating_margin": "fund:revenue",
    "fund_cash_to_assets": "fund:total_assets",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry()


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_DATES, columns=_CODES, dtype="float64")


def _build_panel() -> dict[str, pd.DataFrame]:
    """Hand-built 2-date x 3-symbol panel; every row has distinct values."""
    return {
        "fund:accruals": _frame([[0.10, 0.02, -0.05], [0.08, 0.03, -0.01]]),
        "fund:roa": _frame([[0.15, 0.05, -0.10], [0.12, 0.06, 0.00]]),
        "fund:leverage": _frame([[2.0, 0.5, 0.1], [1.8, 0.6, 0.2]]),
        "fund:cfo": _frame([[300.0, 200.0, 100.0], [320.0, 210.0, 90.0]]),
        "fund:total_assets": _frame(
            [[1000.0, 1000.0, 1000.0], [1100.0, 1050.0, 900.0]]
        ),
        "fund:operating_income": _frame([[200.0, 100.0, 50.0], [220.0, 110.0, 40.0]]),
        "fund:revenue": _frame([[1000.0, 1000.0, 1000.0], [1000.0, 1100.0, 800.0]]),
        "fund:cash": _frame([[400.0, 100.0, 50.0], [420.0, 110.0, 60.0]]),
    }


def _numpy_zscore(values: np.ndarray) -> np.ndarray:
    """Independent per-row z-score: (x - mean) / sample-std, NaN-preserving."""
    mean = np.nanmean(values, axis=1, keepdims=True)
    std = np.nanstd(values, axis=1, ddof=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (values - mean) / std


def _z(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        _numpy_zscore(frame.to_numpy(dtype=np.float64)),
        index=frame.index,
        columns=frame.columns,
    )


def _expected_outputs(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Expected output frames per alpha, derived from the panel by numpy math."""
    total_assets = panel["fund:total_assets"]
    revenue = panel["fund:revenue"]
    return {
        "fund_accruals": -_z(panel["fund:accruals"]),
        "fund_roa": _z(panel["fund:roa"]),
        "fund_leverage": -_z(panel["fund:leverage"]),
        "fund_cfo_yield": _z(panel["fund:cfo"] / total_assets),
        "fund_operating_margin": _z(panel["fund:operating_income"] / revenue),
        "fund_cash_to_assets": _z(panel["fund:cash"] / total_assets),
    }


def _load_module(stem: str):
    return importlib.import_module(f"src.factors.zoo.fundamental.{stem}")


# --------------------------------------------------------------- (a) registry


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED_META))
def test_registry_loads_factor_with_expected_meta(
    registry: Registry, alpha_id: str
) -> None:
    theme, columns, stem = _EXPECTED_META[alpha_id]
    alpha = registry.get(alpha_id)
    assert alpha.zoo == "fundamental"
    assert alpha.module_path == f"src.factors.zoo.fundamental.{stem}"
    assert alpha.meta["theme"] == theme
    assert alpha.meta["columns_required"] == columns
    assert alpha.meta["universe"] == ["equity_us", "equity_cn", "equity_hk"]
    assert alpha.meta["frequency"] == ["1d"]
    assert alpha.meta["decay_horizon"] == 252
    assert alpha.meta["min_warmup_bars"] == 1
    assert alpha.meta["notes"].strip()


# ------------------------------------------------- (b) numeric correctness


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED_META))
def test_compute_matches_independent_numpy_math(
    registry: Registry, alpha_id: str
) -> None:
    panel = _build_panel()
    result = registry.compute(alpha_id, panel)
    expected = _expected_outputs(panel)[alpha_id]

    assert list(result.columns) == _CODES
    assert list(result.index) == list(_DATES)
    # atol covers values that are zero up to fp noise: when a cell equals the
    # row mean exactly (e.g. cfo/TA = [0.3, 0.2, 0.1]), its z-score is ~1e-16
    # with a sign that depends on summation order (pandas vs numpy).
    np.testing.assert_allclose(
        result.to_numpy(dtype=np.float64),
        expected.to_numpy(dtype=np.float64),
        rtol=1e-9,
        atol=1e-12,
        equal_nan=True,
        err_msg=f"{alpha_id} diverged from independent numpy expectation",
    )


def test_accruals_sign_direction(registry: Registry) -> None:
    """Sloan 1996: higher (NI-CFO)/TA must score LOWER on every date."""
    out = registry.compute("fund_accruals", _build_panel())
    accruals = _build_panel()["fund:accruals"]
    for date in _DATES:
        # CCC has the lowest accruals, AAA the highest, on both dates.
        assert accruals.loc[date, "AAA"] > accruals.loc[date, "BBB"]
        assert out.loc[date, "CCC"] > out.loc[date, "BBB"] > out.loc[date, "AAA"]


def test_leverage_sign_direction(registry: Registry) -> None:
    """Low leverage scores high: sign inverted versus the raw ratio."""
    out = registry.compute("fund_leverage", _build_panel())
    leverage = _build_panel()["fund:leverage"]
    for date in _DATES:
        assert leverage.loc[date, "AAA"] > leverage.loc[date, "BBB"]
        assert out.loc[date, "CCC"] > out.loc[date, "BBB"] > out.loc[date, "AAA"]


def test_roa_sign_direction(registry: Registry) -> None:
    """Positive factor: higher ROA scores higher (no inversion)."""
    out = registry.compute("fund_roa", _build_panel())
    for date in _DATES:
        assert out.loc[date, "AAA"] > out.loc[date, "BBB"] > out.loc[date, "CCC"]


# ------------------------------------------------------------ (c) NaN contract


@pytest.mark.parametrize("alpha_id", sorted(_BLANKED_DEPENDENCY))
def test_blank_dependency_bar_yields_all_nan(
    registry: Registry, alpha_id: str
) -> None:
    """Blanking a declared dependency on one bar must NaN that whole bar.

    The registry masks output wherever a declared dependency is missing
    (#1377), and zscore/safe_div propagate NaN — the second date must come
    back all-NaN while the first date is untouched.
    """
    panel = _build_panel()
    panel[_BLANKED_DEPENDENCY[alpha_id]].loc[_DATES[1]] = np.nan

    out = registry.compute(alpha_id, panel)

    assert out.loc[_DATES[1]].isna().all(), (
        f"{alpha_id}: emitted a value on a bar whose declared dependency was NaN"
    )
    assert out.loc[_DATES[0]].notna().all()


# --------------------------------------------------- (d) zero denominator


@pytest.mark.parametrize("alpha_id", sorted(_ZERO_DENOMINATOR))
def test_zero_denominator_is_nan_not_inf(alpha_id: str) -> None:
    """safe_div contract: exact-zero denominator -> NaN, never +/-inf."""
    stem = _EXPECTED_META[alpha_id][2]
    module = _load_module(stem)
    panel = _build_panel()
    panel[_ZERO_DENOMINATOR[alpha_id]].loc[_DATES[0], "BBB"] = 0.0

    out = module.compute(panel)
    arr = out.to_numpy(dtype=np.float64, na_value=np.nan)

    assert np.isnan(out.loc[_DATES[0], "BBB"])
    assert not np.isinf(arr).any()
    # The other two symbols on that date still score against each other.
    assert out.loc[_DATES[0], ["AAA", "CCC"]].notna().all()
    assert out.loc[_DATES[1]].notna().all()
