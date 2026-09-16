"""Read-only sensitivity grid for the current Asistente Casa portfolio.

Fetches canonical persisted history once, then compares optimizer targets across
lookbacks, per-name caps and turnover penalties.  This module never places
orders and never calls generic market-data/Yahoo for Asistente Casa holdings.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import numpy as np

from src.agent.tools import BaseTool
from src.portfolio.service import PortfolioService
from src.tools.portfolio_optimizer_tool import (
    _ALLOWED_OPTIMIZERS,
    _finite_float,
    _history_closes,
    _target_weights,
)

_DEFAULT_OPTIMIZERS = ("equal_volatility", "risk_parity", "turnover_aware")
_DEFAULT_LOOKBACKS = (30, 60, 90, 120)
_DEFAULT_MAX_WEIGHTS = (None, 0.15, 0.12, 0.10)
_DEFAULT_TURNOVER_PENALTIES = (0.0, 0.001, 0.005, 0.01, 0.05)
_MAX_GRID_SCENARIOS = 120


def _list_arg(raw: Any, default: Sequence[Any], field: str) -> list[Any]:
    if raw is None:
        return list(default)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{field} must be a non-empty array")
    return list(raw)


def _current_invested_holdings() -> tuple[list[str], np.ndarray, float]:
    context = PortfolioService().analysis_context()
    if not isinstance(context, Mapping):
        raise ValueError("no current Portfolio snapshot; refresh Portfolio first")
    native = context.get("holdings_native")
    rows = native.get("ARS") if isinstance(native, Mapping) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("current ARS holdings are unavailable")

    symbols: list[str] = []
    values: list[float] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        value = _finite_float(row.get("market_value_native"), f"{symbol}.market_value_native")
        if value <= 0:
            continue
        if symbol in seen:
            raise ValueError(f"duplicate current symbol is ambiguous: {symbol}")
        seen.add(symbol)
        symbols.append(symbol)
        values.append(value)
    if len(symbols) < 2:
        raise ValueError("at least two positive current holdings are required")
    value_array = np.asarray(values, dtype=float)
    invested = float(value_array.sum())
    if not np.isfinite(invested) or invested <= 0:
        raise ValueError("current invested value is invalid")
    return symbols, value_array / invested, invested


def _scenario_metrics(
    symbols: list[str],
    current: np.ndarray,
    target: np.ndarray,
    *,
    invested_value: float,
) -> dict[str, Any]:
    delta = target - current
    turnover = 0.5 * float(np.abs(delta).sum())
    hhi = float(np.square(target).sum())
    order = np.argsort(target)[::-1]
    max_buy_idx = int(np.argmax(delta))
    max_sell_idx = int(np.argmin(delta))
    return {
        "top1_weight": float(target[order[0]]),
        "top3_weight": float(target[order[:3]].sum()),
        "hhi": hhi,
        "effective_n": (1.0 / hhi) if hhi > 0 else None,
        "positions_over_1pct": int((target > 0.01).sum()),
        "positions_effectively_zero": int((target < 1e-8).sum()),
        "estimated_turnover": turnover,
        "max_abs_delta_weight": float(np.abs(delta).max()),
        "changes_over_1pct": int((np.abs(delta) > 0.01).sum()),
        "largest_buy": {
            "symbol": symbols[max_buy_idx],
            "delta_weight": float(delta[max_buy_idx]),
            "delta_value_ars": float(delta[max_buy_idx] * invested_value),
        },
        "largest_sell": {
            "symbol": symbols[max_sell_idx],
            "delta_weight": float(delta[max_sell_idx]),
            "delta_value_ars": float(delta[max_sell_idx] * invested_value),
        },
    }


class PortfolioOptimizerSensitivityTool(BaseTool):
    """Compare current-portfolio optimizer outputs across parameter choices."""

    name = "portfolio_optimize_sensitivity"
    description = (
        "Read-only sensitivity analysis for the current Asistente Casa ARS portfolio. "
        "Compares optimizer target weights across lookbacks, optional per-name caps, "
        "and turnover penalties using one canonical persisted-history fetch. Returns "
        "stability/concentration/turnover diagnostics only; never places orders. "
        "Default optimizers are equal_volatility, risk_parity and turnover_aware."
    )
    parameters = {
        "type": "object",
        "properties": {
            "optimizers": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(_ALLOWED_OPTIMIZERS)},
                "description": "Optimizer names. Defaults to equal_volatility, risk_parity, turnover_aware.",
            },
            "lookbacks": {
                "type": "array",
                "items": {"type": "integer", "minimum": 30, "maximum": 120},
                "description": "Daily return windows; default [30,60,90,120].",
            },
            "max_weights": {
                "type": "array",
                "items": {"type": ["number", "null"]},
                "description": "Per-name caps; default [null,0.15,0.12,0.10].",
            },
            "turnover_penalties": {
                "type": "array",
                "items": {"type": "number", "minimum": 0.0},
                "description": "Only used by turnover_aware; default [0,0.001,0.005,0.01,0.05].",
            },
            "risk_aversion": {"type": "number", "minimum": 0.0},
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        try:
            return json.dumps(
                {"status": "ok", "data": self._run(**kwargs)},
                ensure_ascii=False,
                allow_nan=False,
            )
        except Exception as exc:
            return json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                allow_nan=False,
            )

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        optimizers = [str(x).strip().lower() for x in _list_arg(
            kwargs.get("optimizers"), _DEFAULT_OPTIMIZERS, "optimizers"
        )]
        if len(set(optimizers)) != len(optimizers):
            raise ValueError("optimizers must not contain duplicates")
        unknown = sorted(set(optimizers) - _ALLOWED_OPTIMIZERS)
        if unknown:
            raise ValueError("unsupported optimizers: " + ", ".join(unknown))

        lookbacks = [int(x) for x in _list_arg(
            kwargs.get("lookbacks"), _DEFAULT_LOOKBACKS, "lookbacks"
        )]
        if len(set(lookbacks)) != len(lookbacks) or any(x < 30 or x > 120 for x in lookbacks):
            raise ValueError("lookbacks must be unique integers between 30 and 120")

        raw_caps = _list_arg(kwargs.get("max_weights"), _DEFAULT_MAX_WEIGHTS, "max_weights")
        caps: list[float | None] = []
        for raw in raw_caps:
            if raw is None:
                caps.append(None)
                continue
            cap = _finite_float(raw, "max_weight")
            if not 0.0 < cap <= 1.0:
                raise ValueError("max_weights entries must be null or in (0,1]")
            caps.append(cap)
        if len({"none" if x is None else x for x in caps}) != len(caps):
            raise ValueError("max_weights must not contain duplicates")

        penalties = [
            _finite_float(x, "turnover_penalty")
            for x in _list_arg(
                kwargs.get("turnover_penalties"),
                _DEFAULT_TURNOVER_PENALTIES,
                "turnover_penalties",
            )
        ]
        if any(x < 0 for x in penalties) or len(set(penalties)) != len(penalties):
            raise ValueError("turnover_penalties must be unique non-negative numbers")
        risk_aversion = _finite_float(kwargs.get("risk_aversion", 1.0), "risk_aversion")
        if risk_aversion < 0:
            raise ValueError("risk_aversion must be non-negative")

        scenario_count = sum(
            len(lookbacks) * len(caps) * (len(penalties) if opt == "turnover_aware" else 1)
            for opt in optimizers
        )
        if scenario_count > _MAX_GRID_SCENARIOS:
            raise ValueError(
                f"sensitivity grid has {scenario_count} scenarios; cap is {_MAX_GRID_SCENARIOS}"
            )

        symbols, current, invested_value = _current_invested_holdings()
        current_weights = {symbol: float(current[i]) for i, symbol in enumerate(symbols)}
        for cap in caps:
            if cap is not None and cap * len(symbols) < 1.0 - 1e-12:
                raise ValueError(
                    f"max_weight={cap} is infeasible for {len(symbols)} active instruments"
                )

        max_lookback = max(lookbacks)
        closes = _history_closes(symbols, lookback=max_lookback)
        scenarios: list[dict[str, Any]] = []
        failed_scenarios: list[dict[str, Any]] = []
        targets: dict[tuple[str, int, float | None, float], np.ndarray] = {}

        for optimizer in optimizers:
            opt_penalties = penalties if optimizer == "turnover_aware" else [0.0]
            for lookback in lookbacks:
                window = closes.tail(lookback + 1)
                returns = window.pct_change(fill_method=None).dropna(how="any")
                if len(returns) != lookback:
                    raise ValueError(
                        f"{lookback}-day scenario has {len(returns)} aligned returns"
                    )
                for cap in caps:
                    for penalty in opt_penalties:
                        key = (optimizer, lookback, cap, penalty)
                        try:
                            target = _target_weights(
                                returns,
                                optimizer=optimizer,
                                current_weights=current_weights,
                                max_weight=cap,
                                risk_aversion=risk_aversion,
                                turnover_penalty=penalty,
                            )
                        except Exception as exc:
                            failed_scenarios.append({
                                "optimizer": optimizer,
                                "lookback": lookback,
                                "max_weight": cap,
                                "turnover_penalty": penalty if optimizer == "turnover_aware" else None,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            })
                            continue
                        targets[key] = target
                        metrics = _scenario_metrics(
                            symbols, current, target, invested_value=invested_value
                        )
                        scenarios.append({
                            "optimizer": optimizer,
                            "lookback": lookback,
                            "max_weight": cap,
                            "turnover_penalty": penalty if optimizer == "turnover_aware" else None,
                            **metrics,
                        })

        # Stability is measured against each optimizer's unconstrained 60-day
        # target.  If 60 was not requested, use the closest requested lookback.
        stability: list[dict[str, Any]] = []
        for optimizer in optimizers:
            baseline_lb = min(lookbacks, key=lambda x: (abs(x - 60), x))
            baseline_penalty = 0.0
            baseline_key = (optimizer, baseline_lb, None, baseline_penalty)
            baseline = targets.get(baseline_key)
            if baseline is None:
                # A custom grid may omit the uncapped scenario, or that
                # scenario may itself have failed to converge. Fall back to
                # the nearest successful target for this optimizer; if none
                # succeeded, omit stability rows for it (its failures remain
                # explicit in failed_scenarios).
                candidates = [
                    (key, target) for key, target in targets.items()
                    if key[0] == optimizer
                ]
                if not candidates:
                    continue
                baseline_key, baseline = min(
                    candidates,
                    key=lambda item: (
                        abs(item[0][1] - baseline_lb),
                        item[0][2] is not None,
                        item[0][3],
                        item[0][2] if item[0][2] is not None else -1.0,
                    ),
                )
            for key, target in targets.items():
                if key[0] != optimizer:
                    continue
                distance = 0.5 * float(np.abs(target - baseline).sum())
                stability.append({
                    "optimizer": optimizer,
                    "lookback": key[1],
                    "max_weight": key[2],
                    "turnover_penalty": key[3] if optimizer == "turnover_aware" else None,
                    "distance_from_baseline": distance,
                    "baseline": {
                        "lookback": baseline_key[1],
                        "max_weight": baseline_key[2],
                        "turnover_penalty": baseline_key[3] if optimizer == "turnover_aware" else None,
                    },
                })

        return {
            "currency": "ARS",
            "scope": "invested_sleeve",
            "cash_policy": "excluded_unchanged",
            "history_source": "asistente-casa-persisted-only",
            "history_fetch_count_expected": 1,
            "invested_value_ars": invested_value,
            "position_count": len(symbols),
            "shared_history_first": str(closes.index[0].date()),
            "shared_history_last": str(closes.index[-1].date()),
            "max_lookback": max_lookback,
            "scenario_count": scenario_count,
            "successful_scenario_count": len(scenarios),
            "failed_scenario_count": len(failed_scenarios),
            "scenarios": scenarios,
            "failed_scenarios": failed_scenarios,
            "stability": stability,
            "sector_constraints": {
                "status": "deferred",
                "reason": "canonical sector metadata is not present in the current lightweight Portfolio contract",
            },
        }
