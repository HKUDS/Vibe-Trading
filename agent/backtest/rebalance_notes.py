"""Rebalance notes: per-rebalance turnover and weight-drift detail.

The Portfolio Studio epic (#456) asks for per-rebalance reporting as the
last backend slice, alongside the shipped turnover-aware optimizer and the
risk x-ray. The notes here are computed from the target position frame, so
they work for every optimizer and for the no-optimizer baseline: a rebalance
is any decision date whose target weight vector moved past ``epsilon`` from
the previous one. Trade-derived turnover in ``metrics`` measures what the
execution layer actually exchanged; these notes measure what the signal and
optimizer asked for, which is where churn starts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest.validation import _json_safe


def compute_rebalance_notes(
    target_pos: pd.DataFrame,
    *,
    top_n: int = 5,
    epsilon: float = 1e-6,
) -> Dict[str, Any]:
    """Summarize per-date weight changes in a target position frame.

    Args:
        target_pos: Target weights (dates x codes), e.g. the frame behind
            ``artifacts/positions.csv``. NaN cells are treated as zero.
        top_n: How many largest per-name moves to keep per rebalance.
        epsilon: Turnover at or below this counts as "no rebalance".

    Returns:
        JSON-safe dict with ``rebalances`` (per date: turnover, entries,
        exits, top moves by absolute weight change) and ``summary`` (count
        plus turnover aggregates).
    """
    empty = {
        "rebalances": [],
        "summary": {
            "rebalance_count": 0,
            "turnover_total": 0.0,
            "turnover_mean": 0.0,
            "turnover_max": 0.0,
            "largest_rebalance_date": None,
        },
    }
    if target_pos.empty or len(target_pos) < 2:
        return empty

    codes = target_pos.columns.tolist()
    values = target_pos.fillna(0.0).to_numpy(dtype=float)

    rebalances: List[Dict[str, Any]] = []
    prev = values[0]
    for i in range(1, len(values)):
        curr = values[i]
        delta = curr - prev
        turnover = 0.5 * float(np.abs(delta).sum())
        if turnover > epsilon:
            date = target_pos.index[i]
            entries = [
                {"code": codes[j], "weight": float(curr[j])}
                for j in range(len(codes))
                if abs(prev[j]) <= epsilon and abs(curr[j]) > epsilon
            ]
            exits = [
                {"code": codes[j], "weight": float(prev[j])}
                for j in range(len(codes))
                if abs(curr[j]) <= epsilon and abs(prev[j]) > epsilon
            ]
            moves = sorted(
                (
                    {
                        "code": codes[j],
                        "from": float(prev[j]),
                        "to": float(curr[j]),
                        "delta": float(delta[j]),
                    }
                    for j in range(len(codes))
                    if abs(delta[j]) > epsilon
                ),
                key=lambda move: -abs(move["delta"]),
            )[:top_n]
            rebalances.append(
                {
                    "date": str(date.date()) if hasattr(date, "date") else str(date),
                    "turnover": turnover,
                    "entries": entries,
                    "exits": exits,
                    "top_moves": moves,
                }
            )
        prev = curr

    turnovers = [r["turnover"] for r in rebalances]
    largest = max(range(len(rebalances)), key=lambda k: turnovers[k]) if rebalances else None
    return {
        "rebalances": rebalances,
        "summary": {
            "rebalance_count": len(rebalances),
            "turnover_total": float(sum(turnovers)),
            "turnover_mean": float(np.mean(turnovers)) if turnovers else 0.0,
            "turnover_max": float(max(turnovers)) if turnovers else 0.0,
            "largest_rebalance_date": rebalances[largest]["date"] if largest is not None else None,
        },
    }


def render_rebalance_notes_markdown(notes: Dict[str, Any]) -> str:
    """Render notes as a compact Markdown report."""
    summary = notes["summary"]
    lines = [
        "# Rebalance Notes",
        "",
        f"- rebalances: {summary['rebalance_count']}",
        f"- turnover total / mean / max: {summary['turnover_total']:.4f} / "
        f"{summary['turnover_mean']:.4f} / {summary['turnover_max']:.4f}",
    ]
    if summary["largest_rebalance_date"] is not None:
        lines.append(f"- largest rebalance: {summary['largest_rebalance_date']}")
    lines.append("")

    for rebalance in notes["rebalances"]:
        lines.append(f"## {rebalance['date']} (turnover {rebalance['turnover']:.4f})")
        if rebalance["entries"]:
            joined = ", ".join(item["code"] for item in rebalance["entries"])
            lines.append(f"- entries: {joined}")
        if rebalance["exits"]:
            joined = ", ".join(item["code"] for item in rebalance["exits"])
            lines.append(f"- exits: {joined}")
        for move in rebalance["top_moves"]:
            lines.append(f"- {move['code']}: {move['from']:.4f} -> {move['to']:.4f} ({move['delta']:+.4f})")
        lines.append("")
    return "\n".join(lines)


def write_rebalance_notes(path: Path, notes: Dict[str, Any]) -> Dict[str, Any]:
    """Write notes to ``path`` as strict, RFC-8259 JSON.

    Mirrors :func:`backtest.validation.write_validation_json`: sanitize with
    ``_json_safe`` (non-finite -> null) and serialize with ``allow_nan=False``
    so every strict parser accepts the artifact. Returns the sanitized
    payload that was written.
    """
    safe_notes = _json_safe(notes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(safe_notes, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return safe_notes
