"""Regression gates for optimizer sensitivity analysis (ported patches 011+012)."""

import json

import numpy as np
import pandas as pd

from src.tools import portfolio_optimizer_sensitivity_tool as mod
from src.tools.portfolio_optimizer_sensitivity_tool import PortfolioOptimizerSensitivityTool


def _context():
    return {
        "holdings_native": {
            "ARS": [
                {"symbol": "AAA", "market_value_native": 40.0},
                {"symbol": "BBB", "market_value_native": 30.0},
                {"symbol": "CCC", "market_value_native": 20.0},
                {"symbol": "DDD", "market_value_native": 10.0},
            ]
        }
    }


def _closes(symbols, *, lookback):
    idx = pd.date_range("2026-01-01", periods=lookback + 1, freq="D")
    data = {}
    for i, symbol in enumerate(symbols):
        # Distinct smooth paths keep covariance finite/deterministic.
        x = np.arange(lookback + 1, dtype=float)
        data[symbol] = 100.0 + (i + 1) * x + 0.03 * (i + 1) * x * x
    return pd.DataFrame(data, index=idx)


def test_sensitivity_fetches_history_once_and_returns_expected_grid(monkeypatch):
    calls = []
    monkeypatch.setattr(mod.PortfolioService, "analysis_context", lambda self: _context())

    def fetch(symbols, *, lookback):
        calls.append((tuple(symbols), lookback))
        return _closes(symbols, lookback=lookback)

    monkeypatch.setattr(mod, "_history_closes", fetch)

    raw = PortfolioOptimizerSensitivityTool().execute(
        optimizers=["equal_volatility", "risk_parity"],
        lookbacks=[30, 60],
        max_weights=[None, 0.4],
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    data = payload["data"]
    assert calls == [(('AAA', 'BBB', 'CCC', 'DDD'), 60)]
    assert data["scenario_count"] == 8
    assert data["history_source"] == "asistente-casa-persisted-only"
    assert data["cash_policy"] == "excluded_unchanged"
    assert data["sector_constraints"]["status"] == "deferred"
    for row in data["scenarios"]:
        assert 0.0 < row["top1_weight"] <= 1.0
        assert row["estimated_turnover"] >= 0.0


def test_turnover_penalty_grid_is_reported_separately(monkeypatch):
    monkeypatch.setattr(mod.PortfolioService, "analysis_context", lambda self: _context())
    monkeypatch.setattr(mod, "_history_closes", _closes)
    raw = PortfolioOptimizerSensitivityTool().execute(
        optimizers=["turnover_aware"],
        lookbacks=[30],
        max_weights=[None],
        turnover_penalties=[0.0, 0.001, 0.01],
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    rows = payload["data"]["scenarios"]
    assert len(rows) == 3
    assert [row["turnover_penalty"] for row in rows] == [0.0, 0.001, 0.01]
    assert all(abs(row["top1_weight"]) <= 1.0 for row in rows)


def test_infeasible_cap_fails_closed(monkeypatch):
    monkeypatch.setattr(mod.PortfolioService, "analysis_context", lambda self: _context())
    monkeypatch.setattr(mod, "_history_closes", _closes)
    payload = json.loads(PortfolioOptimizerSensitivityTool().execute(
        optimizers=["risk_parity"],
        lookbacks=[30],
        max_weights=[0.20],
    ))
    assert payload["status"] == "error"
    assert "infeasible" in payload["error"]


def test_grid_size_is_bounded_before_history_fetch(monkeypatch):
    monkeypatch.setattr(mod.PortfolioService, "analysis_context", lambda self: _context())
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("history should not be fetched")

    monkeypatch.setattr(mod, "_history_closes", forbidden)
    payload = json.loads(PortfolioOptimizerSensitivityTool().execute(
        optimizers=["turnover_aware", "risk_parity", "equal_volatility"],
        lookbacks=[30, 60, 90, 120],
        max_weights=[None, 0.30, 0.25, 0.20],
        turnover_penalties=[0.0, 0.001, 0.005, 0.01, 0.02, 0.05],
    ))
    assert payload["status"] == "error"
    assert "scenarios" in payload["error"]
    assert called is False


def test_documented_default_grid_of_112_scenarios_is_within_the_120_cap(monkeypatch):
    """VT-016 grid-cap fixup (patch 012): the documented defaults (16 + 16 +
    80 = 112 scenarios) must fit under the cap without raising.

    The default max_weight caps go down to 0.10, which is only feasible with
    at least 10 active instruments (0.10 * 10 == 1.0), so this uses a wider
    holdings context than the other tests in this module.
    """
    def _wide_context():
        return {
            "holdings_native": {
                "ARS": [
                    {"symbol": f"SYM{i}", "market_value_native": 100.0 - i}
                    for i in range(10)
                ]
            }
        }

    monkeypatch.setattr(mod.PortfolioService, "analysis_context", lambda self: _wide_context())
    monkeypatch.setattr(mod, "_history_closes", _closes)
    payload = json.loads(PortfolioOptimizerSensitivityTool().execute())
    assert payload["status"] == "ok"
    assert payload["data"]["scenario_count"] == 112
