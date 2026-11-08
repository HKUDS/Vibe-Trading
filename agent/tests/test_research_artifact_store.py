"""Persistence and revision contracts for versioned research artifacts."""

from __future__ import annotations

import json
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
        "evidence": [{"source_uri": "https://example.com/filing", "content_hash": "abc"}],
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
    assert reloaded.get_revision(saved.revision.revision_id).content == saved.revision.content


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
    second = _save(store, artifact_id=first.revision.artifact_id, data_as_of="2026-10-27")
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
    assert [item.revision_id for item in store.search(query="Updated conclusion")] == [latest.revision.revision_id]
    assert [item.revision_id for item in store.search(goal_id="goal_nvda")] == [latest.revision.revision_id]
    assert len(store.search()) == 2
    assert len(store.list_revisions(first.revision.artifact_id)) == 2


def test_revision_requires_existing_series_and_preserves_subject(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    with pytest.raises(KeyError):
        _save(store, artifact_id="ra_missing")

    first = _save(store)
    with pytest.raises(ValueError, match="preserve the artifact subject"):
        _save(store, artifact_id=first.revision.artifact_id, subject="Different subject")
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
    assert store.get_revision(first.revision.revision_id).verification_status == "verified"


def test_revision_idempotency_cannot_return_another_series(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store, content="A")
    other = _save(store, content="B")
    changed = _save(store, artifact_id=first.revision.artifact_id, content="B")
    assert changed.created
    assert changed.revision.artifact_id == first.revision.artifact_id
    assert changed.revision.revision_id != other.revision.revision_id


def test_concurrent_instances_append_a_single_serial_revision_chain(tmp_path, monkeypatch):
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
        assert [r.previous_revision_id for r in history[:-1]] == [r.revision_id for r in history[1:]]
    finally:
        for store in stores:
            store.close()


def test_fingerprint_lookup_uses_the_composite_index(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    rows = store._conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM research_artifact_revisions WHERE content_hash = ? AND provenance_hash = ?",
        ("missing-content", "missing-provenance"),
    ).fetchall()
    store.close()

    plan = "\n".join(row["detail"] for row in rows)
    assert "USING INDEX idx_research_artifact_fingerprint" in plan, plan


def test_json_export_is_deterministic_and_preserves_full_series(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    second = _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Updated conclusion.",
        data_as_of="2026-10-27",
        evidence=[{"source_uri": "https://example.com/new-filing"}],
        verification_status="unverified",
    )

    exported = store.export_series(first.revision.artifact_id, "json")
    repeated = store.export_series(first.revision.artifact_id, "json")

    assert exported.to_dict() == repeated.to_dict()
    assert exported.filename == f"{first.revision.artifact_id}.json"
    assert exported.media_type == "application/json"
    document = json.loads(exported.content)
    assert document["schema_version"] == 1
    assert document["artifact_id"] == first.revision.artifact_id
    assert document["revision_count"] == 2
    assert [row["revision_id"] for row in document["revisions"]] == [
        first.revision.revision_id,
        second.revision.revision_id,
    ]
    assert document["revisions"][0]["evidence"][0]["content_hash"] == "abc"
    assert document["revisions"][1]["verification_status"] == "unverified"
    assert "exported_at" not in document


def test_markdown_export_keeps_verification_and_evidence_visible(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    first = _save(store)
    _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Updated conclusion.",
        data_as_of="2026-10-27",
        verification_status="unverified",
    )

    exported = store.export_series(first.revision.artifact_id, "markdown")
    repeated = store.export_series(first.revision.artifact_id, "markdown")

    assert exported.content == repeated.content
    assert exported.filename == f"{first.revision.artifact_id}.md"
    assert exported.media_type == "text/markdown; charset=utf-8"
    assert "# NVDA fundamental review" in exported.content
    assert "## Revision 1" in exported.content
    assert "## Revision 2" in exported.content
    assert "Original conclusion with traceable evidence." in exported.content
    assert "https://example.com/filing" in exported.content
    assert "Verification status: verified" in exported.content
    assert "Verification status: unverified" in exported.content
    assert "exported_at" not in exported.content
    assert exported.content.endswith("\n")

    with_backticks = _save(
        store,
        subject="Evidence fence review",
        evidence=[{"note": "literal ```json fence"}],
    )
    fenced = store.export_series(with_backticks.revision.artifact_id, "markdown")
    assert "````json\n" in fenced.content
    assert "literal ```json fence" in fenced.content
    assert "\n````\n" in fenced.content


def test_markdown_export_keeps_evidence_and_later_revisions_outside_unclosed_content_fence(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    original_content = "text\n```python\na=1"
    first = _save(store, content=original_content)
    _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Later revision.",
        data_as_of="2026-10-28",
    )

    exported = store.export_series(first.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert original_content in exported.content
    assert rendered.count("<h3>Evidence</h3>") == 2
    assert "<h2>Revision 2</h2>" in rendered
    assert "Later revision." in rendered


@pytest.mark.parametrize(
    "opening", ["<!--", "<pre>", "<script>", "<?", "<![CDATA[", "<!A", "<!--\n<pre>", "<!--\n<script>\n<pre>"]
)
def test_markdown_export_isolates_unclosed_html_blocks(tmp_path, opening):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    original_content = f"Research note\n{opening}"
    first = _save(store, content=original_content)
    _save(
        store,
        artifact_id=first.revision.artifact_id,
        content="Later revision.",
        data_as_of="2026-10-28",
    )

    exported = store.export_series(first.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert rendered.count("<h3>Evidence</h3>") == 2
    assert "<h2>Revision 2</h2>" in rendered
    assert "Research note" in rendered
    document = json.loads(store.export_series(first.revision.artifact_id, "json").content)
    assert document["revisions"][0]["content"] == original_content


def test_markdown_export_preserves_closed_html_and_fenced_code(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    original_content = "<pre>visible</pre>\n```html\n<div>code</div>\n```"
    saved = _save(store, content=original_content)

    exported = store.export_series(saved.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert original_content in exported.content
    assert rendered.count("<h3>Evidence</h3>") == 1


def test_markdown_export_preserves_html_inside_unclosed_fence(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    original_content = "```html\n<pre>"
    saved = _save(store, content=original_content)

    exported = store.export_series(saved.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert original_content in exported.content
    assert f"````markdown\n{original_content}\n````\n\n### Evidence" in exported.content
    assert rendered.count("<h3>Evidence</h3>") == 1


def test_markdown_export_ignores_html_closers_inside_fences(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    original_content = "<pre>\n```text\n</pre>\n```"
    saved = _save(store, content=original_content)

    exported = store.export_series(saved.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert rendered.count("<h3>Evidence</h3>") == 1
    document = json.loads(store.export_series(saved.revision.artifact_id, "json").content)
    assert document["revisions"][0]["content"] == original_content


def test_markdown_export_does_not_let_metadata_open_fences(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    subject = "Review\n```text\nsubject body"
    universe = "NVDA\n~~~\nuniverse body"
    saved = _save(store, subject=subject, universe=universe)

    exported = store.export_series(saved.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert "<h2>Revision 1</h2>" in rendered
    assert rendered.count("<h3>Evidence</h3>") == 1
    document = json.loads(store.export_series(saved.revision.artifact_id, "json").content)
    assert document["revisions"][0]["subject"] == subject
    assert document["revisions"][0]["universe"] == universe


@pytest.mark.parametrize(
    "field",
    [
        "data_as_of",
        "verification_status",
        "completeness",
        "hypothesis_id",
        "goal_id",
        "session_id",
        "run_id",
    ],
)
def test_markdown_export_does_not_let_revision_metadata_open_fences(tmp_path, field):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    value = f"{field}\n```text\nmetadata body"
    saved = _save(store, **{field: value})

    exported = store.export_series(saved.revision.artifact_id, "markdown")
    rendered = mistune.html(exported.content)

    assert "<h2>Revision 1</h2>" in rendered
    assert rendered.count("<h3>Evidence</h3>") == 1
    document = json.loads(store.export_series(saved.revision.artifact_id, "json").content)
    assert document["revisions"][0][field] == value


def test_export_rejects_missing_series_and_unknown_format(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    with pytest.raises(KeyError):
        store.export_series("ra_missing", "json")

    saved = _save(store)
    with pytest.raises(ValueError, match="format"):
        store.export_series(saved.revision.artifact_id, "xml")


def test_export_metadata_renders_as_literal_text_and_json_preserves_it(tmp_path):
    import mistune

    store = ResearchArtifactStore(tmp_path / "research.db")
    value = "<script>alert(1)</script> [link](javascript:alert(1)) `code`"
    saved = _save(store, subject=value, verification_status=value)
    rendered = mistune.html(store.export_series(saved.revision.artifact_id, "markdown").content)
    assert "<script>" not in rendered
    assert "<a " not in rendered
    assert "&lt;script&gt;" in rendered
    document = json.loads(store.export_series(saved.revision.artifact_id, "json").content)
    assert document["revisions"][0]["subject"] == value
    assert document["revisions"][0]["verification_status"] == value


def test_nonfinite_evidence_is_rejected_before_persistence(tmp_path):
    store = ResearchArtifactStore(tmp_path / "research.db")
    with pytest.raises(ValueError):
        _save(store, evidence=[{"value": float("nan")}])
