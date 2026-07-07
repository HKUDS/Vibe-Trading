"""Research Card Phase 3 claim/fact artifact tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.reliability.artifacts.store import ArtifactStore
from src.research_card.builder import build_research_card_evidence_artifacts


def test_research_card_generates_implicit_claim_matching_paper_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")

    result = build_research_card_evidence_artifacts(
        {"run_id": "run_paper_candidate", "conclusion_level": "paper_trade_candidate"},
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )

    assert [claim.claim_type for claim in result.claim_set.claims] == ["paper_trade_candidate"]
