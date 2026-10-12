"""Registration + numeric regression for the three industry-neutral CN value factors.

Covers ``fund_pb_ind_neutral``, ``fund_ps_ttm_ind_neutral`` and
``fund_dividend_yield_ind_neutral`` in ``zoo/fundamental/`` (issue #1789
follow-up #2): the ``requires_sector`` gate, within-industry z-score values
recomputed here with independent numpy math, the sign convention (PB/PS
negated, dividend yield positive), and the NaN contract — no label, a
singleton industry group or a blanked dependency all stay NaN, never a
global-fallback number.

Assertions are membership-based, never an exact registry total: the zoo grows
concurrently.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import Registry, SkipAlpha

_DATES = pd.to_datetime(["2024-01-01", "2024-01-02"])
_CODES = ["BANK1", "BANK2", "TECH1", "TECH2"]
_SECTORS = ["银行", "银行", "科技", "科技"]

# alpha_id -> (columns_required, module stem, sign multiplier on the z-score)
_EXPECTED: dict[str, tuple[list[str], str, float]] = {
    "fund_pb_ind_neutral": (["val:pb"], "pb_ind_neutral", -1.0),
    "fund_ps_ttm_ind_neutral": (["val:ps_ttm"], "ps_ttm_ind_neutral", -1.0),
    "fund_dividend_yield_ind_neutral": (["val:dv_ttm"], "dividend_yield_ind_neutral", 1.0),
}

_DEPENDENCY: dict[str, str] = {
    "fund_pb_ind_neutral": "val:pb",
    "fund_ps_ttm_ind_neutral": "val:ps_ttm",
    "fund_dividend_yield_ind_neutral": "val:dv_ttm",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry()


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_DATES, columns=_CODES, dtype="float64")


def _sector_frame(labels: list[list] | None = None) -> pd.DataFrame:
    rows = [list(row) for row in (labels or [_SECTORS, _SECTORS])]
    return pd.DataFrame(rows, index=_DATES, columns=_CODES, dtype=object)


def _build_panel() -> dict[str, pd.DataFrame]:
    """Hand-built 2-date x 4-symbol panel, two industries of two names each."""
    return {
        # Within 银行: BANK2 cheaper; within 科技: TECH2 cheaper.
        "val:pb": _frame([[0.5, 1.5, 8.0, 12.0], [0.6, 1.4, 9.0, 11.0]]),
        "val:ps_ttm": _frame([[1.0, 3.0, 10.0, 30.0], [1.2, 2.8, 12.0, 28.0]]),
        "val:dv_ttm": _frame([[4.0, 2.0, 0.5, 1.5], [3.8, 2.2, 0.6, 1.4]]),
        "sector": _sector_frame(),
    }


def _numpy_group_zscore(values: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Independent per-row within-group z-score: (x - mean) / sample-std."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    for i in range(values.shape[0]):
        for tag in {label for label in labels[i] if label is not None}:
            mask = labels[i] == tag
            finite = values[i][mask & ~np.isnan(values[i])]
            if finite.size < 2:
                continue
            std = finite.std(ddof=1)
            if std <= 0:
                continue
            out[i, mask] = (values[i, mask] - finite.mean()) / std
    return out


def _expected_output(panel: dict[str, pd.DataFrame], alpha_id: str) -> pd.DataFrame:
    columns, _, sign = _EXPECTED[alpha_id]
    values = panel[columns[0]].to_numpy(dtype=np.float64)
    labels = panel["sector"].to_numpy()
    return pd.DataFrame(
        sign * _numpy_group_zscore(values, labels), index=_DATES, columns=_CODES
    )


# ------------------------------------------------------- (a) gate + registry


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED))
def test_registry_loads_factor_with_expected_meta(
    registry: Registry, alpha_id: str
) -> None:
    columns, stem, _ = _EXPECTED[alpha_id]
    alpha = registry.get(alpha_id)
    assert alpha.zoo == "fundamental"
    assert alpha.module_path == f"src.factors.zoo.fundamental.{stem}"
    assert alpha.meta["theme"] == ["value"]
    assert alpha.meta["columns_required"] == columns
    assert alpha.meta["requires_sector"] is True
    assert alpha.meta["universe"] == ["equity_cn"]
    assert alpha.meta["frequency"] == ["1d"]
    assert alpha.meta["decay_horizon"] == 252
    assert alpha.meta["min_warmup_bars"] == 1
    assert alpha.meta["notes"].strip()
    assert alpha.meta["formula_latex"].strip()


def test_the_three_raw_siblings_stay_unsectorized(registry: Registry) -> None:
    """The neutral variants are additions; the raw factors keep their contract."""
    for alpha_id in ("fund_pb", "fund_ps_ttm", "fund_dividend_yield"):
        assert not registry.get(alpha_id).meta.get("requires_sector")


# ------------------------------------------------- (b) numeric correctness


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED))
def test_compute_matches_independent_numpy_math(
    registry: Registry, alpha_id: str
) -> None:
    panel = _build_panel()
    result = registry.compute(alpha_id, panel)
    expected = _expected_output(panel, alpha_id)

    assert list(result.columns) == _CODES
    assert list(result.index) == list(_DATES)
    np.testing.assert_allclose(
        result.to_numpy(dtype=np.float64),
        expected.to_numpy(dtype=np.float64),
        rtol=1e-9,
        atol=1e-12,
        equal_nan=True,
        err_msg=f"{alpha_id} diverged from independent numpy expectation",
    )


def test_pb_ranks_within_industry_not_across_the_row(registry: Registry) -> None:
    """Industry level no longer dominates the score, only relative cheapness.

    A raw -zscore(PB) puts every bank above every tech purely because banks
    carry structurally lower PB. The neutral variant scores each name against
    its own group: the cheap name of each industry gets the same top score
    (+1/sqrt(2) in a two-member group), so TECH1 — expensive in absolute
    terms yet cheap among techs — is no longer ranked below both banks.
    """
    out = registry.compute("fund_pb_ind_neutral", _build_panel())
    date = _DATES[0]
    # Within 银行: cheaper BANK1 scores high. Within 科技: cheaper TECH1 scores high.
    assert out.loc[date, "BANK1"] > out.loc[date, "BANK2"]
    assert out.loc[date, "TECH1"] > out.loc[date, "TECH2"]
    # Two-member groups z-score to exactly ±1/sqrt(2) regardless of level.
    s = 1.0 / np.sqrt(2.0)
    np.testing.assert_allclose(
        out.loc[date].to_numpy(dtype=np.float64), [s, -s, s, -s], rtol=1e-12
    )


def test_dividend_yield_sign_direction(registry: Registry) -> None:
    """High dv_ttm scores high within the industry group (no inversion)."""
    out = registry.compute("fund_dividend_yield_ind_neutral", _build_panel())
    for date in _DATES:
        assert out.loc[date, "BANK1"] > out.loc[date, "BANK2"]
        assert out.loc[date, "TECH2"] > out.loc[date, "TECH1"]


# ------------------------------------------------------------ (c) NaN contract


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED))
def test_missing_sector_tag_skips_cleanly(registry: Registry, alpha_id: str) -> None:
    panel = _build_panel()
    del panel["sector"]

    with pytest.raises(SkipAlpha, match="missing sector tag"):
        registry.compute(alpha_id, panel)


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED))
def test_blank_dependency_bar_yields_all_nan(registry: Registry, alpha_id: str) -> None:
    panel = _build_panel()
    panel[_DEPENDENCY[alpha_id]].loc[_DATES[1]] = np.nan

    out = registry.compute(alpha_id, panel)

    assert out.loc[_DATES[1]].isna().all(), (
        f"{alpha_id}: emitted a value on a bar whose declared dependency was NaN"
    )
    assert out.loc[_DATES[0]].notna().all()


def test_unlabelled_name_is_nan_not_globally_zscored(registry: Registry) -> None:
    """A name with no industry label stays NaN — no global fallback."""
    panel = _build_panel()
    labels = [list(_SECTORS), list(_SECTORS)]
    labels[1][2] = None  # TECH1 unlabelled on date 2
    panel["sector"] = _sector_frame(labels)

    out = registry.compute("fund_pb_ind_neutral", panel)

    assert pd.isna(out.loc[_DATES[1], "TECH1"])
    # Its former group peer loses the second observation → singleton → NaN too.
    assert pd.isna(out.loc[_DATES[1], "TECH2"])
    # The 银行 group is untouched by the tech-side unlabelling: a two-member
    # group z-scores to ±1/sqrt(2) on both dates.
    assert out.loc[_DATES[1], "BANK1"] == pytest.approx(out.loc[_DATES[0], "BANK1"])
    assert out.loc[_DATES[0]].notna().all()


def test_singleton_industry_group_is_nan(registry: Registry) -> None:
    panel = _build_panel()
    panel["sector"] = _sector_frame([["银行", "银行", "科技", "医药"]] * 2)

    out = registry.compute("fund_pb_ind_neutral", panel)

    # TECH1 (科技) and TECH2 (医药) are each a one-name industry → NaN.
    assert out.loc[:, "TECH1"].isna().all()
    assert out.loc[:, "TECH2"].isna().all()
    assert out.loc[:, ["BANK1", "BANK2"]].notna().all().all()


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED))
def test_no_inf_on_degenerate_group_values(
    registry: Registry, alpha_id: str
) -> None:
    """A constant industry group degrades to NaN, never to inf or silent zero."""
    panel = _build_panel()
    panel[_DEPENDENCY[alpha_id]].loc[_DATES[0]] = [7.0, 7.0, 0.0, -3.0]

    out = registry.compute(alpha_id, panel)
    arr = out.to_numpy(dtype=np.float64, na_value=np.nan)

    assert not np.isinf(arr).any()
    assert out.loc[_DATES[0], ["BANK1", "BANK2"]].isna().all()


@pytest.mark.parametrize(
    "stem,column",
    [("pb_ind_neutral", "pb"), ("ps_ttm_ind_neutral", "ps_ttm")],
)
def test_nonpositive_multiples_are_not_ranked_as_cheap(stem: str, column: str) -> None:
    """Mirrors the raw siblings' upstream guard: PB/PS <= 0 is excluded, never 'cheapest'."""
    import importlib

    mod = importlib.import_module(f"src.factors.zoo.fundamental.{stem}")
    frame = pd.DataFrame([[-1.0, 0.0, 1.0, 2.0, 3.0]], columns=list("ABCDE"))
    sector = pd.DataFrame([["G1"] * 5], columns=list("ABCDE"))

    actual = mod.compute({f"val:{column}": frame, "sector": sector})

    assert actual[["A", "B"]].isna().all().all()
    np.testing.assert_allclose(actual[["C", "D", "E"]].to_numpy(), [[1.0, 0.0, -1.0]])
