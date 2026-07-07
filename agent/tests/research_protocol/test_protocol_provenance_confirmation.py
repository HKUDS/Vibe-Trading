"""Tests for v1.2.1 protocol provenance confirmation gates."""

from __future__ import annotations

import pytest

from src.research_protocol.extractor import extract_protocol_provenance
from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.ledger import record_protocol_field_confirmation
from src.research_protocol.protocol_review import review_protocol_for_registration
from src.research_protocol.registry import ProtocolRegistrationError, ResearchProtocol, protocol_hash, register_protocol


def _complete_protocol() -> dict[str, object]:
    return {
        "schema_version": "1.2.1",
        "protocol_id": "proto_complete",
        "hypothesis": "A conservative reversal factor may survive costs.",
        "universe": {"asset_class": "equity"},
        "split_policy": {
            "method": "walk_forward",
            "test_start": "2024-01-01",
            "test_end": "2024-12-31",
        },
        "benchmark_policy": {"primary": "CSI300"},
        "cost_model": {"commission_bps": 3},
        "execution_assumptions": {"rebalance": "daily_close"},
    }


def test_draft_allows_missing_and_inferred_fields() -> None:
    protocol = {"protocol_id": "proto_draft", "hypothesis": "Draft hypothesis"}
    provenance = [
        ProtocolFieldProvenance(field_path="universe.asset_class", source="missing"),
        ProtocolFieldProvenance(
            field_path="split_policy.method",
            source="inferred",
            requires_confirmation=True,
            confirmation_status="pending",
        ),
    ]

    review = review_protocol_for_registration(protocol, provenance, target_status="draft")

    assert review.can_register is True
    assert review.blocking_fields == []
    assert "split_policy.method" in review.confirmation_required_fields


def test_registered_blocks_missing_core_field() -> None:
    protocol = _complete_protocol()
    protocol["universe"] = {}
    provenance = extract_protocol_provenance(protocol)

    review = review_protocol_for_registration(protocol, provenance, target_status="registered")

    assert review.can_register is False
    assert "universe.asset_class" in review.blocking_fields
    with pytest.raises(ProtocolRegistrationError, match="universe.asset_class"):
        register_protocol(protocol, provenance)


def test_registered_blocks_unconfirmed_inferred_core_field() -> None:
    protocol = _complete_protocol()
    provenance = extract_protocol_provenance(protocol)
    provenance.append(
        ProtocolFieldProvenance(
            field_path="benchmark_policy.primary",
            source="inferred",
            requires_confirmation=True,
            confirmation_status="pending",
        )
    )

    review = review_protocol_for_registration(protocol, provenance, target_status="registered")

    assert review.can_register is False
    assert "benchmark_policy.primary" in review.blocking_fields


def test_confirmation_event_allows_registration() -> None:
    protocol = _complete_protocol()
    provenance = extract_protocol_provenance(protocol)
    event = record_protocol_field_confirmation(
        protocol_id="proto_complete",
        field_path="benchmark_policy.primary",
        value="CSI300",
        confirmed_by="pytest",
    )
    provenance.append(
        ProtocolFieldProvenance(
            field_path="benchmark_policy.primary",
            source="inferred",
            requires_confirmation=True,
            confirmation_status="confirmed",
            confirmation_event_hash=event.event_hash,
        )
    )

    registered = register_protocol(protocol, provenance)

    assert registered.status == "registered"
    assert registered.review.can_register is True
    assert event.event_hash == provenance[-1].confirmation_event_hash


def test_provenance_metadata_does_not_change_protocol_hash() -> None:
    protocol = _complete_protocol()
    first = protocol_hash(ResearchProtocol.model_validate(protocol))
    second = protocol_hash(
        ResearchProtocol.model_validate(
            {
                **protocol,
                "provenance": [
                    {
                        "field_path": "hypothesis",
                        "source": "explicit_user",
                        "evidence_text": "User said it directly.",
                    }
                ],
            }
        )
    )

    assert first == second


def test_registration_status_does_not_change_protocol_hash() -> None:
    protocol = _complete_protocol()
    provenance = extract_protocol_provenance(protocol)

    registered = register_protocol(protocol, provenance)

    assert registered.protocol_hash == protocol_hash(ResearchProtocol.model_validate(protocol))


def test_system_default_requires_default_rule_id() -> None:
    with pytest.raises(ValueError, match="default_rule_id"):
        ProtocolFieldProvenance(field_path="split_policy.method", source="system_default")


def test_old_protocol_fixture_loads_without_provenance() -> None:
    protocol = ResearchProtocol.model_validate(
        {
            "schema_version": "1.2.0",
            "protocol_id": "proto_old",
            "hypothesis": "Old fixture loads.",
            "universe": {"asset_class": "equity"},
        }
    )

    assert protocol.provenance == []
    assert protocol.status == "draft"
