"""Shared decay metrics computation for bench history.

Both ``sdm_decay_scan`` and ``sdm_status`` tools call this to compute
baseline/rolling IC and Sharpe metrics from a chronologically ordered
bench-history list.
"""

from __future__ import annotations

from typing import Any

_DECAY_INPUT_KEYS = ("ic_ratio", "rolling_ir", "ic_positive_ratio", "rolling_sharpe")


def has_decay_inputs(metrics: dict[str, float | None]) -> bool:
    """Return True if at least one evaluate_decay input metric is available.

    With all inputs ``None``, ``DecayEvaluator.evaluate_decay`` defaults to
    HEALTHY — callers should report ``insufficient_data`` instead.
    """
    return any(metrics.get(key) is not None for key in _DECAY_INPUT_KEYS)


def compute_decay_metrics(
    bench_history: list[Any],
) -> dict[str, float | None]:
    """Compute baseline and rolling metrics from bench history.

    For factor artifacts: uses ``ic_mean`` to compute baseline/rolling IC metrics.
    For strategy artifacts: uses ``sharpe`` to compute rolling Sharpe.

    ``bench_history`` is expected to be newest-first (as returned by the store);
    it is reversed internally to chronological order before computation.

    Returns:
        Dict with keys: ``baseline_ic_mean``, ``rolling_ic_mean``, ``ic_ratio``,
        ``rolling_ir``, ``ic_positive_ratio``, ``rolling_sharpe``, ``baseline_sharpe``.
        Values are ``None`` when insufficient data (< 3 non-None entries).
    """
    result: dict[str, float | None] = {
        "baseline_ic_mean": None,
        "rolling_ic_mean": None,
        "ic_ratio": None,
        "rolling_ir": None,
        "ic_positive_ratio": None,
        "rolling_sharpe": None,
        "baseline_sharpe": None,
    }

    chronological = list(reversed(bench_history))

    ic_values = [r.ic_mean for r in chronological if r.ic_mean is not None]
    sharpe_values = [r.sharpe for r in chronological if r.sharpe is not None]

    has_ic = len(ic_values) >= 3
    has_sharpe = len(sharpe_values) >= 3

    if has_ic:
        baseline_ics = ic_values[:5]
        rolling_ics = ic_values[-5:]

        baseline_mean = sum(baseline_ics) / len(baseline_ics)
        rolling_mean = sum(rolling_ics) / len(rolling_ics)

        result["baseline_ic_mean"] = round(baseline_mean, 6)
        result["rolling_ic_mean"] = round(rolling_mean, 6)

        if baseline_mean != 0:
            result["ic_ratio"] = round(rolling_mean / baseline_mean, 4)

        if len(rolling_ics) > 1:
            mean_r = sum(rolling_ics) / len(rolling_ics)
            var_r = sum((x - mean_r) ** 2 for x in rolling_ics) / (len(rolling_ics) - 1)
            std_r = var_r**0.5
            if std_r > 0:
                result["rolling_ir"] = round(mean_r / std_r, 4)

        positive_count = sum(1 for v in ic_values if v > 0)
        result["ic_positive_ratio"] = round(positive_count / len(ic_values), 4)

    if has_sharpe:
        result["baseline_sharpe"] = round(sum(sharpe_values[:5]) / len(sharpe_values[:5]), 6)
        result["rolling_sharpe"] = round(sum(sharpe_values[-5:]) / len(sharpe_values[-5:]), 6)

    return result
