from __future__ import annotations

import json
from pathlib import Path

from src.reliability.artifacts.hashing import sha256_json
from src.reliability.data.contracts import DataAuditReport
from src.reliability.quant.scorecard import BacktestReliabilityScorecard, SCORECARD_DIMENSION_KEYS
from src.research_card.model import ResearchCard
from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.model import ResearchProtocol


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "schema_migration"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_protocol_v1_0_fixture_validates_and_hash_is_stable() -> None:
    protocol = ResearchProtocol.model_validate(_load_fixture("protocol_v1_0.json"))

    assert protocol.schema_version == "1.0.0"
    assert protocol.status == "registered"
    assert protocol.evaluation_plan.ic_horizons == [1, 5, 20]
    assert compute_protocol_hash(protocol) == protocol.protocol_hash


def test_data_audit_v1_0_fixture_keeps_source_provenance() -> None:
    audit = DataAuditReport.model_validate(_load_fixture("data_audit_v1_0.json"))

    assert audit.schema_version == "1.0.0"
    assert audit.access_contract.explicit_local is True
    assert audit.access_contract.source == "local:fixture"
    assert audit.access_contract.fallback_chain == ["local:fixture"]
    assert audit.all_sources_open is False
    assert "secret" not in json.dumps(audit.model_dump(mode="json"), ensure_ascii=False).lower()


def test_scorecard_v1_0_fixture_uses_standard_dimension_whitelist() -> None:
    scorecard = BacktestReliabilityScorecard.model_validate(_load_fixture("scorecard_v1_0.json"))

    assert scorecard.schema_version == "1.0.0"
    assert set(scorecard.score_breakdown) == set(SCORECARD_DIMENSION_KEYS)
    assert "dsr" not in scorecard.score_breakdown
    assert "pbo" not in scorecard.score_breakdown
    assert {"dsr", "pbo"} <= set(scorecard.experimental_metrics)
    assert not {item.code for item in scorecard.hard_failures} & {"DSR", "PBO", "QUANT_DSR_GATE", "QUANT_PBO_GATE"}


def test_research_card_v1_0_fixture_validates_optional_scorecard_refs() -> None:
    card = ResearchCard.model_validate(_load_fixture("research_card_v1_0.json"))

    assert card.schema_version == "1.0.0"
    assert card.scorecard is not None
    assert card.scorecard.scorecard_id == "sc_schema_fixture_v1"
    assert card.data_audit_refs == ["audit_schema_fixture_v1"]
    assert card.backtest_refs == ["backtest://fixture/run-1"]
    assert card.conclusion_level == "research_candidate"


def test_schema_migration_fixtures_are_canonical_hashable_json() -> None:
    for fixture_name in (
        "research_card_v1_0.json",
        "protocol_v1_0.json",
        "data_audit_v1_0.json",
        "scorecard_v1_0.json",
    ):
        digest = sha256_json(_load_fixture(fixture_name))
        assert len(digest) == 64
