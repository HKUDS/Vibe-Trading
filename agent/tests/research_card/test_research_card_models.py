from __future__ import annotations

from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.research_card.model import ResearchCard, StructuredFailure, StructuredWarning


def test_research_card_json_roundtrip() -> None:
    card = ResearchCard(
        card_id="card_roundtrip",
        title="Mean Reversion Study",
        protocol_ref="proto_hash",
        hypothesis="Returns mean revert after large down days.",
        universe={"asset_class": "us_equity", "symbols": ["SPY"]},
        data_sources=[{"source": "local", "selected_source": "local"}],
        scorecard=BacktestReliabilityScorecard.minimal(
            scorecard_id="sc_roundtrip",
            conclusion_cap="research_candidate",
        ),
        key_metrics={"sharpe": 1.2},
        benchmark={"primary": "SPY"},
        cost_model={"commission_bps": 1.0},
        execution_assumptions={"signal_time": "close", "fill_time": "next_open"},
        oos_results={"fold_count": 3},
        warnings=[StructuredWarning(code="DATA_WARNING", message="data warning")],
        hard_failures=[StructuredFailure(code="HARD_STOP", message="hard stop")],
        reproducibility={"config_hash": "a" * 64},
        conclusion_level="not_reliable",
    )

    restored = ResearchCard.model_validate_json(card.model_dump_json())

    assert restored == card
    assert restored.schema_version == "1.0.0"


def test_hard_failures_visible() -> None:
    card = ResearchCard(
        card_id="card_failures",
        title="Study",
        hard_failures=[
            StructuredFailure(
                code="QUANT_NO_COST_MODEL_TRADABLE_CLAIM",
                message="cost model required",
            )
        ],
        conclusion_level="not_reliable",
    )

    payload = card.model_dump(mode="json")

    assert payload["hard_failures"][0]["code"] == "QUANT_NO_COST_MODEL_TRADABLE_CLAIM"
    assert payload["conclusion_level"] == "not_reliable"


def test_no_secrets_in_card() -> None:
    card = ResearchCard(
        card_id="card_secret",
        title="Study",
        data_sources=[
            {
                "source": "vendor",
                "api_key": "sk-test-secret-abcdefghijklmnopqrstuvwxyz",
                "broker_token": "Bearer abcdefghijklmnopqrstuvwxyz1234567890",
            }
        ],
        reproducibility={"env": {"OPENAI_API_KEY": "sk-test-secret-abcdefghijklmnopqrstuvwxyz"}},
    )

    payload = card.model_dump(mode="json")

    assert payload["data_sources"][0]["api_key"] == "[REDACTED]"
    assert payload["data_sources"][0]["broker_token"] == "[REDACTED]"
    assert payload["reproducibility"]["env"]["OPENAI_API_KEY"] == "[REDACTED]"
