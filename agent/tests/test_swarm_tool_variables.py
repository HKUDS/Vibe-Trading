"""Regression coverage for SwarmTool preset template-variable extraction.

Several presets used to receive hardcoded variables (commodity='gold',
view='neutral', ...), so a prompt naming copper ran the whole commodity team
on gold. These tests pin prompt-driven extraction, the unchanged defaults for
vague prompts, and the explicit caller-override path.
"""

from __future__ import annotations

from src.tools import swarm_variables
import src.tools.swarm_tool as swarm_tool


def test_commodity_prompt_fills_commodity_and_horizon() -> None:
    variables = swarm_tool._build_variables(
        "commodity_research_team",
        "Analyze copper supply and demand for the next 6 months",
    )

    assert variables == {"commodity": "copper", "horizon": "6 months"}


def test_commodity_chinese_prompt_fills_commodity_and_horizon() -> None:
    variables = swarm_tool._build_variables(
        "commodity_research_team",
        "分析铜的供需格局，未来 6 个月",
    )

    assert variables == {"commodity": "copper", "horizon": "6 months"}


def test_copper_prompt_routes_to_commodity_team_with_its_commodity() -> None:
    prompt = "Analyze copper supply and demand for the next 6 months"

    preset = swarm_tool._match_preset(prompt)

    assert preset == "commodity_research_team"
    assert swarm_tool._build_variables(preset, prompt)["commodity"] == "copper"


def test_crypto_target_keeps_only_the_assets_the_user_named() -> None:
    variables = swarm_tool._build_variables(
        "crypto_research_lab",
        "Analyze ETH and SOL outlook for the next 3 months",
    )

    assert variables["target"] == "ETH, SOL"
    assert variables["timeframe"] == "3 months"


def test_crypto_target_maps_chinese_names_to_symbols() -> None:
    variables = swarm_tool._build_variables("crypto_research_lab", "比特币中长期走势")

    assert variables["target"] == "BTC"
    assert variables["timeframe"] == "long-term 3-12 months"


def test_derivatives_view_follows_the_prompt() -> None:
    variables = swarm_tool._build_variables(
        "derivatives_strategy_desk",
        "Design a bearish options strategy on TSLA",
    )

    assert variables["view"] == "bearish"


def test_factor_type_follows_the_prompt() -> None:
    variables = swarm_tool._build_variables("factor_research_committee", "研究 A 股的动量因子")

    assert variables["factor_type"] == "momentum"


def test_event_type_follows_the_prompt() -> None:
    variables = swarm_tool._build_variables(
        "event_driven_task_force",
        "M&A event-driven opportunities in US equities",
    )

    assert variables["event_type"] == "M&A"


def test_fund_type_follows_the_prompt() -> None:
    variables = swarm_tool._build_variables(
        "fund_selection_panel",
        "Select bond funds for a conservative FOF",
    )

    assert variables["fund_type"] == "bond"


def test_macro_horizon_follows_the_prompt() -> None:
    variables = swarm_tool._build_variables("macro_strategy_forum", "Annual macro outlook for China")

    assert variables["horizon"] == "annual"


def test_vague_prompt_keeps_the_previous_defaults() -> None:
    assert swarm_tool._build_variables("commodity_research_team", "Analyze the commodity market outlook") == {
        "commodity": "gold",
        "horizon": "3 months",
    }


def test_extract_horizon_normalises_common_phrases() -> None:
    assert swarm_variables._extract_horizon("medium-term view") == "3 months"
    assert swarm_variables._extract_horizon("未来半年") == "6 months"
    assert swarm_variables._extract_horizon("a 1 year horizon") == "1 year"


def test_explicit_variables_override_extracted_values() -> None:
    extracted = swarm_tool._build_variables(
        "commodity_research_team",
        "Analyze copper supply and demand for the next 6 months",
    )

    variables, error = swarm_tool._merge_variables(extracted, {"commodity": "silver", "horizon": "1 year"})

    assert error is None
    assert variables == {"commodity": "silver", "horizon": "1 year"}


def test_explicit_variables_keep_unmentioned_extracted_values() -> None:
    extracted = swarm_tool._build_variables("commodity_research_team", "Analyze copper for the next 6 months")

    variables, error = swarm_tool._merge_variables(extracted, {"horizon": "1 month"})

    assert error is None
    assert variables == {"commodity": "copper", "horizon": "1 month"}


def test_explicit_variables_reject_non_mapping() -> None:
    variables, error = swarm_tool._merge_variables({"commodity": "gold"}, ["not", "a", "mapping"])

    assert error is not None
    assert variables == {"commodity": "gold"}


def test_tool_schema_exposes_optional_variables() -> None:
    parameters = swarm_tool.SwarmTool.parameters

    assert "variables" in parameters["properties"]
    assert "variables" not in parameters["required"]
