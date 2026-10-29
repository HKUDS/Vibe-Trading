"""Persistence and revision contracts for versioned research artifacts."""

from __future__ import annotations

import pytest
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from src.research_artifacts import ResearchArtifactStore


def _save(store: ResearchArtifactStore, **overrides):
    payload = {
        "subject": "NVDA fundamental review",
        "universe": "NVDA",
        "content": "Original conclusion with traceable evidence.",
        "data_as_of": "2026-10-20",
        "evidence": [
            {"source_uri": "https://example.com/filing", "content_hash": "abc"}
        ],
        "verification_status": "verified",
        "hypothesis_id": "hyp_nvda",
        "goal_id": "goal_nvda",
        "session_id": "session-a",
        "run_id": "run-a",
    }
    payload.update(overrides)
    return store.save(**payload)


def test_save_search_and_reload_across_instances(tmp_path):
    db_path = tmp_path / "research.db"
    store = ResearchArtifactStore(db_path)
    saved = _save(store)
    store.close()

    reloaded = ResearchArtifactStore(db_path)
    found = reloaded.search(subject="NVDA fundamental review", run_id="run-a")

    assert saved.created is True
    assert [item.revision_id for item in found] == [saved.revision.revision_id]
    assert found[0].evidence[0]["source_uri"] == "https://example.com/filing"
    assert found[0].evidence_missing is False
    assert (
        reloaded.get_revision(saved.revision.revision_id).content
        == saved.revision.content
    )


def test_identical_content_and_provenance_are_idempotent(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    repeated = _save(store)

    assert repeated.created is False
    assert repeated.revision.revision_id == first.revision.revision_id
    assert len(store.list_revisions(first.revision.artifact_id)) == 1


def test_changed_data_as_of_and_evidence_create_linked_revisions(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    second = _save(
        store, artifact_id=first.revision.artifact_id, data_as_of="2026-10-27"
    )
    third = _save(
        store,
        artifact_id=first.revision.artifact_id,
        data_as_of="2026-10-27",
        evidence=[{"source_uri": "https://example.com/new-filing"}],
    )

    assert second.created is True
    assert second.revision.revision_number == 2
    assert second.revision.previous_revision_id == first.revision.revision_id
    assert third.revision.previous_revision_id == second.revision.revision_id
    history = store.list_revisions(first.revision.artifact_id)
    assert [item.revision_id for item in history] == [
        third.revision.revision_id,
        second.revision.revision_id,
        first.revision.revision_id,
    ]
    assert history[-1].content == first.revision.content
    assert history[-1].data_as_of == "2026-10-20"


def test_missing_evidence_and_verification_status_remain_visible(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    saved = _save(store, evidence=[], verification_status="unverified")

    result = saved.revision.to_dict()
    assert result["evidence_missing"] is True
    assert result["verification_status"] == "unverified"
    assert result["data_as_of"] == "2026-10-20"


def test_search_defaults_to_latest_revision_and_supports_link_filters(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    latest = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Updated conclusion.",
        data_as_of="2026-10-27",
        run_id="run-b",
    )
    _save(
        store,
        subject="MSFT sector review",
        universe="MSFT",
        content="Different sector conclusion.",
        hypothesis_id="hyp_msft",
        goal_id="goal_msft",
        session_id="session-b",
        run_id="run-c",
    )

    assert store.search(query="Original conclusion") == []
    assert [item.revision_id for item in store.search(query="Updated conclusion")] == [
        latest.revision.revision_id
    ]
    assert [item.revision_id for item in store.search(goal_id="goal_nvda")] == [
        latest.revision.revision_id
    ]
    assert len(store.search()) == 2
    assert len(store.list_revisions(first.revision.artifact_id)) == 2


def test_revision_requires_existing_series_and_preserves_subject(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    with pytest.raises(KeyError):
        _save(store, artifact_id="ra_missing")

    first = _save(store)
    with pytest.raises(ValueError, match="preserve the artifact subject"):
        _save(
            store, artifact_id=first.revision.artifact_id, subject="Different subject"
        )
    with pytest.raises(ValueError, match="content is required"):
        _save(store, content="   ")


def test_changed_revision_does_not_inherit_verification(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    changed = store.save(
        artifact_id=first.revision.artifact_id,
        content="New conclusion",
        data_as_of="2026-10-27",
    )
    assert changed.revision.verification_status == "unverified"
    assert (
        store.get_revision(first.revision.revision_id).verification_status == "verified"
    )


def test_revision_idempotency_cannot_return_another_series(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="A")
    other = _save(store, content="B")
    changed = _save(store, artifact_id=first.revision.artifact_id, content="B")
    assert changed.created
    assert changed.revision.artifact_id == first.revision.artifact_id
    assert changed.revision.revision_id != other.revision.revision_id


def test_concurrent_instances_append_a_single_serial_revision_chain(
    tmp_path, monkeypatch
):
    db = tmp_path / "research.db"
    first = _save(ResearchArtifactStore(db))
    stores = [ResearchArtifactStore(db) for _ in range(4)]
    start = threading.Barrier(len(stores))
    for store in stores:
        original = store._latest

        def slow_latest(artifact_id, original=original):
            result = original(artifact_id)
            time.sleep(0.03)
            return result

        monkeypatch.setattr(store, "_latest", slow_latest)

    def revise(index):
        start.wait(timeout=5)
        return _save(
            stores[index],
            artifact_id=first.revision.artifact_id,
            content=f"Concurrent revision {index}",
        )

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(revise, range(4)))
        assert sorted(r.revision.revision_number for r in results) == [2, 3, 4, 5]
        history = stores[0].list_revisions(first.revision.artifact_id)
        assert [r.previous_revision_id for r in history[:-1]] == [
            r.revision_id for r in history[1:]
        ]
    finally:
        for store in stores:
            store.close()


def test_nonfinite_evidence_is_rejected_before_persistence(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    with pytest.raises(ValueError):
        _save(store, evidence=[{"value": float("nan")}])
