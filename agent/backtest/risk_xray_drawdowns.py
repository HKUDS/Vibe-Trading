"""Adapt the shared drawdown analysis to bounded Risk X-Ray reports."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.quantlib.risk import drawdown_distribution_analysis

_EPISODE_LIMIT = 5
_RECOVERY_RTOL = 1e-12


def _label(value: object) -> str | None:
    return None if value is None else str(value)


def describe_drawdown_episodes(
    equity: pd.Series,
    *,
    initial_label: str | None,
    complete: bool,
) -> dict[str, Any]:
    """Describe historical periods of the constant-weight wealth model.

    Args:
        equity: Compounded wealth after each observed one-bar return.
        initial_label: Observation at which the model starts with wealth 1.
        complete: Whether the shared return observations form an unbroken path.

    Returns:
        Strict-JSON-safe episode metadata. Durations count observed bars, not
        calendar days; missing or unusable paths are unavailable, not zero risk.
    """
    result: dict[str, Any] = {
        "available": True,
        "reason": None,
        "basis": "constant_weight_model",
        "duration_unit": "bars",
        "recovery_rtol": _RECOVERY_RTOL,
        "total": 0,
        "limit": _EPISODE_LIMIT,
        "items": [],
        "current": None,
    }
    if not complete:
        reason = "missing_return_observations"
    elif equity.empty:
        reason = "empty_path"
    elif not np.isfinite(equity.to_numpy(dtype=float)).all():
        reason = "non_finite_wealth"
    elif (equity <= 0).any():
        reason = "non_positive_wealth"
    else:
        reason = None
    if reason is not None:
        result.update(available=False, reason=reason, total=None)
        return result

    # The shared primitive starts at its first wealth observation. Include the
    # actual model baseline so an initial loss does not disappear from its path.
    path = pd.concat([pd.Series([1.0], index=[initial_label]), equity])
    # Compounding noise must not delay recovery by an entire bar. Normalize
    # only values within the declared comparison tolerance of a running peak.
    values = path.to_numpy(dtype=float)
    peaks = np.maximum.accumulate(values)
    near_peak = np.isclose(values, peaks, rtol=_RECOVERY_RTOL, atol=0.0)
    path = pd.Series(np.where(near_peak, peaks, values), index=path.index)
    analysis = drawdown_distribution_analysis(path)
    items = [
        {
            "peak": _label(episode["peak_index"]),
            "trough": _label(episode["trough_index"]),
            "recovery": _label(episode["recovery_index"]),
            "depth": -float(episode["max_depth"]),
            "duration_bars": int(episode["duration"]),
        }
        for episode in analysis["episodes"]
    ]
    result["total"] = len(items)
    if items and not analysis["episodes"][-1]["recovered"]:
        result["current"] = items[-1]
    result["items"] = sorted(items, key=lambda item: item["depth"])[:_EPISODE_LIMIT]
    return result
