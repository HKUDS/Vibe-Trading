"""A single IC cannot estimate sample spread or enter the factor ranking."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.factors import bench_runner
from src.factors.bench_runner import _compute_single_alpha
from src.tools import alpha_bench_tool


def _panel_and_one_return_row():
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    symbols = [f"S{i}" for i in range(10)]
    close = pd.DataFrame(100 + rng.normal(0, 1, (30, 10)).cumsum(axis=0), index=dates, columns=symbols)
    factor = pd.DataFrame(rng.normal(size=(30, 10)), index=dates, columns=symbols)
    return_df = close.pct_change(fill_method=None).shift(-1).iloc[[10]]
    return {"close": close}, factor, return_df


def test_bench_runner_single_ic_is_explicitly_skipped() -> None:
    panel, factor, return_df = _panel_and_one_return_row()
    with patch("src.factors.bench_runner.get_default_registry") as get_registry:
        registry = MagicMock()
        get_registry.return_value = registry
        registry.compute.return_value = factor
        registry.get.return_value = MagicMock(meta={})
        result = _compute_single_alpha(("alpha_0", panel, return_df))
    assert "row" not in result
    assert "insufficient IC" in result["skip"]["reason"]
    json.dumps(result, allow_nan=False)


def test_alpha_bench_single_ic_is_explicitly_rejected() -> None:
    panel, factor, return_df = _panel_and_one_return_row()
    registry = SimpleNamespace(
        compute=lambda alpha_id, panel: factor,
        get=lambda alpha_id: SimpleNamespace(zoo="z", meta={}),
    )
    with pytest.raises(RuntimeError, match="insufficient IC"):
        alpha_bench_tool._bench_one_alpha(registry, "alpha_0", panel, return_df)


def test_sequential_bench_does_not_rank_a_single_observation(monkeypatch):
    panel, factor, return_df = _panel_and_one_return_row()
    registry = MagicMock()
    registry.list.return_value = ["alpha_0"]
    registry.compute.return_value = factor
    registry.get.return_value = SimpleNamespace(meta={}, inputs={})
    monkeypatch.setattr(bench_runner, "_load_universe_panel", lambda *a: panel)
    monkeypatch.setattr(bench_runner, "_compute_forward_returns", lambda *a, **kw: return_df)
    result = bench_runner.run_bench("test", "mock", "2024-2025", registry=registry)
    assert result["n_alphas_tested"] == 0
    assert "insufficient IC" in result["skipped"][0]["reason"]
    json.dumps(result, allow_nan=False)


def test_two_observations_keep_the_measured_sample_std():
    panel, factor, _ = _panel_and_one_return_row()
    returns = panel["close"].pct_change(fill_method=None).shift(-1).iloc[[10, 11]]
    registry = SimpleNamespace(
        compute=lambda *args: factor,
        get=lambda *args: SimpleNamespace(zoo="z", meta={}),
    )
    from src.factors.factor_analysis_core import compute_ic_series
    expected = compute_ic_series(factor, returns).std()
    row = alpha_bench_tool._bench_one_alpha(registry, "alpha_0", panel, returns)
    assert row["ic_count"] == 2
    assert row["ic_std"] == round(expected, 6)
    json.dumps(row, allow_nan=False)
