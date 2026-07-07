from __future__ import annotations

from pathlib import Path

import pytest

from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.registry import ProtocolImmutableError, ProtocolRegistry

from .test_protocol_models import make_protocol


def test_registered_protocol_is_immutable(tmp_path: Path) -> None:
    registry = ProtocolRegistry(root=tmp_path / "protocols")
    draft = registry.save_draft(make_protocol())
    registered = registry.register(draft.protocol_id, created_by="tester")

    with pytest.raises(ProtocolImmutableError):
        registry.save_draft(registered.model_copy(update={"hypothesis": "changed"}))

    reloaded = registry.get(registered.protocol_id)
    assert reloaded is not None
    assert reloaded.hypothesis == draft.hypothesis
    assert reloaded.protocol_hash == compute_protocol_hash(draft)
    assert reloaded.status == "registered"


def test_register_creates_artifact_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    registry = ProtocolRegistry(
        root=tmp_path / "protocols",
        artifact_root=tmp_path / "artifacts",
    )
    draft = registry.save_draft(make_protocol())

    registered = registry.register(draft.protocol_id, created_by="tester")

    refs = registry.artifact_refs_for(registered.protocol_hash)
    assert registered.protocol_hash
    assert refs
    assert refs[0].artifact_type == "research_protocol"
    assert refs[0].sha256
