"""Regression gates for current portfolio optimization (ported patches 009+010)."""

import json

import numpy as np
import pandas as pd

from src.tools import portfolio_optimizer_tool as module
from src.tools.portfolio_optimizer_tool import CurrentPortfolioOptimizerTool

_ORIGINAL_HISTORY_CLOSES = module._history_closes


def _context():
    return {
        "holdings_native": {
            "ARS": [
                {"symbol": "AAA", "market_value_native": 60.0},
                {"symbol": "BBB", "market_value_native": 30.0},
                {"symbol": "CCC", "market_value_native": 10.0},
            ]
        }
    }


def _history(*, codes, start_date, end_date, interval):
    del start_date, end_date
    assert interval == "1D"
    dates = pd.date_range("2026-01-01", periods=90, freq="B")
    out = {}
    for j, code in enumerate(codes):
        prices = 100.0 * np.cumprod(
            1.0
            + 0.001 * np.sin(np.arange(len(dates)) / (3.0 + j))
            + 0.0002 * (j + 1)
        )
        out[code] = [
            {"date": dt.date().isoformat(), "close": float(price)}
            for dt, price in zip(dates, prices)
        ]
    out["_unresolved"] = []
    return out


def _closes(symbols, *, lookback):
    return _ORIGINAL_HISTORY_CLOSES(symbols, lookback=lookback, history_fetcher=_history)


def _wire(monkeypatch):
    monkeypatch.setattr(module.PortfolioService, "analysis_context", lambda self: _context())
    monkeypatch.setattr(module, "_history_closes", _closes)


def test_risk_parity_returns_advisory_targets_from_current_portfolio(monkeypatch):
    _wire(monkeypatch)
    payload = json.loads(CurrentPortfolioOptimizerTool().execute(optimizer="risk_parity", lookback=60))
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["history_source"] == "asistente-casa-persisted-only"
    assert data["native_currency"] == "ARS"
    assert data["scope"] == "invested_sleeve"
    assert data["advisory_only"] is True
    assert data["orders_created"] is False
    assert data["position_count"] == 3
    assert abs(data["target_weight_sum"] - 1.0) < 1e-9
    assert abs(sum(row["delta_value_ars"] for row in data["allocations"])) < 1e-8


def test_max_weight_is_enforced(monkeypatch):
    _wire(monkeypatch)
    payload = json.loads(
        CurrentPortfolioOptimizerTool().execute(
            optimizer="equal_volatility", lookback=60, max_weight=0.4
        )
    )
    assert payload["status"] == "ok"
    assert max(
        row["target_weight_invested"] for row in payload["data"]["allocations"]
    ) <= 0.4000001


def test_infeasible_max_weight_fails_closed(monkeypatch):
    _wire(monkeypatch)
    payload = json.loads(
        CurrentPortfolioOptimizerTool().execute(
            optimizer="risk_parity", lookback=60, max_weight=0.2
        )
    )
    assert payload["status"] == "error"
    assert "infeasible" in payload["error"]


def test_turnover_aware_uses_current_weights_as_previous_allocation(monkeypatch):
    _wire(monkeypatch)
    payload = json.loads(
        CurrentPortfolioOptimizerTool().execute(
            optimizer="turnover_aware",
            lookback=60,
            risk_aversion=1.0,
            turnover_penalty=0.5,
        )
    )
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["estimated_turnover"] >= 0.0
    assert data["orders_created"] is False
