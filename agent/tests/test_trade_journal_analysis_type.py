"""An unknown ``analysis_type`` must be an error, not an empty ``ok`` result."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json

import pytest

from src.tools.trade_journal_tool import analyze_trade_journal


@pytest.mark.parametrize("bad", ["profil", "Profile", "all", ["profile"], {"type": "profile"}])
def test_unknown_analysis_type_is_an_error(bad):
    out = json.loads(analyze_trade_journal("trades.csv", analysis_type=bad, roots=FileRoots.from_config(get_env_config().api)))
    assert out["status"] == "error"
    assert "analysis_type" in out["error"]


@pytest.mark.parametrize("good", ["full", "profile", "behavior", "strategy"])
def test_known_analysis_types_pass_validation(good):
    out = json.loads(analyze_trade_journal("trades.csv", analysis_type=good, roots=FileRoots.from_config(get_env_config().api)))
    assert "analysis_type" not in out.get("error", "")
