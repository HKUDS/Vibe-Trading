"""Phase 8 demo coverage for the future-data trap."""

from __future__ import annotations

from pathlib import Path


def test_future_data_trap_uses_builder_and_hard_fails_pit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")

    from examples.irr_agl_demos.future_data_trap.runner import run_demo

    result = run_demo(output_dir=tmp_path, dry_run=True)

    assert result["demo"] == "future_data_trap"
    assert result["builder"] == "src.research_card.builder.build_research_card_evidence_artifacts"
    assert result["verifier"] == "src.reliability.artifacts.verifier.EvidenceVerifier"
    assert result["data_audit"]["pit_violations"]
    assert result["methodology_facts"]["pit_safe"] is False
    assert result["methodology_facts"]["has_data_audit"] is True
    assert result["claim_set"]["claims"]
    assert any(claim["claim_type"] in {"generalization", "tradable"} for claim in result["claim_set"]["claims"])
    assert result["scorecard"]["conclusion_level"] == "not_reliable"
    assert result["scorecard"]["hard_failures"] == ["pit_violation_hard_fail"]
    assert result["triggered_rule_ids"] == ["pit_violation_hard_fail"]
    assert result["research_card"]["conclusion_level"] == "not_reliable"
    assert result["research_card"]["hard_failures"] == result["scorecard"]["hard_failures"]
    assert result["evidence_closure_report"]["passed"] is True
    assert result["evidence_closure_report"]["degraded"] is False
    assert result["artifact_refs"]["data_audit"].startswith("art_")
    assert result["artifact_refs"]["research_card"].startswith("art_")


def test_future_data_trap_readme_makes_no_tradability_claim() -> None:
    readme = Path("agent/examples/irr_agl_demos/future_data_trap/README.md").read_text(encoding="utf-8").lower()

    assert "profitable" not in readme
    assert "profitability" not in readme
    assert "tradable strategy" not in readme
