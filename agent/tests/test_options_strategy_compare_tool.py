"""Tests for deterministic multi-strategy options comparison."""

from __future__ import annotations

import json

import pytest


def _tool():
    from src.tools.options_strategy_compare_tool import OptionsStrategyCompareTool

    return OptionsStrategyCompareTool()


def _long_call() -> dict:
    return {
        "name": "long_call",
        "legs": [{"option_type": "call", "strike": 100, "qty": 1, "premium": 8}],
    }


def _spread() -> dict:
    return {
        "name": "bull_spread",
        "legs": [
            {"option_type": "call", "strike": 95, "qty": 1, "premium": 8},
            {"option_type": "call", "strike": 105, "qty": -1, "premium": 3},
        ],
    }


def _execute(**overrides):
    kwargs = {
        "strategies": [_long_call(), _spread()],
        "entry_spot": 100,
        "expiry_days": 0,
        "commission_rate": 0,
        "spot_min": 80,
        "spot_max": 120,
        "spot_points": 21,
        "scenario_iv_values": [0.3],
    }
    kwargs.update(overrides)
    return json.loads(_tool().execute(**kwargs))


def test_common_grid_summaries_and_baseline_deltas() -> None:
    payload = _execute()

    assert payload["status"] == "ok"
    assert payload["tool"] == "options_strategy_compare"
    assert payload["comparison"] == {"baseline_index": 0, "baseline_name": "long_call"}
    assert len(payload["expiry_curve"]["spot"]) == 21
    assert payload["expiry_curve"]["spot"][10] == 100
    assert payload["expiry_curve"]["pnl"]["long_call"][10] == -8
    assert payload["expiry_curve"]["pnl"]["bull_spread"][10] == 0
    assert payload["expiry_curve"]["delta_to_baseline"]["bull_spread"][10] == 8
    assert payload["expiry_curve"]["pnl"]["long_call"][-1] == 12
    assert payload["expiry_curve"]["pnl"]["bull_spread"][-1] == 5
    assert payload["expiry_curve"]["delta_to_baseline"]["bull_spread"][-1] == -7
    assert payload["expiry_curve"]["delta_to_baseline"]["long_call"] == [0] * 21
    assert (
        payload["scenario_grid"]["pnl"]["long_call"][0]
        == payload["expiry_curve"]["pnl"]["long_call"]
    )
    assert payload["scenario_grid"]["delta_to_baseline"]["bull_spread"][0][-1] == -7
    assert payload["strategies"][0]["summary"]["entry_cost"] == 8
    assert payload["strategies"][1]["summary"]["entry_cost"] == 5
    assert "best_strategy" not in payload
    assert "ranking" not in payload


def test_output_is_byte_deterministic_and_preserves_input_order() -> None:
    first = _tool().execute(
        strategies=[_spread(), _long_call()],
        entry_spot=100,
        expiry_days=0,
        commission_rate=0,
        spot_points=21,
        scenario_iv_values=[0.3],
    )
    second = _tool().execute(
        strategies=[_spread(), _long_call()],
        entry_spot=100,
        expiry_days=0,
        commission_rate=0,
        spot_points=21,
        scenario_iv_values=[0.3],
    )

    assert first == second
    payload = json.loads(first)
    assert [row["name"] for row in payload["strategies"]] == [
        "bull_spread",
        "long_call",
    ]
    assert payload["comparison"]["baseline_name"] == "bull_spread"


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"strategies": [_long_call()]}, "at least two"),
        ({"strategies": [_long_call(), _long_call()]}, "unique"),
        ({"baseline_index": 2}, "baseline_index"),
        ({"baseline_index": True}, "baseline_index"),
        ({"spot_points": 202}, "between"),
        ({"strategies": [_long_call(), {"name": "", "legs": []}]}, "name"),
    ],
)
def test_invalid_comparison_inputs_return_error_envelopes(overrides, expected) -> None:
    payload = _execute(**overrides)

    assert payload["status"] == "error"
    assert expected in payload["error"]


def test_explicit_baseline_index_uses_the_selected_strategy() -> None:
    payload = _execute(baseline_index=1)

    assert payload["comparison"] == {
        "baseline_index": 1,
        "baseline_name": "bull_spread",
    }
    assert payload["expiry_curve"]["delta_to_baseline"]["long_call"][-1] == 7
    assert payload["expiry_curve"]["delta_to_baseline"]["bull_spread"] == [0] * 21


def test_tool_is_auto_discovered_as_readonly_and_deterministic() -> None:
    from src.tools import build_registry

    tool = build_registry().get("options_strategy_compare")

    assert tool is not None
    assert tool.is_readonly is True
    assert tool.deterministic is True
    strategy_schema = tool.parameters["properties"]["strategies"]["items"]
    assert strategy_schema["required"] == ["name", "legs"]
    assert strategy_schema["properties"]["legs"]["items"]["required"] == [
        "option_type",
        "strike",
        "qty",
    ]


def test_mcp_wrapper_delegates_the_same_comparison() -> None:
    import mcp_server

    payload = json.loads(
        mcp_server.compare_options_strategies(
            strategies=[_long_call(), _spread()],
            entry_spot=100,
            expiry_days=0,
            commission_rate=0,
            spot_min=80,
            spot_max=120,
            spot_points=21,
            scenario_iv_values=[0.3],
        )
    )

    assert payload["status"] == "ok"
    assert payload["expiry_curve"]["delta_to_baseline"]["bull_spread"][-1] == -7


def test_extreme_finite_inputs_return_error_instead_of_nonstandard_json() -> None:
    payload = _execute(multiplier=1e308)

    assert payload["status"] == "error"
    assert "non-serializable" in payload["error"]
