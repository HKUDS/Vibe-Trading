"""PersistentMemory: file-based cross-session memory, zero external dependencies.

Storage layout:
    ~/.vibe-trading/memory/
    +-- MEMORY.md          # Index (< 200 lines)
    +-- user_prefs.md      # Individual memory entries with YAML frontmatter
    +-- project_btc.md
    +-- ...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.agent.frontmatter import parse_frontmatter as _parse_frontmatter
from typing import List, Optional

logger = logging.getLogger(__name__)

MEMORY_BASE = Path.home() / ".vibe-trading" / "memory"
MAX_INDEX_LINES = 200
MAX_ENTRY_CHARS = 8000
MAX_RESULTS = 5
METADATA_WEIGHT = 2.0
MEMORY_TYPES = ("user", "feedback", "project", "reference")

# Script ranges tokenized and slugged at char level (no word-boundary
# whitespace). Arabic/Hebrew narrowed to letter blocks to exclude bidi
# controls and combining marks from on-disk slugs.
_NON_LATIN_SCRIPT_RANGES = (
    "一-鿿"   # CJK Unified Ideographs   (U+4E00-U+9FFF)
    "㐀-䶿"   # CJK Extension A          (U+3400-U+4DBF)
    "฀-๿"   # Thai                     (U+0E00-U+0E7F)
    "ؠ-ي"   # Arabic letters           (U+0620-U+064A)
    "א-ת"   # Hebrew letters           (U+05D0-U+05EA)
    "Ѐ-ӿ"   # Cyrillic                 (U+0400-U+04FF)
)

_TOKEN_RE = re.compile(rf"[a-zA-Z0-9]{{3,}}|[{_NON_LATIN_SCRIPT_RANGES}]")
_SLUG_DISALLOWED_RE = re.compile(rf"[^a-z0-9_\-{_NON_LATIN_SCRIPT_RANGES}]")


@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry on disk.

    Attributes:
        path: File path.
        title: Memory title.
        description: One-line description (used for retrieval scoring).
        memory_type: Category (user/feedback/project/reference).
        body: Body text content.
        modified_at: File modification timestamp.
    """

    path: Path
    title: str
    description: str
    memory_type: str
    body: str
    modified_at: float


def _tokenize(text: str) -> set[str]:
    """Split text into searchable tokens.

    ASCII words >= 3 chars + individual characters from non-Latin scripts
    listed in ``_NON_LATIN_SCRIPT_RANGES`` (CJK, Thai, Arabic, Hebrew,
    Cyrillic). Underscores are
    treated as word boundaries so snake_case titles (e.g. ``mcp_wiring_test``)
    match natural-language queries (``"mcp wiring"``) as well as verbatim
    lookups.

    Args:
        text: Input text.

    Returns:
        Set of tokens.
    """
    return set(_TOKEN_RE.findall(text.lower()))


def _coerce_str(value: object, default: str = "") -> str:
    """Coerce frontmatter values to a display string.

    ``parse_frontmatter`` returns lists for ``[a, b]`` syntax and bools for
    ``true``/``false``. ``MemoryEntry`` annotates these fields as ``str`` so
    callers (CLI rendering, recall scoring) can rely on string operations.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


class PersistentMemory:
    """File-based persistent memory that survives across sessions.

    Design:
        - Frozen snapshot injected into system prompt at session start (preserves prompt cache).
        - Disk writes via add()/remove() update files immediately but do NOT change the snapshot.
        - Next session picks up the updated state.

    Attributes:
        snapshot: Frozen memory index text for system prompt injection.
    """

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        """Initialize PersistentMemory.

        Args:
            memory_dir: Override memory directory (default: ~/.vibe-trading/memory/).
        """
        self._dir = memory_dir or MEMORY_BASE
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "MEMORY.md"
        self._snapshot: str = ""
        self._load_snapshot()

    def _load_snapshot(self) -> None:
        """Load index as frozen snapshot. Called once at init."""
        if self._index_path.exists():
            try:
                text = self._index_path.read_text(encoding="utf-8")
                lines = text.split("\n")[:MAX_INDEX_LINES]
                self._snapshot = "\n".join(lines)
            except OSError:
                self._snapshot = ""

    @property
    def snapshot(self) -> str:
        """Frozen memory index for system prompt injection."""
        return self._snapshot

    def _scan_entries(self) -> List[MemoryEntry]:
        """Scan all .md files (except MEMORY.md) and parse frontmatter.

        Returns:
            List of parsed memory entries.
        """
        entries: List[MemoryEntry] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            entries.append(MemoryEntry(
                path=path,
                title=_coerce_str(meta.get("name"), default=path.stem),
                description=_coerce_str(meta.get("description")),
                memory_type=_coerce_str(meta.get("type"), default="project"),
                body=body[:MAX_ENTRY_CHARS],
                modified_at=path.stat().st_mtime,
            ))
        return entries

    def list_entries(self) -> List[MemoryEntry]:
        """Return all persisted memory entries, filename-sorted."""
        return self._scan_entries()

    def find(self, name: str) -> Optional[MemoryEntry]:
        """Resolve a memory by exact title, then by on-disk filename stem.

        Stem fallback accepts both the full ``{type}_{slug}`` form and the
        bare ``slug`` suffix so users can paste either form from the index.
        """
        needle = name.strip()
        if not needle:
            return None
        entries = self._scan_entries()
        for entry in entries:
            if entry.title == needle:
                return entry
        for entry in entries:
            stem = entry.path.stem
            if stem == needle or stem.endswith(f"_{needle}"):
                return entry
        return None

    def remove_entry(self, entry: MemoryEntry) -> bool:
        """Delete a resolved entry without re-scanning to find it again."""
        try:
            entry.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove memory entry %s: %s", entry.path, exc)
            return False
        self._rebuild_index()
        return True

    def find_relevant(self, query: str, max_results: int = MAX_RESULTS) -> List[MemoryEntry]:
        """Keyword search across all memory entries.

        Scoring: metadata_hits * 2.0 + body_hits * 1.0.

        Args:
            query: Search query.
            max_results: Maximum entries to return.

        Returns:
            Top-scoring memory entries.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._scan_entries():
            meta_tokens = _tokenize(f"{entry.title} {entry.description}")
            body_tokens = _tokenize(entry.body)
            score = len(query_tokens & meta_tokens) * METADATA_WEIGHT + len(query_tokens & body_tokens)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], -x[1].modified_at))
        return [entry for _, entry in scored[:max_results]]

    def add(self, name: str, content: str, memory_type: str = "project",
            description: str = "") -> Path:
        """Save a new memory entry and update the index.

        Args:
            name: Memory name (used as filename slug).
            content: Memory body text.
            memory_type: One of user/feedback/project/reference.
            description: One-line description for retrieval scoring.

        Returns:
            Path to the created memory file.
        """
        # Preserve non-Latin script characters in the slug — collapsing
        # them all to ``_`` caused two same-length non-Latin names to share a
        # filename and silently overwrite each other (see PR #95 for CJK;
        # this generalizes to Thai/Arabic/Hebrew/Cyrillic).
        slug = _SLUG_DISALLOWED_RE.sub("_", name.lower().strip())[:60]
        filename = f"{memory_type}_{slug}.md"
        path = self._dir / filename

        safe_name = name.replace("\n", " ").replace("\r", " ")
        safe_desc = (description or name).replace("\n", " ").replace("\r", " ")
        frontmatter = (
            f"---\nname: {safe_name}\n"
            f"description: {safe_desc}\n"
            f"type: {memory_type}\n---\n\n"
            f"{content}"
        )
        path.write_text(frontmatter, encoding="utf-8")
        self._update_index(name, filename, description or name)
        return path

    def remove(self, name: str) -> bool:
        """Remove a memory entry by name.

        Args:
            name: Memory name to remove.

        Returns:
            True if found and removed.
        """
        for entry in self._scan_entries():
            if entry.title == name:
                entry.path.unlink(missing_ok=True)
                self._rebuild_index()
                return True
        return False

    def _update_index(self, title: str, filename: str, description: str) -> None:
        """Append or update an entry in MEMORY.md."""
        new_line = f"- [{title}]({filename}) — {description}"

        if self._index_path.exists():
            lines = self._index_path.read_text(encoding="utf-8").split("\n")
            updated = False
            for i, line in enumerate(lines):
                if f"[{title}]" in line:
                    lines[i] = new_line
                    updated = True
                    break
            if not updated:
                lines.append(new_line)
            text = "\n".join(lines[:MAX_INDEX_LINES])
        else:
            text = new_line

        self._index_path.write_text(text, encoding="utf-8")

    def _rebuild_index(self) -> None:
        """Rebuild MEMORY.md from all existing entry files."""
        entries = self._scan_entries()
        lines = [f"- [{e.title}]({e.path.name}) — {e.description}" for e in entries]
        self._index_path.write_text("\n".join(lines[:MAX_INDEX_LINES]), encoding="utf-8")
