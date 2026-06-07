"""Fixed evaluator for ztrade autoresearch candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.ztrade_autoresearch.protocol import DEFAULT_GATES, GateConfig


@dataclass(frozen=True)
class MetricRow:
    candidate_id: str
    window_id: str
    role: str
    start: str
    end: str
    return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    win_rate: float
    regime: str


@dataclass(frozen=True)
class GateVerdict:
    verdict: str
    score: float
    gates: dict[str, bool]
    reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def evaluate_candidate(
    rows: list[MetricRow],
    *,
    baseline_id: str,
    candidate_id: str,
    gates: GateConfig = DEFAULT_GATES,
    expected_window_count: int | None = None,
) -> GateVerdict:
    """Evaluate one candidate against baseline over fixed windows."""
    pairs = _paired_rows(rows, baseline_id=baseline_id, candidate_id=candidate_id)
    if not pairs:
        return GateVerdict(
            verdict="BLOCKED",
            score=0.0,
            gates={"coverage": False},
            reasons=["no paired baseline/candidate windows"],
        )

    deltas = [candidate.return_pct - baseline.return_pct for baseline, candidate in pairs]
    return_delta = sum(deltas)
    dd_delta = _avg([candidate.max_drawdown_pct for _, candidate in pairs]) - _avg(
        [baseline.max_drawdown_pct for baseline, _ in pairs]
    )
    loss_windows = sum(1 for delta in deltas if delta < 0)
    loss_window_ratio = loss_windows / len(pairs)
    bear_pairs = [(baseline, candidate) for baseline, candidate in pairs if candidate.regime == "bear"]
    bear_deltas = [candidate.return_pct - baseline.return_pct for baseline, candidate in bear_pairs]
    bear_return_delta = sum(bear_deltas)
    bear_loss_windows = sum(1 for delta in bear_deltas if delta < 0)
    bear_loss_window_ratio = bear_loss_windows / len(bear_pairs) if bear_pairs else 0.0
    bear_dd_delta = (
        _avg([candidate.max_drawdown_pct for _, candidate in bear_pairs])
        - _avg([baseline.max_drawdown_pct for baseline, _ in bear_pairs])
        if bear_pairs
        else 0.0
    )
    baseline_trades = sum(row.trade_count for row, _ in pairs)
    candidate_trades = sum(row.trade_count for _, row in pairs)
    retention = candidate_trades / baseline_trades if baseline_trades else 0.0
    candidate_weighted_win_rate = _weighted_win_rate([candidate for _, candidate in pairs])
    positive = [delta for delta in deltas if delta > 0]
    concentration = max(positive) / sum(positive) if sum(positive) > 0 else 1.0
    candidate_mean_annual_return = _avg([candidate.annual_return_pct for _, candidate in pairs])
    baseline_mean_annual_return = _avg([baseline.annual_return_pct for baseline, _ in pairs])
    candidate_sum_return = sum(candidate.return_pct for _, candidate in pairs)
    baseline_sum_return = sum(baseline.return_pct for baseline, _ in pairs)

    # Proposal: v47 search-space expansion (commit f8ac736) — anti-overfit gates
    # from the 趋势起爆点 framework.
    # false_ignition_miss_rate: of bull-regime windows (where strategy claims
    # to have a "trend ignition" advantage), what fraction actually lost? A
    # candidate that loses in bull windows is missing real ignitions.
    bull_pairs = [(b, c) for b, c in pairs if c.regime == "bull"]
    bull_deltas = [c.return_pct - b.return_pct for b, c in bull_pairs]
    bull_loss_windows = sum(1 for d in bull_deltas if d < 0)
    false_ignition_miss_rate = (
        bull_loss_windows / len(bull_pairs) if bull_pairs else 0.0
    )
    # per_window_r2: bull-window aggregate gain / (2 * bear-window aggregate
    # loss). The framework says high R:R = big wins cover small losses. A
    # value >= 0.50 means bull gains are at least 1.0x bear losses (after
    # weighting bear loss x2 to be conservative). 0.5 is the gate floor.
    bull_gain = sum(d for d in bull_deltas if d > 0)
    bear_loss = abs(sum(d for d in bear_deltas if d < 0))
    per_window_r2 = bull_gain / (2.0 * bear_loss + 0.001)

    gate_results = {
        "coverage": expected_window_count is None or len(pairs) == expected_window_count,
        "return_delta": return_delta >= gates.return_delta_min_pct,
        "drawdown": dd_delta <= gates.average_max_drawdown_worsen_max_pct,
        "loss_windows": loss_windows <= gates.loss_windows_max,
        "fixed_loss_window_ratio": loss_window_ratio <= gates.fixed_loss_window_ratio_max,
        "bear_return_delta": not bear_pairs or bear_return_delta >= gates.bear_return_delta_min_pct,
        "bear_loss_window_ratio": not bear_pairs or bear_loss_window_ratio <= gates.bear_loss_window_ratio_max,
        "bear_drawdown": not bear_pairs or bear_dd_delta <= gates.bear_average_max_drawdown_worsen_max_pct,
        "trade_retention": retention >= gates.trade_retention_min,
        "concentration": concentration <= gates.concentration_max,
        "min_trades": candidate_trades >= gates.min_trades,
        # Proposal gates (Proposal v47 search-space expansion)
        "false_ignition_miss_rate": false_ignition_miss_rate <= gates.false_ignition_miss_rate_max,
        "per_window_r2": per_window_r2 >= gates.per_window_r2_min,
    }
    diagnostics = {
        "windows": len(pairs),
        "expected_windows": expected_window_count,
        "return_delta": round(return_delta, 6),
        "average_max_drawdown_delta": round(dd_delta, 6),
        "loss_windows": loss_windows,
        "loss_window_ratio": round(loss_window_ratio, 6),
        "bear_windows": len(bear_pairs),
        "bear_return_delta": round(bear_return_delta, 6),
        "bear_loss_windows": bear_loss_windows,
        "bear_loss_window_ratio": round(bear_loss_window_ratio, 6),
        "bear_average_max_drawdown_delta": round(bear_dd_delta, 6),
        "trade_retention": round(retention, 6),
        "concentration": round(concentration, 6),
        "candidate_trades": candidate_trades,
        "baseline_trades": baseline_trades,
        "candidate_trade_weighted_win_rate": round(candidate_weighted_win_rate, 6),
        "candidate_mean_annual_return_pct": round(candidate_mean_annual_return, 6),
        "baseline_mean_annual_return_pct": round(baseline_mean_annual_return, 6),
        "candidate_sum_return_pct": round(candidate_sum_return, 6),
        "baseline_sum_return_pct": round(baseline_sum_return, 6),
        "false_ignition_miss_rate": round(false_ignition_miss_rate, 6),
        "bull_loss_windows": bull_loss_windows,
        "per_window_r2": round(per_window_r2, 6),
        "stop_target_met": candidate_weighted_win_rate > 0.50 and candidate_mean_annual_return > 30.0,
    }
    return GateVerdict(
        verdict="KEEP" if all(gate_results.values()) else "DISCARD",
        score=round(return_delta - max(0.0, dd_delta), 6),
        gates=gate_results,
        reasons=[key for key, passed in gate_results.items() if not passed],
        diagnostics=diagnostics,
    )


def _paired_rows(
    rows: list[MetricRow],
    *,
    baseline_id: str,
    candidate_id: str,
) -> list[tuple[MetricRow, MetricRow]]:
    result = []
    windows = sorted({row.window_id for row in rows})
    for window_id in windows:
        baseline = [row for row in rows if row.window_id == window_id and row.candidate_id == baseline_id]
        candidate = [row for row in rows if row.window_id == window_id and row.candidate_id == candidate_id]
        if len(baseline) == 1 and len(candidate) == 1:
            result.append((baseline[0], candidate[0]))
    return result


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _weighted_win_rate(rows: list[MetricRow]) -> float:
    trades = sum(row.trade_count for row in rows)
    if not trades:
        return 0.0
    return sum(row.win_rate * row.trade_count for row in rows) / trades
