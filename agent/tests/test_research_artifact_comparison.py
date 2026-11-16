"""Deterministic, read-only comparison of immutable research revisions."""

from __future__ import annotations

import pytest

from src.research_artifacts import ResearchArtifactStore


def _save(store: ResearchArtifactStore, **overrides):
    payload = {
        "subject": "NVDA fundamental review",
        "universe": "NVDA",
        "content": "Original conclusion.\nKeep the risk review.",
        "data_as_of": "2026-10-20",
        "evidence": [
            {"source_uri": "https://example.com/shared"},
            {"source_uri": "https://example.com/shared"},
            {"source_uri": "https://example.com/old"},
        ],
        "verification_status": "verified",
        "completeness": "complete",
        "goal_id": "goal-a",
        "session_id": "session-a",
    }
    payload.update(overrides)
    return store.save(**payload)


def test_compare_any_revisions_reports_changes_without_mutating_history(tmp_path):
    db_path = tmp_path / "research.db"
    store = ResearchArtifactStore(db_path)
    first = _save(store)
    artifact_id = first.revision.artifact_id
    _save(
        store,
        artifact_id=artifact_id,
        content="Intermediate conclusion.\nKeep the risk review.",
    )
    third = _save(
        store,
        artifact_id=artifact_id,
        content="Updated conclusion.\nKeep the risk review.",
        data_as_of="2026-11-03",
        evidence=[
            {"source_uri": "https://example.com/shared"},
            {"source_uri": "https://example.com/new"},
        ],
        verification_status="unverified",
        completeness="partial",
        goal_id="goal-b",
    )
    original_first = first.revision.to_dict()
    original_third = third.revision.to_dict()
    store.close()

    reloaded = ResearchArtifactStore(db_path)
    result = reloaded.compare_revisions(
        artifact_id=artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=third.revision.revision_id,
    )

    assert result["artifact_id"] == artifact_id
    assert result["from"]["revision_number"] == 1
    assert result["to"]["revision_number"] == 3
    assert result["content"]["changed"] is True
    assert "-Original conclusion." in result["content"]["diff"]
    assert "+Updated conclusion." in result["content"]["diff"]
    assert result["content"]["truncated"] is False
    assert result["evidence"] == {
        "added": [{"source_uri": "https://example.com/new"}],
        "removed": [
            {"source_uri": "https://example.com/shared"},
            {"source_uri": "https://example.com/old"},
        ],
        "unchanged_count": 1,
        "order_changed": False,
        "changed": True,
    }
    assert result["metadata"] == {
        "data_as_of": {"from": "2026-10-20", "to": "2026-11-03"},
        "verification_status": {"from": "verified", "to": "unverified"},
        "completeness": {"from": "complete", "to": "partial"},
        "goal_id": {"from": "goal-a", "to": "goal-b"},
    }
    assert reloaded.get_revision(first.revision.revision_id).to_dict() == original_first
    assert reloaded.get_revision(third.revision.revision_id).to_dict() == original_third


def test_compare_same_revision_has_no_differences(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    saved = _save(store)

    result = store.compare_revisions(
        artifact_id=saved.revision.artifact_id,
        from_revision_id=saved.revision.revision_id,
        to_revision_id=saved.revision.revision_id,
    )

    assert result["content"] == {
        "changed": False,
        "from_hash": saved.revision.content_hash,
        "to_hash": saved.revision.content_hash,
        "from_line_count": 2,
        "to_line_count": 2,
        "from_newline_style": "lf",
        "to_newline_style": "lf",
        "diff": [],
        "truncated": False,
    }
    assert result["evidence"]["added"] == []
    assert result["evidence"]["removed"] == []
    assert result["evidence"]["unchanged_count"] == 3
    assert result["evidence"]["changed"] is False
    assert result["metadata"] == {}


def test_compare_rejects_missing_or_cross_series_revisions(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    other = _save(
        store, subject="MSFT review", universe="MSFT", content="Different research."
    )

    with pytest.raises(KeyError, match="not found in research artifact"):
        store.compare_revisions(
            artifact_id=first.revision.artifact_id,
            from_revision_id=first.revision.revision_id,
            to_revision_id=other.revision.revision_id,
        )
    with pytest.raises(KeyError, match="not found in research artifact"):
        store.compare_revisions(
            artifact_id=first.revision.artifact_id,
            from_revision_id=first.revision.revision_id,
            to_revision_id="ra_missing_r1",
        )


def test_compare_bounds_unified_diff_and_marks_truncation(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="\n".join(f"old line {index}" for index in range(250)))
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="\n".join(f"new line {index}" for index in range(250)),
    )

    result = store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )

    assert len(result["content"]["diff"]) == 400
    assert result["content"]["truncated"] is True
    assert result["content"]["from_line_count"] == 250
    assert result["content"]["to_line_count"] == 250


def test_compare_preserves_internal_line_ending_difference(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="First line.\r\nSecond line.")
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="First line.\nSecond line.",
    )

    result = store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )

    assert result["content"]["changed"] is True
    assert result["content"]["from_newline_style"] == "crlf"
    assert result["content"]["to_newline_style"] == "lf"
    assert "-First line.\\r\\n" in result["content"]["diff"]
    assert "+First line.\\n" in result["content"]["diff"]


def test_compare_shows_line_endings_for_mixed_styles_on_changed_and_context_lines(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="a\r\nb\nc\nd\n")
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="a\nb\r\nc\nd\n",
    )

    result = store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )

    assert result["content"]["from_newline_style"] == "mixed"
    assert result["content"]["to_newline_style"] == "mixed"
    assert "-a\\r\\n" in result["content"]["diff"]
    assert "-b\\n" in result["content"]["diff"]
    assert "+a\\n" in result["content"]["diff"]
    assert "+b\\r\\n" in result["content"]["diff"]
    assert " c\\n" in result["content"]["diff"]
    assert " d" in result["content"]["diff"]
    assert "\\ No newline at end of file" in result["content"]["diff"]


def test_compare_reports_pure_evidence_reordering(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(
        store,
        evidence=[
            {"source_uri": "https://example.com/a"},
            {"source_uri": "https://example.com/b"},
        ],
    )
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        evidence=[
            {"source_uri": "https://example.com/b"},
            {"source_uri": "https://example.com/a"},
        ],
    )

    result = store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )

    assert result["evidence"] == {
        "added": [],
        "removed": [],
        "unchanged_count": 2,
        "order_changed": True,
        "changed": True,
    }
