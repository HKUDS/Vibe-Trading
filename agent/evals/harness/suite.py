"""Bundled task catalog and batch replay of actual, unmodified run bundles."""

from __future__ import annotations

import json
from pathlib import Path

from .report import aggregate_reports
from .runner import evaluate_case, load_case
from .schema import VerdictStatus


def case_paths() -> dict[str, Path]:
    """Discover evaluator cases; fixture JSON is never mistaken for a case."""
    paths = {}
    for path in sorted((Path(__file__).parent / "cases").rglob("*.json")):
        if "fixtures" in path.parts:
            continue
        case = load_case(path)
        if case.case_id in paths:
            raise ValueError(f"duplicate harness case ID: {case.case_id}")
        paths[case.case_id] = path
    return paths


def list_cases() -> list[dict]:
    """Describe available prompts and what each case actually evaluates."""
    return [
        {"id": case.case_id, "scenario": case.scenario, "prompt": case.prompt, "checks": sorted(case.expect)}
        for case in (load_case(path) for path in case_paths().values())
    ]


def replay_run(run_dir: Path, case_ids: list[str] | None = None, trace_dir: Path | None = None) -> dict:
    """Evaluate a stored run against explicit cases or its exact original prompt."""
    paths = case_paths()
    if case_ids is None:
        prompt = json.loads((run_dir / "req.json").read_text()).get("prompt")
        case_ids = [key for key, path in paths.items() if load_case(path).prompt == prompt]
        if not case_ids:
            raise ValueError(
                "no bundled case matches this run's original prompt; select an explicit case or use a custom CLI case"
            )
    missing = set(case_ids) - paths.keys()
    if missing:
        raise ValueError(f"unknown harness cases: {', '.join(sorted(missing))}")
    reports = [evaluate_case(load_case(paths[key]), run_dir, trace_dir=trace_dir) for key in dict.fromkeys(case_ids)]
    summary = aggregate_reports(reports)
    statuses = {verdict.status for report in reports for verdict in report.verdicts}
    status = (
        "invalid_artifact"
        if VerdictStatus.INVALID_ARTIFACT in statuses
        else "failed"
        if VerdictStatus.FAIL in statuses
        else "not_evaluable"
        if VerdictStatus.NOT_EVALUABLE in statuses
        else "passed"
    )
    return {
        "kind": "replay",
        "evaluation_status": status,
        "summary": summary,
        "reports": [report.to_dict() for report in reports],
        "llm_calls": 0,
        "network_calls": 0,
    }


def replay_suite(bindings: list[dict]) -> dict:
    """Replay each case against its own stored run without rewriting prompts."""
    if not bindings or len(bindings) > 100:
        raise ValueError("replay bindings must contain 1 to 100 case/run pairs")
    results = []
    for entry in bindings:
        result = replay_run(
            Path(entry["run_dir"]), [entry["case_id"]], Path(entry["trace_dir"]) if entry.get("trace_dir") else None
        )
        results.append(result)
    return {
        "kind": "replay_suite",
        "results": results,
        "passed": all(result["evaluation_status"] == "passed" for result in results),
        "case_count": len(results),
        "llm_calls": 0,
        "network_calls": 0,
    }
