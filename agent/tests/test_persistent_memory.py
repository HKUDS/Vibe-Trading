"""Tests for PersistentMemory: file-based cross-session memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory.persistent import PersistentMemory, MemoryEntry, _tokenize


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_ascii_words(self) -> None:
        tokens = _tokenize("hello world testing")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens

    def test_short_words_excluded(self) -> None:
        tokens = _tokenize("I am ok no")
        # All < 3 chars, should be excluded
        assert len(tokens) == 0

    def test_cjk_characters(self) -> None:
        tokens = _tokenize("比特币价格分析")
        assert "比" in tokens
        assert "币" in tokens
        assert "价" in tokens

    def test_mixed(self) -> None:
        tokens = _tokenize("AAPL 苹果 stock analysis")
        assert "aapl" in tokens
        assert "苹" in tokens
        assert "stock" in tokens
        assert "analysis" in tokens

    def test_empty(self) -> None:
        assert _tokenize("") == set()


# ---------------------------------------------------------------------------
# PersistentMemory.add
# ---------------------------------------------------------------------------


class TestAdd:
    def test_creates_file_and_index(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        path = pm.add("test-mem", "Some content", "project", description="Test desc")
        assert path.exists()
        assert "test-mem" in path.read_text(encoding="utf-8")
        index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
        assert "test-mem" in index

    def test_slug_sanitization(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        path = pm.add("My Fancy Skill!", "body", "user")
        assert "my_fancy_skill_" in path.name

    def test_frontmatter_structure(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        path = pm.add("meta-test", "body here", "feedback", description="one line")
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "name: meta-test" in text
        assert "type: feedback" in text
        assert "description: one line" in text
        assert "body here" in text

    def test_multiple_adds(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("mem-a", "aaa", "project")
        pm.add("mem-b", "bbb", "user")
        pm.add("mem-c", "ccc", "reference")
        md_files = list(tmp_path.glob("*.md"))
        # 3 entries + MEMORY.md = 4
        assert len(md_files) == 4

    def test_overwrite_same_name(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("overwrite", "v1", "project")
        pm.add("overwrite", "v2", "project")
        # Should overwrite the same file
        path = tmp_path / "project_overwrite.md"
        assert "v2" in path.read_text(encoding="utf-8")

    def test_index_update_not_duplicate(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("dup-check", "v1", "project")
        pm.add("dup-check", "v2", "project")
        index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
        assert index.count("[dup-check]") == 1


# ---------------------------------------------------------------------------
# PersistentMemory.find_relevant
# ---------------------------------------------------------------------------


class TestFindRelevant:
    def test_basic_search(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("btc-strategy", "Bitcoin mean reversion", "project", description="BTC trading strategy")
        pm.add("aapl-analysis", "Apple earnings report", "project", description="AAPL fundamental analysis")
        results = pm.find_relevant("Bitcoin trading")
        assert len(results) >= 1
        assert results[0].title == "btc-strategy"

    def test_cjk_search(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("a-share", "上证指数分析报告", "project", description="A股市场分析")
        results = pm.find_relevant("上证指数")
        assert len(results) >= 1

    def test_no_match(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("something", "unrelated content", "project")
        results = pm.find_relevant("xyznonexistent999")
        assert len(results) == 0

    def test_max_results(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        for i in range(10):
            pm.add(f"stock-{i}", f"stock analysis number {i}", "project", description=f"stock {i}")
        results = pm.find_relevant("stock analysis", max_results=3)
        assert len(results) == 3

    def test_metadata_weighted_higher(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        # "bitcoin" in description (metadata) → weighted 2x
        pm.add("meta-match", "unrelated body text", "project", description="bitcoin trading strategy")
        # "bitcoin" only in body → weighted 1x
        pm.add("body-match", "bitcoin analysis deep dive", "project", description="some other topic")
        results = pm.find_relevant("bitcoin")
        assert len(results) == 2
        assert results[0].title == "meta-match"

    def test_empty_query(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("anything", "content", "project")
        results = pm.find_relevant("")
        assert results == []


# ---------------------------------------------------------------------------
# PersistentMemory.remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_existing(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("to-remove", "gone soon", "project")
        assert pm.remove("to-remove") is True
        # File gone
        assert not list(tmp_path.glob("*to_remove*"))
        # Index rebuilt without it
        index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
        assert "to-remove" not in index

    def test_remove_nonexistent(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.remove("ghost") is False

    def test_remove_then_find(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("ephemeral", "temporary data", "project", description="temp")
        pm.remove("ephemeral")
        results = pm.find_relevant("temporary")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# PersistentMemory.snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_loaded_at_init(self, tmp_path: Path) -> None:
        pm1 = PersistentMemory(memory_dir=tmp_path)
        pm1.add("snap-test", "content", "project", description="snapshot check")
        # New instance should load snapshot from MEMORY.md
        pm2 = PersistentMemory(memory_dir=tmp_path)
        assert "snap-test" in pm2.snapshot

    def test_snapshot_frozen(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("after-init", "new content", "project")
        # Snapshot was frozen at init time (before add), so it should NOT contain "after-init"
        # unless the dir was empty at init (then snapshot is empty string)
        # In either case, snapshot should not update after add
        snap_before_check = pm.snapshot
        pm.add("another", "more content", "project")
        assert pm.snapshot == snap_before_check

    def test_empty_dir_snapshot(self, tmp_path: Path) -> None:
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.snapshot == ""
