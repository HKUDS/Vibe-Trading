"""Bundled task catalog and batch replay of actual, unmodified run bundles."""

from __future__ import annotations

import json
from pathlib import Path

from .report import aggregate_reports
from .runner import evaluate_case, load_case
from .schema import VerdictStatus

# A disproved claim or corrupt artifact takes precedence over missing evidence.
_REPLAY_STATUSES = {
    VerdictStatus.INVALID_ARTIFACT: "invalid_artifact",
    VerdictStatus.FAIL: "failed",
    VerdictStatus.NOT_EVALUABLE: "not_evaluable",
    VerdictStatus.PASS: "passed",
}


def _evaluation_status(statuses: set[str]) -> str:
    return next((status for status in _REPLAY_STATUSES.values() if status in statuses), "passed")


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
    statuses = {_REPLAY_STATUSES[verdict.status] for report in reports for verdict in report.verdicts}
    status = _evaluation_status(statuses)
    return {
        "kind": "replay",
        "evaluation_status": status,
        "summary": summary,
        "reports": [report.to_dict() for report in reports],
        "llm_calls": 0,
        "network_calls": 0,
    }


def validate_bindings(bindings) -> list[tuple[Path, str, Path | None]]:
    """Validate and normalize batch replay bindings before executing any case."""
    if not isinstance(bindings, list) or not bindings or len(bindings) > 100:
        raise ValueError("replay bindings must be a JSON array of 1 to 100 case/run pairs")
    normalized: list[tuple[Path, str, Path | None]] = []
    for index, entry in enumerate(bindings):
        if not isinstance(entry, dict):
            raise ValueError(f"replay binding[{index}] must be an object")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"replay binding[{index}].case_id must be a non-empty string")
        run_dir = entry.get("run_dir")
        if not isinstance(run_dir, (str, Path)) or not str(run_dir).strip():
            raise ValueError(f"replay binding[{index}].run_dir must be a non-empty path string")
        trace_dir = entry.get("trace_dir")
        if trace_dir is not None and (not isinstance(trace_dir, (str, Path)) or not str(trace_dir).strip()):
            raise ValueError(f"replay binding[{index}].trace_dir must be a non-empty path string when provided")
        normalized.append((Path(run_dir), case_id, Path(trace_dir) if trace_dir is not None else None))
    return normalized


def replay_suite(bindings: list[dict]) -> dict:
    """Replay each case against its own stored run without rewriting prompts."""
    normalized = validate_bindings(bindings)
    results = [replay_run(run_dir, [case_id], trace_dir) for run_dir, case_id, trace_dir in normalized]
    status = _evaluation_status({result["evaluation_status"] for result in results})
    return {
        "kind": "replay_suite",
        "evaluation_status": status,
        "results": results,
        "passed": status == "passed",
        "case_count": len(results),
        "llm_calls": 0,
        "network_calls": 0,
    }
