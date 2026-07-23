"""Tests for memory GC, find_relevant weighting, and RememberTool reinforce."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.config.accessor import reset_env_config
from src.memory.lifecycle import MemoryLifecycle
from src.memory.persistent import PersistentMemory
from src.tools.remember_tool import RememberTool


@pytest.fixture(autouse=True)
def _reset_config_cache():
    """Reset env config singleton so monkeypatch.setenv() takes effect."""
    reset_env_config()
    yield
    reset_env_config()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _create_memory_file(
    tmp_path: Path,
    name: str,
    content: str = "test body",
    memory_type: str = "project",
    quality_score: float = 0.5,
    access_count: int = 0,
    keywords: list | None = None,
    created_at: str = "2025-01-01T00:00:00",
    last_accessed: str = "2025-01-01T00:00:00",
    related_memories: list | None = None,
    entry_id: str = "ab12cd",
    importance: float = 0.5,
) -> Path:
    """Helper to create a memory file with extended frontmatter."""
    kw_str = ", ".join(keywords) if keywords else ""
    rel_str = ", ".join(related_memories) if related_memories else ""
    slug = name.lower().replace(" ", "_")[:40]
    filename = f"{memory_type}_{slug}.md"
    path = tmp_path / filename
    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"description: {name}\n"
        f"type: {memory_type}\n"
        f"id: {entry_id}\n"
        f"created_at: {created_at}\n"
        f"updated_at: {created_at}\n"
        f"keywords: [{kw_str}]\n"
        f"quality_score: {quality_score}\n"
        f"access_count: {access_count}\n"
        f"last_accessed: {last_accessed}\n"
        f"importance: {importance}\n"
        f"related_memories: [{rel_str}]\n"
        f"---\n\n"
        f"{content}"
    )
    path.write_text(frontmatter, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. run_gc
# ---------------------------------------------------------------------------


class TestRunGC:
    def test_gc_dry_run_no_file_changes(self, tmp_path: Path, monkeypatch) -> None:
        """dry_run=True should not modify or move any files."""
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        # Create old, low-quality entry that should be flagged
        _create_memory_file(
            tmp_path, "old-bad", quality_score=0.05, access_count=0,
            created_at="2024-01-01T00:00:00", last_accessed="2024-01-01T00:00:00",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        # Override MAX_MEMORY_COUNT so dry_run still processes entries
        lc.MAX_MEMORY_COUNT = 0
        actions = lc.run_gc(dry_run=True)
        # File still exists — not moved
        assert (tmp_path / "project_old-bad.md").exists()
        assert len(actions) >= 1

    def test_gc_archives_low_importance(self, tmp_path: Path, monkeypatch) -> None:
        """Entries below ARCHIVE_THRESHOLD should be moved to archive/."""
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        _create_memory_file(
            tmp_path, "garbage", quality_score=0.01, access_count=0,
            created_at="2024-01-01T00:00:00", last_accessed="2024-01-01T00:00:00",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        actions = lc.run_gc(dry_run=False)
        # Should be archived
        assert len(actions) >= 1
        assert actions[0]["action"] == "archive"
        assert (tmp_path / "archive" / "project_garbage.md").exists()
        assert not (tmp_path / "project_garbage.md").exists()

    def test_gc_respects_min_age(self, tmp_path: Path, monkeypatch) -> None:
        """Entries younger than MIN_AGE_DAYS should not be gc'd."""
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        # Recent entry (created_at = now)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        _create_memory_file(
            tmp_path, "young", quality_score=0.01, access_count=0,
            created_at=now_iso, last_accessed=now_iso,
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        actions = lc.run_gc(dry_run=False)
        # Young entry should be untouched
        assert len(actions) == 0
        assert (tmp_path / "project_young.md").exists()

    def test_gc_disabled_when_flag_off(self, tmp_path: Path, monkeypatch) -> None:
        """run_gc() returns [] when VT_MEMORY_GC=0."""
        monkeypatch.setenv("VT_MEMORY_GC", "0")
        _create_memory_file(
            tmp_path, "should-stay", quality_score=0.01,
            created_at="2024-01-01T00:00:00", last_accessed="2024-01-01T00:00:00",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.run_gc(dry_run=False) == []

    def test_gc_log_created(self, tmp_path: Path, monkeypatch) -> None:
        """GC actions should be logged to gc.log."""
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        _create_memory_file(
            tmp_path, "log-test", quality_score=0.01, access_count=0,
            created_at="2024-01-01T00:00:00", last_accessed="2024-01-01T00:00:00",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        # Override MAX_MEMORY_COUNT so dry_run processes entries
        lc.MAX_MEMORY_COUNT = 0
        lc.run_gc(dry_run=True)
        log_path = tmp_path / "gc.log"
        assert log_path.exists()
        log_content = log_path.read_text(encoding="utf-8")
        assert "dry_run" in log_content
        assert "log-test" in log_content

    def test_gc_delete_disabled_in_tier1(self, tmp_path: Path, monkeypatch) -> None:
        """ENABLE_DELETE=False should force archive even for very low scores."""
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        _create_memory_file(
            tmp_path, "very-low", quality_score=0.001, access_count=0,
            created_at="2024-01-01T00:00:00", last_accessed="2024-01-01T00:00:00",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        # Tier 1: ENABLE_DELETE is False by default
        assert lc.ENABLE_DELETE is False
        lc.run_gc(dry_run=False)
        # Even with importance below DELETE_THRESHOLD, it is archived not deleted
        assert (tmp_path / "archive" / "project_very-low.md").exists()
        assert not (tmp_path / "project_very-low.md").exists()


# ---------------------------------------------------------------------------
# 2. find_relevant importance weighting
# ---------------------------------------------------------------------------


class TestFindRelevantImportanceWeighting:
    def test_higher_importance_ranks_higher(self, tmp_path: Path, monkeypatch) -> None:
        """Entry with more metadata overlap should rank above body-only match."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        # "trading strategy" appears in title/description (metadata, 2x weight)
        _create_memory_file(
            tmp_path, "trading strategy notes", content="general notes",
            quality_score=0.9, importance=0.9, entry_id="hi1234",
        )
        # "trading strategy" only in body (1x weight)
        _create_memory_file(
            tmp_path, "random notes", content="trading strategy details here",
            quality_score=0.1, importance=0.1, entry_id="lo5678",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        results = pm.find_relevant("trading strategy")
        assert len(results) == 2
        # Metadata-weighted entry ranks first
        assert results[0].title == "trading strategy notes"

    def test_keywords_participate_in_scoring(self, tmp_path: Path, monkeypatch) -> None:
        """Keywords in frontmatter should contribute to retrieval score."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        _create_memory_file(
            tmp_path, "kw-entry", content="unrelated body",
            keywords=["momentum", "alpha"], entry_id="kw1234",
        )
        _create_memory_file(
            tmp_path, "no-kw", content="unrelated body two",
            entry_id="nk5678",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        results = pm.find_relevant("momentum alpha")
        # The keyword-bearing entry should be found
        assert any(e.title == "kw-entry" for e in results)


# ---------------------------------------------------------------------------
# 3. RememberTool reinforce
# ---------------------------------------------------------------------------


class TestRememberToolReinforce:
    def test_reinforce_action_success(self, tmp_path: Path, monkeypatch) -> None:
        """RememberTool reinforce action should return ok status."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "tool-mem", quality_score=0.5)
        pm = PersistentMemory(memory_dir=tmp_path)
        tool = RememberTool(memory=pm)
        result = tool.execute(action="reinforce", title="tool-mem", event="task_success")
        assert '"status": "ok"' in result

    def test_reinforce_missing_params(self, tmp_path: Path) -> None:
        """Missing title or event should return error."""
        pm = PersistentMemory(memory_dir=tmp_path)
        tool = RememberTool(memory=pm)
        # Missing event
        result = tool.execute(action="reinforce", title="some-mem")
        assert '"status": "error"' in result
        # Missing title
        result2 = tool.execute(action="reinforce", event="task_success")
        assert '"status": "error"' in result2
