"""Agent tool for deterministic comparison of multi-leg option strategies."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from backtest.options_payoff import OptionLeg, expiry_payoff, scenario_grid
from src.agent.tools import BaseTool
from src.tools.options_payoff_tool import (
    _coerce_legs,
    _MAX_LEGS,
    _optional_float,
    _required_float,
    _rounded,
    _rounded_array,
    _scenario_ivs,
    _spot_bounds,
    _spot_points,
)

_MAX_STRATEGIES = 4
_MAX_SPOT_POINTS = 201


class OptionsStrategyCompareTool(BaseTool):
    """Compare several option strategies on one spot and IV grid."""

    name = "options_strategy_compare"
    description = (
        "Compare two to four European multi-leg option strategies on a shared "
        "spot and IV grid. Returns each strategy's analytic summary, expiry and "
        "scenario P&L, and deltas against a selected baseline. Comparison is "
        "descriptive and does not rank or recommend strategies. Research only."
    )
    repeatable = True
    is_readonly = True
    deterministic = True
    parameters = {
        "type": "object",
        "properties": {
            "strategies": {
                "type": "array",
                "minItems": 2,
                "maxItems": _MAX_STRATEGIES,
                "description": "Named strategies, each with the same leg shape as options_payoff.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1, "maxLength": 64},
                        "legs": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": _MAX_LEGS,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "option_type": {
                                        "type": "string",
                                        "enum": ["call", "put"],
                                    },
                                    "strike": {"type": "number", "exclusiveMinimum": 0},
                                    "qty": {"type": "integer"},
                                    "premium": {"type": "number", "minimum": 0},
                                },
                                "required": ["option_type", "strike", "qty"],
                            },
                        },
                    },
                    "required": ["name", "legs"],
                },
            },
            "baseline_index": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "description": "Zero-based strategy index used for P&L deltas.",
            },
            "entry_spot": {"type": "number", "exclusiveMinimum": 0},
            "expiry_days": {"type": "number", "minimum": 0},
            "risk_free_rate": {"type": "number", "default": 0.05},
            "volatility": {"type": "number", "exclusiveMinimum": 0, "default": 0.3},
            "multiplier": {"type": "number", "exclusiveMinimum": 0, "default": 1.0},
            "commission_rate": {
                "type": "number",
                "minimum": 0,
                "exclusiveMaximum": 1,
                "default": 0.001,
            },
            "spot_min": {"type": "number", "minimum": 0},
            "spot_max": {"type": "number", "exclusiveMinimum": 0},
            "spot_points": {
                "type": "integer",
                "minimum": 21,
                "maximum": _MAX_SPOT_POINTS,
                "default": 121,
            },
            "scenario_iv_values": {
                "type": "array",
                "minItems": 1,
                "maxItems": 9,
                "items": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "required": ["strategies", "entry_spot", "expiry_days"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Compute strategy summaries and baseline-relative P&L matrices."""
        try:
            strategies = _coerce_strategies(kwargs.get("strategies"))
            baseline_index = _baseline_index(
                kwargs.get("baseline_index"), len(strategies)
            )
            entry_spot = _required_float(kwargs, "entry_spot")
            expiry_days = _required_float(kwargs, "expiry_days")
            rate = _optional_float(kwargs, "risk_free_rate", 0.05)
            volatility = _optional_float(kwargs, "volatility", 0.3)
            multiplier = _optional_float(kwargs, "multiplier", 1.0)
            commission_rate = _optional_float(kwargs, "commission_rate", 0.001)
            spot_points = _spot_points(kwargs.get("spot_points"))
            if spot_points > _MAX_SPOT_POINTS:
                raise ValueError(
                    f"spot_points must be between 21 and {_MAX_SPOT_POINTS}"
                )
            all_legs = [leg for _, legs in strategies for leg in legs]
            spot_min, spot_max = _spot_bounds(kwargs, all_legs, entry_spot)
            iv_values = _scenario_ivs(kwargs.get("scenario_iv_values"), volatility)
            spots = np.linspace(spot_min, spot_max, spot_points)
            time_to_expiry = expiry_days / 365.0
            reports = [
                expiry_payoff(
                    legs,
                    spots,
                    entry_spot=entry_spot,
                    time_to_expiry=time_to_expiry,
                    rate=rate,
                    iv=volatility,
                    multiplier=multiplier,
                    commission_rate=commission_rate,
                )
                for _, legs in strategies
            ]
            scenarios = [
                scenario_grid(
                    legs,
                    spots,
                    iv_values,
                    entry_spot=entry_spot,
                    time_to_expiry=time_to_expiry,
                    rate=rate,
                    entry_iv=volatility,
                    multiplier=multiplier,
                    commission_rate=commission_rate,
                )
                for _, legs in strategies
            ]
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return _error(str(exc))

        names = [name for name, _ in strategies]
        baseline_name = names[baseline_index]
        expiry_delta = {
            name: np.asarray(report.payoff) - np.asarray(reports[baseline_index].payoff)
            for name, report in zip(names, reports, strict=True)
        }
        scenario_delta = {
            name: np.asarray(scenario) - np.asarray(scenarios[baseline_index])
            for name, scenario in zip(names, scenarios, strict=True)
        }
        payload = {
            "status": "ok",
            "tool": self.name,
            "inputs": {
                "strategies": [
                    {
                        "name": name,
                        "legs": [
                            {
                                "option_type": leg.option_type,
                                "strike": leg.strike,
                                "qty": leg.qty,
                                "premium": leg.premium,
                            }
                            for leg in legs
                        ],
                    }
                    for name, legs in strategies
                ],
                "entry_spot": entry_spot,
                "expiry_days": expiry_days,
                "risk_free_rate": rate,
                "volatility": volatility,
                "multiplier": multiplier,
                "commission_rate": commission_rate,
            },
            "comparison": {
                "baseline_index": baseline_index,
                "baseline_name": baseline_name,
            },
            "strategies": [
                {"name": name, "summary": _summary(report)}
                for name, report in zip(names, reports, strict=True)
            ],
            "expiry_curve": {
                "spot": _rounded_array(spots),
                "pnl": {
                    name: _rounded_array(report.payoff)
                    for name, report in zip(names, reports, strict=True)
                },
                "delta_to_baseline": {
                    name: _rounded_array(values)
                    for name, values in expiry_delta.items()
                },
            },
            "scenario_grid": {
                "iv_values": _rounded_array(iv_values),
                "spot": _rounded_array(spots),
                "pnl": {
                    name: [
                        _rounded_array(row) for row in np.asarray(scenario, dtype=float)
                    ]
                    for name, scenario in zip(names, scenarios, strict=True)
                },
                "delta_to_baseline": {
                    name: [
                        _rounded_array(row) for row in np.asarray(values, dtype=float)
                    ]
                    for name, values in scenario_delta.items()
                },
            },
            "limitations": [
                "European Black-Scholes marks with constant rate and volatility per scenario.",
                "No dividends, early exercise, assignment, slippage, or margin model.",
                "Scenario P&L is mark-to-market and does not deduct a hypothetical exit commission.",
                "Comparison is descriptive and does not rank or recommend a strategy.",
            ],
        }
        try:
            return json.dumps(
                payload, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        except ValueError as exc:
            return _error(f"non-serializable numeric result: {exc}")


def _coerce_strategies(raw: Any) -> list[tuple[str, list[OptionLeg]]]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("strategies must contain at least two entries")
    if len(raw) > _MAX_STRATEGIES:
        raise ValueError(f"strategies may contain at most {_MAX_STRATEGIES} entries")
    result: list[tuple[str, list[OptionLeg]]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"strategies[{index}] must be an object")
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"strategies[{index}].name must be a non-empty string")
        name = raw_name.strip()
        if len(name) > 64:
            raise ValueError(
                f"strategies[{index}].name must contain at most 64 characters"
            )
        if name.casefold() in seen:
            raise ValueError("strategy names must be unique")
        seen.add(name.casefold())
        result.append((name, _coerce_legs(item.get("legs"))))
    return result


def _baseline_index(raw: Any, strategy_count: int) -> int:
    if raw is None or raw == "":
        return 0
    if isinstance(raw, bool):
        raise ValueError("baseline_index must be an integer")
    try:
        numeric = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("baseline_index must be an integer") from exc
    if not np.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("baseline_index must be an integer")
    index = int(numeric)
    if not 0 <= index < strategy_count:
        raise ValueError(f"baseline_index must be between 0 and {strategy_count - 1}")
    return index


def _summary(report: Any) -> dict[str, Any]:
    return {
        "net_premium": _rounded(report.net_premium),
        "entry_commission": _rounded(report.entry_commission),
        "entry_cost": _rounded(report.entry_cost),
        "entry_side": (
            "flat"
            if abs(report.entry_cost) <= 1e-12
            else "debit" if report.entry_cost > 0 else "credit"
        ),
        "breakevens": [_rounded(value) for value in report.breakevens],
        "breakeven_intervals": [
            {"start": _rounded(start), "end": None if end is None else _rounded(end)}
            for start, end in report.breakeven_intervals
        ],
        "max_profit": None if report.profit_unbounded else _rounded(report.max_profit),
        "max_loss": None if report.loss_unbounded else _rounded(report.max_loss),
        "profit_unbounded": report.profit_unbounded,
        "loss_unbounded": report.loss_unbounded,
    }


def _error(message: str) -> str:
    return json.dumps(
        {"status": "error", "tool": "options_strategy_compare", "error": message},
        ensure_ascii=False,
    )
