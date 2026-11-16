"""Portable exports for an exact pair of immutable research revisions."""

from __future__ import annotations

import hashlib
import json

from src.research_artifacts import ResearchArtifactStore


def _save(store: ResearchArtifactStore, **overrides):
    payload = {
        "subject": "NVDA fundamental review",
        "universe": "NVDA",
        "content": "Original conclusion.\nKeep the risk review.",
        "data_as_of": "2026-10-20",
        "evidence": [{"source_uri": "https://example.com/old"}],
        "verification_status": "verified",
        "completeness": "complete",
        "goal_id": "goal-a",
    }
    payload.update(overrides)
    return store.save(**payload)


def _pair(store: ResearchArtifactStore):
    first = _save(store)
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Updated conclusion.\nKeep the risk review.",
        data_as_of="2026-11-03",
        evidence=[{"source_uri": "https://example.com/new"}],
        verification_status="unverified",
        goal_id="goal-b",
    )
    return first, revised


def _export(store: ResearchArtifactStore, first, revised, format: str):
    return store.export_comparison(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
        format=format,
    )


def test_comparison_json_export_is_deterministic_and_preserves_exact_selection(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first, revised = _pair(store)

    exported = _export(store, first, revised, "json")
    repeated = _export(store, first, revised, "json")

    assert exported.to_dict() == repeated.to_dict()
    assert exported.filename == f"{first.revision.artifact_id}-r1-r2.json"
    assert exported.media_type == "application/json"
    assert exported.sha256 == hashlib.sha256(exported.content.encode()).hexdigest()
    document = json.loads(exported.content)
    assert document["schema_version"] == 1
    assert document["kind"] == "research_artifact_revision_comparison"
    assert document["comparison"] == store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )
    assert document["comparison"]["from"]["revision_id"] == first.revision.revision_id
    assert document["comparison"]["to"]["revision_id"] == revised.revision.revision_id
    assert "revisions" not in document
    assert "exported_at" not in document


def test_comparison_markdown_export_contains_diff_evidence_and_metadata(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first, revised = _pair(store)

    exported = _export(store, first, revised, "markdown")

    assert exported.filename == f"{first.revision.artifact_id}-r1-r2.md"
    assert exported.media_type == "text/markdown; charset=utf-8"
    assert exported.sha256 == hashlib.sha256(exported.content.encode()).hexdigest()
    assert exported.content.startswith("# Research revision comparison\n")
    assert "From revision: r1" in exported.content
    assert "To revision: r2" in exported.content
    assert "```diff" in exported.content
    assert "-Original conclusion." in exported.content
    assert "+Updated conclusion." in exported.content
    assert "## Evidence" in exported.content
    assert "https://example.com/new" in exported.content
    assert "https://example.com/old" in exported.content
    assert "## Metadata" in exported.content
    assert '"data_as_of"' in exported.content
    assert '"goal_id"' in exported.content
    assert "Read-only comparison. Exporting does not revalidate research." in exported.content
    assert exported.content.endswith("\n")


def test_comparison_markdown_export_marks_truncation_and_retains_full_content_facts(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="\n".join(f"old line {index}" for index in range(250)))
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="\n".join(f"new line {index}" for index in range(250)),
    )

    comparison = store.compare_revisions(
        artifact_id=first.revision.artifact_id,
        from_revision_id=first.revision.revision_id,
        to_revision_id=revised.revision.revision_id,
    )
    exported = _export(store, first, revised, "markdown")

    assert comparison["content"]["truncated"] is True
    assert len(comparison["content"]["diff"]) == 400
    assert "Diff truncated after 400 generated lines." in exported.content
    assert "Lines: 250 -> 250" in exported.content
    assert first.revision.content_hash in exported.content
    assert revised.revision.content_hash in exported.content


def test_comparison_markdown_export_isolates_fences_and_html(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="Before\n```diff\n<script>alert(1)</script>")
    revised = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="After\n<!--\nliteral ```json fence",
        evidence=[{"note": "```json <script>alert(1)</script>"}],
        verification_status="verified\n```text\nmetadata",
    )

    exported = _export(store, first, revised, "markdown")
    rendered = mistune.html(exported.content)

    assert "<h2>Content</h2>" in rendered
    assert "<h2>Evidence</h2>" in rendered
    assert "<h2>Metadata</h2>" in rendered
    assert "<script>" not in rendered
    assert "Read-only comparison. Exporting does not revalidate research." in exported.content
