"""Fixture inputs for the future-data trap demo."""

from __future__ import annotations

RUN_ID = "demo_future_data_trap"


def data_audit() -> dict:
    """Return a deterministic data audit with a point-in-time violation."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "pit_safe": False,
        "pit_violations": [
            {
                "field": "future_return_5d",
                "detected_in": "feature_matrix",
                "reason": "Label-derived future return was available before the decision timestamp.",
            }
        ],
        "checked_rows": 240,
    }


def protocol() -> dict:
    """Return a registered protocol so the PIT rule is the decisive failure."""
    return {
        "schema_version": "1.2.1",
        "protocol_id": "protocol_future_data_trap",
        "protocol_hash": "protocol_hash_future_data_trap",
        "registered": True,
        "hypothesis": "A deterministic fixture tests whether PIT violations override high metrics.",
        "universe": {"asset_class": "equity"},
        "split_policy": {
            "method": "train_test",
            "test_start": "2024-01-01",
            "test_end": "2024-06-30",
        },
        "benchmark_policy": {"primary": "SPY"},
        "cost_model": {"commission_bps": 1.0, "slippage_bps": 2.0},
        "execution_assumptions": {"bar": "close"},
    }


def scorecard() -> dict:
    """Return optimistic raw metrics that must not override the PIT failure."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "paper_trade_candidate",
        "metrics": {"sharpe": 4.2, "max_drawdown": -0.03, "trial_count": 1},
        "warnings": [],
    }


def research_card() -> dict:
    """Return a raw card input with a structured strong research claim."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "paper_trade_candidate",
        "title": "Future Data Trap",
        "trial_count": 1,
        "structured_claims": [
            {
                "claim_type": "generalization",
                "claim_text": "The reported result generalizes across the declared evaluation split.",
                "source": "research_card",
                "source_ref": "fixture.future_data_trap.research_card",
            }
        ],
    }
