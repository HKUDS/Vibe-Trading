"""Tests for v1.2.1 structured research claims."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.governance.evidence_index import EvidenceIndexStore
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.extractor import build_claim_set_from_research_card
from src.reliability.claims.validators import validate_claim_set
from src.research_card.builder import build_research_card_evidence_artifacts


def test_claimset_captures_tradable_claim_from_card_conclusion() -> None:
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": "run_claim_tradable",
            "conclusion_level": "research_candidate",
            "structured_claims": [
                {
                    "claim_type": "tradable",
                    "claim_text": "The strategy is tradable after applying the configured cost model.",
                    "source_ref": "research_card.structured_claims[0]",
                    "confidence": 0.86,
                    "evidence_refs": ["art_cost_model"],
                }
            ],
        }
    )

    assert [claim.claim_type for claim in claim_set.claims] == ["tradable"]
    assert claim_set.claims[0].source == "research_card"
    assert claim_set.claims[0].evidence_refs == ["art_cost_model"]


def test_claimset_captures_alpha_claim_from_structured_card_field() -> None:
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": "run_claim_alpha",
            "claims": {
                "alpha": {
                    "claim_text": "The factor shows alpha versus the benchmark.",
                    "source_ref": "research_card.claims.alpha",
                    "confidence": 0.78,
                }
            },
        }
    )

    assert len(claim_set.claims) == 1
    assert claim_set.claims[0].claim_type == "alpha"
    assert claim_set.claims[0].source_ref == "research_card.claims.alpha"


def test_claimset_no_secret_in_claim_text_or_metadata() -> None:
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": "run_claim_secret",
            "structured_claims": [
                {
                    "claim_type": "alpha",
                    "claim_text": "alpha supported by sk-test-secret-value-abcdefghijklmnopqrstuvwxyz",
                    "source_ref": "research_card.structured_claims[0]",
                }
            ],
        },
        validate=False,
    )

    with pytest.raises(ValueError, match="secret"):
        validate_claim_set(claim_set)


def test_implicit_claim_generated_for_research_candidate() -> None:
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": "run_claim_implicit",
            "conclusion_level": "research_candidate",
            "summary": "Structured evidence supports further research.",
        }
    )

    assert len(claim_set.claims) == 1
    assert claim_set.claims[0].claim_type == "generalization"
    assert claim_set.claims[0].source_ref == "research_card.conclusion_level"


def test_claimset_artifact_registered_and_indexed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")

    result = build_research_card_evidence_artifacts(
        {
            "run_id": "run_claim_artifact",
            "conclusion_level": "research_candidate",
            "structured_claims": [
                {
                    "claim_type": "tradable",
                    "claim_text": "The strategy is tradable with explicit costs.",
                    "source_ref": "research_card.structured_claims[0]",
                }
            ],
        },
        artifact_store=artifact_store,
        evidence_index=index_store,
    )

    claim_record = artifact_store.get_record(result.claim_set_artifact_id)
    fact_record = artifact_store.get_record(result.methodology_fact_artifact_id)
    index = index_store.get("run_claim_artifact")

    assert claim_record is not None
    assert claim_record.artifact_type == "claim_set"
    assert fact_record is not None
    assert fact_record.artifact_type == "methodology_facts"
    assert index is not None
    assert index.claim_set_artifact_refs == [result.claim_set_artifact_id]
    assert index.methodology_fact_artifact_refs == [result.methodology_fact_artifact_id]
