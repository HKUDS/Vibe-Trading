"""Tests for the additive factor-research run contract."""

from __future__ import annotations

import json

import pytest

from src.factors.research_contract import (
    RESEARCH_CONTRACT_SCHEMA,
    build_research_contract,
)


def test_contract_is_json_safe_and_preserves_stage_lineage() -> None:
    contract = build_research_contract(
        mode="strict",
        stage="composite_evaluation",
        universe="csi300",
        period="2020-2025",
        factor_ids=["value", "value", "momentum"],
        lineage=["value_raw", {"kind": "neutralized", "id": "momentum_neutralized"}],
        transformations=[
            {"kind": "neutralization", "controls": ["industry", "size"]},
            "walk_forward_combination",
        ],
        evaluation={"horizon": 21, "method": "icir"},
    )

    assert contract["schema"] == RESEARCH_CONTRACT_SCHEMA
    assert contract["mode"] == "strict"
    assert contract["stage"] == "composite_evaluation"
    assert contract["factor_ids"] == ["value", "momentum"]
    assert contract["factor_count"] == 2
    assert contract["lineage"][0] == {"id": "value_raw"}
    assert contract["transformations"][1] == {"id": "walk_forward_combination"}
    json.dumps(contract, ensure_ascii=True, allow_nan=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "audit"),
        ("stage", "unknown_stage"),
    ],
)
def test_contract_rejects_unknown_enums(field: str, value: str) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=field):
        build_research_contract(**kwargs)


def test_contract_rejects_non_json_extension_records() -> None:
    with pytest.raises(ValueError, match="lineage"):
        build_research_contract(lineage=[{"hash": object()}])
