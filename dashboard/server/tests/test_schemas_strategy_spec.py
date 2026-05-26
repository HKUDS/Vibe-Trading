"""Unit tests for StrategySpec, IndicatorSpec, EntryBlock, ExitRule, _parse_condition."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import (
    EntryBlock,
    IndicatorSpec,
    StrategySpec,
    _parse_condition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_STRATEGY_DICT = {
    "name": "funding_mean_reversion_v1",
    "archetype": "mean_reversion",
    "symbol": "ETH",
    "timeframe_signal": "4H",
    "indicators": {
        "funding_z": {
            "source": "stage1:funding_zscore_30d",
            "smoothing": "none",
        },
        "oi_smooth": {
            "source": "stage1:oi_zscore_7d",
            "smoothing": "ema_3",
        },
    },
    "entry_long": {
        "description": "Enter long when funding is deeply negative.",
        "conditions": ["funding_z_percentile_30d <= 10"],
    },
    "entry_short": {
        "description": "Enter short when funding is extremely positive.",
        "conditions": ["funding_z_percentile_30d >= 90"],
    },
    "exit_rules": [
        {"condition": "time_based", "max_hold_hours": 48},
        {"condition": "take_profit_pct", "value": 0.03},
        {"condition": "stop_loss_pct", "value": 0.015},
        {
            "condition": "signal_invalidation",
            "expression": "funding_z_percentile_30d between 40,60",
        },
    ],
}


# ---------------------------------------------------------------------------
# (a) Valid YAML-like dict parsed into StrategySpec successfully
# ---------------------------------------------------------------------------


def test_valid_strategy_spec_parses():
    spec = StrategySpec(**VALID_STRATEGY_DICT)
    assert spec.name == "funding_mean_reversion_v1"
    assert spec.symbol == "ETH"
    assert spec.timeframe_signal == "4H"
    assert "funding_z" in spec.indicators
    assert spec.indicators["funding_z"].source == "stage1:funding_zscore_30d"
    assert spec.indicators["oi_smooth"].smoothing == "ema_3"
    assert spec.entry_long is not None
    assert len(spec.exit_rules) == 4


# ---------------------------------------------------------------------------
# (b) Unknown source (e.g. "binance:price") → ValidationError
# ---------------------------------------------------------------------------


def test_unknown_source_raises():
    bad = dict(VALID_STRATEGY_DICT)
    bad["indicators"] = {
        "price": {"source": "binance:price", "smoothing": "none"}
    }
    with pytest.raises(ValidationError) as exc_info:
        StrategySpec(**bad)
    assert "source" in str(exc_info.value).lower() or "stage1:" in str(exc_info.value)


# ---------------------------------------------------------------------------
# (c) Unknown condition vocabulary → ValidationError with condition index
# ---------------------------------------------------------------------------


def test_invalid_condition_raises_with_index():
    bad = dict(VALID_STRATEGY_DICT)
    bad["entry_long"] = {
        "description": "bad entry",
        "conditions": [
            "funding_z_percentile_30d <= 10",  # valid (index 0)
            "NOT A VALID CONDITION",             # invalid (index 1)
        ],
    }
    with pytest.raises(ValidationError) as exc_info:
        StrategySpec(**bad)
    err_text = str(exc_info.value)
    assert "1" in err_text  # condition index 1 mentioned


# ---------------------------------------------------------------------------
# (d) _parse_condition returns correct tuple for persist pattern
# ---------------------------------------------------------------------------


def test_parse_condition_persist():
    result = _parse_condition("funding_zscore_30d <= -1.5 persist 2/3")
    assert result == ("funding_zscore_30d", "<=", -1.5, 2, 3)


def test_parse_condition_no_persist():
    indicator, op, value, m, n = _parse_condition("funding_rate >= 0.01")
    assert indicator == "funding_rate"
    assert op == ">="
    assert value == pytest.approx(0.01)
    assert m is None
    assert n is None


def test_parse_condition_percentile():
    indicator, op, value, m, n = _parse_condition("oi_percentile_7d < 20")
    assert indicator == "oi_percentile_7d"
    assert op == "<"
    assert value == pytest.approx(20.0)
    assert m is None and n is None


def test_parse_condition_invalid_raises():
    with pytest.raises(ValueError, match="Unrecognised"):
        _parse_condition("THIS IS NOT DSL !!!")


# ---------------------------------------------------------------------------
# (e) Each ExitRule variant dispatched correctly by discriminator
# ---------------------------------------------------------------------------


def test_exit_rule_time_based():
    spec = StrategySpec(
        **{**VALID_STRATEGY_DICT, "exit_rules": [{"condition": "time_based", "max_hold_hours": 72}]}
    )
    rule = spec.exit_rules[0]
    assert rule.condition == "time_based"
    assert rule.max_hold_hours == 72


def test_exit_rule_take_profit():
    spec = StrategySpec(
        **{**VALID_STRATEGY_DICT, "exit_rules": [{"condition": "take_profit_pct", "value": 0.05}]}
    )
    rule = spec.exit_rules[0]
    assert rule.condition == "take_profit_pct"
    assert rule.value == pytest.approx(0.05)


def test_exit_rule_stop_loss():
    spec = StrategySpec(
        **{**VALID_STRATEGY_DICT, "exit_rules": [{"condition": "stop_loss_pct", "value": 0.02}]}
    )
    rule = spec.exit_rules[0]
    assert rule.condition == "stop_loss_pct"
    assert rule.value == pytest.approx(0.02)


def test_exit_rule_signal_invalidation():
    spec = StrategySpec(
        **{
            **VALID_STRATEGY_DICT,
            "exit_rules": [
                {
                    "condition": "signal_invalidation",
                    "expression": "funding_zscore_30d_percentile_30d between 40,60",
                }
            ],
        }
    )
    rule = spec.exit_rules[0]
    assert rule.condition == "signal_invalidation"
    assert "between" in rule.expression


def test_exit_rule_signal_invalidation_bad_expression():
    with pytest.raises(ValidationError):
        StrategySpec(
            **{
                **VALID_STRATEGY_DICT,
                "exit_rules": [
                    {
                        "condition": "signal_invalidation",
                        "expression": "not valid expression",
                    }
                ],
            }
        )


def test_exit_rule_unknown_condition():
    with pytest.raises(ValidationError):
        StrategySpec(
            **{
                **VALID_STRATEGY_DICT,
                "exit_rules": [{"condition": "trailing_stop", "value": 0.01}],
            }
        )
