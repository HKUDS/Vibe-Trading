"""Tests for v1.2.1 methodology fact extraction."""

from __future__ import annotations

from src.reliability.quant.methodology_facts import build_methodology_fact_set


def test_methodology_facts_reads_trial_count_from_ledger() -> None:
    facts = build_methodology_fact_set(
        run_id="run_trials",
        trial_ledger={"events": [{"event_type": "trial"} for _ in range(8)]},
    )

    assert facts.trial_count == 8


def test_methodology_facts_detects_no_cost_model() -> None:
    facts = build_methodology_fact_set(
        run_id="run_no_cost",
        protocol={"status": "registered", "benchmark_policy": {"primary": "CSI300"}},
        research_card={"execution_assumptions": {"slippage_bps": 2}},
    )

    assert facts.has_cost_model is False


def test_methodology_facts_detects_no_benchmark() -> None:
    facts = build_methodology_fact_set(
        run_id="run_no_benchmark",
        protocol={"status": "registered", "cost_model": {"commission_bps": 3}},
    )

    assert facts.has_benchmark is False


def test_methodology_facts_detects_pit_violation() -> None:
    facts = build_methodology_fact_set(
        run_id="run_pit",
        data_audit={"artifact_id": "art_audit", "pit_violations": [{"field": "close"}]},
    )

    assert facts.has_data_audit is True
    assert facts.pit_safe is False
    assert facts.generated_from_artifacts == ["art_audit"]
