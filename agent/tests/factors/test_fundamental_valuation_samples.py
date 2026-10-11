"""Registration + numeric regression for the three Tier-2 CN valuation factors.

Covers ``fund_pb``, ``fund_ps_ttm`` and ``fund_dividend_yield`` in
``zoo/fundamental/`` (research/fundamental_factor_expansion_proposal.md §4
Tier 2 #11/#12/#13), plus the ``val:`` namespace plumbing: the AlphaMeta
gate, the runner injection through a mocked tushare ``daily_basic`` API, the
whitelist rejection and the NaN-on-missing-data contract.

Assertions are membership-based, never an exact registry total: the zoo grows
concurrently. Expected values are recomputed here with an independent numpy
formula (mean / sample-std z-score) rather than reusing ``src.factors.base``
operators, so a regression in the shared operator does not silently validate
itself.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backtest import runner
from backtest.loaders import valuation_loader
from src.factors.registry import AlphaMeta, Registry

_DATES = pd.to_datetime(["2024-01-01", "2024-01-02"])
_CODES = ["AAA", "BBB", "CCC"]

# alpha_id -> (theme, columns_required, module stem under zoo/fundamental/)
_EXPECTED_META: dict[str, tuple[list[str], list[str], str]] = {
    "fund_pb": (["value"], ["val:pb"], "pb"),
    "fund_ps_ttm": (["value"], ["val:ps_ttm"], "ps_ttm"),
    "fund_dividend_yield": (["value"], ["val:dv_ttm"], "dividend_yield"),
}

# One declared dependency per alpha, blanked wholesale in the NaN-contract test.
_BLANKED_DEPENDENCY: dict[str, str] = {
    "fund_pb": "val:pb",
    "fund_ps_ttm": "val:ps_ttm",
    "fund_dividend_yield": "val:dv_ttm",
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry()


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_DATES, columns=_CODES, dtype="float64")


def _build_panel() -> dict[str, pd.DataFrame]:
    """Hand-built 2-date x 3-symbol panel; every row has distinct values."""
    return {
        # PB: CCC cheapest, AAA most expensive on both dates.
        "val:pb": _frame([[3.0, 1.5, 0.5], [2.8, 1.6, 0.6]]),
        "val:ps_ttm": _frame([[4.0, 2.0, 1.0], [3.6, 2.2, 0.8]]),
        # dv_ttm in percent units, as tushare daily_basic reports it.
        "val:dv_ttm": _frame([[0.5, 2.0, 4.5], [0.6, 2.1, 4.4]]),
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
    return {
        "fund_pb": -_z(panel["val:pb"]),
        "fund_ps_ttm": -_z(panel["val:ps_ttm"]),
        "fund_dividend_yield": _z(panel["val:dv_ttm"]),
    }


def _load_module(stem: str):
    return importlib.import_module(f"src.factors.zoo.fundamental.{stem}")


# ------------------------------------------------------- (a) gate + registry


def test_alpha_meta_gate_accepts_val_columns() -> None:
    meta = AlphaMeta(
        id="test_val_alpha",
        theme=["value"],
        formula_latex="x",
        columns_required=["val:pb"],
        universe=["equity_cn"],
        frequency=["1d"],
        decay_horizon=252,
        min_warmup_bars=1,
    )

    assert meta.columns_required == ["val:pb"]


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
    assert alpha.meta["universe"] == ["equity_cn"]
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
    np.testing.assert_allclose(
        result.to_numpy(dtype=np.float64),
        expected.to_numpy(dtype=np.float64),
        rtol=1e-9,
        atol=1e-12,
        equal_nan=True,
        err_msg=f"{alpha_id} diverged from independent numpy expectation",
    )


def test_pb_sign_direction(registry: Registry) -> None:
    """Low PB scores high: cheaper-on-book names rank above expensive ones."""
    out = registry.compute("fund_pb", _build_panel())
    pb = _build_panel()["val:pb"]
    for date in _DATES:
        assert pb.loc[date, "AAA"] > pb.loc[date, "BBB"] > pb.loc[date, "CCC"]
        assert out.loc[date, "CCC"] > out.loc[date, "BBB"] > out.loc[date, "AAA"]


def test_dividend_yield_sign_direction(registry: Registry) -> None:
    """High dv_ttm scores high (no inversion)."""
    out = registry.compute("fund_dividend_yield", _build_panel())
    for date in _DATES:
        assert out.loc[date, "CCC"] > out.loc[date, "BBB"] > out.loc[date, "AAA"]


# ------------------------------------------------------------ (c) NaN contract


@pytest.mark.parametrize("alpha_id", sorted(_BLANKED_DEPENDENCY))
def test_blank_dependency_bar_yields_all_nan(
    registry: Registry, alpha_id: str
) -> None:
    """Blanking a declared val: dependency on one bar must NaN that whole bar.

    The registry masks output wherever a declared dependency is missing
    (#1377), and zscore propagates NaN — the second date must come back
    all-NaN while the first date is untouched.
    """
    panel = _build_panel()
    panel[_BLANKED_DEPENDENCY[alpha_id]].loc[_DATES[1]] = np.nan

    out = registry.compute(alpha_id, panel)

    assert out.loc[_DATES[1]].isna().all(), (
        f"{alpha_id}: emitted a value on a bar whose declared dependency was NaN"
    )
    assert out.loc[_DATES[0]].notna().all()


# ------------------------------------------- (d) no inf on degenerate inputs


@pytest.mark.parametrize("alpha_id", sorted(_EXPECTED_META))
def test_extreme_and_zero_values_never_produce_inf(
    registry: Registry, alpha_id: str
) -> None:
    """Invalid multiples stay NaN; zero dividends remain valid observations."""
    panel = _build_panel()
    dep = _BLANKED_DEPENDENCY[alpha_id]
    panel[dep].loc[_DATES[0]] = [0.0, 0.0, 0.0]
    panel[dep].loc[_DATES[1]] = [0.0, -1.5, 1e12]

    if alpha_id in {"fund_pb", "fund_ps_ttm"}:
        from src.factors.registry import RegistryError
        with pytest.raises(RegistryError, match=">95% NaN"):
            registry.compute(alpha_id, panel)
        out = _load_module(_EXPECTED_META[alpha_id][2]).compute(panel)
        assert out.isna().all().all()  # one valid multiple cannot form a cross-section
    else:
        out = registry.compute(alpha_id, panel)
        assert out.loc[_DATES[1]].notna().all()
    assert not np.isinf(out.to_numpy(dtype=np.float64)).any()
    assert out.loc[_DATES[0]].isna().all(), "constant row must z-score to NaN"


# ------------------------------------------------- runner injection (mocked)


class _FakeDailyBasicApi:
    """Mimics ``pro.daily_basic``: serves only 000001.SZ, one date short."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def daily_basic(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        if kwargs["ts_code"] != "000001.SZ":
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20240102", "20240103"],
                "pb": [1.1, 1.2],
                "ps_ttm": [2.1, 2.2],
                "dv_ttm": [3.1, 3.2],
            }
        )


@pytest.fixture
def fake_tushare(monkeypatch: pytest.MonkeyPatch) -> _FakeDailyBasicApi:
    api = _FakeDailyBasicApi()
    monkeypatch.setenv("TUSHARE_TOKEN", "ts-test-token")
    monkeypatch.setitem(
        sys.modules, "tushare", SimpleNamespace(pro_api=lambda token="": api)
    )
    return api


def _cn_data_map() -> dict[str, pd.DataFrame]:
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    frame = lambda: pd.DataFrame(  # noqa: E731
        {
            "open": [10.0, 10.5, 10.2],
            "high": [10.6, 10.7, 10.8],
            "low": [9.9, 10.1, 10.0],
            "close": [10.1, 10.3, 10.4],
            "volume": [1000, 1100, 1200],
        },
        index=index,
    )
    return {"000001.SZ": frame(), "600000.SH": frame()}


def test_runner_injects_declared_val_columns_for_cn_symbols(
    fake_tushare: _FakeDailyBasicApi,
) -> None:
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    result = runner._maybe_inject_fundamentals_for_factor_panel(
        _cn_data_map(),
        {
            "start_date": "2024-01-02",
            "end_date": "2024-01-04",
            "selected_factors": [{"columns_required": ["close", "val:pb"]}],
        },
    )

    injected = result["000001.SZ"]["val:pb"]
    assert injected.loc[index[0]] == pytest.approx(1.1)
    assert injected.loc[index[1]] == pytest.approx(1.2)
    # 2024-01-04 was not served by daily_basic: stays NaN, never fabricated.
    assert pd.isna(injected.loc[index[2]])
    # 600000.SH was not served either: whole column NaN, still injected.
    assert result["600000.SH"]["val:pb"].isna().all()
    assert [call["ts_code"] for call in fake_tushare.calls] == [
        "000001.SZ",
        "600000.SH",
    ]
    assert fake_tushare.calls[0]["fields"] == "ts_code,trade_date,pb"


def test_runner_val_injection_skips_non_cn_symbols(
    fake_tushare: _FakeDailyBasicApi,
) -> None:
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    data_map = {
        "AAPL.US": _cn_data_map()["000001.SZ"],
        "00700.HK": _cn_data_map()["000001.SZ"],
    }

    result = runner._maybe_inject_fundamentals_for_factor_panel(
        data_map,
        {
            "start_date": "2024-01-02",
            "end_date": "2024-01-04",
            "selected_factors": [{"columns_required": ["val:dv_ttm"]}],
        },
    )

    assert fake_tushare.calls == []
    assert result["AAPL.US"]["val:dv_ttm"].reindex(index).isna().all()
    assert result["00700.HK"]["val:dv_ttm"].reindex(index).isna().all()


def test_runner_rejects_val_field_outside_whitelist() -> None:
    with pytest.raises(ValueError, match="unsupported val: field"):
        runner._maybe_inject_fundamentals_for_factor_panel(
            _cn_data_map(),
            {
                "start_date": "2024-01-02",
                "end_date": "2024-01-04",
                "selected_factors": [{"columns_required": ["val:total_mv"]}],
            },
        )


def test_val_whitelist_covers_exactly_the_daily_basic_fields() -> None:
    from backtest.loaders.valuation_loader import VALUATION_FIELDS

    assert VALUATION_FIELDS == ("pe", "pe_ttm", "pb", "ps_ttm", "dv_ttm")


def test_missing_token_degrades_to_nan_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No TUSHARE_TOKEN: the run survives on NaN frames instead of crashing."""
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    monkeypatch.setattr(valuation_loader, "_baostock_available", lambda: False)
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = {"close": pd.DataFrame({"000001.SZ": [10.1, 10.3, 10.4]}, index=index)}

    runner._inject_valuation_panel(
        panel,
        symbols=["000001.SZ"],
        val_columns=["val:pb"],
        start="2024-01-02",
        end="2024-01-04",
    )

    assert panel["val:pb"].isna().all().all()
    assert list(panel["val:pb"].index) == list(index)

@pytest.mark.parametrize('stem,column', [('pb', 'pb'), ('ps_ttm', 'ps_ttm')])
def test_nonpositive_multiples_are_not_ranked_as_cheap(stem, column):
    frame = pd.DataFrame([[-1., 0., 1., 2., 3.]], columns=list('ABCDE'))
    actual = _load_module(stem).compute({f'val:{column}': frame})
    assert actual[['A', 'B']].isna().all().all()
    np.testing.assert_allclose(actual[['C', 'D', 'E']].to_numpy(), [[1., 0., -1.]])
