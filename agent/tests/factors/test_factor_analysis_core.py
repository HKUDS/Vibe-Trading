"""Regression tests for factor analysis core helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.factors.factor_analysis_core import compute_group_equity
from src.tools.factor_analysis_tool import run_factor_analysis


def _panel(n_dates: int = 30, n_codes: int = 10, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="B")
    codes = [f"C{i:02d}" for i in range(n_codes)]
    rng = np.random.default_rng(seed)
    factor = pd.DataFrame(rng.normal(size=(n_dates, n_codes)), index=dates, columns=codes)
    ret = pd.DataFrame(rng.normal(scale=0.01, size=(n_dates, n_codes)), index=dates, columns=codes)
    return factor, ret


def test_compute_group_equity_rejects_nonpositive_n_groups() -> None:
    factor, ret = _panel()
    with pytest.raises(ValueError, match="n_groups"):
        compute_group_equity(factor, ret, -1)
    with pytest.raises(ValueError, match="n_groups"):
        compute_group_equity(factor, ret, 0)
    eq = compute_group_equity(factor, ret, 1)
    assert not eq.empty
    assert list(eq.columns) == ["Group_1"]


def test_run_factor_analysis_nonpositive_n_groups_returns_json_error() -> None:
    factor, ret = _panel()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        factor.to_csv(root / "f.csv")
        ret.to_csv(root / "r.csv")
        out = json.loads(
            run_factor_analysis(
                str(root / "f.csv"),
                str(root / "r.csv"),
                str(root / "out"),
                n_groups=-1,
            )
        )
        assert out["status"] == "error"
        assert "n_groups" in out["error"]


def test_run_factor_analysis_single_day_ic_std_is_finite_json() -> None:
    """One IC date must not emit NaN ic_std (ddof=1) into the JSON summary."""
    factor, ret = _panel(n_dates=1, n_codes=8, seed=3)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        factor.to_csv(root / "f.csv")
        ret.to_csv(root / "r.csv")
        raw = run_factor_analysis(
            str(root / "f.csv"),
            str(root / "r.csv"),
            str(root / "out"),
            n_groups=5,
        )
        out = json.loads(raw)
        assert out["status"] == "ok"
        assert out["ic_count"] == 1
        assert out["ic_std"] == 0.0
        assert out["ir"] == 0.0
        summary = json.loads((root / "out" / "ic_summary.json").read_text(encoding="utf-8"))
        assert summary["ic_std"] == 0.0
        json.dumps(out, allow_nan=False)
        json.dumps(summary, allow_nan=False)
