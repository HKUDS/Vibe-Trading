from __future__ import annotations

from src.alpha_quality.model import ExecutionMetrics


def cost_exceeds_alpha(execution: ExecutionMetrics | None) -> bool:
    if execution is None or execution.return_mean is None:
        return False
    if execution.return_mean < 0:
        return True
    if execution.cost_bps_mean is None:
        return False
    alpha_bps = execution.return_mean * 10_000.0
    return execution.cost_bps_mean > alpha_bps
