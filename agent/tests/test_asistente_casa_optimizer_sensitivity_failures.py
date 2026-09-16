"""Regression gates for per-scenario failure isolation (ported patch 013)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import src.tools.portfolio_optimizer_sensitivity_tool as sensitivity


def test_one_solver_failure_is_reported_without_aborting_grid(monkeypatch):
    rows = [
        {"symbol": "AAA", "market_value_native": 60.0},
        {"symbol": "BBB", "market_value_native": 40.0},
    ]
    monkeypatch.setattr(
        sensitivity.PortfolioService,
        "analysis_context",
        lambda self: {"holdings_native": {"ARS": rows}},
    )
    closes = pd.DataFrame(
        {
            "AAA": np.linspace(100.0, 131.0, 31),
            "BBB": np.linspace(100.0, 116.0, 31),
        },
        index=pd.date_range("2026-01-01", periods=31, freq="D"),
    )
    monkeypatch.setattr(sensitivity, "_history_closes", lambda symbols, lookback: closes)

    calls = {"n": 0}

    def fake_target(returns, **kwargs):
        calls["n"] += 1
        if kwargs["max_weight"] == 0.6:
            raise RuntimeError("Iteration limit reached")
        return np.asarray([0.55, 0.45], dtype=float)

    monkeypatch.setattr(sensitivity, "_target_weights", fake_target)
    tool = sensitivity.PortfolioOptimizerSensitivityTool()
    payload = json.loads(
        tool.execute(
            optimizers=["turnover_aware"],
            lookbacks=[30],
            max_weights=[None, 0.6],
            turnover_penalties=[0.01],
        )
    )

    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["scenario_count"] == 2
    assert data["successful_scenario_count"] == 1
    assert data["failed_scenario_count"] == 1
    assert len(data["scenarios"]) == 1
    assert data["failed_scenarios"] == [{
        "optimizer": "turnover_aware",
        "lookback": 30,
        "max_weight": 0.6,
        "turnover_penalty": 0.01,
        "error_type": "RuntimeError",
        "error": "Iteration limit reached",
    }]
    assert calls["n"] == 2


def test_all_solver_failures_still_return_explicit_batch_diagnostics(monkeypatch):
    rows = [
        {"symbol": "AAA", "market_value_native": 50.0},
        {"symbol": "BBB", "market_value_native": 50.0},
    ]
    monkeypatch.setattr(
        sensitivity.PortfolioService,
        "analysis_context",
        lambda self: {"holdings_native": {"ARS": rows}},
    )
    closes = pd.DataFrame(
        {"AAA": np.linspace(100.0, 131.0, 31), "BBB": np.linspace(100.0, 115.0, 31)},
        index=pd.date_range("2026-01-01", periods=31, freq="D"),
    )
    monkeypatch.setattr(sensitivity, "_history_closes", lambda symbols, lookback: closes)
    monkeypatch.setattr(
        sensitivity,
        "_target_weights",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("solver failed")),
    )

    payload = json.loads(
        sensitivity.PortfolioOptimizerSensitivityTool().execute(
            optimizers=["turnover_aware"],
            lookbacks=[30],
            max_weights=[None],
            turnover_penalties=[0.01],
        )
    )
    assert payload["status"] == "ok"
    assert payload["data"]["scenario_count"] == 1
    assert payload["data"]["successful_scenario_count"] == 0
    assert payload["data"]["failed_scenario_count"] == 1
    assert payload["data"]["stability"] == []
