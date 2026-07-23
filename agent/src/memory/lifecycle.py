"""Memory lifecycle management: quality scoring, decay, and garbage collection.

Provides reinforcement learning-style quality updates, Ebbinghaus-inspired
importance decay, and capacity-based garbage collection. All write operations
are guarded by file-level locking (single-writer model).

Feature flags (env vars):
    VT_MEMORY_QUALITY  – enable quality scoring / access tracking
    VT_MEMORY_GC       – enable garbage collection
    VT_MEMORY_DECAY    – enable importance decay formula
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from types import MappingProxyType

from src.memory.persistent import (
    MemoryEntry,
    PersistentMemory,
    compute_importance,
    memory_lock,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


def is_quality_enabled() -> bool:
    """Check if quality scoring is enabled via VT_MEMORY_QUALITY env var."""
    from src.config.accessor import get_env_config

    return get_env_config().memory.quality_enabled


def is_gc_enabled() -> bool:
    """Check if garbage collection is enabled via VT_MEMORY_GC env var."""
    from src.config.accessor import get_env_config

    return get_env_config().memory.gc_enabled


def is_decay_enabled() -> bool:
    """Check if importance decay is enabled via VT_MEMORY_DECAY env var."""
    from src.config.accessor import get_env_config

    return get_env_config().memory.decay_enabled


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Current time as ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# MemoryLifecycle
# ---------------------------------------------------------------------------


class MemoryLifecycle:
    """Lifecycle management for persistent memory: quality scoring, decay, GC.

    Wraps a PersistentMemory instance and provides reinforcement, garbage
    collection, and access tracking. All write operations are guarded by
    file-level locking.
    """

    _EVENT_DELTAS: MappingProxyType[str, float] = MappingProxyType(
        {
            "task_success": 0.1,
            "task_failure": -0.15,
            "user_confirm": 0.2,
            "user_reject": -0.3,
            "passive_decay": -0.05,
        }
    )

    # Safety: per-memory per-session cap
    _MAX_SESSION_DELTA = 0.5

    # GC thresholds
    ARCHIVE_THRESHOLD = 0.15
    DELETE_THRESHOLD = 0.05
    MIN_AGE_DAYS = 7
    MAX_MEMORY_COUNT = 500
    ENABLE_DELETE = False  # Tier 1: archive only

    def __init__(self, memory: PersistentMemory) -> None:
        self._memory = memory
        self._session_deltas: dict[str, float] = {}  # name -> cumulative delta

    @property
    def memory_dir(self) -> Path:
        """Return the underlying memory directory."""
        return self._memory._dir

    # ------------------------------------------------------------------
    # Reinforcement
    # ------------------------------------------------------------------

    def reinforce(self, name: str, event: str, source: str = "system") -> bool:
        """Update quality score based on usage feedback.

        Args:
            name: Memory entry name (exact match).
            event: One of "task_success", "task_failure", "user_confirm",
                   "user_reject", "passive_decay".
            source: "user" (full confidence) or "system" (0.7x discount).

        Returns:
            True if reinforced successfully, False if skipped.
        """
        if not is_quality_enabled():
            return False
        if event not in self._EVENT_DELTAS:
            logger.warning("reinforce: unknown event %r", event)
            return False

        delta = self._EVENT_DELTAS[event]
        if source == "system":
            delta *= 0.7

        # Session cap check
        current = self._session_deltas.get(name, 0.0)
        if abs(current + delta) > self._MAX_SESSION_DELTA:
            logger.info("reinforce(%s): session cap reached (%.2f)", name, current)
            return False

        entry = self._memory.find(name)
        if entry is None:
            logger.warning("reinforce(%s): not found", name)
            return False

        with memory_lock(self.memory_dir) as acquired:
            if not acquired:
                return False
            try:
                new_qs = max(0.0, min(1.0, entry.quality_score + delta))
                self._update_frontmatter_field(
                    entry.path, "quality_score", f"{new_qs:.2f}"
                )
                self._update_frontmatter_field(entry.path, "updated_at", _now_iso())
                self._session_deltas[name] = current + delta
                return True
            except (FileNotFoundError, IOError) as exc:
                logger.warning("reinforce(%s) skipped: %s", name, exc)
                return False

    # ------------------------------------------------------------------
    # Access tracking
    # ------------------------------------------------------------------

    def track_access(self, entry: MemoryEntry) -> None:
        """Increment access_count and update last_accessed for a recalled entry."""
        if not is_quality_enabled():
            return
        with memory_lock(self.memory_dir) as acquired:
            if not acquired:
                return
            try:
                self._update_frontmatter_field(
                    entry.path, "access_count", str(entry.access_count + 1)
                )
                self._update_frontmatter_field(entry.path, "last_accessed", _now_iso())
            except (FileNotFoundError, IOError) as exc:
                logger.warning("track_access(%s) skipped: %s", entry.title, exc)

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def run_gc(self, dry_run: bool = True) -> list[dict]:
        """Run garbage collection on memory store.

        Args:
            dry_run: If True (default), log actions without modifying files.

        Returns:
            List of action records [{name, action, importance, reason}].
        """
        if not is_gc_enabled():
            return []

        entries = self._memory.list_entries()

        now = time.time()
        actions: list[dict] = []

        for entry in entries:
            age_days = (now - entry.created_at) / 86400.0
            if age_days < self.MIN_AGE_DAYS:
                continue

            days_since_access = (now - entry.last_accessed) / 86400.0
            imp = compute_importance(
                entry.quality_score, entry.access_count, days_since_access
            )

            action = None
            reason = ""
            if imp < self.DELETE_THRESHOLD and self.ENABLE_DELETE:
                action = "delete"
                reason = f"importance {imp:.3f} < delete threshold"
            elif imp < self.ARCHIVE_THRESHOLD:
                action = "archive"
                reason = f"importance {imp:.3f} < archive threshold"

            if action:
                record = {
                    "name": entry.title,
                    "action": action,
                    "importance": round(imp, 4),
                    "reason": reason,
                }
                actions.append(record)
                if not dry_run:
                    # Tier 1: force archive even if classified as delete
                    effective = "archive" if not self.ENABLE_DELETE else action
                    self._execute_gc_action(entry, effective)

        self._append_gc_log(actions, dry_run)
        return actions

    def _execute_gc_action(self, entry: MemoryEntry, action: str) -> None:
        """Execute a GC action (archive or delete) on an entry."""
        archive_dir = self.memory_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        with memory_lock(self.memory_dir) as acquired:
            if not acquired:
                return
            try:
                if action == "archive":
                    dest = archive_dir / entry.path.name
                    entry.path.rename(dest)
                elif action == "delete":
                    dest = archive_dir / entry.path.name
                    dest.write_text(
                        entry.path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    entry.path.unlink()
            except (OSError, IOError) as exc:
                logger.warning("GC action(%s, %s) failed: %s", entry.title, action, exc)
                return

        # Rebuild index after removal
        self._memory._rebuild_index()

    def _append_gc_log(self, actions: list[dict], dry_run: bool) -> None:
        """Append GC decisions to gc.log."""
        log_path = self.memory_dir / "gc.log"
        timestamp = _now_iso()
        mode = "dry_run" if dry_run else "execute"
        lines = [f"[{timestamp}] mode={mode} actions={len(actions)}"]
        for a in actions:
            lines.append(
                f"  {a['action']}: {a['name']} "
                f"(importance={a['importance']}, {a['reason']})"
            )
        lines.append("")

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as exc:
            logger.warning("append_gc_log failed: %s", exc)

    # ------------------------------------------------------------------
    # Frontmatter manipulation
    # ------------------------------------------------------------------

    def _update_frontmatter_field(self, path: Path, field: str, value: str) -> None:
        """Update a single frontmatter field in a memory file.

        Uses an atomic write-then-rename strategy to prevent file corruption
        if the process crashes mid-write.
        """
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")

        if not lines or lines[0].strip() != "---":
            logger.warning(
                "_update_frontmatter_field(%s): no frontmatter delimiters in %s",
                field,
                path,
            )
            return
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            logger.warning(
                "_update_frontmatter_field(%s): no closing delimiter in %s",
                field,
                path,
            )
            return

        field_found = False
        for i in range(1, end_idx):
            if lines[i].startswith(f"{field}:"):
                lines[i] = f"{field}: {value}"
                field_found = True
                break
        if not field_found:
            lines.insert(end_idx, f"{field}: {value}")

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text("\n".join(lines), encoding="utf-8")
        os.replace(tmp_path, path)
