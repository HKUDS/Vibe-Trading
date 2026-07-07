"""Phase 8 demo coverage for the overfit best-trial trap."""

from __future__ import annotations

from pathlib import Path


def test_overfit_best_trial_discloses_all_trials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")

    from examples.irr_agl_demos.overfit_best_trial_trap.runner import run_demo

    result = run_demo(output_dir=tmp_path, dry_run=True)

    assert result["demo"] == "overfit_best_trial_trap"
    assert result["builder"] == "src.research_card.builder.build_research_card_evidence_artifacts"
    assert result["trial_ledger"]["trial_count"] == 8
    assert len(result["trial_ledger"]["events"]) == 8
    assert result["selected_trial"]["trial_id"] == "trial_07"
    assert result["methodology_facts"]["trial_count"] == 8
    assert result["research_card"]["trial_count"] == 8
    assert result["scorecard"]["conclusion_level"] in {"not_reliable", "exploratory", "research_candidate"}
    assert result["research_card"]["conclusion_level"] in {"not_reliable", "exploratory", "research_candidate"}
    assert any("selection" in warning.lower() for warning in result["scorecard"]["warnings"])
    assert result["evidence_closure_report"]["passed"] is True
    assert result["artifact_refs"]["trial_events"]
    assert len(result["artifact_refs"]["trial_events"]) == 8


def test_overfit_best_trial_readme_makes_no_tradability_claim() -> None:
    readme = Path("agent/examples/irr_agl_demos/overfit_best_trial_trap/README.md").read_text(encoding="utf-8").lower()

    assert "profitable" not in readme
    assert "profitability" not in readme
    assert "tradable strategy" not in readme
