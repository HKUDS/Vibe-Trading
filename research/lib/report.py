"""
Markdown report builders for factor research output.
"""

from datetime import datetime, timezone

import numpy as np

from .factor_metrics import FactorResult


def build_factor_report(
    title: str,
    period_days: int,
    data_summary: dict,
    factor_results: list,
    caveats: list,
    threshold: float = 0.05,
) -> str:
    """Build a markdown report for factor evaluation results.

    Args:
        title: top-level header
        period_days: lookback window in days
        data_summary: dict of metadata to display (rows fetched, source, etc.)
        factor_results: list[FactorResult]
        caveats: list of bullet strings
        threshold: |IC| cutoff to call a factor predictive
    """
    lines: list = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Period: last {period_days} days (UTC, as of {datetime.now(timezone.utc).isoformat()})")
    for k, v in data_summary.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Factor IC / IR vs Forward Return")
    lines.append("")
    lines.append("| factor | horizon | IC (Spearman) | IR (rolling 30d) | n_samples | interpretation |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for r in factor_results:
        ic_s = f"{r.ic:+.4f}" if not np.isnan(r.ic) else "NA"
        ir_s = f"{r.ir:+.3f}" if not np.isnan(r.ir) else "NA"
        interp = f"predictive (|IC|>{threshold})" if r.predictive(threshold) else "weak / none"
        lines.append(f"| {r.factor} | {r.horizon} | {ic_s} | {ir_s} | {r.n_samples} | {interp} |")
    lines.append("")
    lines.append("## Summary (plain language)")
    lines.append("")
    sig = [r for r in factor_results if r.predictive(threshold)]
    if sig:
        for r in sig:
            direction = "正向" if r.ic > 0 else "負向"
            arrow = "高" if r.ic > 0 else "低"
            lines.append(
                f"- **{r.factor} @ {r.horizon}**: IC = {r.ic:+.4f}（{direction}相關）。"
                f"{r.factor} 高 -> 未來 {r.horizon} 報酬{arrow}。"
            )
    else:
        lines.append(f"- 樣本內所有因子皆 |IC| < {threshold}，**單獨使用不具預測力**。")
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    for c in caveats:
        lines.append(f"- {c}")
    return "\n".join(lines)
