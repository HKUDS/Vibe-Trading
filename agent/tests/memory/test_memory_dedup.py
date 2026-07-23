"""Tests for content deduplication in PersistentMemory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.memory.persistent import (
    DEDUP_WINDOW_SECONDS,
    PersistentMemory,
    content_hash,
)


class TestContentHash:
    """Unit tests for the content_hash() helper."""

    def test_deterministic(self) -> None:
        """Same inputs always produce the same hash."""
        h1 = content_hash("My Memory", "A description", "body")
        h2 = content_hash("My Memory", "A description", "body")
        assert h1 == h2

    def test_length_is_12_hex_chars(self) -> None:
        """Hash output is a 12-character hex digest prefix."""
        h = content_hash("name", "desc", "content")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive(self) -> None:
        """Upper/lower case differences produce the same hash."""
        h1 = content_hash("My Memory", "Some Description", "Body Text")
        h2 = content_hash("my memory", "some description", "body text")
        assert h1 == h2

    def test_whitespace_normalized(self) -> None:
        """Leading/trailing whitespace is stripped before hashing."""
        h1 = content_hash("  name  ", "  desc  ", "  body  ")
        h2 = content_hash("name", "desc", "body")
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        """Different inputs produce different hashes."""
        h1 = content_hash("alpha", "first description", "body1")
        h2 = content_hash("beta", "second description", "body2")
        assert h1 != h2

    def test_same_name_desc_different_body(self) -> None:
        """Same name+desc but different body produces different hash."""
        h1 = content_hash("title", "desc", "version 1")
        h2 = content_hash("title", "desc", "version 2")
        assert h1 != h2


class TestIsDuplicate:
    """Tests for PersistentMemory.is_duplicate() method."""

    def test_first_call_is_not_duplicate(self, tmp_path: Path) -> None:
        """First write of any content is never a duplicate."""
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.is_duplicate("test", "desc", "body") is False

    def test_second_call_within_window_is_duplicate(self, tmp_path: Path) -> None:
        """Repeated call within 30s window is flagged as duplicate."""
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.is_duplicate("test", "desc", "body") is False
        assert pm.is_duplicate("test", "desc", "body") is True

    def test_different_content_not_duplicate(self, tmp_path: Path) -> None:
        """Different content is never flagged as duplicate."""
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.is_duplicate("alpha", "first", "body1") is False
        assert pm.is_duplicate("beta", "second", "body2") is False

    def test_same_name_different_body_not_duplicate(self, tmp_path: Path) -> None:
        """Same name+desc but different body is NOT a duplicate (overwrite)."""
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.is_duplicate("note", "desc", "v1") is False
        assert pm.is_duplicate("note", "desc", "v2") is False

    def test_case_whitespace_variations_are_duplicate(self, tmp_path: Path) -> None:
        """Case and whitespace differences are treated as same content."""
        pm = PersistentMemory(memory_dir=tmp_path)
        assert pm.is_duplicate("My Note", "Important Info", "Body") is False
        # Same content with different case/whitespace
        assert pm.is_duplicate("  MY NOTE  ", "  important info  ", "  body  ") is True

    def test_expired_window_allows_rewrite(self, tmp_path: Path) -> None:
        """After the dedup window expires, the same content can be written again."""
        pm = PersistentMemory(memory_dir=tmp_path)

        # First call at t=1000
        with patch("src.memory.persistent._time.time", return_value=1000.0):
            assert pm.is_duplicate("note", "desc", "body") is False

        # Second call still within window (t=1000 + 29s)
        with patch("src.memory.persistent._time.time", return_value=1029.0):
            assert pm.is_duplicate("note", "desc", "body") is True

        # Third call after window expired (t=1000 + 31s)
        with patch("src.memory.persistent._time.time", return_value=1031.0):
            assert pm.is_duplicate("note", "desc", "body") is False

    def test_cross_instance_cache_isolation(self, tmp_path: Path) -> None:
        """Each PersistentMemory instance has its own _recent_hashes cache."""
        pm1 = PersistentMemory(memory_dir=tmp_path)
        pm2 = PersistentMemory(memory_dir=tmp_path)

        assert pm1.is_duplicate("shared", "content", "body") is False
        # pm2 has a fresh cache, so same content is not flagged
        assert pm2.is_duplicate("shared", "content", "body") is False


class TestAddDedup:
    """Integration tests: dedup check within the add() method."""

    def test_duplicate_add_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """Second add() with same name+desc within window returns None."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        pm = PersistentMemory(memory_dir=tmp_path)
        result1 = pm.add("My Note", "body content", description="important")
        assert result1 is not None
        assert isinstance(result1, Path)

        result2 = pm.add("My Note", "body content", description="important")
        assert result2 is None

    def test_duplicate_add_does_not_create_second_file(self, tmp_path: Path, monkeypatch) -> None:
        """Blocked duplicate does not write a second .md file."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        pm = PersistentMemory(memory_dir=tmp_path)
        pm.add("Unique Entry", "content", description="desc")
        # Count .md files (excluding MEMORY.md)
        md_files = [f for f in tmp_path.glob("*.md") if f.name != "MEMORY.md"]
        assert len(md_files) == 1

        pm.add("Unique Entry", "content", description="desc")
        md_files = [f for f in tmp_path.glob("*.md") if f.name != "MEMORY.md"]
        # Still only 1 file
        assert len(md_files) == 1

    def test_different_entries_both_written(self, tmp_path: Path) -> None:
        """Entries with different content are both persisted."""
        pm = PersistentMemory(memory_dir=tmp_path)
        r1 = pm.add("First", "body1", description="desc1")
        r2 = pm.add("Second", "body2", description="desc2")
        assert r1 is not None
        assert r2 is not None
        assert r1 != r2

    def test_add_after_window_expires(self, tmp_path: Path, monkeypatch) -> None:
        """Same content can be written again after dedup window expires."""
        monkeypatch.setenv("VT_MEMORY_QUALITY", "1")
        pm = PersistentMemory(memory_dir=tmp_path)

        with patch("src.memory.persistent._time.time", return_value=1000.0):
            r1 = pm.add("Retry Note", "body", description="retry desc")
        assert r1 is not None

        # Within window: blocked
        with patch("src.memory.persistent._time.time", return_value=1010.0):
            r2 = pm.add("Retry Note", "body", description="retry desc")
        assert r2 is None

        # After window: allowed
        with patch("src.memory.persistent._time.time", return_value=1031.0):
            r3 = pm.add("Retry Note", "body", description="retry desc")
        assert r3 is not None
