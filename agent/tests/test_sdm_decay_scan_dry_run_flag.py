"""sdm_decay_scan reads a JSON-string dry_run flag by its value."""

import json

import pytest

from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchResult,
    DecaySignal,
    DecaySnapshot,
)
from src.strategy_store.store import InMemoryStrategyStore
from src.tools.sdm_decay_scan_tool import SdmDecayScanTool


def _decaying_store(monkeypatch):
    store = InMemoryStrategyStore()
    monkeypatch.setattr("src.tools.sdm_decay_scan_tool._get_store", lambda: store)
    aid = store.register_artifact(
        Artifact(
            id="",
            name="decay_factor",
            type=ArtifactType.FACTOR,
            universe="CSI300",
            status=ArtifactStatus.ACTIVE,
        )
    )
    for _ in range(5):
        store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.08))
    for _ in range(5):
        store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.04))
    for _ in range(2):
        store.record_decay_snapshot(
            DecaySnapshot(artifact_id=aid, ic_ratio=0.5, decay_signal=DecaySignal.WARNING)
        )
    return store, aid


@pytest.mark.parametrize("flag", ["false", "False", "0", "no"])
def test_string_false_dry_run_applies_the_transition(monkeypatch, flag):
    store, aid = _decaying_store(monkeypatch)

    result = json.loads(SdmDecayScanTool().execute(dry_run=flag))

    assert result["dry_run"] is False
    assert result["transitions_applied"] == 1
    assert store.get_artifact(aid).status == ArtifactStatus.MONITORING


def test_string_true_dry_run_changes_nothing(monkeypatch):
    store, aid = _decaying_store(monkeypatch)

    result = json.loads(SdmDecayScanTool().execute(dry_run="true"))

    assert result["dry_run"] is True
    assert result["transitions_applied"] == 0
    assert store.get_artifact(aid).status == ArtifactStatus.ACTIVE
