"""Portfolio risk x-ray: concentration, volatility, drawdown, tail risk, and
co-movement for a weighted basket, computed from close-price panels.

This is the Portfolio Studio risk-x-ray backend (roadmap slice). Everything
here is a pure function of prices and weights — no I/O, no network, no
loader imports — so the same computation serves the agent tool, the API,
and tests. Data fetching lives in the caller.

Conventions:
- Long-only v1: negative weights are rejected up front rather than silently
  mis-computing concentration (a short leg is a different feature).
- Non-finite inputs are never trusted and non-finite outputs are never
  emitted: every reported float passes through ``_finite`` so the result
  survives ``json.dumps(..., allow_nan=False)``.
- Look-ahead is structurally impossible: all statistics are computed over
  trailing returns only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from backtest.validation import _json_safe

MIN_HISTORY_DAYS = 30
PERIODS_PER_YEAR = 252
VAR_LEVELS = (0.95, 0.99)


def _finite(value: float | None) -> float | None:
    """Return ``value`` when finite, else ``None`` (strict-JSON safe)."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _validate_weights(
    closes: pd.DataFrame, weights: Mapping[str, float]
) -> tuple[dict[str, float], list[str]]:
    """Normalize weights to sum 1; reject unknown symbols and bad values.

    Returns the cleaned weight map (restricted to available columns) and any
    warnings worth surfacing to the caller.
    """
    warnings: list[str] = []
    if not weights:
        raise ValueError("weights must name at least one symbol")

    unknown = [sym for sym in weights if sym not in closes.columns]
    if unknown:
        raise ValueError(f"weights reference symbols with no price data: {sorted(unknown)}")

    cleaned: dict[str, float] = {}
    for sym, raw in weights.items():
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"weight for {sym!r} is not a number: {raw!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"weight for {sym!r} is not finite: {raw!r}")
        if value < 0:
            raise ValueError(
                f"weight for {sym!r} is negative ({value}); the risk x-ray is long-only for now"
            )
        cleaned[sym] = value

    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    if abs(total - 1.0) > 1e-6:
        warnings.append(f"weights summed to {total:.6f}; renormalized to 1.0")
        cleaned = {sym: value / total for sym, value in cleaned.items()}
    return cleaned, warnings


def compute_risk_xray(
    closes: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    periods_per_year: int = PERIODS_PER_YEAR,
    var_levels: Sequence[float] = VAR_LEVELS,
    min_history: int = MIN_HISTORY_DAYS,
) -> dict[str, Any]:
    """Compute the risk x-ray for a weighted basket.

    Args:
        closes: Close-price panel, one column per symbol, sorted by date.
        weights: Symbol → weight. Renormalized to 1.0 with a warning when the
            sum differs; must be long-only and reference existing columns.
        periods_per_year: Annualization factor for the bar interval.
        var_levels: Tail levels for historical VaR / expected shortfall.
        min_history: Minimum valid bars a symbol must have to be included.

    Returns:
        A strict-JSON-safe dict (``json.dumps(..., allow_nan=False)`` must
        never fail on it) with concentration, volatility, drawdown, tail
        risk, diversification, and correlation sections, plus ``skipped``
        and ``warnings`` bookkeeping.

    Raises:
        ValueError: On unusable input (empty panel, bad weights, or nothing
            left after the history filter / calendar alignment).
    """
    if closes is None or closes.empty:
        raise ValueError("price panel is empty")
    frame = closes.dropna(axis=1, how="all")
    if frame.empty:
        raise ValueError("price panel has no non-NaN closes")

    weights, warnings = _validate_weights(frame, weights)

    # History filter: thin symbols are excluded rather than allowed to skew
    # the whole x-ray on a handful of bars.
    kept: list[str] = []
    skipped: list[dict[str, str]] = []
    for sym in weights:
        valid = int(frame[sym].count())
        if valid < min_history:
            skipped.append({"symbol": sym, "reason": f"only {valid} valid bars (min {min_history})"})
        else:
            kept.append(sym)
    if not kept:
        raise ValueError(f"no symbol has at least {min_history} valid bars")
    if skipped:
        # Renormalize over the survivors so the x-ray still describes a
        # fully invested basket, and say so.
        kept_weights = {sym: weights[sym] for sym in kept}
        total = sum(kept_weights.values())
        if total <= 0:
            raise ValueError("surviving symbols have zero total weight")
        weights = {sym: value / total for sym, value in kept_weights.items()}
        warnings.append("weights renormalized over symbols that survived the history filter")

    aligned = frame[kept].dropna(axis=0, how="any")
    if len(aligned) < 2:
        raise ValueError(
            "fewer than 2 shared trading days after aligning calendars across symbols"
        )

    returns = aligned.pct_change(fill_method=None).dropna(how="any")
    if returns.empty:
        raise ValueError("no overlapping return observations across symbols")

    w = np.array([weights[sym] for sym in kept], dtype=float)
    port = returns.to_numpy(dtype=float) @ w
    port_returns = pd.Series(port, index=returns.index)

    result: dict[str, Any] = {
        "inputs": {
            "symbols": kept,
            "weights": {sym: round(float(weights[sym]), 8) for sym in kept},
            "aligned_days": int(len(aligned)),
            "return_observations": int(len(returns)),
            "first_date": str(aligned.index[0]),
            "last_date": str(aligned.index[-1]),
        },
        "concentration": _concentration(w),
        "volatility": _volatility(port_returns, periods_per_year),
        "drawdown": _drawdown(port_returns),
        "tail_risk": _tail_risk(port_returns, var_levels),
        "diversification": _diversification(returns, w, port_returns, periods_per_year),
        "correlation": _correlation(returns, port_returns),
        "skipped": skipped,
        "warnings": warnings,
    }
    return result


def _concentration(w: np.ndarray) -> dict[str, Any]:
    hhi = float(np.sum(w**2))
    order = np.argsort(w)[::-1]
    return {
        "hhi": _finite(hhi),
        "effective_n": _finite(1.0 / hhi) if hhi > 0 else None,
        "top1_weight": _finite(float(w[order[0]])) if len(order) else None,
        "top3_weight": _finite(float(w[order[:3]].sum())) if len(order) else None,
    }


def _volatility(port: pd.Series, ppy: int) -> dict[str, Any]:
    vol = float(port.std(ddof=1)) if len(port) > 1 else None
    downside = port[port < 0]
    downside_dev = float(downside.std(ddof=1)) if len(downside) > 1 else None
    return {
        "daily_vol": _finite(vol),
        "annualized_vol": _finite(vol * math.sqrt(ppy)) if vol is not None else None,
        "downside_deviation_annualized": (
            _finite(downside_dev * math.sqrt(ppy)) if downside_dev is not None else None
        ),
    }


def _drawdown(port: pd.Series) -> dict[str, Any]:
    if port.empty:
        return {"max_drawdown": None, "max_drawdown_start": None, "max_drawdown_trough": None}
    equity = (1.0 + port).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    trough_idx = dd.idxmin()
    start_idx = equity.loc[:trough_idx].idxmax()
    return {
        "max_drawdown": _finite(float(dd.loc[trough_idx])),
        "max_drawdown_start": str(start_idx),
        "max_drawdown_trough": str(trough_idx),
    }


def _tail_risk(port: pd.Series, levels: Sequence[float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    losses = -port.to_numpy(dtype=float)
    for level in levels:
        if len(losses) < 2:
            var = es = None
        else:
            var = float(np.quantile(losses, level))
            tail = losses[losses >= var]
            es = float(tail.mean()) if len(tail) else None
        key = f"{int(round(level * 100))}"
        out[f"var_{key}"] = _finite(var)
        out[f"expected_shortfall_{key}"] = _finite(es)
    out["method"] = "historical simulation (non-parametric)"
    return out


def _diversification(
    returns: pd.DataFrame, w: np.ndarray, port: pd.Series, ppy: int
) -> dict[str, Any]:
    if returns.shape[1] < 2:
        return {"diversification_ratio": None, "note": "needs at least 2 assets"}
    asset_vols = returns.std(ddof=1).to_numpy(dtype=float)
    port_vol = float(port.std(ddof=1)) if len(port) > 1 else 0.0
    if port_vol <= 0 or not math.isfinite(port_vol):
        return {"diversification_ratio": None, "note": "portfolio variance is zero"}
    ratio = float(np.dot(w, asset_vols) / port_vol)
    return {"diversification_ratio": _finite(ratio)}


def _correlation(returns: pd.DataFrame, port: pd.Series) -> dict[str, Any]:
    if returns.shape[1] < 2:
        return {
            "avg_pairwise_abs": None,
            "max_pair": None,
            "beta_to_equal_weight": None,
            "note": "needs at least 2 assets",
        }
    corr = returns.corr().to_numpy(dtype=float)
    n = corr.shape[0]
    off_diag = [abs(corr[i, j]) for i in range(n) for j in range(i + 1, n)]
    avg_pairwise = float(np.mean(off_diag)) if off_diag else None

    max_pair = None
    if off_diag:
        i, j = max(
            ((i, j) for i in range(n) for j in range(i + 1, n)),
            key=lambda pair: abs(corr[pair[0], pair[1]]),
        )
        max_pair = {
            "symbols": [str(returns.columns[i]), str(returns.columns[j])],
            "corr": _finite(float(corr[i, j])),
        }

    market = returns.mean(axis=1)
    market_var = float(market.var(ddof=1)) if len(market) > 1 else 0.0
    if market_var > 0 and math.isfinite(market_var):
        beta = float(port.cov(market) / market_var)
    else:
        beta = None

    return {
        "avg_pairwise_abs": _finite(avg_pairwise),
        "max_pair": max_pair,
        "beta_to_equal_weight": _finite(beta),
    }


def average_invested_weights(target_pos: pd.DataFrame) -> tuple[dict[str, float], float]:
    """Derive the run's average basket from the target position frame.

    Returns ``(weights, avg_invested)``: the mean target weight per symbol
    restricted to symbols the strategy actually held on average, and the mean
    row sum (how much of the book was invested at all). The final row alone
    would be the wrong object here, since many strategies end flat.

    Raises:
        ValueError: when the frame is empty, the strategy never held
            anything on average, or any symbol's average exposure is net
            short — ``compute_risk_xray`` is long-only, and silently
            x-raying just the long half of a long-short book would present
            a partial basket as the whole strategy.
    """
    if target_pos is None or target_pos.empty:
        raise ValueError("target position frame is empty")
    means = target_pos.mean(axis=0)
    short_book = [str(sym) for sym, w in means.items() if float(w) < 0]
    if short_book:
        raise ValueError(
            "long-only x-ray cannot describe net short average exposure "
            f"in {', '.join(short_book)}"
        )
    weights = {str(sym): float(w) for sym, w in means.items() if float(w) > 0}
    avg_invested = float(target_pos.sum(axis=1).mean())
    if not weights:
        raise ValueError("strategy held no average exposure")
    return weights, avg_invested


def render_risk_xray_markdown(report: dict[str, Any]) -> str:
    """Render an x-ray report as a compact Markdown summary."""
    inputs = report["inputs"]
    conc = report["concentration"]
    vol = report["volatility"]
    dd = report["drawdown"]
    tail = report["tail_risk"]
    lines = [
        "# Portfolio Risk X-Ray",
        "",
        f"- basket: {', '.join(inputs['symbols'])}",
        f"- window: {inputs['first_date']} .. {inputs['last_date']} "
        f"({inputs['aligned_days']} aligned days)",
    ]
    if conc.get("hhi") is not None:
        lines.append(
            f"- concentration: hhi {conc['hhi']:.4f}, "
            f"effective n {conc['effective_n']:.2f}, "
            f"top1 {conc['top1_weight']:.2%}, top3 {conc['top3_weight']:.2%}"
        )
    if vol.get("annualized_vol") is not None:
        lines.append(f"- annualized vol: {vol['annualized_vol']:.2%}")
    if dd.get("max_drawdown") is not None:
        lines.append(f"- max drawdown: {dd['max_drawdown']:.2%}")
    if tail.get("var_95") is not None:
        lines.append(
            f"- tail (historical): VaR95 {tail['var_95']:.2%}, ES95 {tail['expected_shortfall_95']:.2%}"
        )
    if report["skipped"]:
        joined = ", ".join(item["symbol"] for item in report["skipped"])
        lines.append(f"- skipped: {joined}")
    lines.append("")
    return "\n".join(lines)


def write_risk_xray(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Write the report to ``path`` as strict, RFC-8259 JSON.

    Same contract as ``write_rebalance_notes``: sanitize with ``_json_safe``
    and serialize with ``allow_nan=False``. Returns the sanitized payload.
    """
    safe_report = _json_safe(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(safe_report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return safe_report
