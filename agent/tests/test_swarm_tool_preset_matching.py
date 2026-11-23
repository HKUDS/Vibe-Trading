"""Regression coverage for SwarmTool natural-language preset routing."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json

import src.tools.swarm_tool as swarm_tool


def test_explicit_preset_name_wins_over_keyword_scoring() -> None:
    prompt = (
        "[Swarm Team Mode] Use the investment_committee preset to evaluate "
        "whether to go long or short on NVDA given current market conditions"
    )

    assert swarm_tool._match_preset(prompt) == "investment_committee"


def test_plain_given_does_not_trigger_iv_derivatives_match() -> None:
    prompt = "Evaluate whether to go long or short on NVDA given current market conditions"

    assert swarm_tool._match_preset(prompt) != "derivatives_strategy_desk"


def test_explicit_preset_name_accepts_spaces() -> None:
    prompt = "Use the investment committee preset for NVDA"

    assert swarm_tool._match_preset(prompt) == "investment_committee"


def test_explicit_preset_parameter_is_normalized() -> None:
    preset, error = swarm_tool._resolve_preset(
        "Continue and finish the report.",
        explicit_preset="Investment Committee",
    )

    assert error is None
    assert preset == "investment_committee"


def test_ambiguous_continuation_does_not_fallback_to_equity_team() -> None:
    preset, error = swarm_tool._resolve_preset(
        "Continue and finish report. Continue from 'Trim 25% of position if price r'."
    )

    assert preset is None
    assert error is not None
    assert "equity_research_team" in error


def test_swarm_tool_rejects_ambiguous_continuation_before_starting_run() -> None:
    payload = json.loads(
        swarm_tool.SwarmTool(policy=ToolPolicy.from_config(get_env_config())).execute(
            prompt="Continue and finish report. Continue from 'Trim 25% of position if price r'."
        )
    )

    assert payload["status"] == "error"
    assert "Ambiguous continuation" in payload["error"]
