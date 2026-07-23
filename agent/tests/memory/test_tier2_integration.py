"""Tier 2 end-to-end integration tests.

Validates that enabling Tier 2 feature flags produces the expected
hierarchical routing, semantic linking, FTS indexing, and compression
behaviors through the real PersistentMemory / MemoryLifecycle / RememberTool
stack.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.config.accessor import reset_env_config
from src.memory.persistent import PersistentMemory, MemoryEntry
from src.memory.lifecycle import MemoryLifecycle
from src.tools.remember_tool import RememberTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_fts_singleton():
    """Reset FTS singleton between tests to avoid cross-test contamination."""
    import src.memory.search_index as si

    original = si._shared_index
    si._shared_index = None
    yield
    if si._shared_index is not None:
        try:
            si._shared_index.close()
        except Exception:
            pass
    si._shared_index = original


@pytest.fixture()
def fts_db(tmp_path, monkeypatch):
    """Redirect FTS singleton to a temporary database."""
    import src.memory.search_index as si

    db_path = tmp_path / "test_fts.db"
    monkeypatch.setattr(si, "_DEFAULT_DB_PATH", db_path)
    return db_path


# ---------------------------------------------------------------------------
# 1. Hierarchy: add routes to subdirectory
# ---------------------------------------------------------------------------


class TestHierarchyAddRoutesToSubdir:
    def test_hierarchy_add_routes_to_subdir(self, tmp_path, monkeypatch):
        """With VT_MEMORY_HIERARCHY=true, add() writes to type subdir."""
        monkeypatch.setenv("VT_MEMORY_HIERARCHY", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        path = mem.add("test entry", "some content here", "user")

        assert path is not None
        # File should live under tmp_path/user/
        assert path.parent == tmp_path / "user"
        assert path.exists()


# ---------------------------------------------------------------------------
# 2. Hierarchy: scan_all finds both flat and routed entries
# ---------------------------------------------------------------------------


class TestHierarchyScanAllFindsBoth:
    def test_hierarchy_scan_all_finds_both(self, tmp_path, monkeypatch):
        """list_entries() discovers both flat legacy files and subdir files."""
        monkeypatch.setenv("VT_MEMORY_HIERARCHY", "true")
        reset_env_config()

        # Create flat legacy file in base dir
        flat_file = tmp_path / "legacy_note.md"
        flat_file.write_text(
            "---\nname: legacy note\ndescription: old flat entry\ntype: project\n"
            "id: aaa111\ncreated_at: 2025-01-01T00:00:00\n"
            "updated_at: 2025-01-01T00:00:00\nkeywords: []\n"
            "quality_score: 0.5\naccess_count: 0\n"
            "last_accessed: 2025-01-01T00:00:00\nimportance: 0.5\n"
            "related_memories: []\ncategory: project\ncompression_level: raw\n"
            "---\n\nLegacy content",
            encoding="utf-8",
        )

        # Create file in project/ subdir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        new_file = project_dir / "new_entry.md"
        new_file.write_text(
            "---\nname: new entry\ndescription: new subdir entry\ntype: project\n"
            "id: bbb222\ncreated_at: 2025-01-01T00:00:00\n"
            "updated_at: 2025-01-01T00:00:00\nkeywords: []\n"
            "quality_score: 0.5\naccess_count: 0\n"
            "last_accessed: 2025-01-01T00:00:00\nimportance: 0.5\n"
            "related_memories: []\ncategory: project\ncompression_level: raw\n"
            "---\n\nNew content",
            encoding="utf-8",
        )

        mem = PersistentMemory(tmp_path)
        entries = mem.list_entries()
        titles = {e.title for e in entries}
        assert "legacy note" in titles
        assert "new entry" in titles
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# 3. Links: add generates .relations.json sidecar
# ---------------------------------------------------------------------------


class TestLinksAddGeneratesRelationsJson:
    def test_links_add_generates_relations_json(self, tmp_path, monkeypatch):
        """With VT_MEMORY_LINKS=true, adding overlapping entries creates sidecar."""
        monkeypatch.setenv("VT_MEMORY_LINKS", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        # Add 3 entries with overlapping content to trigger BM25 linking
        mem.add(
            "quantitative backtest engine",
            "The quantitative backtest engine runs factor-based strategies "
            "on historical market data using vectorized operations.",
            "project",
        )
        mem.add(
            "backtest strategy runner",
            "The strategy runner executes backtest logic with market data "
            "and produces performance metrics for quantitative analysis.",
            "project",
        )
        mem.add(
            "market data loader for backtest",
            "Loads historical market data for quantitative backtest execution "
            "from multiple data sources with caching support.",
            "project",
        )

        # Check that at least one .relations.json was created
        relation_files = list(tmp_path.rglob("*.relations.json"))
        assert len(relation_files) >= 1, (
            f"Expected at least one .relations.json, found: {relation_files}"
        )


# ---------------------------------------------------------------------------
# 4. FTS: add then search finds entry
# ---------------------------------------------------------------------------


class TestFtsAddThenSearchFinds:
    def test_fts_add_then_search_finds(self, tmp_path, monkeypatch, fts_db):
        """With VT_MEMORY_FTS_INDEX=true, find_relevant uses FTS index."""
        monkeypatch.setenv("VT_MEMORY_FTS_INDEX", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        mem.add(
            "quant strategy notes",
            "This document describes a quantitative backtest strategy "
            "using momentum factors and mean reversion signals.",
            "project",
        )

        results = mem.find_relevant("backtest")
        assert len(results) >= 1
        assert any("quant" in e.title.lower() for e in results)


# ---------------------------------------------------------------------------
# 5. FTS: remove cleans index
# ---------------------------------------------------------------------------


class TestFtsRemoveCleansIndex:
    def test_fts_remove_cleans_index(self, tmp_path, monkeypatch, fts_db):
        """After remove, FTS search returns empty."""
        monkeypatch.setenv("VT_MEMORY_FTS_INDEX", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        mem.add(
            "ephemeral note",
            "This ephemeral note about cryptocurrency volatility "
            "should disappear after removal.",
            "project",
        )

        # Verify it's findable
        results = mem.find_relevant("ephemeral")
        assert len(results) >= 1

        # Remove and verify gone
        removed = mem.remove("ephemeral note")
        assert removed is True

        results = mem.find_relevant("ephemeral")
        assert results == []


# ---------------------------------------------------------------------------
# 6. Compression: GC triggers daily compression
# ---------------------------------------------------------------------------


class TestCompressionGcTriggersDaily:
    def test_compression_gc_triggers_daily(self, tmp_path, monkeypatch):
        """With VT_MEMORY_COMPRESSION=true, run_gc compresses old raw entries."""
        monkeypatch.setenv("VT_MEMORY_COMPRESSION", "true")
        monkeypatch.setenv("VT_MEMORY_GC", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        path = mem.add(
            "aging memory",
            "This is a sufficiently long piece of content that describes "
            "multiple aspects of quantitative trading strategies including "
            "momentum factors, mean reversion signals, and volatility "
            "targeting approaches used in systematic portfolio construction. "
            "The content also covers risk management techniques and position "
            "sizing algorithms for automated trading systems. "
            "Furthermore we discuss backtesting methodologies and walk-forward "
            "analysis to validate strategy robustness across market regimes.",
            "project",
        )
        assert path is not None

        # Manually set last_accessed to 10 days ago to trigger daily compression
        ten_days_ago = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 10 * 86400)
        )
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            f"last_accessed: {text.split('last_accessed: ')[1].split(chr(10))[0]}",
            f"last_accessed: {ten_days_ago}",
        )
        # Ensure compression_level is raw
        assert "compression_level: raw" in text
        path.write_text(text, encoding="utf-8")

        # Also set created_at to 10 days ago so it passes MIN_AGE_DAYS check
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            f"created_at: {text.split('created_at: ')[1].split(chr(10))[0]}",
            f"created_at: {ten_days_ago}",
        )
        path.write_text(text, encoding="utf-8")

        # Run GC with dry_run=False to trigger compression
        lifecycle = MemoryLifecycle(mem)
        lifecycle.run_gc(dry_run=False)

        # Verify compression_level changed to daily
        updated_text = path.read_text(encoding="utf-8")
        assert "compression_level: daily" in updated_text


# ---------------------------------------------------------------------------
# 7. Recall includes related field when links enabled
# ---------------------------------------------------------------------------


class TestRecallIncludesRelatedField:
    def test_recall_includes_related_field(self, tmp_path, monkeypatch):
        """With VT_MEMORY_LINKS=true, recall JSON includes 'related' field."""
        monkeypatch.setenv("VT_MEMORY_LINKS", "true")
        # Disable quality to avoid dedup blocking
        monkeypatch.setenv("VT_MEMORY_QUALITY", "false")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        # Add 3 entries with strong overlap for link discovery
        mem.add(
            "alpha factor research",
            "Alpha factor research involves constructing quantitative signals "
            "from market microstructure data for systematic trading.",
            "project",
        )
        mem.add(
            "factor backtesting framework",
            "The factor backtesting framework evaluates quantitative alpha "
            "signals using historical market microstructure data.",
            "project",
        )
        mem.add(
            "market microstructure analysis",
            "Market microstructure analysis reveals patterns in order flow "
            "that inform quantitative alpha factor construction.",
            "project",
        )

        tool = RememberTool(memory=mem)
        result_json = tool.execute(action="recall", query="quantitative alpha factor")
        result = json.loads(result_json)

        assert result["status"] == "ok"
        assert result["count"] >= 1
        # At least one memory should have a "related" field
        has_related = any("related" in m for m in result["memories"])
        assert has_related, (
            f"Expected at least one memory with 'related' field, got: {result['memories']}"
        )


# ---------------------------------------------------------------------------
# 8. Remove cleans .relations.json sidecar
# ---------------------------------------------------------------------------


class TestRemoveCleansRelationsSidecar:
    def test_remove_cleans_relations_sidecar(self, tmp_path, monkeypatch):
        """With VT_MEMORY_LINKS=true, remove() deletes .relations.json."""
        monkeypatch.setenv("VT_MEMORY_LINKS", "true")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        # Add entries with overlap to trigger link creation
        mem.add(
            "target entry for removal",
            "Target entry covering quantitative momentum factor strategies "
            "for systematic portfolio optimization and alpha generation.",
            "project",
        )
        mem.add(
            "related momentum analysis",
            "Momentum analysis for quantitative systematic factor strategies "
            "helps with portfolio alpha generation and risk management.",
            "project",
        )
        mem.add(
            "factor portfolio optimizer",
            "Portfolio optimizer for quantitative momentum factor alpha "
            "generation using systematic risk-adjusted strategies.",
            "project",
        )

        # Verify at least one relations file exists
        relation_files_before = list(tmp_path.rglob("*.relations.json"))
        assert len(relation_files_before) >= 1

        # Find and remove the target entry
        removed = mem.remove("target entry for removal")
        assert removed is True

        # The sidecar for the removed entry should be gone
        from src.memory.semantic_links import SemanticLinker
        linker = SemanticLinker(tmp_path)
        # Try to find the relations file for any file named like the target
        target_files = list(tmp_path.rglob("*target_entry*"))
        # The .md file itself should be deleted
        target_md = [f for f in target_files if f.suffix == ".md"]
        assert len(target_md) == 0, "Target .md file should be deleted"
        # Relations file for target should also be gone
        target_rel = [f for f in target_files if "relations.json" in f.name]
        assert len(target_rel) == 0, "Target .relations.json should be deleted"


# ---------------------------------------------------------------------------
# 9. Flags off: no behavior change from Tier 1
# ---------------------------------------------------------------------------


class TestFlagsOffNoBehaviorChange:
    def test_flags_off_no_behavior_change(self, tmp_path, monkeypatch):
        """With all flags off, no subdir, .relations.json, or FTS db created."""
        # Explicitly ensure all Tier 2 flags are off
        monkeypatch.setenv("VT_MEMORY_HIERARCHY", "false")
        monkeypatch.setenv("VT_MEMORY_LINKS", "false")
        monkeypatch.setenv("VT_MEMORY_FTS_INDEX", "false")
        monkeypatch.setenv("VT_MEMORY_COMPRESSION", "false")
        reset_env_config()

        mem = PersistentMemory(tmp_path)
        path = mem.add("plain memory", "just plain content", "user")
        assert path is not None

        # File should be in base dir (no subdirectory routing)
        assert path.parent == tmp_path

        # find_relevant should work (fallback token scan)
        results = mem.find_relevant("plain")
        assert len(results) >= 1

        # Remove should work
        removed = mem.remove("plain memory")
        assert removed is True

        # No .relations.json should exist
        relation_files = list(tmp_path.rglob("*.relations.json"))
        assert relation_files == []

        # No category subdirectories should be created
        subdirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        # archive dir may exist from other operations but no category dirs
        category_dirs = [d for d in subdirs if d.name in ("user", "feedback", "project", "reference")]
        assert category_dirs == []

        # No FTS database file in the memory dir
        db_files = list(tmp_path.rglob("*.db"))
        assert db_files == []
