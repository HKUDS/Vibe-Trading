"""Unit tests for FactorCandidate, CandidatesManifest, and DATA_UNAVAILABLE."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from schemas import CandidatesManifest, FactorCandidate, FactorVerdict


VALID_CANDIDATE = {
    "name": "funding_z_30d",
    "formula": "z_score(funding_rate, 30d)",
    "data_source": "okx_funding",
    "transform": "z_30d",
    "expected_ic_sign": "+",
    "economic_logic": "Elevated funding rates predict mean reversion in perpetual futures.",
    "horizons_h": [1, 4, 24],
    "category": "funding",
}


def test_missing_required_field_raises():
    """(a) Missing economic_logic raises ValidationError."""
    data = {k: v for k, v in VALID_CANDIDATE.items() if k != "economic_logic"}
    with pytest.raises(ValidationError):
        FactorCandidate(**data)


def test_invalid_category_raises():
    """(b) category not in {funding, basis, oi} raises ValidationError."""
    data = {**VALID_CANDIDATE, "category": "volume"}
    with pytest.raises(ValidationError):
        FactorCandidate(**data)


def test_invalid_expected_ic_sign_raises():
    """(c) expected_ic_sign not in {+, -, ?} raises ValidationError."""
    data = {**VALID_CANDIDATE, "expected_ic_sign": "~"}
    with pytest.raises(ValidationError):
        FactorCandidate(**data)


def test_valid_factor_candidate():
    """(d) Valid full FactorCandidate passes validation."""
    candidate = FactorCandidate(**VALID_CANDIDATE)
    assert candidate.name == "funding_z_30d"
    assert candidate.category == "funding"
    assert candidate.expected_ic_sign == "+"


def test_valid_candidates_manifest():
    """(e) Valid CandidatesManifest with a list of candidates passes validation."""
    manifest = CandidatesManifest(
        symbol="BTC",
        generated_at=datetime(2026, 5, 24, 0, 0, 0),
        candidates=[FactorCandidate(**VALID_CANDIDATE)],
    )
    assert manifest.symbol == "BTC"
    assert len(manifest.candidates) == 1
    assert manifest.schema_version == 1
    assert manifest.source_swarm_run is None


def test_data_unavailable_verdict():
    """(f) DATA_UNAVAILABLE is a valid member of FactorVerdict and equals 'data_unavailable'."""
    assert FactorVerdict.DATA_UNAVAILABLE == "data_unavailable"
    assert FactorVerdict("data_unavailable") is FactorVerdict.DATA_UNAVAILABLE
