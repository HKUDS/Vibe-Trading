"""Tests for the Agent-facing options_payoff tool envelope."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json

import pytest

from src.tools.options_payoff_tool import OptionsPayoffTool


def _spread_legs() -> list[dict[str, object]]:
    """Return a deterministic debit-spread fixture."""
    return [
        {"option_type": "call", "strike": 95.0, "qty": 1, "premium": 8.0},
        {"option_type": "call", "strike": 105.0, "qty": -1, "premium": 3.0},
    ]


def test_tool_returns_analytic_summary_curve_and_scenarios() -> None:
    """The success envelope is bounded, serializable, and engine-cost aware."""
    raw = OptionsPayoffTool().execute(
        legs=_spread_legs(),
        entry_spot=100.0,
        expiry_days=30,
        multiplier=100,
        commission_rate=0.001,
        spot_min=80,
        spot_max=120,
        spot_points=21,
    )
    payload = json.loads(raw)

    assert payload["status"] == "ok"
    assert payload["tool"] == "options_payoff"
    assert payload["summary"]["net_premium"] == pytest.approx(500.0)
    assert payload["summary"]["entry_commission"] == pytest.approx(1.1)
    assert payload["summary"]["entry_cost"] == pytest.approx(501.1)
    assert payload["summary"]["breakevens"] == pytest.approx([100.011])
    assert payload["summary"]["max_profit"] == pytest.approx(498.9)
    assert payload["summary"]["max_loss"] == pytest.approx(-501.1)
    assert len(payload["expiry_curve"]["spot"]) == 21
    assert len(payload["expiry_curve"]["pnl"]) == 21
    assert len(payload["scenario_grid"]["iv_values"]) == 5
    assert len(payload["scenario_grid"]["pnl"]) == 5
    assert all(len(row) == 21 for row in payload["scenario_grid"]["pnl"])


def test_unbounded_values_are_json_null_with_explicit_flags() -> None:
    """Tool output never serializes non-standard Infinity values."""
    payload = json.loads(
        OptionsPayoffTool().execute(
            legs=[
                {
                    "option_type": "call",
                    "strike": 100,
                    "qty": -1,
                    "premium": 5,
                }
            ],
            entry_spot=100,
            expiry_days=30,
            spot_points=21,
        )
    )

    assert payload["status"] == "ok"
    assert payload["summary"]["loss_unbounded"] is True
    assert payload["summary"]["max_loss"] is None


def test_tool_is_auto_discovered_by_the_agent_registry() -> None:
    """Creating the module is sufficient to expose the read-only Agent tool."""
    from src.tools import build_registry

    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()))
    tool = registry.get("options_payoff")
    assert tool is not None
    assert tool.is_readonly is True


def test_mcp_wrapper_exposes_the_same_research_calculation() -> None:
    """The public MCP wrapper delegates to the Agent tool without mutation."""
    import mcp_server

    payload = json.loads(
        mcp_server.analyze_options_payoff(
            legs=_spread_legs(),
            entry_spot=100.0,
            expiry_days=30,
            multiplier=100.0,
            commission_rate=0.001,
            spot_points=21,
        )
    )
    assert payload["status"] == "ok"
    assert payload["summary"]["breakevens"] == pytest.approx([100.011])


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"legs": [], "entry_spot": 100, "expiry_days": 30}, "non-empty"),
        (
            {
                "legs": [{"option_type": "call", "strike": 100, "qty": 1.5}],
                "entry_spot": 100,
                "expiry_days": 30,
            },
            "integer",
        ),
        (
            {
                "legs": _spread_legs(),
                "entry_spot": 100,
                "expiry_days": 30,
                "spot_points": 10,
            },
            "between",
        ),
        (
            {
                "legs": _spread_legs(),
                "entry_spot": 100,
                "expiry_days": 30,
                "scenario_iv_values": [0.2, 0.0],
            },
            "positive",
        ),
    ],
)
def test_tool_returns_error_envelopes(kwargs: dict[str, object], expected: str) -> None:
    """Malformed tool arguments are contained in JSON error envelopes."""
    payload = json.loads(OptionsPayoffTool().execute(**kwargs))
    assert payload["status"] == "error"
    assert expected in payload["error"]


def test_overflowing_result_returns_error_envelope_not_exception() -> None:
    """A finite but extreme multiplier overflows the P&L to inf; it must not raise."""
    raw = OptionsPayoffTool().execute(
        legs=[{"option_type": "call", "strike": 100.0, "qty": 10}],
        entry_spot=100.0,
        expiry_days=30,
        multiplier=1e308,
    )
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "non-serializable" in payload["error"]
