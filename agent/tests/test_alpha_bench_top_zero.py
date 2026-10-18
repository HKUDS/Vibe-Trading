"""``top=0`` must be rejected, not silently replaced by the default of 20."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def run_alpha_bench(monkeypatch):
    for name in (
        "backtest.loaders.cn_adjust",
        "src.agent.tools",
        "src.config.accessor",
        "src.config.paths",
    ):
        try:
            importlib.import_module(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, MagicMock())
    monkeypatch.delitem(sys.modules, "src.tools.alpha_bench_tool", raising=False)
    mod = importlib.import_module("src.tools.alpha_bench_tool")
    yield mod.run_alpha_bench
    sys.modules.pop("src.tools.alpha_bench_tool", None)


@pytest.mark.parametrize("bad", [0, -3, "0"])
def test_non_positive_top_is_rejected(run_alpha_bench, bad):
    out = run_alpha_bench(universe="csi300", period="2020-2025", top=bad)
    assert out == {"status": "error", "error": "top must be > 0"}


def test_non_integer_top_is_an_error_envelope(run_alpha_bench):
    out = run_alpha_bench(universe="csi300", period="2020-2025", top="abc")
    assert out["status"] == "error"
    assert "top" in out["error"]


def test_omitted_top_is_not_rejected_as_top(run_alpha_bench):
    out = run_alpha_bench(universe="csi300", period="2020-2025")
    assert "top must" not in out.get("error", "")
