"""Hierarchical directory routing for memory entries (Tier 2).

Organizes memory files into category subdirectories based on memory_type,
enabling O(category_size) scoped searches instead of O(n) flat scans.

Feature flag: VT_MEMORY_HIERARCHY (default off).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Category directories matching MEMORY_TYPES in persistent.py
CATEGORIES = ("user", "feedback", "project", "reference")

# Files/dirs to skip when scanning
_SKIP_NAMES = frozenset({"MEMORY.md", ".hierarchy.yaml", ".lock", "archive", "gc.log"})


@dataclass
class CategorySummary:
    """Summary metadata for a single category directory."""

    count: int = 0
    keywords: List[str] = field(default_factory=list)


class MemoryHierarchy:
    """Manages hierarchical directory structure for memory entries.

    Provides O(category_size) routed access to memory files organized
    by memory_type, while maintaining backward compatibility with
    flat-stored entries in the base directory.
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialize with the memory base directory.

        Args:
            base_dir: Root directory for memory storage
                      (e.g. ~/.vibe-trading/memory/).
        """
        self._base_dir = base_dir
        self._index_path = base_dir / ".hierarchy.yaml"

    @property
    def base_dir(self) -> Path:
        """Return the configured base directory."""
        return self._base_dir

    def _ensure_category_dir(self, category: str) -> Path:
        """Create category subdirectory if it does not exist.

        Args:
            category: One of CATEGORIES or any string.

        Returns:
            Path to the category subdirectory.
        """
        cat_dir = self._base_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        return cat_dir

    def route_entry(self, memory_type: str, filename: str) -> Path:
        """Determine storage path: base_dir/{memory_type}/{filename}.

        Creates category directory on demand.
        Falls back to base_dir for unknown types.

        Args:
            memory_type: Category identifier (e.g. "user", "project").
            filename: The .md filename for the memory entry.

        Returns:
            Full path where the entry should be stored.
        """
        if memory_type in CATEGORIES:
            cat_dir = self._ensure_category_dir(memory_type)
            return cat_dir / filename
        # Unknown type falls back to base directory
        logger.warning(
            "Unknown memory_type '%s', routing to base dir", memory_type
        )
        return self._base_dir / filename

    def scan_all(self) -> List[Path]:
        """Scan base dir + all category subdirs for *.md files.

        Skips entries listed in _SKIP_NAMES and the archive/ directory.
        Includes flat-stored entries in base dir for backward compatibility.

        Returns:
            Sorted list of .md file paths.
        """
        results: List[Path] = []

        # Scan base directory (flat legacy entries)
        if self._base_dir.is_dir():
            for item in self._base_dir.iterdir():
                if item.name in _SKIP_NAMES:
                    continue
                if item.is_file() and item.suffix == ".md":
                    results.append(item)

        # Scan each known category subdirectory
        for category in CATEGORIES:
            cat_dir = self._base_dir / category
            if cat_dir.is_dir():
                for item in cat_dir.iterdir():
                    if item.is_file() and item.suffix == ".md":
                        results.append(item)

        results.sort(key=lambda p: p.name)
        return results

    def scan_category(self, category: str) -> List[Path]:
        """Scan only one category subdir for *.md files.

        Args:
            category: The category name to scan.

        Returns:
            Sorted list of .md file paths in that category directory.
        """
        cat_dir = self._base_dir / category
        results: List[Path] = []

        if not cat_dir.is_dir():
            return results

        for item in cat_dir.iterdir():
            if item.is_file() and item.suffix == ".md":
                results.append(item)

        results.sort(key=lambda p: p.name)
        return results

    def rebuild_index(self, entries: list) -> None:
        """Write .hierarchy.yaml with per-category summary.

        Format:
            categories:
              <name>:
                count: <int>
                keywords: [kw1, kw2, ...]
            rebuilt_at: <ISO-8601>

        Uses manual YAML formatting (no PyYAML dependency).

        Args:
            entries: List of dicts with at least 'memory_type' key and
                     optionally 'keywords' (list of strings).
        """
        # Aggregate per-category statistics
        cat_data: Dict[str, CategorySummary] = {
            cat: CategorySummary() for cat in CATEGORIES
        }

        for entry in entries:
            mtype = entry.get("memory_type", "")
            if mtype not in cat_data:
                continue
            cat_data[mtype].count += 1
            # Collect keywords (deduplicate later)
            keywords = entry.get("keywords", [])
            if isinstance(keywords, list):
                cat_data[mtype].keywords.extend(keywords)

        # Deduplicate and limit keywords per category
        max_keywords = 10  # keep index compact
        for summary in cat_data.values():
            seen: Set[str] = set()
            unique: List[str] = []
            for kw in summary.keywords:
                kw_lower = kw.lower().strip()
                if kw_lower and kw_lower not in seen:
                    seen.add(kw_lower)
                    unique.append(kw_lower)
            summary.keywords = unique[:max_keywords]

        # Generate ISO-8601 timestamp
        rebuilt_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

        # Write YAML manually
        lines: List[str] = [
            "# Auto-generated memory hierarchy index",
            f'rebuilt_at: "{rebuilt_at}"',
            "categories:",
        ]
        for cat in CATEGORIES:
            summary = cat_data[cat]
            kw_list = ", ".join(summary.keywords)
            lines.append(f"  {cat}:")
            lines.append(f"    count: {summary.count}")
            lines.append(f"    keywords: [{kw_list}]")

        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.debug("Rebuilt hierarchy index at %s", self._index_path)

    def _parse_index_keywords(self) -> Dict[str, List[str]]:
        """Parse .hierarchy.yaml to extract per-category keywords.

        Returns:
            Dict mapping category name to list of keywords.
            Empty dict if index file does not exist or is malformed.
        """
        if not self._index_path.is_file():
            return {}

        result: Dict[str, List[str]] = {}
        current_cat: Optional[str] = None

        try:
            text = self._index_path.read_text(encoding="utf-8")
        except OSError:
            return {}

        for line in text.splitlines():
            stripped = line.strip()

            # Detect category header (e.g. "  user:")
            if (
                stripped.endswith(":")
                and not stripped.startswith("#")
                and not stripped.startswith("categories")
                and not stripped.startswith("rebuilt_at")
            ):
                cat_name = stripped.rstrip(":")
                if cat_name in CATEGORIES:
                    current_cat = cat_name
                    if current_cat not in result:
                        result[current_cat] = []
                else:
                    current_cat = None

            # Detect keywords line (e.g. "    keywords: [a, b, c]")
            elif stripped.startswith("keywords:") and current_cat:
                # Extract content between brackets
                bracket_start = stripped.find("[")
                bracket_end = stripped.find("]")
                if bracket_start != -1 and bracket_end != -1:
                    inner = stripped[bracket_start + 1 : bracket_end]
                    keywords = [
                        k.strip() for k in inner.split(",") if k.strip()
                    ]
                    result[current_cat] = keywords

        return result

    def prune_search_scope(
        self, query_tokens: Set[str], category_filter: str = ""
    ) -> List[Path]:
        """Narrow search scope based on category filter or keyword overlap.

        If category_filter is set, only scan that category.
        Otherwise scan all categories (maintains compatibility).

        When no category_filter is provided and an index exists, categories
        are ordered by keyword overlap score (most relevant first), but all
        files are still returned for completeness.

        Args:
            query_tokens: Set of lowercase query terms for relevance scoring.
            category_filter: If non-empty, restrict scan to this category.

        Returns:
            List of .md file paths in priority order.
        """
        # Direct category filter — fast path
        if category_filter:
            if category_filter in CATEGORIES:
                return self.scan_category(category_filter)
            # Unknown filter: fall back to full scan
            logger.warning(
                "Unknown category_filter '%s', falling back to scan_all",
                category_filter,
            )
            return self.scan_all()

        # No filter: use keyword overlap to order categories
        index_keywords = self._parse_index_keywords()

        if not index_keywords:
            # No index available — full scan
            return self.scan_all()

        # Score each category by keyword overlap with query tokens
        scored: List[tuple] = []
        for cat in CATEGORIES:
            cat_kws = set(index_keywords.get(cat, []))
            overlap = len(query_tokens & cat_kws)
            scored.append((overlap, cat))

        # Sort descending by overlap score
        scored.sort(key=lambda x: x[0], reverse=True)

        # Collect files: prioritized categories first, then base dir
        results: List[Path] = []
        seen: Set[Path] = set()

        for _score, cat in scored:
            for p in self.scan_category(cat):
                if p not in seen:
                    results.append(p)
                    seen.add(p)

        # Include flat base-dir entries for backward compatibility
        if self._base_dir.is_dir():
            for item in self._base_dir.iterdir():
                if item.name in _SKIP_NAMES:
                    continue
                if item.is_file() and item.suffix == ".md" and item not in seen:
                    results.append(item)
                    seen.add(item)

        return results

    def migrate_flat_entry(
        self, file_path: Path, memory_type: str
    ) -> Optional[Path]:
        """Move a flat-stored entry to its category subdir.

        Only moves if the file currently resides in base_dir (not already
        in a subdirectory). Preserves file content unchanged.

        Args:
            file_path: Current path of the memory .md file.
            memory_type: Target category for the file.

        Returns:
            New path after migration, or None if migration was skipped
            (file not in base dir, target same as current, or error).
        """
        # Validate source exists and is in base directory
        if not file_path.is_file():
            logger.warning("Cannot migrate non-existent file: %s", file_path)
            return None

        if file_path.parent != self._base_dir:
            logger.debug(
                "File %s not in base dir, skip migration", file_path.name
            )
            return None

        if memory_type not in CATEGORIES:
            logger.warning(
                "Cannot migrate to unknown category '%s'", memory_type
            )
            return None

        # Determine destination
        dest_dir = self._ensure_category_dir(memory_type)
        dest_path = dest_dir / file_path.name

        if dest_path.exists():
            logger.warning(
                "Destination already exists, skip migration: %s", dest_path
            )
            return None

        try:
            file_path.rename(dest_path)
            logger.info(
                "Migrated %s -> %s/%s",
                file_path.name,
                memory_type,
                file_path.name,
            )
            return dest_path
        except OSError as exc:
            logger.error("Migration failed for %s: %s", file_path.name, exc)
            return None
