"""Deterministic spreadsheet representations of persisted research reports."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

_FOLD_COLUMNS = [
    "phase",
    "fold",
    "selected_candidate",
    "parameters_json",
    "training_start",
    "training_end",
    "test_start",
    "test_end",
    "plan_sha256",
    "selection_sha256",
    "strategy_sha256",
    "input_manifest_sha256",
    "final_value",
    "total_return",
    "annual_return",
    "max_drawdown",
    "sharpe",
    "trade_count",
    "total_turnover",
]
_METRIC_COLUMNS = _FOLD_COLUMNS[_FOLD_COLUMNS.index("final_value") :]
_FORMULA_PREFIX = re.compile(r"^\s*[=+\-@]")


def _invalid() -> ValueError:
    return ValueError("walk-forward fold report is invalid; rerun the study")


def _required_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid()
    return value


def _finite_number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _invalid()
    return value


def _fold_row(report: dict[str, Any], fold: Any, phase: str) -> dict[str, Any]:
    if not isinstance(fold, dict) or type(fold.get("fold")) is not int or fold["fold"] < 1:
        raise _invalid()
    if fold.get("plan_sha256") != _required_text(report, "plan_sha256"):
        raise _invalid()
    if not isinstance(fold.get("parameters"), dict):
        raise _invalid()
    test = fold.get("test")
    metrics = test.get("metrics") if isinstance(test, dict) else None
    if not isinstance(metrics, dict):
        raise _invalid()
    _finite_number(metrics.get("total_return"))
    try:
        parameters = json.dumps(
            fold["parameters"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid() from exc
    row = {
        "phase": phase,
        "fold": fold["fold"],
        "selected_candidate": _required_text(fold, "name"),
        "parameters_json": parameters,
        "plan_sha256": fold["plan_sha256"],
        "selection_sha256": _required_text(fold, "selection_sha256"),
        "strategy_sha256": _required_text(report, "strategy_sha256"),
        "input_manifest_sha256": _required_text(report, "input_manifest_sha256"),
    }
    for key in ("training_start", "training_end", "test_start", "test_end"):
        row[key] = _required_text(fold, key)
    for key in _METRIC_COLUMNS:
        value = metrics.get(key)
        row[key] = "" if value is None else _finite_number(value)
    return row


def build_walk_forward_folds_csv(report: dict[str, Any]) -> bytes:
    """Serialize validation and holdout folds without changing the JSON report."""
    if report.get("kind") != "walk_forward" or not isinstance(report.get("folds"), list):
        raise _invalid()
    entries = [("validation", fold) for fold in report["folds"]]
    if report.get("holdout") is not None:
        entries.append(("holdout", report["holdout"]))
    if not entries:
        raise _invalid()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_FOLD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for phase, fold in entries:
        row = _fold_row(report, fold, phase)
        writer.writerow(
            {
                key: f"'{value}" if isinstance(value, str) and _FORMULA_PREFIX.match(value) else value
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8")
