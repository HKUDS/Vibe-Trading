"""Readers for persisted run artifacts shared by the run detail and preview routes."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.api.models import BacktestMetrics
from src.ui_services import load_csv_records, load_json_file

EQUITY_CURVE_MAX_POINTS = 1000

# Artifacts a run card can show: metrics, curves, trades, positions, validation
# or strategy source.
_REPORT_ARTIFACT_RE = re.compile(
    r"(?:metrics|equity|trades|positions|ohlcv|validation|strategy)\.(?:csv|json|pine|py)$",
    re.IGNORECASE,
)


def load_backtest_metrics(run_dir: Path) -> Optional[BacktestMetrics]:
    """Parse ``artifacts/metrics.csv`` into backtest metrics.

    Args:
        run_dir: Run directory.

    Returns:
        Parsed metrics, or ``None`` when the file is missing or lacks the
        required summary fields.
    """
    rows = load_csv_records(run_dir / "artifacts" / "metrics.csv", limit=1)
    if not rows:
        return None
    parsed: Dict[str, Any] = {}
    for key, value in rows[0].items():
        if not key or not value:
            continue
        try:
            parsed[key] = (
                int(float(value))
                if key in ("trade_count", "max_consecutive_loss")
                else float(value)
            )
        except (ValueError, TypeError):
            continue
    if "final_value" not in parsed:
        return None
    try:
        return BacktestMetrics(**parsed)
    except (ValueError, TypeError):
        return None


def equity_curve_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project ``equity.csv`` rows onto chart points.

    Args:
        rows: Rows read from ``equity.csv``.

    Returns:
        One ``time``/``equity``/``drawdown`` point per row, keeping only the
        columns the row has.
    """
    curve: List[Dict[str, Any]] = []
    for row in rows:
        point: Dict[str, Any] = {}
        if "timestamp" in row:
            point["time"] = row["timestamp"]
        if "equity" in row:
            point["equity"] = row["equity"]
        if "drawdown" in row:
            point["drawdown"] = row["drawdown"]
        curve.append(point)
    return curve


def _artifact_names(run_dir: Path) -> Set[str]:
    """Return file names directly under ``artifacts/``; empty if unreadable."""
    try:
        with os.scandir(run_dir / "artifacts") as entries:
            return {entry.name for entry in entries if entry.is_file()}
    except OSError:
        return set()


def is_report_worthy(run_dir: Path, names: Optional[Set[str]] = None) -> bool:
    """Tell whether a run produced anything a run card can show.

    Every chat turn gets a run directory, so most runs are plain replies;
    deciding from file names keeps those to a directory listing.

    Args:
        run_dir: Run directory.
        names: File names under ``artifacts/`` when already listed.

    Returns:
        ``True`` when the run has report artifacts, price data or a non-empty
        run card.
    """
    if names is None:
        names = _artifact_names(run_dir)
    return (
        any(_REPORT_ARTIFACT_RE.search(name) for name in names)
        or "price_series.csv" in names
        or any(name.startswith("ohlcv_") and name.endswith(".csv") for name in names)
        or bool(load_json_file(run_dir / "run_card.json"))
    )


def build_run_preview(run_dir: Path) -> Dict[str, Any]:
    """Summarize a run for its chat card without loading chart payloads.

    Args:
        run_dir: Existing run directory.

    Returns:
        ``metrics``, the first ``EQUITY_CURVE_MAX_POINTS`` equity points with
        the same shape as the full run response, and ``report_worthy``.
    """
    names = _artifact_names(run_dir)
    metrics = load_backtest_metrics(run_dir) if "metrics.csv" in names else None
    equity_rows = (
        load_csv_records(
            run_dir / "artifacts" / "equity.csv", limit=EQUITY_CURVE_MAX_POINTS
        )
        if "equity.csv" in names
        else []
    )
    return {
        "metrics": metrics.model_dump(mode="json") if metrics else None,
        "equity_curve": equity_curve_from_rows(equity_rows),
        "report_worthy": is_report_worthy(run_dir, names),
    }
