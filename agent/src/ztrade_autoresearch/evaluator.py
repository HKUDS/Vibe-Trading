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
    return_pct: float
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
    baseline_trades = sum(row.trade_count for row, _ in pairs)
    candidate_trades = sum(row.trade_count for _, row in pairs)
    retention = candidate_trades / baseline_trades if baseline_trades else 0.0
    positive = [delta for delta in deltas if delta > 0]
    concentration = max(positive) / sum(positive) if sum(positive) > 0 else 1.0

    gate_results = {
        "return_delta": return_delta >= gates.return_delta_min_pct,
        "drawdown": dd_delta <= gates.average_max_drawdown_worsen_max_pct,
        "loss_windows": loss_windows <= gates.loss_windows_max,
        "trade_retention": retention >= gates.trade_retention_min,
        "concentration": concentration <= gates.concentration_max,
        "min_trades": candidate_trades >= gates.min_trades,
    }
    diagnostics = {
        "windows": len(pairs),
        "return_delta": round(return_delta, 6),
        "average_max_drawdown_delta": round(dd_delta, 6),
        "loss_windows": loss_windows,
        "trade_retention": round(retention, 6),
        "concentration": round(concentration, 6),
        "candidate_trades": candidate_trades,
        "baseline_trades": baseline_trades,
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
