"""TraceWriter: crash-safe JSONL trace writer.

One JSON record per line; each write is flushed and fsynced so the record
survives an immediate host crash. Large fields are written to sidecar files
(temp-write -> fsync -> ``os.replace`` -> directory fsync) BEFORE the record
that references them is fsynced, so a durable record never points at a
missing or truncated sidecar. Sidecars keep traces complete without turning
every CLI/history read into a giant file load.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read a positive integer environment variable with a safe fallback.

    Args:
        name: Environment variable name.
        default: Fallback value.

    Returns:
        Parsed positive integer, or ``default`` when unset/invalid.
    """
    raw = os.getenv(name)  # noqa: env-gate — generic env override reader
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


TOOL_RESULT_OFFLOAD_THRESHOLD = _env_int(
    "VIBE_TRADING_TRACE_TOOL_RESULT_INLINE_LIMIT",
    50_000,
)
TRACE_TEXT_OFFLOAD_THRESHOLD = _env_int(
    "VIBE_TRADING_TRACE_TEXT_INLINE_LIMIT",
    50_000,
)
OFFLOAD_PREVIEW_CHARS = _env_int("VIBE_TRADING_TRACE_PREVIEW_CHARS", 500)

OPTIONAL_IRR_TRACE_FIELDS = frozenset({
    "artifact_refs",
    "data_audit_id",
    "policy_decision_id",
    "governance_overhead_ms",
    "warning_codes",
    "hard_failure_codes",
})


class TraceWriter:
    """JSONL trace writer, one record per line, crash-safe.

    Attributes:
        dir_path: Directory containing ``trace.jsonl`` and sidecar blobs.
        path: Path to the trace JSONL file.
    """

    def __init__(self, dir_path: Path) -> None:
        """Initialize TraceWriter.

        Args:
            dir_path: Directory where trace files are written.
        """
        self.dir_path = dir_path
        self.path = self.dir_path / "trace.jsonl"
        self._fsync_warned = False
        self.dir_path.mkdir(parents=True, exist_ok=True)
        created = not self.path.exists()
        self._file = open(self.path, "a", encoding="utf-8")
        try:
            if created:
                # Make the new trace.jsonl directory entry itself durable.
                self._fsync_dir(self.dir_path)
        except Exception:
            self._file.close()
            raise

    def write(self, entry: Dict[str, Any]) -> None:
        """Write a trace record, flushed and fsynced for crash safety.

        ``flush`` alone only moves bytes into the OS page cache; a host
        crash or container kill would lose the last records. Trace volume
        is low (one entry per LLM/tool event), so one fsync per record is
        an acceptable cost for post-mortem visibility. If fsync fails
        (e.g. unsupported filesystem), a warning is logged once and writes
        continue flush-only.

        Args:
            entry: Trace entry; a ``ts`` field is added automatically.
        """
        if "ts" not in entry:
            entry["ts"] = time.time()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
        try:
            os.fsync(self._file.fileno())
        except OSError as exc:
            self._warn_fsync_failure(exc, self.path)

    def write_text_entry(
        self,
        entry: Dict[str, Any],
        *,
        field: str,
        value: str,
        offload_kind: str,
        threshold: int | None = None,
    ) -> None:
        """Write an entry with one potentially large text field.

        Args:
            entry: Base trace entry. Mutated before writing.
            field: Text field name, e.g. ``"content"`` or ``"prompt"``.
            value: Full text value to preserve.
            offload_kind: Stable label used in the sidecar filename hash input.
            threshold: Optional inline threshold override.
        """
        self._attach_text_field(
            entry,
            field=field,
            value=value,
            offload_kind=offload_kind,
            threshold=threshold or TRACE_TEXT_OFFLOAD_THRESHOLD,
            offload_dir_name="trace-blobs",
        )
        self.write(entry)

    def write_tool_result(
        self,
        call_id: str,
        result: str,
        tool_name: str,
        status: str,
        elapsed_ms: int,
        iteration: int,
    ) -> None:
        """Write a tool_result entry, offloading large results to disk.

        Args:
            call_id: Provider tool call ID.
            result: Raw tool result string after any caller-side redaction.
            tool_name: Tool name.
            status: ``"ok"`` or ``"error"``.
            elapsed_ms: Execution time in milliseconds.
            iteration: Current iteration number.
        """
        entry: Dict[str, Any] = {
            "type": "tool_result",
            "iter": iteration,
            "tool": tool_name,
            "call_id": call_id,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "preview": result[:OFFLOAD_PREVIEW_CHARS],
        }
        self._attach_text_field(
            entry,
            field="result",
            value=result,
            offload_kind=f"tool-result-{tool_name}-{call_id}",
            threshold=TOOL_RESULT_OFFLOAD_THRESHOLD,
            offload_dir_name="tool-results",
            preview_field="result_preview",
        )
        self.write(entry)

    def close(self) -> None:
        """Close the file handle."""
        self._file.close()

    def _attach_text_field(
        self,
        entry: Dict[str, Any],
        *,
        field: str,
        value: str,
        offload_kind: str,
        threshold: int,
        offload_dir_name: str,
        preview_field: str | None = None,
    ) -> None:
        """Attach text inline or as a sidecar path.

        The sidecar is written atomically and durably here, BEFORE the
        caller writes (and fsyncs) the record that references it, so a
        crash never leaves a durable record pointing at a missing or
        truncated sidecar.
        """
        if len(value) <= threshold:
            entry[field] = value
            return

        offload_dir = self.dir_path / offload_dir_name
        if not offload_dir.is_dir():
            offload_dir.mkdir(parents=True, exist_ok=True)
            # Make the new sidecar directory entry itself durable.
            self._fsync_dir(self.dir_path)
        digest = hashlib.sha256(f"{offload_kind}\0{value}".encode("utf-8")).hexdigest()
        path = offload_dir / f"{digest[:24]}.txt"
        self._write_sidecar_durable(path, value)
        entry[f"{field}_path"] = f"{offload_dir_name}/{path.name}"
        entry[preview_field or f"{field}_preview"] = value[:OFFLOAD_PREVIEW_CHARS]
        entry[f"{field}_size"] = len(value)

    def _write_sidecar_durable(self, path: Path, value: str) -> None:
        """Atomically write a sidecar blob, durably where the filesystem allows.

        Write sequence: temp file in the same directory -> write every byte ->
        fsync -> ``os.replace`` -> parent-directory fsync. The rename is what
        makes it atomic: a crash leaves either no sidecar or a complete one,
        never a partial write under the final name. Because the blob is fully
        renamed into place before the caller writes the record that points at
        it, a record never references a sidecar that is not on disk.

        Durability against a HOST crash additionally needs fsync. Where fsync
        is unsupported the error is logged once and the write still completes:
        the sidecar is present and readable, only its survival across a power
        loss is not guaranteed. Failing the run instead would lose the trace
        outright, which is the worse outcome for a diagnostic artifact.

        Args:
            path: Final sidecar path.
            value: Full text to persist.

        Raises:
            OSError: When the blob cannot be written or renamed at all. The
                caller must not write the referencing record in that case.
        """
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            payload = value.encode("utf-8")
            written = 0
            # os.write may write fewer bytes than requested; a single call can
            # silently truncate a large sidecar.
            while written < len(payload):
                written += os.write(fd, payload[written:])
            try:
                os.fsync(fd)
            except OSError as exc:
                self._warn_fsync_failure(exc, tmp)
        except BaseException:
            os.close(fd)
            # Never leave a half-written temp file behind for the next run.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        else:
            os.close(fd)
        os.replace(tmp, path)
        self._fsync_dir(path.parent)

    def _fsync_dir(self, directory: Path) -> None:
        """Fsync a directory so new/renamed entries survive a crash.

        Args:
            directory: Directory whose entry table should be flushed.
        """
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            self._warn_fsync_failure(exc, directory)
        finally:
            os.close(dir_fd)

    def _warn_fsync_failure(self, exc: OSError, target: Path) -> None:
        """Log the first fsync failure for this writer, then stay quiet.

        Args:
            exc: The fsync error.
            target: File or directory whose fsync failed.
        """
        if self._fsync_warned:
            return
        self._fsync_warned = True
        logger.warning(
            "trace fsync failed on %s (%s); trace durability degraded to flush-only for this writer",
            target,
            exc,
        )

    @staticmethod
    def read(
        dir_path: Path,
        *,
        resolve_offloads: bool = False,
        resolve_fields: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read trace.jsonl records.

        Args:
            dir_path: Directory containing ``trace.jsonl``.
            resolve_offloads: Whether to read sidecar files back into entries.
            resolve_fields: Optional field allowlist to resolve. For example,
                ``{"content", "prompt"}`` avoids loading large tool results.

        Returns:
            List of trace records.
        """
        path = dir_path / "trace.jsonl"
        if not path.exists():
            return []
        fields = set(resolve_fields) if resolve_fields is not None else None
        entries: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resolve_offloads:
                TraceWriter._resolve_entry_offloads(dir_path, entry, fields)
            entries.append(entry)
        return entries

    @staticmethod
    def _resolve_entry_offloads(
        dir_path: Path,
        entry: Dict[str, Any],
        fields: Optional[set[str]],
    ) -> None:
        """Resolve safe sidecar paths into their original fields."""
        for key, rel_path in list(entry.items()):
            if not key.endswith("_path") or not isinstance(rel_path, str):
                continue
            field = key[:-5]
            if fields is not None and field not in fields:
                continue
            if field in entry:
                continue
            result_file = TraceWriter._safe_sidecar_path(dir_path, rel_path)
            if result_file is None or not result_file.exists():
                continue
            try:
                entry[field] = result_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

    @staticmethod
    def _safe_sidecar_path(dir_path: Path, rel_path: str) -> Path | None:
        """Return a sidecar path only if it stays inside ``dir_path``."""
        root = dir_path.resolve()
        candidate = (dir_path / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    @staticmethod
    def find_trace_dir(
        run_id: str,
        runs_dir: Optional[Path] = None,
        sessions_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Find the trace directory for a run/session id.

        Args:
            run_id: Run or session ID.
            runs_dir: Base runs directory. Defaults to the user-level
                runs dir under the runtime root.
            sessions_dir: Base sessions directory. Defaults to the
                user-level sessions dir under the runtime root.

        Returns:
            Directory containing ``trace.jsonl``, or ``None`` when absent.
        """
        if sessions_dir is None:
            from src.config.paths import get_sessions_dir

            sessions_dir = get_sessions_dir()
        if runs_dir is None:
            from src.config.paths import get_runs_dir

            runs_dir = get_runs_dir()

        session_dir = sessions_dir / run_id
        if (session_dir / "trace.jsonl").exists():
            return session_dir

        run_dir = runs_dir / run_id
        if (run_dir / "trace.jsonl").exists():
            return run_dir

        return None
