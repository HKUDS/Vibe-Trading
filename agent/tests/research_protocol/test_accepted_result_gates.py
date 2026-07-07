from __future__ import annotations

from pathlib import Path

import pytest

from src.research_protocol.acceptance import (
    AcceptanceError,
    AcceptedResult,
    validate_accepted_result,
)
from src.research_protocol.registry import ProtocolRegistry

from .test_protocol_models import make_protocol


def _registered_hash(tmp_path: Path) -> str:
    registry = ProtocolRegistry(root=tmp_path / "protocols", artifact_root=tmp_path / "artifacts")
    draft = registry.save_draft(make_protocol())
    return registry.register(draft.protocol_id, created_by="tester").protocol_hash


def _accepted(protocol_hash: str, **updates) -> AcceptedResult:
    payload = {
        "protocol_hash": protocol_hash,
        "trial_count": 3,
        "data_audit_ids": ["audit_1"],
        "policy_decision_ids": ["pd_1"],
        "backtest_artifact_refs": ["art_backtest_1"],
        "alpha_artifact_refs": [],
        "best_trial": False,
        "selection_policy": None,
        "abandoned_count": 0,
        "rejected_count": 0,
    }
    payload.update(updates)
    return AcceptedResult(**payload)


def test_accepted_result_requires_registered_protocol(tmp_path: Path) -> None:
    registry = ProtocolRegistry(root=tmp_path / "protocols", artifact_root=tmp_path / "artifacts")

    with pytest.raises(AcceptanceError, match="registered protocol"):
        validate_accepted_result(_accepted("missing_hash"), registry=registry)


def test_accepted_result_requires_trial_count(tmp_path: Path) -> None:
    protocol_hash = _registered_hash(tmp_path)

    with pytest.raises(AcceptanceError, match="trial_count"):
        validate_accepted_result(_accepted(protocol_hash, trial_count=None))


def test_best_trial_requires_selection_policy(tmp_path: Path) -> None:
    protocol_hash = _registered_hash(tmp_path)

    with pytest.raises(AcceptanceError, match="selection policy"):
        validate_accepted_result(
            _accepted(protocol_hash, best_trial=True, selection_policy=None, abandoned_count=1, rejected_count=1)
        )

    with pytest.raises(AcceptanceError, match="abandoned/rejected"):
        validate_accepted_result(
            _accepted(protocol_hash, best_trial=True, selection_policy="highest OOS IC")
        )
