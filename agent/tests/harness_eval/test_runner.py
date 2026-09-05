"""End-to-end deterministic assertions and aggregate coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from evals.harness.report import aggregate_reports
from evals.harness.runner import evaluate_case, main
from evals.harness.schema import EvaluationReport, HarnessCase, VerdictStatus


def _by_code(report: EvaluationReport) -> dict[str, object]:
    return {verdict.code: verdict for verdict in report.verdicts}


def test_complete_synthetic_bundle_passes_observable_assertions(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    report = evaluate_case(harness_case, artifact_dir)
    verdicts = _by_code(report)

    assert report.status_counts == {
        "PASS": 17,
        "FAIL": 0,
        "NOT_EVALUABLE": 5,
        "INVALID_ARTIFACT": 0,
    }
    assert verdicts["prompt.request_preserved"].status is VerdictStatus.PASS
    assert verdicts["identity.constraint"].status is VerdictStatus.PASS
    assert verdicts["tools.false_skips"].status is VerdictStatus.NOT_EVALUABLE
    assert verdicts["completion.status"].status is VerdictStatus.NOT_EVALUABLE
    assert verdicts["budget.max_visible_tools"].status is VerdictStatus.NOT_EVALUABLE
    assert verdicts["tools.result_join"].observed["outcomes"]["ok"] == 1


def test_failures_and_invalid_artifacts_are_not_collapsed(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    (artifact_dir / "req.json").write_text(
        json.dumps({"prompt": "rewritten"}), encoding="utf-8"
    )
    state = {"status": "failed"}
    (artifact_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    usage = json.loads((artifact_dir / "llm_usage.json").read_text(encoding="utf-8"))
    usage["totals"]["input_tokens"] = 999
    (artifact_dir / "llm_usage.json").write_text(json.dumps(usage), encoding="utf-8")
    with (artifact_dir / "trace.jsonl").open("a", encoding="utf-8") as trace:
        trace.write(
            json.dumps(
                {
                    "type": "tool_result",
                    "tool": "ghost",
                    "call_id": "orphan",
                    "status": "ok",
                }
            )
            + "\n"
        )

    report = evaluate_case(harness_case, artifact_dir)
    verdicts = _by_code(report)

    assert verdicts["prompt.request_preserved"].status is VerdictStatus.FAIL
    assert (
        verdicts["execution.reconciled_status"].status is VerdictStatus.INVALID_ARTIFACT
    )
    assert verdicts["tools.result_join"].status is VerdictStatus.INVALID_ARTIFACT
    assert verdicts["budget.max_input_tokens"].status is VerdictStatus.INVALID_ARTIFACT


def test_trace_error_status_reconciles_to_failed_state(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    (artifact_dir / "state.json").write_text(
        json.dumps({"status": "failed"}), encoding="utf-8"
    )
    lines = [
        json.loads(line)
        for line in (artifact_dir / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    lines[-1]["status"] = "error"
    (artifact_dir / "trace.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines),
        encoding="utf-8",
    )
    case = replace(
        harness_case,
        expect={**harness_case.expect, "execution": {"allowed": ["failed"]}},
    )

    report = evaluate_case(case, artifact_dir)

    assert _by_code(report)["execution.reconciled_status"].status is VerdictStatus.PASS


def test_missing_current_instrumentation_is_never_a_pass(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    (artifact_dir / "llm_usage.json").unlink()
    grounding = json.loads(
        (artifact_dir / "artifacts" / "grounding_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    grounding["identity"]["records"][0].pop("resolution_constraints")
    (artifact_dir / "artifacts" / "grounding_evidence.json").write_text(
        json.dumps(grounding), encoding="utf-8"
    )

    report = evaluate_case(harness_case, artifact_dir)
    verdicts = _by_code(report)

    assert verdicts["budget.max_input_tokens"].status is VerdictStatus.NOT_EVALUABLE
    assert verdicts["identity.constraint"].status is VerdictStatus.NOT_EVALUABLE


def test_missing_required_grounding_artifact_is_invalid(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    (artifact_dir / "artifacts" / "grounding_evidence.json").unlink()

    report = evaluate_case(harness_case, artifact_dir)
    verdicts = _by_code(report)

    assert (
        verdicts["identity.artifact_available"].status is VerdictStatus.INVALID_ARTIFACT
    )
    assert (
        verdicts["evidence.artifact_available"].status is VerdictStatus.INVALID_ARTIFACT
    )


def test_tampered_manifest_is_invalid_artifact(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    manifest = json.loads(
        (artifact_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    manifest["manifest_hash"] = "sha256:" + "0" * 64
    (artifact_dir / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    report = evaluate_case(harness_case, artifact_dir)

    assert (
        _by_code(report)["methodology.manifest_integrity"].status
        is VerdictStatus.INVALID_ARTIFACT
    )


def test_complete_provider_usage_can_fail_token_budget(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    case = replace(
        harness_case,
        expect={
            **harness_case.expect,
            "budget": {**harness_case.expect["budget"], "max_input_tokens": 99},
        },
    )

    report = evaluate_case(case, artifact_dir)

    assert _by_code(report)["budget.max_input_tokens"].status is VerdictStatus.FAIL


def test_forbidden_successful_tool_and_blocked_bypass_fail(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    records = [
        {
            "type": "tool_call",
            "iter": 2,
            "tool": "place_order",
            "call_id": "order",
            "args": {},
            "blocked": True,
        },
        {
            "type": "tool_result",
            "iter": 2,
            "tool": "place_order",
            "call_id": "order",
            "status": "ok",
        },
    ]
    with (artifact_dir / "trace.jsonl").open("a", encoding="utf-8") as trace:
        for record in records:
            trace.write(json.dumps(record) + "\n")

    report = evaluate_case(harness_case, artifact_dir)
    verdicts = _by_code(report)

    assert verdicts["risk.forbidden_successful_tools"].status is VerdictStatus.FAIL
    assert verdicts["risk.authorization_bypasses"].status is VerdictStatus.FAIL


def test_unknown_tool_result_status_is_invalid_artifact(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    lines = [
        json.loads(line)
        for line in (artifact_dir / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    next(line for line in lines if line["type"] == "tool_result")["status"] = "maybe"
    (artifact_dir / "trace.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines),
        encoding="utf-8",
    )

    report = evaluate_case(harness_case, artifact_dir)

    assert (
        _by_code(report)["tools.result_join"].status is VerdictStatus.INVALID_ARTIFACT
    )


def test_provider_usage_gap_makes_token_budget_not_evaluable(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    usage = json.loads((artifact_dir / "llm_usage.json").read_text(encoding="utf-8"))
    usage["totals"] = {
        "input_tokens": 40,
        "output_tokens": 10,
        "total_tokens": 50,
        "calls": 1,
    }
    usage["per_iteration"] = [usage["per_iteration"][0]]
    (artifact_dir / "llm_usage.json").write_text(json.dumps(usage), encoding="utf-8")

    report = evaluate_case(harness_case, artifact_dir)

    assert (
        _by_code(report)["budget.max_input_tokens"].status
        is VerdictStatus.NOT_EVALUABLE
    )


def test_aggregate_reports_exposes_coverage(
    harness_case: HarnessCase,
    artifact_dir: Path,
) -> None:
    first = evaluate_case(harness_case, artifact_dir)
    second = replace(first, case_id="second")

    aggregate = aggregate_reports([first, second])

    assert aggregate["case_count"] == 2
    assert aggregate["status_counts"]["NOT_EVALUABLE"] == 10
    assert aggregate["evaluation_coverage"] == 34 / 44
    assert aggregate["by_scenario"][harness_case.scenario]["PASS"] == 34
    assert aggregate["metrics"]["task_completion"] == {
        "assertions": 2,
        "evaluable": 0,
        "pass_rate": None,
        "coverage": 0.0,
        "not_evaluable": 2,
        "invalid_artifact": 0,
    }
    assert aggregate["metrics"]["identity_resolution"]["pass_rate"] == 1.0


def test_cli_exit_codes_distinguish_failures_from_invalid_input(
    harness_case: HarnessCase,
    artifact_dir: Path,
    tmp_path: Path,
) -> None:
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema_version": harness_case.schema_version,
                "case_id": harness_case.case_id,
                "scenario": harness_case.scenario,
                "prompt": harness_case.prompt,
                "history": list(harness_case.history),
                "data_snapshot": harness_case.data_snapshot,
                "expect": harness_case.expect,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "--case",
                str(case_path),
                "--run-dir",
                str(artifact_dir),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["status_counts"]["PASS"] == 17

    (artifact_dir / "req.json").write_text(
        json.dumps({"prompt": "changed"}), encoding="utf-8"
    )
    assert main(["--case", str(case_path), "--run-dir", str(artifact_dir)]) == 1

    case_path.write_text("{}", encoding="utf-8")
    assert main(["--case", str(case_path), "--run-dir", str(artifact_dir)]) == 2
