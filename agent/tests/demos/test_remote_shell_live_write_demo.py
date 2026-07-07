"""Phase 8 demo coverage for remote shell and live-write deny barriers."""

from __future__ import annotations

from pathlib import Path


def test_remote_shell_live_write_demo_records_deny_barrier_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    monkeypatch.setenv("VIBE_TRADING_GOVERNANCE_MODE", "observe")

    from examples.irr_agl_demos.remote_shell_live_write_trap.runner import run_demo

    result = run_demo(output_dir=tmp_path, dry_run=True)

    assert result["demo"] == "remote_shell_live_write_trap"
    assert result["shell_execution_counter"] == 0
    assert result["trade_execution_counter"] == 0
    assert len(result["decisions"]) == 2
    assert all(decision["deny_barrier_engaged"] is True for decision in result["decisions"])
    assert all(decision["inner_tool_executed"] is False for decision in result["decisions"])
    assert all(decision["status"] == "shadow_denied" for decision in result["decisions"])

    decision_ids = [decision["decision_id"] for decision in result["decisions"]]
    assert result["index_policy_decision_ids"] == decision_ids
    assert result["api_policy_decision_ids"] == decision_ids
    assert result["research_card"]["policy_decision_ids"] == decision_ids
    assert result["evidence_closure_report"]["passed"] is True
    assert result["evidence_closure_report"]["required_refs_present"]["policy_decision_ids"] is True
    assert result["evidence_closure_report"]["required_refs_present"]["policy_decision_artifact_refs"] is True
    assert result["evidence_closure_report"]["required_refs_present"]["trace_event_refs"] is True


def test_remote_shell_live_write_readme_makes_no_tradability_claim() -> None:
    readme = Path("agent/examples/irr_agl_demos/remote_shell_live_write_trap/README.md").read_text(encoding="utf-8").lower()

    assert "profitable" not in readme
    assert "profitability" not in readme
    assert "tradable strategy" not in readme
