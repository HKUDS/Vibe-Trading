"""Fundamental factor panel gate and runner injection tests."""

from __future__ import annotations

import sys
import types
from typing import Any

import pandas as pd
import pytest

from backtest import runner
from src.factors.registry import AlphaMeta


def _meta(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "test_alpha",
        "theme": ["quality"],
        "formula_latex": "x",
        "columns_required": ["close"],
        "universe": ["equity_us"],
        "frequency": ["1d"],
        "decay_horizon": 1,
        "min_warmup_bars": 1,
    }
    base.update(overrides)
    return base


def test_panel_column_gate_accepts_price_and_fund_prefix() -> None:
    meta = AlphaMeta(**_meta(columns_required=["close", "fund:roe"]))

    assert meta.columns_required == ["close", "fund:roe"]


def test_panel_column_gate_accepts_unknown_fund_field() -> None:
    meta = AlphaMeta(**_meta(columns_required=["fund:whatever"]))

    assert meta.columns_required == ["fund:whatever"]


def test_panel_column_gate_accepts_val_prefix() -> None:
    meta = AlphaMeta(**_meta(columns_required=["close", "val:pb"]))

    assert meta.columns_required == ["close", "val:pb"]


def test_panel_column_gate_accepts_unknown_val_field() -> None:
    # The gate is prefix-based like fund:; the daily_basic whitelist is
    # enforced at injection time, not at metadata validation.
    meta = AlphaMeta(**_meta(columns_required=["val:whatever"]))

    assert meta.columns_required == ["val:whatever"]


def test_panel_column_gate_rejects_unknown_non_prefixed_column() -> None:
    with pytest.raises(ValueError, match="unknown panel column: garbage"):
        AlphaMeta(**_meta(columns_required=["garbage"]))


def test_panel_column_gate_rejects_unknown_prefix() -> None:
    with pytest.raises(ValueError, match="unknown panel column: est:eps"):
        AlphaMeta(**_meta(columns_required=["est:eps"]))


def test_decay_horizon_accepts_annual_report_scale_window() -> None:
    meta = AlphaMeta(**_meta(decay_horizon=400))

    assert meta.decay_horizon == 400


def test_runner_injects_requested_fundamental_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.bdate_range("2024-01-02", periods=3)
    panel = {
        "close": pd.DataFrame(
            {"AAPL.US": [100.0, 101.0, 102.0]},
            index=index,
        )
    }
    captured: dict[str, Any] = {}

    def fake_load_fundamental_panel(**kwargs: Any) -> dict[str, pd.DataFrame]:
        captured.update(kwargs)
        return {
            "roe": pd.DataFrame(
                {"AAPL.US": [0.1, 0.2, 0.3]},
                index=index,
            )
        }

    module = types.ModuleType("backtest.loaders.fundamentals_loader")
    module.load_fundamental_panel = fake_load_fundamental_panel
    monkeypatch.setitem(sys.modules, "backtest.loaders.fundamentals_loader", module)

    runner._inject_fundamental_panel(
        panel,
        symbols=["AAPL.US"],
        fund_columns=["fund:roe"],
        start="2024-01-01",
        end="2024-01-31",
    )

    assert captured["symbols"] == ["AAPL.US"]
    assert captured["fields"] == ["roe"]
    assert captured["start"] == "2024-01-01"
    assert captured["end"] == "2024-01-31"
    assert captured["freq"] == "ttm"
    assert captured["pit"] is True
    assert captured["source"] == "auto"
    assert captured["index"] is index
    pd.testing.assert_frame_equal(
        panel["fund:roe"],
        pd.DataFrame({"AAPL.US": [0.1, 0.2, 0.3]}, index=index),
    )


def test_runner_does_not_import_loader_without_fund_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.bdate_range("2024-01-02", periods=2)
    data_map = {
        "AAPL.US": pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
            },
            index=index,
        )
    }
    calls: list[dict[str, Any]] = []

    def fake_load_fundamental_panel(**kwargs: Any) -> dict[str, pd.DataFrame]:
        calls.append(kwargs)
        return {}

    module = types.ModuleType("backtest.loaders.fundamentals_loader")
    module.load_fundamental_panel = fake_load_fundamental_panel
    monkeypatch.setitem(sys.modules, "backtest.loaders.fundamentals_loader", module)

    result = runner._maybe_inject_fundamentals_for_factor_panel(
        data_map,
        {"selected_factors": [{"columns_required": ["close"]}]},
    )

    assert result is data_map
    assert calls == []


def test_runner_selected_fund_factor_projects_panel_back_to_data_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.bdate_range("2024-01-02", periods=2)
    data_map = {
        "AAPL.US": pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
            },
            index=index,
        )
    }
    captured: dict[str, Any] = {}

    def fake_load_fundamental_panel(**kwargs: Any) -> dict[str, pd.DataFrame]:
        captured.update(kwargs)
        return {"roe": pd.DataFrame({"AAPL.US": [0.4, 0.5]}, index=index)}

    module = types.ModuleType("backtest.loaders.fundamentals_loader")
    module.load_fundamental_panel = fake_load_fundamental_panel
    monkeypatch.setitem(sys.modules, "backtest.loaders.fundamentals_loader", module)

    result = runner._maybe_inject_fundamentals_for_factor_panel(
        data_map,
        {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "selected_factors": [{"columns_required": ["close", "fund:roe"]}],
        },
    )

    assert captured["fields"] == ["roe"]
    assert captured["index"] is index
    assert result is not data_map
    assert result["AAPL.US"]["fund:roe"].tolist() == [0.4, 0.5]


def test_runner_injects_nan_fundamental_frame_when_loader_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.bdate_range("2024-01-02", periods=2)
    panel = {
        "close": pd.DataFrame(
            {"AAPL.US": [100.0, 101.0], "MSFT.US": [200.0, 201.0]},
            index=index,
        )
    }

    def failing_load_fundamental_panel(**_: Any) -> dict[str, pd.DataFrame]:
        raise RuntimeError("synthetic provider outage")

    module = types.ModuleType("backtest.loaders.fundamentals_loader")
    module.load_fundamental_panel = failing_load_fundamental_panel
    monkeypatch.setitem(sys.modules, "backtest.loaders.fundamentals_loader", module)

    runner._inject_fundamental_panel(
        panel,
        symbols=["AAPL.US", "MSFT.US"],
        fund_columns=["fund:roe"],
        start="2024-01-01",
        end="2024-01-31",
    )

    assert list(panel["fund:roe"].columns) == ["AAPL.US", "MSFT.US"]
    assert panel["fund:roe"].index is index
    assert panel["fund:roe"].isna().all().all()
