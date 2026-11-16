"""Research Lab commands using the same persisted jobs as the Web UI."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path


def parameter_candidates(specs: list[str]) -> list[dict]:
    """Expand explicitly named constructor choices into a bounded grid."""
    choices = {}
    for spec in specs:
        name, sep, raw = spec.partition("=")
        if not sep or not name.isidentifier() or name.startswith("_") or name in choices:
            raise ValueError("parameters use distinct name=value1,value2 specifications")
        values = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                raise ValueError("parameter choices cannot be empty")
            try:
                value = json.loads(token)
            except ValueError:
                value = token
            values.append(value)
        choices[name] = values
    size = 1
    for values in choices.values():
        size *= len(values)
    if size > 12:
        raise ValueError("the parameter grid may contain at most 12 candidates")
    return [
        {"name": f"candidate-{i}", "parameters": dict(zip(choices, combination))}
        for i, combination in enumerate(itertools.product(*choices.values()), 1)
    ]


def add_subparser(subparsers):
    """Register costs, walk-forward, audit, replay, cases, and recovery commands."""
    parser = subparsers.add_parser(
        "research-lab", help="Study execution costs, frozen OOS parameters, factors and task replays"
    )
    commands = parser.add_subparsers(dest="lab_command", required=True)
    costs = commands.add_parser("costs", help="Re-run a saved price snapshot under different execution costs")
    costs.add_argument("run_dir")
    costs.add_argument("--fee-multipliers", nargs="+", type=float, default=[1, 2, 3])
    costs.add_argument("--slippage-bps", nargs="+", type=float, default=[0, 5])
    wf = commands.add_parser("walk-forward", help="Train, select and freeze parameters before OOS execution")
    wf.add_argument("run_dir")
    wf.add_argument("--parameter", action="append", default=[])
    wf.add_argument("--train-bars", required=True, type=int)
    wf.add_argument("--test-bars", required=True, type=int)
    wf.add_argument("--holdout-bars", default=0, type=int)
    wf.add_argument("--max-folds", default=5, type=int)
    wf.add_argument("--objective", choices=["sharpe", "total_return"], default="sharpe")
    wf.add_argument("--training", choices=["rolling", "expanding"], default="rolling")
    audit = commands.add_parser("audit", help="Check formula and minimum-history contracts across the Alpha Zoo")
    audit.add_argument("--alpha-id", action="append")
    replay = commands.add_parser("replay", help="Verify saved run artifacts without an LLM or network")
    replay.add_argument("run_dir", nargs="?")
    replay.add_argument("--case", action="append", dest="case_ids")
    replay.add_argument("--trace-dir")
    replay.add_argument("--bindings", type=Path, help="JSON array of case_id/run_dir/optional trace_dir bindings")
    cases = commands.add_parser("cases", help="List bundled task prompts and their evaluation contracts")
    show = commands.add_parser("show", help="Recover a persisted job and its report")
    show.add_argument("job_id")
    for command in (costs, wf, audit, replay, cases, show):
        command.add_argument("--json", action="store_true", help="Emit the complete machine-readable result")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    """Execute the requested operation and print its durable job/report envelope."""
    from src.research_lab import service

    try:
        if args.lab_command == "cases":
            from evals.harness.suite import list_cases

            result = {"cases": list_cases()}
        elif args.lab_command == "show":
            result = service.get_job(args.job_id)
        elif args.lab_command == "costs":
            scenarios = [
                {"name": f"fees-{fee:g}-slippage-{bps:g}", "fee_multiplier": fee, "extra_slippage_bps": bps}
                for fee, bps in itertools.product(args.fee_multipliers, args.slippage_bps)
            ]
            result = service.run("cost_sensitivity", {"run_dir": args.run_dir, "scenarios": scenarios})
        elif args.lab_command == "walk-forward":
            result = service.run(
                "walk_forward",
                {
                    "run_dir": args.run_dir,
                    "candidates": parameter_candidates(args.parameter),
                    **{
                        name: getattr(args, name)
                        for name in ("train_bars", "test_bars", "holdout_bars", "max_folds", "objective", "training")
                    },
                },
            )
        elif args.lab_command == "audit":
            result = service.run("factor_audit", {"alpha_ids": args.alpha_id})
        elif args.bindings:
            from evals.harness.suite import replay_suite

            result = replay_suite(json.loads(args.bindings.read_text()))
        else:
            if not args.run_dir:
                raise ValueError("replay requires a run directory or --bindings")
            result = service.run(
                "replay", {"run_dir": args.run_dir, "case_ids": args.case_ids, "trace_dir": args.trace_dir}
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        report = result.get("result", result)
        if (
            result.get("status") == "failed"
            or report.get("evaluation_status") in {"failed", "invalid_artifact"}
            or report.get("passed") is False
            or report.get("finding_count", 0) > 0
        ):
            return 1
        return 2 if report.get("evaluation_status") == "not_evaluable" else 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
