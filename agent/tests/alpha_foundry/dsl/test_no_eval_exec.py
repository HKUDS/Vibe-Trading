from __future__ import annotations

import builtins
import importlib
import subprocess

import pandas as pd
import pytest

from src.alpha_foundry.dsl.operators import evaluate_formula


def test_evaluate_formula_does_not_use_dynamic_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("dynamic execution called")

    monkeypatch.setattr(builtins, "eval", fail)
    monkeypatch.setattr(builtins, "compile", fail)
    monkeypatch.setattr(importlib, "import_module", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    panel = {
        "close": pd.DataFrame(
            {"AAA": [1.0, 2.0, 3.0], "BBB": [3.0, 2.0, 1.0]},
            index=pd.date_range("2024-01-01", periods=3, freq="D"),
        )
    }

    result = evaluate_formula("rank(delta(close, 1))", panel)

    assert list(result.columns) == ["AAA", "BBB"]
    assert result.iloc[-1].notna().all()
