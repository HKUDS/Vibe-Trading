"""Aggregate Harness reports while preserving evaluation coverage."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .schema import EvaluationReport, VerdictStatus


def aggregate_reports(reports: Iterable[EvaluationReport]) -> dict[str, Any]:
    """Aggregate verdict counts by status and scenario without dropping gaps."""
    materialized = list(reports)
    totals: Counter[str] = Counter()
    by_scenario: dict[str, Counter[str]] = defaultdict(Counter)
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    for report in materialized:
        for verdict in report.verdicts:
            status = verdict.status.value
            totals[status] += 1
            by_scenario[report.scenario][status] += 1
            by_code[verdict.code][status] += 1
    all_statuses = [status.value for status in VerdictStatus]

    def complete(counter: Counter[str]) -> dict[str, int]:
        return {status: counter[status] for status in all_statuses}

    assertion_count = sum(totals.values())
    evaluable = totals[VerdictStatus.PASS.value] + totals[VerdictStatus.FAIL.value]
    metric_groups = {
        "task_completion": ("completion.status",),
        "identity_resolution": ("identity.status", "identity.authorized_symbols"),
        "required_tool_coverage": ("tools.required.",),
        "evidence_coverage": ("evidence.required_symbols",),
        "high_risk_boundary": (
            "risk.forbidden_successful_tools",
            "risk.authorization_bypasses",
        ),
    }
    return {
        "schema_version": 1,
        "case_count": len(materialized),
        "assertion_count": assertion_count,
        "evaluation_coverage": (
            (evaluable / assertion_count) if assertion_count else 0.0
        ),
        "status_counts": complete(totals),
        "by_scenario": {
            name: complete(counts) for name, counts in sorted(by_scenario.items())
        },
        "by_assertion": {
            name: complete(counts) for name, counts in sorted(by_code.items())
        },
        "metrics": {
            name: _metric_summary(materialized, prefixes)
            for name, prefixes in metric_groups.items()
        },
    }


def _metric_summary(
    reports: Iterable[EvaluationReport],
    prefixes: tuple[str, ...],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for report in reports:
        for verdict in report.verdicts:
            if any(
                verdict.code == prefix or verdict.code.startswith(prefix)
                for prefix in prefixes
            ):
                counts[verdict.status.value] += 1
    total = sum(counts.values())
    evaluable = counts[VerdictStatus.PASS.value] + counts[VerdictStatus.FAIL.value]
    return {
        "assertions": total,
        "evaluable": evaluable,
        "pass_rate": (
            counts[VerdictStatus.PASS.value] / evaluable if evaluable else None
        ),
        "coverage": evaluable / total if total else 0.0,
        "not_evaluable": counts[VerdictStatus.NOT_EVALUABLE.value],
        "invalid_artifact": counts[VerdictStatus.INVALID_ARTIFACT.value],
    }
