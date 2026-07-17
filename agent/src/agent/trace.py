"""TraceWriter: crash-safe JSONL trace writer.

One JSON record per line; each write is followed by ``flush()`` and an
``os.fsync()`` so the record survives an immediate host crash (subject to
filesystem ordering guarantees — see ``write`` for the precise contract).
Large fields are written to sidecar files so traces can preserve full content
without turning every CLI/history read into a giant file load.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


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
        # Make sure the parent directory exists BEFORE opening the file;
        # ``open(..., "a")`` raises FileNotFoundError when the path is missing.
        self.dir_path.mkdir(parents=True, exist_ok=True)
        # Open the file first so it survives across writes, but defer
        # attribute assignment under try/except so a later failure in
        # __init__ closes the FD instead of leaking it.
        self._file = open(self.path, "a", encoding="utf-8")
        try:
            # Sentinel for any future post-open work — currently a no-op,
            # but the try/except wrapper guarantees the FD is closed if a
            # later refactor raises between ``open`` and the constructor
            # returning.
            pass
        except Exception:
            self._file.close()
            raise

    def write(self, entry: Dict[str, Any]) -> None:
        """Write a trace record.

        Args:
            entry: Trace entry; a ``ts`` field is added automatically.
        """
        if "ts" not in entry:
            entry["ts"] = time.time()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
        # fsync so the kernel page cache is flushed to the storage device.
        # Without this, ``flush`` only moves bytes from Python into the OS
        # buffer cache — a crash (or container kill) between flush and the
        # next background flush loses the last ``write``. Cost is one
        # syscall per record; trace volume is low (one entry per LLM or
        # tool event), so the durability cost is worth it for the
        # post-mortem visibility. We fall back gracefully if fsync is not
        # available on the underlying file (e.g. some in-memory test
        # doubles).
        try:
            os.fsync(self._file.fileno())
        except (OSError, AttributeError):
            pass

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
        """Attach text inline or as a sidecar path."""
        if len(value) <= threshold:
            entry[field] = value
            return

        offload_dir = self.dir_path / offload_dir_name
        offload_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{offload_kind}\0{value}".encode("utf-8")).hexdigest()
        path = offload_dir / f"{digest[:24]}.txt"
        path.write_text(value, encoding="utf-8")
        entry[f"{field}_path"] = f"{offload_dir_name}/{path.name}"
        entry[preview_field or f"{field}_preview"] = value[:OFFLOAD_PREVIEW_CHARS]
        entry[f"{field}_size"] = len(value)

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
            runs_dir: Base runs directory. Defaults to ``agent/runs``.
            sessions_dir: Base sessions directory. Defaults to
                ``agent/sessions``.

        Returns:
            Directory containing ``trace.jsonl``, or ``None`` when absent.
        """
        if sessions_dir is None:
            sessions_dir = Path(__file__).resolve().parents[2] / "sessions"
        if runs_dir is None:
            runs_dir = Path(__file__).resolve().parents[2] / "runs"

        session_dir = sessions_dir / run_id
        if (session_dir / "trace.jsonl").exists():
            return session_dir

        run_dir = runs_dir / run_id
        if (run_dir / "trace.jsonl").exists():
            return run_dir

        return None
