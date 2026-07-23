"""PersistentMemory: file-based cross-session memory, zero external dependencies."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import sys
import time as _time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from src.agent.frontmatter import parse_frontmatter as _parse_frontmatter

logger = logging.getLogger(__name__)

MEMORY_BASE = Path.home() / ".vibe-trading" / "memory"
MAX_INDEX_LINES = 200
MAX_ENTRY_CHARS = 8000
MAX_RESULTS = 5
METADATA_WEIGHT = 2.0
MEMORY_TYPES = ("user", "feedback", "project", "reference")

_LOCK_TIMEOUT_S = 5.0

# Sliding window for content deduplication (seconds).
# Catches rapid-fire duplicates from retry loops or parallel agent calls.
DEDUP_WINDOW_SECONDS = 30.0


def content_hash(name: str, description: str, content: str = "") -> str:
    """Generate deterministic hash for deduplication."""
    payload = f"{name.strip().lower()}|{description.strip().lower()}|{content.strip().lower()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


@contextmanager
def memory_lock(memory_dir: Path) -> Generator[bool, None, None]:
    """Acquire exclusive file lock; yields True if acquired, False on timeout."""
    if sys.platform == "win32":
        yield True
        return
    import fcntl

    lock_path = memory_dir / ".lock"
    lock_path.touch(exist_ok=True)
    fd = None
    try:
        fd = open(lock_path, "w")  # noqa: SIM115
        deadline = _time.monotonic() + _LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield True
                return
            except (OSError, BlockingIOError):
                if _time.monotonic() >= deadline:
                    logger.warning("memory_lock: timeout after %.1fs", _LOCK_TIMEOUT_S)
                    yield False
                    return
                _time.sleep(0.1)
    finally:
        if fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            fd.close()


HALF_LIFE_DAYS = 14.0
_DECAY_LAMBDA = math.log(2) / HALF_LIFE_DAYS
_ACCESS_BOOST = 0.1


def compute_importance(
    quality_score: float, access_count: int, days_since_last_access: float
) -> float:
    """Compute importance via Ebbinghaus-inspired decay formula."""
    from src.config.accessor import get_env_config

    if not get_env_config().memory.decay_enabled:
        return quality_score
    retention = math.exp(-_DECAY_LAMBDA * max(0.0, days_since_last_access))
    access_bonus = min(0.3, access_count * _ACCESS_BOOST)
    raw = quality_score * (retention + access_bonus)
    return min(1.0, max(0.0, raw))


def _is_decay_enabled() -> bool:
    """Check if importance decay is enabled via VT_MEMORY_DECAY env var."""
    from src.config.accessor import get_env_config

    return get_env_config().memory.decay_enabled


def _is_quality_enabled() -> bool:
    """Check if quality scoring is enabled via VT_MEMORY_QUALITY env var."""
    from src.config.accessor import get_env_config

    return get_env_config().memory.quality_enabled


# Script ranges for non-Latin tokenization and slug generation.
_NON_LATIN_SCRIPT_RANGES = (
    "一-鿿"  # CJK Unified Ideographs
    "㐀-䶿"  # CJK Extension A
    "฀-๿"  # Thai
    "ؠ-ي"  # Arabic letters
    "א-ת"  # Hebrew letters
    "Ѐ-ӿ"  # Cyrillic
)

_TOKEN_RE = re.compile(rf"[a-zA-Z0-9]{{3,}}|[{_NON_LATIN_SCRIPT_RANGES}]")
_SLUG_DISALLOWED_RE = re.compile(rf"[^a-z0-9_\-{_NON_LATIN_SCRIPT_RANGES}]")


@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry on disk."""

    path: Path
    title: str
    description: str
    memory_type: str
    body: str
    modified_at: float
    id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    keywords: tuple[str, ...] = ()
    quality_score: float = 0.5
    access_count: int = 0
    last_accessed: float = 0.0
    importance: float = 0.5
    related_memories: tuple[str, ...] = ()


def _tokenize(text: str) -> set[str]:
    """Split text into searchable tokens (ASCII >=3 chars + non-Latin chars)."""
    return set(_TOKEN_RE.findall(text.lower()))


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TRUNCATION_MARKER = "\n\n[truncated at {limit} chars]\n"


def _sanitize_body(content: str) -> str:
    """Strip C0/C1 control bytes from `content` while keeping ``\\n`` and ``\\t``."""
    return _CONTROL_CHAR_RE.sub("", content)


def _truncate_body(content: str, limit: int = MAX_ENTRY_CHARS) -> str:
    """Clip `content` to `limit` chars, leaving room for the marker."""
    if len(content) <= limit:
        return content
    marker = _TRUNCATION_MARKER.format(limit=limit)
    head_len = max(0, limit - len(marker))
    return content[:head_len] + marker


def _coerce_str(value: object, default: str = "") -> str:
    """Coerce frontmatter values to a display string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _parse_timestamp(value: object, fallback: float) -> float:
    """Parse a timestamp from frontmatter. Returns epoch float."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    return fallback


class PersistentMemory:
    """File-based persistent memory that survives across sessions."""

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        self._dir = memory_dir or MEMORY_BASE
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "MEMORY.md"
        self._snapshot: str = ""
        self._recent_hashes: dict[str, float] = {}  # hash -> epoch timestamp
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
        """Scan all .md files (except MEMORY.md) and parse frontmatter."""
        entries: List[MemoryEntry] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            mtime = path.stat().st_mtime
            raw_kw = meta.get("keywords", [])
            keywords = tuple(
                str(k)[:30] for k in (raw_kw if isinstance(raw_kw, list) else [])
            )[:5]
            raw_related = meta.get("related_memories", [])
            related = tuple(
                str(r)
                for r in (raw_related if isinstance(raw_related, list) else [])
                if isinstance(r, str)
                and len(r) == 6
                and all(c in "0123456789abcdef" for c in r.lower())
            )

            qs = meta.get("quality_score", 0.5)
            try:
                qs = max(0.0, min(1.0, float(qs)))
            except (TypeError, ValueError):
                qs = 0.5

            ac = meta.get("access_count", 0)
            try:
                ac = max(0, int(ac))
            except (TypeError, ValueError):
                ac = 0
            # Generate id if missing
            entry_id = str(meta.get("id", ""))
            if not entry_id or len(entry_id) != 6:
                entry_id = hashlib.sha256(
                    f"{meta.get('name', path.stem)}{mtime}".encode()
                ).hexdigest()[:6]

            # Timestamps and importance
            created = _parse_timestamp(meta.get("created_at"), mtime)
            updated = _parse_timestamp(meta.get("updated_at"), mtime)
            last_acc = _parse_timestamp(meta.get("last_accessed"), mtime)
            now = _time.time()
            days_since = max(0.0, (now - last_acc) / 86400.0)
            importance = compute_importance(qs, ac, days_since)

            entries.append(
                MemoryEntry(
                    path=path,
                    title=_coerce_str(meta.get("name"), default=path.stem),
                    description=_coerce_str(meta.get("description")),
                    memory_type=_coerce_str(meta.get("type"), default="project"),
                    body=body[:MAX_ENTRY_CHARS],
                    modified_at=mtime,
                    id=entry_id,
                    created_at=created,
                    updated_at=updated,
                    keywords=keywords,
                    quality_score=qs,
                    access_count=ac,
                    last_accessed=last_acc,
                    importance=importance,
                    related_memories=related,
                )
            )
        return entries

    def list_entries(self) -> List[MemoryEntry]:
        """Return all persisted memory entries, filename-sorted."""
        return self._scan_entries()

    def find(self, name: str) -> Optional[MemoryEntry]:
        """Resolve a memory by exact title, then by on-disk filename stem."""
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
        with memory_lock(self._dir) as acquired:
            if not acquired:
                logger.warning("remove_entry(%s): lock timeout", entry.title)
            try:
                entry.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove memory entry %s: %s", entry.path, exc)
                return False
            self._rebuild_index()
        return True

    def find_relevant(
        self, query: str, max_results: int = MAX_RESULTS
    ) -> List[MemoryEntry]:
        """Keyword search across all entries, weighted by importance."""
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._scan_entries():
            meta_tokens = _tokenize(f"{entry.title} {entry.description}")
            body_tokens = _tokenize(entry.body)
            kw_tokens = _tokenize(" ".join(entry.keywords))
            token_score = (
                len(query_tokens & meta_tokens) * METADATA_WEIGHT
                + len(query_tokens & kw_tokens) * METADATA_WEIGHT
                + len(query_tokens & body_tokens)
            )
            if token_score > 0:
                final_score = token_score
                if _is_decay_enabled():
                    final_score *= 0.5 + 0.5 * entry.importance
                scored.append((final_score, entry))

        scored.sort(key=lambda x: (-x[0], -x[1].modified_at))
        return [entry for _, entry in scored[:max_results]]

    def is_duplicate(self, name: str, description: str, content: str = "") -> bool:
        """Check if a memory with similar content was recently written.

        Uses a 30-second sliding window to catch rapid-fire duplicates
        from retry loops or parallel agent calls.
        """
        new_hash = content_hash(name, description, content)
        now = _time.time()
        self._cleanup_expired_hashes(now)
        if new_hash in self._recent_hashes:
            if now - self._recent_hashes[new_hash] < DEDUP_WINDOW_SECONDS:
                return True
        self._recent_hashes[new_hash] = now
        return False

    def _cleanup_expired_hashes(self, now: float) -> None:
        """Remove hash entries older than the dedup window to bound memory use."""
        threshold = now - DEDUP_WINDOW_SECONDS
        expired = [h for h, ts in self._recent_hashes.items() if ts < threshold]
        for h in expired:
            del self._recent_hashes[h]

    def add(
        self,
        name: str,
        content: str,
        memory_type: str = "project",
        description: str = "",
    ) -> Optional[Path]:
        """Save a new memory entry and update the index."""
        if _is_quality_enabled() and self.is_duplicate(name, description, content):
            logger.debug(
                "Duplicate memory write blocked within %.0fs window: %s",
                DEDUP_WINDOW_SECONDS,
                name,
            )
            return None

        stripped_name = name.strip()
        if not stripped_name:
            raise ValueError("memory name must not be empty or whitespace-only")
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"memory_type must be one of: {', '.join(MEMORY_TYPES)}")

        slug = _SLUG_DISALLOWED_RE.sub("_", stripped_name.lower())[:60]
        if slug.strip("_") == "":
            digest = hashlib.sha256(stripped_name.encode("utf-8")).hexdigest()[:6]
            slug = f"{slug}_{digest}" if slug else digest

        filename = f"{memory_type}_{slug}.md"
        path = self._dir / filename
        safe_name = stripped_name.replace("\n", " ").replace("\r", " ")
        safe_desc = (description or stripped_name).replace("\n", " ").replace("\r", " ")
        clean_content = _truncate_body(_sanitize_body(content))

        entry_id = hashlib.sha256(
            f"{stripped_name}{_time.time()}".encode()
        ).hexdigest()[:6]
        now_iso = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime())

        frontmatter = (
            f"---\nname: {safe_name}\n"
            f"description: {safe_desc}\n"
            f"type: {memory_type}\n"
            f"id: {entry_id}\n"
            f"created_at: {now_iso}\n"
            f"updated_at: {now_iso}\n"
            f"keywords: []\n"
            f"quality_score: 0.5\n"
            f"access_count: 0\n"
            f"last_accessed: {now_iso}\n"
            f"importance: 0.5\n"
            f"related_memories: []\n"
            f"---\n\n"
            f"{clean_content}"
        )
        with memory_lock(self._dir) as acquired:
            if not acquired:
                logger.warning(
                    "add(%s): lock timeout, best-effort write", stripped_name
                )
            path.write_text(frontmatter, encoding="utf-8")
            self._update_index(stripped_name, filename, description or stripped_name)
        return path

    def remove(self, name: str) -> bool:
        """Remove a memory entry by name. Returns True if found and removed."""
        for entry in self._scan_entries():
            if entry.title == name:
                with memory_lock(self._dir) as acquired:
                    if not acquired:
                        logger.warning("remove(%s): lock timeout", name)
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
        self._index_path.write_text(
            "\n".join(lines[:MAX_INDEX_LINES]), encoding="utf-8"
        )
