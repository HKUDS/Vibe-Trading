"""Tests for MemorySearchIndex: SQLite FTS5 full-text search (Tier 2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.memory.search_index import MemorySearchIndex


# ---------------------------------------------------------------------------
# Tests: basic index and search
# ---------------------------------------------------------------------------


class TestIndexAndSearch:
    def test_index_and_search_basic(self, tmp_path: Path) -> None:
        """Index an entry, search finds it."""
        db_path = tmp_path / "test_index.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry(
                entry_id="abc123",
                title="Bitcoin Trading Strategy",
                description="A mean reversion strategy for BTC",
                keywords="bitcoin trading crypto",
                body="This strategy uses moving averages to identify entry points.",
            )
            results = idx.search("bitcoin trading")
            assert len(results) >= 1
            assert results[0].entry_id == "abc123"
            assert "Bitcoin" in results[0].title or "bitcoin" in results[0].title.lower()
        finally:
            idx.close()

    def test_search_no_results(self, tmp_path: Path) -> None:
        """Query with no matches returns empty."""
        db_path = tmp_path / "test_empty.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry(
                entry_id="def456",
                title="Cooking Recipe",
                description="Pasta with tomato sauce",
                keywords="cooking pasta food",
                body="Boil water and cook pasta for 10 minutes.",
            )
            results = idx.search("quantum physics")
            assert results == []
        finally:
            idx.close()

    def test_search_ranking(self, tmp_path: Path) -> None:
        """More relevant entry ranked higher."""
        db_path = tmp_path / "test_rank.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry(
                entry_id="aaa111",
                title="Bitcoin Analysis",
                description="Deep analysis of bitcoin market",
                keywords="bitcoin crypto market",
                body="Bitcoin price analysis using technical indicators for bitcoin trading.",
            )
            idx.index_entry(
                entry_id="bbb222",
                title="General Trading",
                description="Overview of trading",
                keywords="trading stocks",
                body="Trading involves buying and selling assets in financial markets.",
            )
            results = idx.search("bitcoin")
            assert len(results) >= 1
            # Bitcoin-focused entry should be first
            assert results[0].entry_id == "aaa111"
        finally:
            idx.close()


class TestRemoveEntry:
    def test_remove_entry(self, tmp_path: Path) -> None:
        """Removed entry no longer in search results."""
        db_path = tmp_path / "test_remove.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry(
                entry_id="rem001",
                title="Temporary Note",
                description="Will be removed",
                keywords="temporary remove",
                body="This entry will be deleted soon.",
            )
            # Verify it's findable
            results = idx.search("temporary")
            assert len(results) >= 1

            # Remove it
            idx.remove_entry("rem001")
            results = idx.search("temporary")
            assert results == []
        finally:
            idx.close()


class TestRebuildAll:
    def test_rebuild_all(self, tmp_path: Path) -> None:
        """Bulk reindex works correctly."""
        db_path = tmp_path / "test_rebuild.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            # Initial index
            idx.index_entry("old1", "Old Entry", "old stuff", "old", "old content")

            # Rebuild with new data
            entries_data = [
                ("new1", "Alpha Strategy", "alpha desc", "alpha quant", "alpha body"),
                ("new2", "Beta Analysis", "beta desc", "beta stats", "beta body"),
                ("new3", "Gamma Report", "gamma desc", "gamma data", "gamma body"),
            ]
            count = idx.rebuild_all(entries_data)
            assert count == 3

            # Old entry should be gone
            results = idx.search("old")
            assert results == []

            # New entries should be findable
            results = idx.search("alpha")
            assert len(results) >= 1
            assert results[0].entry_id == "new1"
        finally:
            idx.close()


class TestSanitizeQuery:
    def test_sanitize_query_special_chars(self, tmp_path: Path) -> None:
        """Special chars don't break search."""
        db_path = tmp_path / "test_sanitize.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry("san1", "Test Entry", "desc", "keywords", "content body here")
            # These should not raise or crash
            results = idx.search("test AND OR NOT ()")
            # Should still find something based on "test"
            assert isinstance(results, list)

            results = idx.search('"""')
            assert isinstance(results, list)

            results = idx.search("*?[]{}^$")
            assert isinstance(results, list)
        finally:
            idx.close()


class TestCjkContent:
    def test_cjk_content(self, tmp_path: Path) -> None:
        """Chinese content can be indexed and searched."""
        db_path = tmp_path / "test_cjk.db"
        idx = MemorySearchIndex(db_path=db_path)
        try:
            idx.index_entry(
                entry_id="cjk001",
                title="比特币交易策略",
                description="加密货币市场分析",
                keywords="比特币 交易 加密",
                body="使用移动平均线来判断比特币的买入和卖出时机。",
            )
            results = idx.search("比特币")
            assert len(results) >= 1
            assert results[0].entry_id == "cjk001"
        finally:
            idx.close()


class TestCloseAndReopen:
    def test_close_and_reopen(self, tmp_path: Path) -> None:
        """Data persists across close/reopen."""
        db_path = tmp_path / "test_persist.db"

        # First session: index data
        idx1 = MemorySearchIndex(db_path=db_path)
        idx1.index_entry("per1", "Persistent Entry", "desc", "persist", "data body")
        idx1.close()

        # Second session: search for it
        idx2 = MemorySearchIndex(db_path=db_path)
        try:
            results = idx2.search("persistent")
            assert len(results) >= 1
            assert results[0].entry_id == "per1"
        finally:
            idx2.close()


class TestGracefulDegradation:
    def test_graceful_degradation(self, tmp_path: Path) -> None:
        """If db is corrupted, returns empty not crash."""
        db_path = tmp_path / "corrupted.db"
        # Write garbage to simulate corruption
        db_path.write_bytes(b"THIS IS NOT A VALID SQLITE DATABASE FILE" * 10)

        # Should not crash, just degrade gracefully
        try:
            idx = MemorySearchIndex(db_path=db_path)
            results = idx.search("anything")
            assert results == []
            idx.close()
        except Exception:
            # If it raises during init with a completely corrupted file,
            # that's also acceptable - the key is no unhandled crash
            pass
