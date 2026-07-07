"""Fixture inputs for the overfit best-trial trap demo."""

from __future__ import annotations

RUN_ID = "demo_overfit_best_trial_trap"


def trial_events() -> list[dict]:
    """Return eight deterministic trial events with the selected trial visible."""
    sharpes = [0.31, 0.44, 0.27, 0.53, 0.49, 0.58, 1.91, 0.36]
    return [
        {
            "event_type": "trial",
            "trial_id": f"trial_{index + 1:02d}",
            "params": {"lookback": 10 + index * 5},
            "metrics": {"sharpe": sharpe, "turnover": round(0.18 + index * 0.01, 2)},
            "selected": index == 6,
        }
        for index, sharpe in enumerate(sharpes)
    ]


def trial_ledger() -> dict:
    """Return a TrialLedger-shaped deterministic payload."""
    events = trial_events()
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "trial_count": len(events),
        "events": events,
        "selected_trial_id": "trial_07",
    }


def selected_trial() -> dict:
    """Return the disclosed selected trial."""
    return next(event for event in trial_events() if event["selected"])


def protocol() -> dict:
    """Return enough methodology context to avoid unrelated scorecard gates."""
    return {
        "schema_version": "1.2.1",
        "protocol_id": "protocol_overfit_best_trial_trap",
        "protocol_hash": "protocol_hash_overfit_best_trial_trap",
        "registered": True,
        "hypothesis": "A deterministic fixture checks whether trial selection is disclosed.",
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
    """Return a raw scorecard that discloses the best-trial selection."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "research_candidate",
        "metrics": {
            "best_trial": "trial_07",
            "selected_trial": "trial_07",
            "sharpe": 1.91,
            "trial_count": 8,
        },
        "warnings": ["selection_disclosure: 8 trials evaluated; selected trial is trial_07"],
    }


def research_card() -> dict:
    """Return a raw card input that keeps trial count and selected trial visible."""
    return {
        "schema_version": "1.2.1",
        "run_id": RUN_ID,
        "conclusion_level": "research_candidate",
        "title": "Overfit Best Trial Trap",
        "trial_count": 8,
        "selected_trial": selected_trial(),
        "warnings": ["selection_disclosure: 8 trials evaluated; selected trial is trial_07"],
        "structured_claims": [
            {
                "claim_type": "alpha",
                "claim_text": "The selected trial reports benchmark-relative alpha before selection adjustment.",
                "source": "research_card",
                "source_ref": "fixture.overfit_best_trial_trap.research_card",
            }
        ],
    }
