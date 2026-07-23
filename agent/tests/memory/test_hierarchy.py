"""Tests for MemoryHierarchy: hierarchical directory routing (Tier 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory.hierarchy import CATEGORIES, MemoryHierarchy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(path: Path, title: str = "test", memory_type: str = "project") -> Path:
    """Write a dummy .md file with basic frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\nname: {title}\ntype: {memory_type}\n"
        f"keywords: [{title}]\n---\n\nBody of {title}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRouteEntry:
    def test_route_entry_creates_subdir(self, tmp_path: Path) -> None:
        """Routing to known categories creates subdirectory."""
        h = MemoryHierarchy(tmp_path)
        for cat in CATEGORIES:
            result = h.route_entry(cat, f"{cat}_note.md")
            assert result.parent.name == cat
            assert result.parent.is_dir()
            assert result.name == f"{cat}_note.md"

    def test_route_entry_unknown_type_falls_back(self, tmp_path: Path) -> None:
        """Unknown memory_type routes to base directory."""
        h = MemoryHierarchy(tmp_path)
        result = h.route_entry("unknown_type", "note.md")
        assert result.parent == tmp_path
        assert result.name == "note.md"


class TestScan:
    def test_scan_all_includes_root_and_subdirs(self, tmp_path: Path) -> None:
        """scan_all finds .md files in both base dir and category subdirs."""
        h = MemoryHierarchy(tmp_path)
        # Root-level entry
        _write_md(tmp_path / "legacy.md", title="legacy")
        # Category entry
        _write_md(tmp_path / "user" / "user_note.md", title="user_note")
        _write_md(tmp_path / "project" / "proj_note.md", title="proj_note")

        results = h.scan_all()
        names = [p.name for p in results]
        assert "legacy.md" in names
        assert "user_note.md" in names
        assert "proj_note.md" in names

    def test_scan_all_skips_special_files(self, tmp_path: Path) -> None:
        """scan_all skips MEMORY.md and .hierarchy.yaml."""
        h = MemoryHierarchy(tmp_path)
        (tmp_path / "MEMORY.md").write_text("index", encoding="utf-8")
        (tmp_path / ".hierarchy.yaml").write_text("meta", encoding="utf-8")
        _write_md(tmp_path / "real.md", title="real")

        results = h.scan_all()
        names = [p.name for p in results]
        assert "MEMORY.md" not in names
        assert ".hierarchy.yaml" not in names
        assert "real.md" in names

    def test_scan_category_only_target(self, tmp_path: Path) -> None:
        """scan_category only returns files in specified category."""
        h = MemoryHierarchy(tmp_path)
        _write_md(tmp_path / "user" / "u1.md", title="u1")
        _write_md(tmp_path / "project" / "p1.md", title="p1")
        _write_md(tmp_path / "root.md", title="root")

        user_files = h.scan_category("user")
        assert len(user_files) == 1
        assert user_files[0].name == "u1.md"

    def test_scan_category_empty(self, tmp_path: Path) -> None:
        """scan_category for non-existent dir returns empty list."""
        h = MemoryHierarchy(tmp_path)
        assert h.scan_category("feedback") == []


class TestRebuildIndex:
    def test_rebuild_index_writes_yaml(self, tmp_path: Path) -> None:
        """rebuild_index generates .hierarchy.yaml with correct structure."""
        h = MemoryHierarchy(tmp_path)
        entries = [
            {"memory_type": "user", "keywords": ["trading", "strategy"]},
            {"memory_type": "user", "keywords": ["portfolio"]},
            {"memory_type": "project", "keywords": ["backtest"]},
        ]
        h.rebuild_index(entries)

        index_path = tmp_path / ".hierarchy.yaml"
        assert index_path.is_file()
        content = index_path.read_text(encoding="utf-8")
        assert "categories:" in content
        assert "user:" in content
        assert "count: 2" in content
        assert "trading" in content
        assert "project:" in content
        assert "count: 1" in content
        assert "rebuilt_at:" in content


class TestPruneSearchScope:
    def test_prune_search_scope_with_category_filter(self, tmp_path: Path) -> None:
        """With category_filter, only scans that category."""
        h = MemoryHierarchy(tmp_path)
        _write_md(tmp_path / "user" / "u1.md", title="u1")
        _write_md(tmp_path / "project" / "p1.md", title="p1")

        results = h.prune_search_scope(set(), category_filter="user")
        names = [p.name for p in results]
        assert "u1.md" in names
        assert "p1.md" not in names

    def test_prune_search_scope_keyword_overlap(self, tmp_path: Path) -> None:
        """Categories with keyword overlap are prioritized."""
        h = MemoryHierarchy(tmp_path)
        # Create entries in subdirs
        _write_md(tmp_path / "user" / "u1.md", title="u1")
        _write_md(tmp_path / "project" / "p1.md", title="p1")

        # Build index with known keywords
        entries = [
            {"memory_type": "user", "keywords": ["alpha", "beta"]},
            {"memory_type": "project", "keywords": ["gamma", "delta"]},
        ]
        h.rebuild_index(entries)

        # Query with tokens overlapping "project" keywords
        results = h.prune_search_scope({"gamma", "delta"})
        names = [p.name for p in results]
        # project files should appear first (higher overlap)
        assert "p1.md" in names
        assert names.index("p1.md") < names.index("u1.md")


class TestMigrateFlatEntry:
    def test_migrate_flat_entry(self, tmp_path: Path) -> None:
        """Moves file from root to category subdir."""
        h = MemoryHierarchy(tmp_path)
        src = _write_md(tmp_path / "old_note.md", title="old_note")
        assert src.exists()

        new_path = h.migrate_flat_entry(src, "user")
        assert new_path is not None
        assert new_path.parent.name == "user"
        assert new_path.name == "old_note.md"
        assert new_path.exists()
        assert not src.exists()

    def test_migrate_skips_already_in_subdir(self, tmp_path: Path) -> None:
        """Does not migrate files already in a subdirectory."""
        h = MemoryHierarchy(tmp_path)
        src = _write_md(tmp_path / "user" / "already.md", title="already")

        result = h.migrate_flat_entry(src, "project")
        assert result is None

    def test_migrate_unknown_category(self, tmp_path: Path) -> None:
        """Cannot migrate to unknown category."""
        h = MemoryHierarchy(tmp_path)
        src = _write_md(tmp_path / "note.md", title="note")

        result = h.migrate_flat_entry(src, "nonexistent")
        assert result is None
        assert src.exists()
