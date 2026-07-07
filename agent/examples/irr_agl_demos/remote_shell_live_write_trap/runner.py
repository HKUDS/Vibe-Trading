"""Run the deterministic remote shell and live-write deny-barrier demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parents[3]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from examples.irr_agl_demos.common import (  # noqa: E402
    BUILDER_NAME,
    VERIFIER_NAME,
    build_card_evidence,
    json_main,
    policy_decision_ids_via_api,
    prepare_demo_context,
    trace_writer,
    write_demo_summary,
)
from examples.irr_agl_demos.remote_shell_live_write_trap import fixture  # noqa: E402
from src.governance.decision_recorder import DecisionRecorder  # noqa: E402
from src.governance.route_coverage import build_governed_tool_registry  # noqa: E402
from src.governance.runtime import PolicyDenied  # noqa: E402


def run_demo(*, output_dir: Path | str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Run the demo and return a compact, JSON-safe summary."""
    del dry_run
    context = prepare_demo_context(output_dir, "remote_shell_live_write_trap")
    writer = trace_writer(context)
    try:
        shell_tool = fixture.CountingTool(name="fake_shell", risk_level="R5_SHELL", is_readonly=False)
        trade_tool = fixture.CountingTool(name="fake_trade_write", risk_level="R4_TRADE_WRITE", is_readonly=False)
        shell_decision = _execute_denied_tool(
            context=context,
            writer=writer,
            tool=shell_tool,
            surface="remote_api",
            mode="observe",
            params={"command": "echo demo-denied"},
        )
        trade_decision = _execute_denied_tool(
            context=context,
            writer=writer,
            tool=trade_tool,
            surface="scheduler",
            mode="warn",
            params={"symbol": "DEMO", "quantity": 1},
        )
    finally:
        writer.close()

    decisions = [shell_decision, trade_decision]
    decision_ids = [decision["decision_id"] for decision in decisions]
    built = build_card_evidence(
        context,
        research_card=fixture.research_card(decision_ids),
        scorecard=fixture.scorecard(decision_ids),
        policy_decision_ids=decision_ids,
    )
    index = context.index_store.get(fixture.RUN_ID)
    api_decision_ids = policy_decision_ids_via_api(context, fixture.RUN_ID)
    artifacts = built.artifacts
    result = {
        "demo": "remote_shell_live_write_trap",
        "builder": BUILDER_NAME,
        "verifier": VERIFIER_NAME,
        "run_id": fixture.RUN_ID,
        "shell_execution_counter": shell_tool.execution_counter,
        "trade_execution_counter": trade_tool.execution_counter,
        "decisions": decisions,
        "index_policy_decision_ids": list(index.policy_decision_ids) if index is not None else [],
        "api_policy_decision_ids": api_decision_ids,
        "scorecard": artifacts.scorecard.model_dump(mode="json"),
        "research_card": artifacts.research_card,
        "evidence_closure_report": built.report.model_dump(mode="json"),
        "artifact_refs": {
            "policy_decisions": list(index.policy_decision_artifact_refs) if index is not None else [],
            "claim_set": artifacts.claim_set_artifact_id,
            "methodology_facts": artifacts.methodology_fact_artifact_id,
            "scorecard": artifacts.scorecard_artifact_id,
            "research_card": artifacts.research_card_artifact_id,
        },
    }
    write_demo_summary(context, result)
    return result


def _execute_denied_tool(
    *,
    context,
    writer,
    tool: fixture.CountingTool,
    surface: str,
    mode: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    recorder = DecisionRecorder(
        artifact_store=context.artifact_store,
        trace_writer=writer,
        evidence_index=context.index_store,
        evidence_outbox=context.outbox,
        generated_by="remote_shell_live_write_trap.runner",
    )
    governed = build_governed_tool_registry(
        fixture.registry_with(tool),
        surface=surface,
        mode=mode,
        run_id=fixture.RUN_ID,
        decision_recorder=recorder,
    )
    try:
        governed.execute(tool.name, params)
    except PolicyDenied as exc:
        envelope = exc.envelope
        return {
            "decision_id": envelope.decision_id,
            "tool_name": envelope.tool_name,
            "surface": envelope.surface,
            "mode": envelope.mode,
            "risk_level": envelope.risk_level,
            "status": envelope.status,
            "deny_barrier_engaged": envelope.deny_barrier_engaged,
            "inner_tool_executed": envelope.inner_tool_executed,
            "artifact_ref": envelope.evidence_identity.policy_decision_artifact_id,
            "trace_event_ref": envelope.evidence_identity.trace_event_id,
        }
    raise AssertionError(f"{tool.name} unexpectedly executed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Use isolated local demo stores only.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for local demo evidence.")
    args = parser.parse_args(argv)
    json_main(run_demo(output_dir=args.output_dir, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
