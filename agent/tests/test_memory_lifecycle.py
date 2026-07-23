"""Tests for memory lifecycle: quality scoring, decay, and reinforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.accessor import reset_env_config
from src.memory.lifecycle import (
    MemoryLifecycle,
    compute_importance,
    is_decay_enabled,
    is_gc_enabled,
    is_quality_enabled,
    memory_lock,
)
from src.memory.persistent import PersistentMemory


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
# 1. MemoryEntry new fields (backward compatibility)
# ---------------------------------------------------------------------------


class TestMemoryEntryNewFields:
    def test_old_file_without_new_fields_uses_defaults(self, tmp_path: Path) -> None:
        """Legacy files without new frontmatter fields should parse with safe defaults."""
        path = tmp_path / "project_old.md"
        path.write_text(
            "---\nname: old-mem\ndescription: legacy\ntype: project\n---\n\nold body\n",
            encoding="utf-8",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.quality_score == 0.5
        assert e.access_count == 0
        assert e.keywords == ()
        assert e.related_memories == ()
        assert len(e.id) == 6

    def test_new_file_with_all_fields(self, tmp_path: Path) -> None:
        """Files with extended frontmatter should parse all fields correctly."""
        _create_memory_file(
            tmp_path, "full-entry", quality_score=0.8, access_count=5,
            keywords=["alpha", "beta"], entry_id="aa11bb",
            related_memories=["cc22dd", "ee33ff"],
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.quality_score == 0.8
        assert e.access_count == 5
        assert e.keywords == ("alpha", "beta")
        assert e.id == "aa11bb"
        assert e.related_memories == ("cc22dd", "ee33ff")

    def test_invalid_quality_score_clamped(self, tmp_path: Path) -> None:
        """quality_score outside [0,1] should be clamped."""
        path = tmp_path / "project_high.md"
        path.write_text(
            "---\nname: high\ndescription: x\ntype: project\nquality_score: 2.5\n---\n\nbody\n",
            encoding="utf-8",
        )
        path2 = tmp_path / "project_low.md"
        path2.write_text(
            "---\nname: low\ndescription: x\ntype: project\nquality_score: -0.5\n---\n\nbody\n",
            encoding="utf-8",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = {e.title: e for e in pm.list_entries()}
        assert entries["high"].quality_score == 1.0
        assert entries["low"].quality_score == 0.0

    def test_invalid_access_count_reset(self, tmp_path: Path) -> None:
        """Non-integer access_count should reset to 0."""
        path = tmp_path / "project_badac.md"
        path.write_text(
            "---\nname: badac\ndescription: x\ntype: project\naccess_count: abc\n---\n\nbody\n",
            encoding="utf-8",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        assert entries[0].access_count == 0

    def test_keywords_truncated_to_five(self, tmp_path: Path) -> None:
        """More than 5 keywords should be truncated."""
        _create_memory_file(
            tmp_path, "many-kw",
            keywords=["a", "b", "c", "d", "e", "f", "g"],
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        assert len(entries[0].keywords) == 5

    def test_related_memories_filters_invalid_ids(self, tmp_path: Path) -> None:
        """Non-6-char or non-hex IDs in related_memories should be dropped."""
        _create_memory_file(
            tmp_path, "bad-rel",
            related_memories=["ab12cd", "too_long_id", "0a33ff", "x", "ok33ff"],
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        # Only 6-char hex IDs survive
        assert entries[0].related_memories == ("ab12cd", "0a33ff")

    def test_id_generated_when_missing(self, tmp_path: Path) -> None:
        """Missing id field should auto-generate 6-char hex."""
        path = tmp_path / "project_noid.md"
        path.write_text(
            "---\nname: noid\ndescription: x\ntype: project\n---\n\nbody\n",
            encoding="utf-8",
        )
        pm = PersistentMemory(memory_dir=tmp_path)
        entries = pm.list_entries()
        assert len(entries[0].id) == 6
        assert all(c in "0123456789abcdef" for c in entries[0].id)


# ---------------------------------------------------------------------------
# 2. compute_importance
# ---------------------------------------------------------------------------


class TestComputeImportance:
    def test_high_quality_recent_access(self, monkeypatch) -> None:
        """High quality + recent access = high importance."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        result = compute_importance(0.9, 3, 0.0)
        # retention=1.0, access_bonus=min(0.3, 3*0.1)=0.3 => 0.9*(1.0+0.3)=1.17 => capped 1.0
        assert result == pytest.approx(1.0)

    def test_low_quality_old_access(self, monkeypatch) -> None:
        """Low quality + old access = low importance."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        result = compute_importance(0.2, 0, 30.0)
        # retention=exp(-lambda*30), access_bonus=0 => small value
        assert result < 0.15

    def test_decay_disabled_returns_quality(self, monkeypatch) -> None:
        """When VT_MEMORY_DECAY=0, importance equals quality_score."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "0")
        assert compute_importance(0.7, 10, 100.0) == 0.7

    def test_access_bonus_capped_at_0_3(self, monkeypatch) -> None:
        """Access bonus should not exceed 0.3."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        # access_count=100 => bonus = min(0.3, 100*0.1) = 0.3
        r1 = compute_importance(0.5, 100, 0.0)
        r2 = compute_importance(0.5, 3, 0.0)
        # Both should use 0.3 cap: 0.5*(1.0+0.3)=0.65
        assert r1 == r2 == pytest.approx(0.65)

    def test_importance_capped_at_1_0(self, monkeypatch) -> None:
        """Output should never exceed 1.0."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        result = compute_importance(1.0, 10, 0.0)
        assert result <= 1.0

    def test_zero_quality_always_zero(self, monkeypatch) -> None:
        """quality_score=0 should produce importance=0 regardless of access."""
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        assert compute_importance(0.0, 100, 0.0) == 0.0


# ---------------------------------------------------------------------------
# 3. reinforce
# ---------------------------------------------------------------------------


class TestReinforce:
    def test_reinforce_task_success_increases_score(self, tmp_path: Path, monkeypatch) -> None:
        """task_success event should increase quality_score by 0.1."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "my-mem", quality_score=0.5)
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("my-mem", "task_success", source="user") is True
        # Re-read from disk
        entries = pm.list_entries()
        assert entries[0].quality_score == pytest.approx(0.6, abs=0.01)

    def test_reinforce_user_reject_decreases_score(self, tmp_path: Path, monkeypatch) -> None:
        """user_reject event should decrease quality_score by 0.3."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "reject-mem", quality_score=0.7)
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("reject-mem", "user_reject", source="user") is True
        entries = pm.list_entries()
        assert entries[0].quality_score == pytest.approx(0.4, abs=0.01)

    def test_reinforce_system_source_discounted(self, tmp_path: Path, monkeypatch) -> None:
        """source='system' should apply 0.7x discount to delta."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "sys-mem", quality_score=0.5)
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("sys-mem", "task_success", source="system") is True
        entries = pm.list_entries()
        # delta = 0.1 * 0.7 = 0.07 => 0.5 + 0.07 = 0.57
        assert entries[0].quality_score == pytest.approx(0.57, abs=0.01)

    def test_reinforce_clamped_to_bounds(self, tmp_path: Path, monkeypatch) -> None:
        """Score should never go below 0.0 or above 1.0."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        # Test lower bound
        _create_memory_file(tmp_path, "low-mem", quality_score=0.1, entry_id="lo1234")
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        lc.reinforce("low-mem", "user_reject", source="user")  # -0.3
        entries = pm.list_entries()
        assert entries[0].quality_score == 0.0

    def test_reinforce_session_cap(self, tmp_path: Path, monkeypatch) -> None:
        """Per-memory per-session delta should not exceed 0.5."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "cap-mem", quality_score=0.5)
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        # Each task_success = +0.1 (user). 5 calls = 0.5 cap reached.
        for _ in range(5):
            lc.reinforce("cap-mem", "task_success", source="user")
        # 6th call should be blocked by session cap
        assert lc.reinforce("cap-mem", "task_success", source="user") is False

    def test_reinforce_disabled_when_flag_off(self, tmp_path: Path, monkeypatch) -> None:
        """reinforce() returns False when VT_MEMORY_QUALITY=0."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "0")
        _create_memory_file(tmp_path, "off-mem")
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("off-mem", "task_success") is False

    def test_reinforce_nonexistent_memory(self, tmp_path: Path, monkeypatch) -> None:
        """reinforce() on non-existent memory should return False."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("ghost", "task_success") is False

    def test_reinforce_unknown_event(self, tmp_path: Path, monkeypatch) -> None:
        """reinforce() with unknown event should return False."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        _create_memory_file(tmp_path, "evt-mem")
        pm = PersistentMemory(memory_dir=tmp_path)
        lc = MemoryLifecycle(pm)
        assert lc.reinforce("evt-mem", "unknown_event") is False


# ---------------------------------------------------------------------------
# 4. Feature flags
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    def test_flags_default_off(self, monkeypatch) -> None:
        """All flags should default to disabled (0)."""
        monkeypatch.delenv("VT_MEMORY_QUALITY", raising=False)
        monkeypatch.delenv("VT_MEMORY_GC", raising=False)
        monkeypatch.delenv("VT_MEMORY_DECAY", raising=False)
        assert is_quality_enabled() is False
        assert is_gc_enabled() is False
        assert is_decay_enabled() is False

    def test_flags_enabled_when_set(self, monkeypatch) -> None:
        """Flags should be enabled when env var = '1'."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        monkeypatch.setenv("VT_MEMORY_GC", "1")
        monkeypatch.setenv("VT_MEMORY_DECAY", "1")
        assert is_quality_enabled() is True
        assert is_gc_enabled() is True
        assert is_decay_enabled() is True


# ---------------------------------------------------------------------------
# 5. memory_lock
# ---------------------------------------------------------------------------


class TestMemoryLock:
    def test_lock_acquired_yields_true(self, tmp_path: Path) -> None:
        """Normal lock acquisition should yield True."""
        with memory_lock(tmp_path) as acquired:
            assert acquired is True

    def test_lock_file_created(self, tmp_path: Path) -> None:
        """Lock file .lock should be created in memory dir."""
        with memory_lock(tmp_path):
            assert (tmp_path / ".lock").exists()
