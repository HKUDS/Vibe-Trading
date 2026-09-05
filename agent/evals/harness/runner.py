"""CLI and API for case-by-artifact deterministic Harness evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .artifacts import ArtifactBundle
from .assertions import evaluate_assertions
from .schema import EvaluationReport, HarnessCase, VerdictStatus


def load_case(path: Path) -> HarnessCase:
    """Load one versioned case JSON document."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return HarnessCase.from_dict(value)


def evaluate_case(
    case: HarnessCase,
    run_dir: Path,
    *,
    trace_dir: Path | None = None,
) -> EvaluationReport:
    """Evaluate one case without invoking an LLM, tool, or network client."""
    bundle = ArtifactBundle.load(run_dir, trace_dir=trace_dir)
    verdicts = evaluate_assertions(case, bundle)
    return EvaluationReport(
        schema_version=1,
        case_id=case.case_id,
        scenario=case.scenario,
        artifact_root=str(bundle.run_dir),
        verdicts=verdicts,
        metadata={
            "trace_root": str(bundle.trace_dir),
            "artifact_presence": sorted(bundle.present),
            "artifact_errors": dict(bundle.errors),
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a Vibe-Trading run artifact bundle offline"
    )
    parser.add_argument(
        "--case", required=True, type=Path, help="path to one Harness case JSON file"
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="directory containing req/state/artifacts",
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help="optional separate directory containing trace and manifest",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the JSON report to this path instead of stdout",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline verifier and return a CI-friendly exit status."""
    args = _parser().parse_args(argv)
    try:
        case = load_case(args.case)
        report = evaluate_case(case, args.run_dir, trace_dir=args.trace_dir)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _emit({"schema_version": 1, "error": str(exc)}, args.output)
        return 2
    _emit(report.to_dict(), args.output)
    statuses = {verdict.status for verdict in report.verdicts}
    if VerdictStatus.INVALID_ARTIFACT in statuses:
        return 2
    if VerdictStatus.FAIL in statuses:
        return 1
    return 0


def _emit(payload: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
