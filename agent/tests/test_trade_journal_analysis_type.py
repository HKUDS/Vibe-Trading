"""An unknown ``analysis_type`` must be an error, not an empty ``ok`` result."""

from __future__ import annotations

import importlib
import json
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def analyze(monkeypatch):
    for name in (
        "backtest.engines._market_hooks",
        "src.agent.tools",
        "src.tools.path_utils",
        "src.tools.trade_journal_parsers",
    ):
        try:
            importlib.import_module(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, MagicMock())
    monkeypatch.delitem(sys.modules, "src.tools.trade_journal_tool", raising=False)
    mod = importlib.import_module("src.tools.trade_journal_tool")
    yield mod.analyze_trade_journal
    sys.modules.pop("src.tools.trade_journal_tool", None)


@pytest.mark.parametrize("bad", ["profil", "Profile", "all"])
def test_unknown_analysis_type_is_an_error(analyze, bad):
    out = json.loads(analyze("trades.csv", analysis_type=bad))
    assert out["status"] == "error"
    assert "analysis_type" in out["error"]


@pytest.mark.parametrize("good", ["full", "profile", "behavior", "strategy"])
def test_known_analysis_types_pass_validation(analyze, good):
    out = json.loads(analyze("trades.csv", analysis_type=good))
    assert "analysis_type" not in out.get("error", "")
