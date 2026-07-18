"""Regression tests for alpha-bench forward-return missing-data handling."""

from __future__ import annotations

import pandas as pd

from src.tools.alpha_bench_tool import _compute_forward_returns


def test_forward_returns_preserve_missing_close_boundaries() -> None:
    close = pd.DataFrame(
        {"AAA": [100.0, None, 121.0]},
        index=pd.date_range("2026-01-01", periods=3, freq="D"),
    )

    forward = _compute_forward_returns({"close": close})

    assert forward["AAA"].isna().all()
