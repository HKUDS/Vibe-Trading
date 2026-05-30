"""Unit tests for FactorCandidate, CandidatesManifest, and DATA_UNAVAILABLE."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from schemas import CandidatesManifest, FactorCandidate, FactorVerdict


VALID_CANDIDATE = {
    "name": "funding_z_30d",
    "formula": "z_score(funding_rate, 30d)",
    "feature_key": "rsi_14",
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
    """(b) category not in the allowed Literal set raises ValidationError."""
    data = {**VALID_CANDIDATE, "category": "not_a_real_category"}
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


def test_old_candidate_without_feature_key_passes():
    """Old manifests without feature_key, data_source, or transform still validate."""
    minimal = {
        "name": "funding_z_30d",
        "formula": "z_score(funding_rate, 30d)",
        "expected_ic_sign": "+",
        "economic_logic": "Elevated funding rates predict mean reversion.",
        "horizons_h": [1, 4, 24],
        "category": "funding",
    }
    candidate = FactorCandidate(**minimal)
    assert candidate.feature_key is None
    assert candidate.data_source is None
    assert candidate.transform is None


def test_new_candidates_json_validates():
    """A full JSON string with feature_key passes CandidatesManifest.model_validate_json()."""
    import json

    json_str = json.dumps({
        "schema_version": 1,
        "symbol": "BTC",
        "generated_at": "2026-05-30T00:00:00",
        "source_swarm_run": None,
        "candidates": [
            {
                "name": "rsi_14_momentum",
                "formula": "RSI(close, 14)",
                "feature_key": "rsi_14",
                "data_source": None,
                "transform": None,
                "expected_ic_sign": "+",
                "economic_logic": "RSI captures short-term momentum reversals.",
                "horizons_h": [1, 4, 24],
                "category": "momentum",
            }
        ],
    })
    manifest = CandidatesManifest.model_validate_json(json_str)
    assert manifest.symbol == "BTC"
    assert manifest.candidates[0].feature_key == "rsi_14"
    assert manifest.candidates[0].data_source is None
    assert manifest.candidates[0].transform is None
