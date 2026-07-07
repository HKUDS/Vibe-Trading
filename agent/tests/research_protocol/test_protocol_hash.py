from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.model import UniverseSpec

from .test_protocol_models import make_protocol


GOLDEN_PROTOCOL_HASH = "c78e4d2f6be110a879541467a317fc837b0c365ad9040957143a468a7fec7109"


def test_protocol_hash_stable_for_fixture() -> None:
    assert compute_protocol_hash(make_protocol()) == GOLDEN_PROTOCOL_HASH


def test_protocol_hash_changes_when_universe_changes() -> None:
    original = compute_protocol_hash(make_protocol())
    changed = compute_protocol_hash(
        make_protocol(
            universe=UniverseSpec(
                asset_class="ashare",
                universe_name="zz500",
                point_in_time=True,
            )
        )
    )

    assert changed != original


def test_protocol_hash_ignores_metadata_and_ids() -> None:
    original = compute_protocol_hash(make_protocol())
    noisy = make_protocol(
        protocol_id="proto_other",
        protocol_hash="old_hash",
        status="registered",
        created_by="someone_else",
        metadata={"note": "this should not affect research design"},
    )

    assert compute_protocol_hash(noisy) == original


def test_protocol_hash_rejects_nan() -> None:
    with pytest.raises(ValidationError, match="finite"):
        make_protocol(cost_model={"commission_bps": math.nan})
