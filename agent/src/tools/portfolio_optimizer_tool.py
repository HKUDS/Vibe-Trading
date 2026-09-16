"""Read-only current-portfolio optimization for Asistente Casa.

Uses Vibe's existing optimizer math with canonical persisted Asistente Casa
history.  It returns advisory target weights and ARS rebalance deltas only.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backtest.constraints import MaxWeight
from backtest.optimizers.equal_volatility import EqualVolatilityOptimizer
from backtest.optimizers.max_diversification import MaxDiversificationOptimizer
from backtest.optimizers.mean_variance import MeanVarianceOptimizer
from backtest.optimizers.risk_parity import RiskParityOptimizer
from backtest.optimizers.turnover_aware import TurnoverAwareOptimizer
from src.agent.tools import BaseTool
from src.portfolio.service import PortfolioService
from src.tools.portfolio_risk_tool import _fetch_asistente_casa_history

_ALLOWED_OPTIMIZERS = {
    "equal_volatility",
    "risk_parity",
    "mean_variance",
    "max_diversification",
    "turnover_aware",
}
_MIN_LOOKBACK = 30
_MAX_LOOKBACK = 120


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, not boolean")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not np.isfinite(out):
        raise ValueError(f"{field} must be finite")
    return out


def _history_closes(
    symbols: list[str], *, lookback: int, history_fetcher=_fetch_asistente_casa_history
) -> pd.DataFrame:
    # Request a calendar buffer because the source contains trading-day EOD bars.
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(lookback * 3, 120))
    raw = history_fetcher(
        codes=symbols,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        interval="1D",
    )
    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        records = raw.get(symbol) if isinstance(raw, Mapping) else None
        if not isinstance(records, list) or not records:
            raise ValueError(f"canonical history missing for {symbol}")
        dates: list[pd.Timestamp] = []
        closes: list[float] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            try:
                dt = pd.Timestamp(record.get("date"))
                close = float(record.get("close"))
            except (TypeError, ValueError):
                continue
            if pd.isna(dt) or not np.isfinite(close) or close <= 0:
                continue
            dates.append(dt)
            closes.append(close)
        if not closes:
            raise ValueError(f"canonical history has no usable closes for {symbol}")
        series[symbol] = pd.Series(closes, index=dates, name=symbol).sort_index()

    panel = pd.DataFrame(series).sort_index().dropna(axis=0, how="any")
    if len(panel) < lookback + 1:
        raise ValueError(
            f"only {len(panel)} shared close observations; need at least {lookback + 1}"
        )
    return panel.tail(lookback + 1)


def _target_weights(
    returns: pd.DataFrame,
    *,
    optimizer: str,
    current_weights: dict[str, float],
    max_weight: float | None,
    risk_aversion: float,
    turnover_penalty: float,
) -> np.ndarray:
    symbols = list(returns.columns)
    cov = returns.cov().to_numpy(dtype=float)
    mu = returns.mean().to_numpy(dtype=float)
    if not np.isfinite(cov).all() or not np.isfinite(mu).all():
        raise ValueError("return moments contain non-finite values")

    if optimizer == "equal_volatility":
        instance = EqualVolatilityOptimizer(lookback=len(returns))
        target = instance._calc_weights({"vols": returns.std()})
    elif optimizer == "risk_parity":
        instance = RiskParityOptimizer(lookback=len(returns))
        target = instance._calc_weights({"cov": cov})
    elif optimizer == "mean_variance":
        # Keep upstream's zero risk-free default. Its risk_free argument is in
        # the same units as the input mean; accepting an annualized rate here
        # would create a silent daily/annual scale mismatch.
        instance = MeanVarianceOptimizer(lookback=len(returns), risk_free=0.0)
        target = instance._calc_weights({"cov": cov, "mu": mu})
    elif optimizer == "max_diversification":
        instance = MaxDiversificationOptimizer(lookback=len(returns))
        target = instance._calc_weights({"cov": cov})
    elif optimizer == "turnover_aware":
        instance = TurnoverAwareOptimizer(
            lookback=len(returns),
            risk_aversion=risk_aversion,
            turnover_penalty=turnover_penalty,
            max_per_name=max_weight,
        )
        # For a current-portfolio recommendation, the current invested weights
        # are the previous allocation against which turnover is penalized.
        instance._prev = dict(current_weights)
        target = instance._calc_weights({"cov": cov, "mu": mu, "active": symbols})
    else:  # guarded by caller, kept fail-closed for direct use
        raise ValueError(f"unsupported optimizer: {optimizer}")

    target = np.asarray(target, dtype=float)
    if target.shape != (len(symbols),) or not np.isfinite(target).all():
        raise RuntimeError("optimizer returned an invalid weight vector")
    target = np.maximum(target, 0.0)
    if max_weight is not None and optimizer != "turnover_aware":
        if max_weight * len(symbols) < 1.0 - 1e-12:
            raise ValueError(
                f"max_weight={max_weight} is infeasible for {len(symbols)} active instruments"
            )
        target = MaxWeight(max_weight).apply(target, symbols)
    total = float(target.sum())
    if total <= 0:
        raise RuntimeError("optimizer returned zero total weight")
    target = target / total
    if max_weight is not None and float(target.max()) > max_weight + 1e-7:
        raise RuntimeError("optimizer target violates max_weight")
    return target


class CurrentPortfolioOptimizerTool(BaseTool):
    """Suggest target weights for the current Asistente Casa invested sleeve."""

    name = "portfolio_optimize"
    description = (
        "Read-only portfolio optimization for the current Asistente Casa ARS portfolio. "
        "Uses canonical persisted daily history and Vibe's built-in optimizers to return "
        "advisory target weights plus ARS rebalance deltas. It never places orders, never "
        "uses Yahoo for Asistente Casa holdings, and leaves cash outside the optimized "
        "invested sleeve. Supported optimizers: equal_volatility, risk_parity, "
        "mean_variance, max_diversification, turnover_aware."
    )
    parameters = {
        "type": "object",
        "properties": {
            "optimizer": {
                "type": "string",
                "enum": sorted(_ALLOWED_OPTIMIZERS),
                "description": "Weighting method; risk_parity is a robust default without return forecasts.",
            },
            "lookback": {
                "type": "integer",
                "minimum": _MIN_LOOKBACK,
                "maximum": _MAX_LOOKBACK,
                "description": "Shared daily-return observations used for covariance/mean estimation (default 60).",
            },
            "max_weight": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "maximum": 1.0,
                "description": "Optional per-instrument target cap, e.g. 0.12 for 12%.",
            },
            "risk_aversion": {
                "type": "number",
                "minimum": 0.0,
                "description": "Turnover-aware variance penalty (default 1.0).",
            },
            "turnover_penalty": {
                "type": "number",
                "minimum": 0.0,
                "description": "Turnover-aware L1 penalty in daily-return units (default 0.0).",
            },
        },
        "required": ["optimizer"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        try:
            result = self._run(**kwargs)
            return json.dumps({"status": "ok", "data": result}, ensure_ascii=False, allow_nan=False)
        except Exception as exc:  # tool boundary must remain strict-JSON safe
            return json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                allow_nan=False,
            )

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        optimizer = str(kwargs.get("optimizer") or "").strip().lower()
        if optimizer not in _ALLOWED_OPTIMIZERS:
            raise ValueError(
                "optimizer must be one of: " + ", ".join(sorted(_ALLOWED_OPTIMIZERS))
            )
        lookback = int(kwargs.get("lookback") or 60)
        if not _MIN_LOOKBACK <= lookback <= _MAX_LOOKBACK:
            raise ValueError(f"lookback must be between {_MIN_LOOKBACK} and {_MAX_LOOKBACK}")

        max_weight_raw = kwargs.get("max_weight")
        max_weight = None
        if max_weight_raw is not None:
            max_weight = _finite_float(max_weight_raw, "max_weight")
            if not 0.0 < max_weight <= 1.0:
                raise ValueError("max_weight must be in (0, 1]")

        risk_aversion = _finite_float(kwargs.get("risk_aversion", 1.0), "risk_aversion")
        turnover_penalty = _finite_float(
            kwargs.get("turnover_penalty", 0.0), "turnover_penalty"
        )
        if risk_aversion < 0 or turnover_penalty < 0:
            raise ValueError("risk_aversion and turnover_penalty must be non-negative")

        context = PortfolioService().analysis_context()
        if not isinstance(context, Mapping):
            raise ValueError("no current Portfolio snapshot; refresh Portfolio first")
        native = context.get("holdings_native")
        rows = native.get("ARS") if isinstance(native, Mapping) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("current ARS holdings are unavailable")

        holdings: list[tuple[str, float]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            value = _finite_float(row.get("market_value_native"), f"{symbol or '?'}.market_value_native")
            if not symbol or value <= 0:
                continue
            if symbol in seen:
                raise ValueError(f"duplicate current symbol is ambiguous: {symbol}")
            seen.add(symbol)
            holdings.append((symbol, value))
        if len(holdings) < 2:
            raise ValueError("at least two positive current holdings are required")

        invested_value = float(sum(value for _, value in holdings))
        symbols = [symbol for symbol, _ in holdings]
        current_weights = {symbol: value / invested_value for symbol, value in holdings}

        closes = _history_closes(symbols, lookback=lookback)
        returns = closes.pct_change(fill_method=None).dropna(how="any")
        if len(returns) != lookback:
            raise ValueError(
                f"expected {lookback} aligned return observations, got {len(returns)}"
            )
        target = _target_weights(
            returns,
            optimizer=optimizer,
            current_weights=current_weights,
            max_weight=max_weight,
            risk_aversion=risk_aversion,
            turnover_penalty=turnover_penalty,
        )

        allocations: list[dict[str, Any]] = []
        for i, symbol in enumerate(symbols):
            current = float(current_weights[symbol])
            target_weight = float(target[i])
            target_value = target_weight * invested_value
            current_value = holdings[i][1]
            allocations.append(
                {
                    "symbol": symbol,
                    "current_weight_invested": current,
                    "target_weight_invested": target_weight,
                    "delta_weight": target_weight - current,
                    "current_value_ars": current_value,
                    "target_value_ars": target_value,
                    "delta_value_ars": target_value - current_value,
                }
            )
        allocations.sort(key=lambda row: (-abs(row["delta_weight"]), row["symbol"]))

        turnover = 0.5 * sum(abs(row["delta_weight"]) for row in allocations)
        warnings: list[str] = []
        if optimizer == "mean_variance":
            warnings.append(
                "mean_variance uses historical daily sample means and zero risk-free rate; "
                "it is input-sensitive and should be treated as a scenario, not a forecast"
            )
        if optimizer == "turnover_aware" and turnover_penalty == 0.0:
            warnings.append(
                "turnover_penalty is 0.0, so this run does not penalize allocation changes"
            )

        return {
            "optimizer": optimizer,
            "lookback_return_observations": lookback,
            "history_first_date": str(closes.index[0].date()),
            "history_last_date": str(closes.index[-1].date()),
            "history_source": "asistente-casa-persisted-only",
            "native_currency": "ARS",
            "scope": "invested_sleeve",
            "cash_policy": "cash excluded from optimization and left unchanged",
            "position_count": len(symbols),
            "invested_value_ars": invested_value,
            "current_weight_sum": float(sum(current_weights.values())),
            "target_weight_sum": float(target.sum()),
            "estimated_turnover": float(turnover),
            "max_weight": max_weight,
            "allocations": allocations,
            "warnings": warnings,
            "advisory_only": True,
            "orders_created": False,
        }
