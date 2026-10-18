"""A bench row built from one IC observation must stay finite, strict JSON."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

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


def _assert_finite_row(row: dict) -> None:
    assert row["ic_count"] == 1
    assert math.isfinite(row["ic_std"])
    assert row["ic_std"] == 0.0
    assert row["ir"] == 0.0
    json.dumps(row, allow_nan=False)


def test_bench_runner_single_ic_row_is_finite() -> None:
    panel, factor, return_df = _panel_and_one_return_row()
    with patch("src.factors.bench_runner.get_default_registry") as get_registry:
        registry = MagicMock()
        get_registry.return_value = registry
        registry.compute.return_value = factor
        registry.get.return_value = MagicMock(meta={})
        result = _compute_single_alpha(("alpha_0", panel, return_df))
    _assert_finite_row(result["row"])


def test_alpha_bench_single_ic_row_is_finite() -> None:
    panel, factor, return_df = _panel_and_one_return_row()
    registry = SimpleNamespace(
        compute=lambda alpha_id, panel: factor,
        get=lambda alpha_id: SimpleNamespace(zoo="z", meta={}),
    )
    row = alpha_bench_tool._bench_one_alpha(registry, "alpha_0", panel, return_df)
    _assert_finite_row(row)
