"""Tests for the fundamental data tool facade and first fundamental factors."""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from src.tools.get_fundamentals_tool import GetFundamentalsTool


def _install_loader(monkeypatch: pytest.MonkeyPatch, func) -> None:
    module = types.ModuleType("backtest.loaders.fundamentals_loader")
    module.load_fundamental_panel = func
    monkeypatch.setitem(sys.modules, "backtest.loaders.fundamentals_loader", module)


def test_get_fundamentals_tool_success_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    def load_fundamental_panel(**kwargs):
        assert kwargs["symbols"] == ["AAPL.US", "MSFT.US"]
        assert kwargs["fields"] == ["roe"]
        assert kwargs["freq"] == "ttm"
        assert kwargs["pit"] is True
        assert kwargs["source"] == "auto"
        assert kwargs["index"] is None
        idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
        return {
            "roe": pd.DataFrame(
                {
                    "AAPL.US": [0.21, np.nan],
                    "MSFT.US": [np.inf, 0.18],
                },
                index=idx,
            )
        }

    _install_loader(monkeypatch, load_fundamental_panel)

    payload = GetFundamentalsTool().execute(
        symbols=["AAPL.US", "MSFT.US"],
        fields=["roe"],
        start="2026-01-01",
        end="2026-01-31",
    )
    parsed = json.loads(payload)

    assert parsed["ok"] is True
    assert parsed["source"] == "auto"
    assert parsed["freq"] == "ttm"
    assert parsed["pit"] is True
    assert parsed["symbols"] == ["AAPL.US", "MSFT.US"]
    assert parsed["fields"] == ["roe"]
    assert parsed["data"]["roe"] == [
        {"date": "2026-01-02T00:00:00", "AAPL.US": 0.21, "MSFT.US": None},
        {"date": "2026-01-03T00:00:00", "AAPL.US": None, "MSFT.US": 0.18},
    ]


def test_get_fundamentals_tool_loader_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load_fundamental_panel(**kwargs):
        raise RuntimeError("fixture loader exploded")

    _install_loader(monkeypatch, load_fundamental_panel)

    payload = GetFundamentalsTool().execute(
        symbols=["AAPL.US"],
        fields=["roe"],
        start="2026-01-01",
        end="2026-01-31",
    )
    parsed = json.loads(payload)

    assert parsed["ok"] is False
    assert "fixture loader exploded" in parsed["error"]


def _panel(values: list[list[float]], columns: list[str] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        values,
        index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
        columns=columns or ["A", "B", "C"],
        dtype=float,
    )


def _assert_row_zscore_properties(result: pd.DataFrame) -> None:
    assert np.allclose(result.mean(axis=1), 0.0, atol=1e-12)
    assert np.allclose(result.std(axis=1, ddof=1), 1.0, atol=1e-12)


def test_fund_roe_compute_cross_sectional_zscore() -> None:
    from src.factors.zoo.fundamental.roe import compute

    result = compute({"fund:roe": _panel([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0]])})

    _assert_row_zscore_properties(result)
    assert result.iloc[0].tolist() == [-1.0, 0.0, 1.0]


def test_fund_gross_profitability_compute_cross_sectional_zscore() -> None:
    from src.factors.zoo.fundamental.gross_profitability import compute

    result = compute({"fund:gross_profitability": _panel([[3.0, 6.0, 9.0], [4.0, 8.0, 12.0]])})

    _assert_row_zscore_properties(result)
    assert result.iloc[1].tolist() == [-1.0, 0.0, 1.0]


def test_fund_asset_growth_compute_is_inverted_zscore() -> None:
    from src.factors.zoo.fundamental.asset_growth import compute

    result = compute({"fund:asset_growth": _panel([[0.01, 0.02, 0.03], [0.10, 0.20, 0.30]])})

    _assert_row_zscore_properties(result)
    assert np.allclose(result.iloc[0], [1.0, 0.0, -1.0], atol=1e-12)


def test_fund_earnings_yield_compute_hybrid_zscore_and_safe_division() -> None:
    from src.factors.zoo.fundamental.earnings_yield import compute

    result = compute(
        {
            "close": _panel([[10.0, 10.0, 10.0], [0.0, 10.0, 10.0]]),
            "fund:net_income": _panel([[10.0, 20.0, 30.0], [5.0, 20.0, 30.0]]),
            "fund:shares_diluted": _panel([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]]),
        }
    )

    _assert_row_zscore_properties(result)
    assert np.allclose(result.iloc[0], [-1.0, 0.0, 1.0], atol=1e-12)
    assert np.isnan(result.loc[pd.Timestamp("2026-01-03"), "A"])
