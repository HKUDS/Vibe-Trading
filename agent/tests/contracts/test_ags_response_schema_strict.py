from __future__ import annotations

from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_quality.decision.model import AdvisoryCode, HardFailureCode, QualityDecision


def test_alpha_genesis_report_schema_keys_are_stable_and_research_only() -> None:
    report = build_alpha_genesis_report(report_id="schema", candidate_id="candidate")
    payload = report.to_dict()

    assert set(payload) == {
        "report_id",
        "candidate_id",
        "parent_seed_id",
        "formula",
        "formula_hash",
        "factor_definition_hash",
        "data_snapshot_hash",
        "pit_contract_present",
        "survivorship_bias",
        "split_config",
        "data_scope",
        "predictive_metrics",
        "robustness_metrics",
        "tradability_metrics",
        "novelty_metrics",
        "synergy_metrics",
        "hard_failures",
        "warnings",
        "decision",
        "cap_reasons",
        "trial_count",
        "trial_group_id",
        "limitations",
        "non_goals",
        "metadata",
        "generated_at",
        "schema_version",
    }
    assert payload["schema_version"] == "alpha_genesis_report.v1"
    assert payload["decision"] in {item.value for item in QualityDecision}
    assert "not live trading advice" in payload["non_goals"]


def test_ags_code_enums_include_agents_contract_codes() -> None:
    assert {
        "LOOKAHEAD_DETECTED",
        "TEST_SET_CONTAMINATED",
        "PIT_CONTRACT_MISSING",
        "NON_REPRODUCIBLE",
        "INSUFFICIENT_SAMPLE",
        "OOS_IC_COLLAPSE",
        "COST_EXCEEDS_ALPHA",
        "EXECUTION_RETURN_MISSING",
        "DUPLICATE_ALPHA",
        "FACTOR_FORMULA_AMBIGUOUS",
        "SCORECARD_OVERRIDE_ATTEMPT",
    }.issubset({item.value for item in HardFailureCode})
    assert {
        "HIGH_PBO_PROXY",
        "LOW_DEFLATED_SHARPE",
        "RECENT_DECAY",
        "HIGH_TURNOVER",
        "UNEXPLAINED_EXPOSURE",
        "HIGH_CROWDING",
        "EOD_PROXY_LIMITATION",
        "LOW_CAPACITY",
    }.issubset({item.value for item in AdvisoryCode})
