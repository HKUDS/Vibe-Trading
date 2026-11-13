"""Agent tool for deterministic multi-leg option payoff analysis."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from backtest.options_payoff import OptionLeg, expiry_payoff, scenario_grid
from src.agent.tools import BaseTool
from src.quantlib.units import compare_rates

_MAX_LEGS = 20
_MIN_SPOT_POINTS = 21
_MAX_SPOT_POINTS = 501
_DEFAULT_SPOT_POINTS = 121
_MAX_IV_SCENARIOS = 9
_MAX_ALTERNATIVES = 5


_LEGS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": _MAX_LEGS,
    "description": (
        "Signed option legs. Positive qty is long; negative qty is "
        "short. Omit premium to price that leg with Black-Scholes."
    ),
    "items": {
        "type": "object",
        "properties": {
            "option_type": {"type": "string", "enum": ["call", "put"]},
            "strike": {"type": "number", "exclusiveMinimum": 0},
            "qty": {"type": "integer"},
            "premium": {
                "type": "number",
                "minimum": 0,
                "description": "Optional per-share entry premium.",
            },
        },
        "required": ["option_type", "strike", "qty"],
    },
}


class OptionsPayoffTool(BaseTool):
    """Analyze expiry payoff and spot/IV scenarios for an option strategy."""

    name = "options_payoff"
    description = (
        "Analyze a European multi-leg option strategy using deterministic "
        "piecewise-linear expiry math and Black-Scholes spot/IV scenarios. "
        "Returns entry debit/credit and commission, analytic breakevens, "
        "bounded or unbounded max profit/loss, an expiry payoff curve, and a "
        "scenario P&L matrix. Pass label and alternatives=[{label, legs}, ...] to calculate "
        "multiple strategies AND their cap/floor/cost comparisons in one call, with shared "
        "entry price, stock position, expiry and fees. No separate comparison call is needed. "
        "Use expiry_spot_values for exact scenario prices and their "
        "expiry P&L/returns rather than estimating from the chart. Set underlying_qty=1 for a covered collar/covered call "
        "(shares = underlying_qty * multiplier); default 0 analyzes only options. Research only; does not place orders."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "legs": _LEGS_SCHEMA,
            "label": {"type": "string", "description": "Name of the base strategy, e.g. A.", "default": "base"},
            "alternatives": {
                "type": "array",
                "maxItems": _MAX_ALTERNATIVES,
                "description": "Other named option-leg sets on the same stock position and pricing assumptions. "
                "Each is calculated and compared with the base in this call.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "legs": _LEGS_SCHEMA,
                    },
                    "required": ["label", "legs"],
                    "additionalProperties": False,
                },
            },
            "entry_spot": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Underlying spot at entry.",
            },
            "underlying_qty": {
                "type": "number",
                "default": 0,
                "description": "Signed stock units per multiplier. 1 means 100 shares with multiplier=100. Included in P&L and bounds.",
            },
            "price_as_of": {
                "type": "string",
                "description": "Observation date of entry_spot; label assumptions if not a live quote.",
            },
            "expiry_days": {
                "type": "number",
                "minimum": 0,
                "description": "Calendar days remaining to expiry.",
            },
            "risk_free_rate": {
                "type": "number",
                "default": 0.05,
                "description": "Annual continuously compounded risk-free rate.",
            },
            "volatility": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 0.3,
                "description": "Annualized entry volatility, e.g. 0.3 for 30%.",
            },
            "multiplier": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 1.0,
                "description": "Currency multiplier per option price unit.",
            },
            "commission_rate": {
                "type": "number",
                "minimum": 0,
                "exclusiveMaximum": 1,
                "default": 0.001,
                "description": "Entry commission fraction, aligned with the backtest engine.",
            },
            "spot_min": {
                "type": "number",
                "minimum": 0,
                "description": "Optional lower chart/scenario spot bound.",
            },
            "spot_max": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Optional upper chart/scenario spot bound.",
            },
            "spot_points": {
                "type": "integer",
                "minimum": _MIN_SPOT_POINTS,
                "maximum": _MAX_SPOT_POINTS,
                "default": _DEFAULT_SPOT_POINTS,
            },
            "expiry_spot_values": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_SPOT_POINTS,
                "items": {"type": "number", "minimum": 0},
                "description": "Exact underlying prices at expiry for compact P&L and return rows. "
                "Prices may lie outside the display grid. Return uses absolute entry stock notional; "
                "options-only strategies have no stock denominator and return null.",
            },
            "scenario_iv_values": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_IV_SCENARIOS,
                "items": {"type": "number", "exclusiveMinimum": 0},
                "description": (
                    "Optional annualized IV scenarios. Defaults to 50%, 75%, 100%, 125%, and 150% of entry volatility."
                ),
            },
        },
        "required": ["legs", "entry_spot", "expiry_days"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Calculate the base and optional alternatives with one shared basis.

        Args:
            **kwargs: Single-strategy inputs plus named alternative leg sets.

        Returns:
            Original payoff envelope, with per-alternative results and automatic
            comparisons when requested. A failed alternative does not discard
            successful calculations.
        """
        label = kwargs.get("label", "base")
        alternatives = kwargs.get("alternatives", [])
        if alternatives is None:
            alternatives = []
        if not isinstance(label, str) or not label.strip():
            return _error("label must be a nonempty string")
        if not isinstance(alternatives, list) or len(alternatives) > _MAX_ALTERNATIVES:
            return _error(f"alternatives must be an array of at most {_MAX_ALTERNATIVES} named leg sets")
        labels = {label}
        for alternative in alternatives:
            if not isinstance(alternative, dict) or set(alternative) != {"label", "legs"}:
                return _error("Each alternative needs label and legs only; pricing assumptions are shared")
            name = alternative["label"]
            if not isinstance(name, str) or not name.strip() or name in labels:
                return _error("Strategy labels must be nonempty and distinct")
            labels.add(name)
        result = json.loads(self._execute_single(**kwargs))
        if not alternatives or result.get("status") != "ok":
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        result.update(label=label, alternatives=[], comparisons=[])
        for alternative in alternatives:
            calculated = json.loads(self._execute_single(**{**kwargs, "legs": alternative["legs"]}))
            result["alternatives"].append({"label": alternative["label"], **calculated})
            result["comparisons"].append(_compare_payoffs(result, calculated, label, alternative["label"]))
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    def _execute_single(self, **kwargs: Any) -> str:
        """Run payoff and scenario analysis.

        Args:
            **kwargs: Inputs described by :attr:`parameters`.

        Returns:
            JSON envelope with summary, expiry curve, scenario grid, and model
            limitations. Invalid inputs return a JSON error envelope.
        """
        try:
            legs = _coerce_legs(kwargs.get("legs"))
            entry_spot = _required_float(kwargs, "entry_spot")
            underlying_qty = _optional_float(kwargs, "underlying_qty", 0.0)
            expiry_days = _required_float(kwargs, "expiry_days")
            rate = _optional_float(kwargs, "risk_free_rate", 0.05)
            volatility = _optional_float(kwargs, "volatility", 0.3)
            multiplier = _optional_float(kwargs, "multiplier", 1.0)
            commission_rate = _optional_float(kwargs, "commission_rate", 0.001)
            spot_points = _spot_points(kwargs.get("spot_points"))
            spot_min, spot_max = _spot_bounds(kwargs, legs, entry_spot)
            iv_values = _scenario_ivs(kwargs.get("scenario_iv_values"), volatility)

            exact_spots = kwargs.get("expiry_spot_values")
            if exact_spots is not None:
                if not isinstance(exact_spots, (list, tuple)) or not 1 <= len(exact_spots) <= _MAX_SPOT_POINTS:
                    raise ValueError(f"expiry_spot_values must contain 1 to {_MAX_SPOT_POINTS} prices")
                if any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                    for v in exact_spots
                ):
                    raise ValueError("expiry_spot_values must contain non-negative finite prices")
            display_spots = np.linspace(spot_min, spot_max, spot_points)
            # One engine call prices both the display grid and the requested
            # scenarios; no second payoff formula or interpolation path.
            spots = np.concatenate((display_spots, exact_spots or []))
            time_to_expiry = expiry_days / 365.0
            report = expiry_payoff(
                legs,
                spots,
                entry_spot=entry_spot,
                time_to_expiry=time_to_expiry,
                rate=rate,
                iv=volatility,
                multiplier=multiplier,
                commission_rate=commission_rate,
                underlying_qty=underlying_qty,
            )
            scenarios = scenario_grid(
                legs,
                display_spots,
                iv_values,
                entry_spot=entry_spot,
                time_to_expiry=time_to_expiry,
                rate=rate,
                entry_iv=volatility,
                multiplier=multiplier,
                commission_rate=commission_rate,
                underlying_qty=underlying_qty,
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return _error(str(exc))

        denominator = abs(underlying_qty * multiplier * entry_spot)
        expiry_scenarios = [
            {
                "spot": float(spot),
                "pnl": float(pnl),
                "return_fraction": float(pnl / denominator) if denominator else None,
                "return_percent": float(pnl / denominator * 100) if denominator else None,
            }
            for spot, pnl in zip(report.spot_grid[spot_points:], report.payoff[spot_points:])
        ]
        payload = {
            "status": "ok",
            "tool": self.name,
            "inputs": {
                "legs": [
                    {
                        "option_type": leg.option_type,
                        "strike": leg.strike,
                        "qty": leg.qty,
                        "premium": leg.premium,
                    }
                    for leg in legs
                ],
                "entry_spot": entry_spot,
                "underlying_qty": underlying_qty,
                "price_as_of": kwargs.get("price_as_of"),
                "expiry_spot_values": exact_spots,
                "expiry_days": expiry_days,
                "risk_free_rate": rate,
                "volatility": volatility,
                "multiplier": multiplier,
                "commission_rate": commission_rate,
            },
            "calculation_basis": {
                "entry_spot": entry_spot,
                "price_as_of": kwargs.get("price_as_of"),
                "underlying_shares": underlying_qty * multiplier,
                "option_entry_cost_including_commission": report.entry_cost,
                "return_denominator": abs(underlying_qty * multiplier * entry_spot),
                "entry_cost_return": report.entry_cost / denominator if denominator else None,
                "return_convention": "P&L / absolute entry stock notional; not return on total cash invested",
                "max_profit_return": (
                    report.max_profit / abs(underlying_qty * multiplier * entry_spot)
                    if underlying_qty and not report.profit_unbounded
                    else None
                ),
                "max_loss_return": (
                    report.max_loss / abs(underlying_qty * multiplier * entry_spot)
                    if underlying_qty and not report.loss_unbounded
                    else None
                ),
            },
            "summary": {
                "net_premium": _rounded(report.net_premium),
                "entry_commission": _rounded(report.entry_commission),
                "entry_cost": _rounded(report.entry_cost),
                "entry_side": (
                    "flat" if abs(report.entry_cost) <= 1e-12 else "debit" if report.entry_cost > 0 else "credit"
                ),
                "breakevens": [_rounded(value) for value in report.breakevens],
                "breakeven_intervals": [
                    {
                        "start": _rounded(start),
                        "end": None if end is None else _rounded(end),
                    }
                    for start, end in report.breakeven_intervals
                ],
                "max_profit": (None if report.profit_unbounded else _rounded(report.max_profit)),
                "max_loss": (None if report.loss_unbounded else _rounded(report.max_loss)),
                "profit_unbounded": report.profit_unbounded,
                "loss_unbounded": report.loss_unbounded,
            },
            "expiry_scenarios": expiry_scenarios,
            "expiry_curve": {
                "spot": _rounded_array(display_spots),
                "pnl": _rounded_array(report.payoff[:spot_points]),
            },
            "scenario_grid": {
                "iv_values": _rounded_array(iv_values),
                "spot": _rounded_array(display_spots),
                "pnl": [_rounded_array(row) for row in np.asarray(scenarios, dtype=float)],
            },
            "limitations": [
                "European Black-Scholes marks with constant rate and volatility per scenario.",
                "No dividends, early exercise, assignment, slippage, stock fees, funding, or margin model.",
                "Scenario P&L is mark-to-market and does not deduct a hypothetical exit commission.",
            ],
        }
        try:
            return json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except ValueError as exc:
            # Extreme finite inputs (e.g. a ~1e308 multiplier) overflow to inf
            # in the results; report that instead of raising out of execute().
            return _error(f"non-serializable numeric result: {exc}")


def _compare_payoffs(base: dict, alternative: dict, base_label: str, label: str) -> dict:
    """Compare computed stock-notional returns; higher does not mean better."""
    comparison = {"left_label": label, "right_label": base_label, "operation": "alternative - base"}
    if alternative.get("status") != "ok":
        return {**comparison, "status": "unavailable", "reason": alternative.get("error", "Calculation failed")}
    lhs, rhs = alternative["calculation_basis"], base["calculation_basis"]
    if not rhs["return_denominator"]:
        return {**comparison, "status": "unavailable", "reason": "No entry stock notional for rate comparison"}
    metrics = {}
    for field in ("max_profit_return", "max_loss_return", "entry_cost_return"):
        left, right = lhs[field], rhs[field]
        if left is None or right is None:
            metrics[field] = {"status": "unavailable", "reason": "Unbounded payoff has no finite return"}
            continue
        compared = compare_rates(left, right)
        metrics[field] = {
            key: compared[key] for key in ("left_decimal", "right_decimal", "relation", "difference_percentage_points")
        }
    return {**comparison, "status": "ok", "metrics": metrics}


def _coerce_legs(raw: Any) -> list[OptionLeg]:
    """Parse and validate raw JSON-style leg objects."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("legs must be a non-empty array")
    if len(raw) > _MAX_LEGS:
        raise ValueError(f"legs may contain at most {_MAX_LEGS} entries")

    legs: list[OptionLeg] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"legs[{index}] must be an object")
        option_type = str(item.get("option_type") or "").strip().lower()
        try:
            strike = float(item["strike"])
            raw_qty = item["qty"]
            qty_number = float(raw_qty)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"legs[{index}] has invalid strike or qty: {exc}") from exc
        if isinstance(raw_qty, bool) or not qty_number.is_integer():
            raise ValueError(f"legs[{index}].qty must be a non-zero integer")
        qty = int(qty_number)
        raw_premium = item.get("premium")
        try:
            premium = None if raw_premium is None else float(raw_premium)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"legs[{index}].premium must be numeric or null") from exc
        legs.append(OptionLeg(option_type, strike, qty, premium))
    return legs


def _required_float(kwargs: dict[str, Any], name: str) -> float:
    """Read a required finite float."""
    if name not in kwargs or kwargs[name] is None or kwargs[name] == "":
        raise ValueError(f"{name} is required")
    try:
        value = float(kwargs[name])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _optional_float(kwargs: dict[str, Any], name: str, default: float) -> float:
    """Read an optional finite float, treating null and empty text as omitted."""
    raw = kwargs.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _spot_points(raw: Any) -> int:
    """Validate the bounded display-grid size."""
    if raw is None or raw == "":
        return _DEFAULT_SPOT_POINTS
    if isinstance(raw, bool):
        raise ValueError("spot_points must be an integer")
    try:
        numeric = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("spot_points must be an integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("spot_points must be an integer")
    points = int(numeric)
    if not _MIN_SPOT_POINTS <= points <= _MAX_SPOT_POINTS:
        raise ValueError(f"spot_points must be between {_MIN_SPOT_POINTS} and {_MAX_SPOT_POINTS}")
    return points


def _spot_bounds(kwargs: dict[str, Any], legs: list[OptionLeg], entry_spot: float) -> tuple[float, float]:
    """Resolve explicit chart bounds or safe defaults covering every strike."""
    reference = [entry_spot, *(leg.strike for leg in legs)]
    default_min = max(min(reference) * 0.5, 0.0)
    default_max = max(reference) * 1.5
    spot_min = _optional_float(kwargs, "spot_min", default_min)
    spot_max = _optional_float(kwargs, "spot_max", default_max)
    if spot_min < 0:
        raise ValueError("spot_min must be non-negative")
    if spot_max <= spot_min:
        raise ValueError("spot_max must be greater than spot_min")
    return spot_min, spot_max


def _scenario_ivs(raw: Any, entry_iv: float) -> np.ndarray:
    """Resolve bounded explicit IV scenarios or the skill's five defaults."""
    if raw is None:
        values = [
            entry_iv * 0.5,
            entry_iv * 0.75,
            entry_iv,
            entry_iv * 1.25,
            entry_iv * 1.5,
        ]
    else:
        if not isinstance(raw, list) or not raw:
            raise ValueError("scenario_iv_values must be a non-empty array")
        if len(raw) > _MAX_IV_SCENARIOS:
            raise ValueError(f"scenario_iv_values may contain at most {_MAX_IV_SCENARIOS} entries")
        try:
            values = [float(value) for value in raw]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("scenario_iv_values must contain numbers") from exc
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all() or (array <= 0).any():
        raise ValueError("scenario_iv_values must contain positive finite values")
    return array


def _rounded(value: float) -> float:
    """Round a finite scalar for stable, compact JSON."""
    return round(float(value), 6)


def _rounded_array(values: np.ndarray) -> list[float]:
    """Round a numeric array for stable, compact JSON."""
    return [round(float(value), 6) for value in np.asarray(values).tolist()]


def _error(message: str) -> str:
    """Build a stable error envelope."""
    return json.dumps(
        {"status": "error", "tool": "options_payoff", "error": message},
        ensure_ascii=False,
    )
