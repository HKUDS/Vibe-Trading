"""TraceWriter: crash-safe JSONL trace writer.

One JSON record per line; append + flush guarantees no data loss on crash.
Large tool results (>50K chars) are offloaded to separate files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

TOOL_RESULT_OFFLOAD_THRESHOLD = 50_000
OFFLOAD_PREVIEW_CHARS = 500


class TraceWriter:
    """JSONL trace writer, one record per line, crash-safe.

    Attributes:
        dir_path: Directory containing trace.jsonl and tool-results/.
        path: Path to the trace.jsonl file.
    """

    def __init__(self, dir_path: Path) -> None:
        """Initialize TraceWriter.

        Args:
            dir_path: Directory where trace.jsonl (and tool-results/) are written.
        """
        self.dir_path = dir_path
        dir_path.mkdir(parents=True, exist_ok=True)
        self.path = dir_path / "trace.jsonl"
        self._file = open(self.path, "a", encoding="utf-8")

    def write(self, entry: Dict[str, Any]) -> None:
        """Write a trace record.

        Args:
            entry: Trace entry; a ts field is added automatically.
        """
        if "ts" not in entry:
            entry["ts"] = time.time()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def write_tool_result(
        self,
        call_id: str,
        result: str,
        tool_name: str,
        status: str,
        elapsed_ms: int,
        iteration: int,
    ) -> None:
        """Write a tool_result trace entry, offloading large results to disk.

        Results ≤ TOOL_RESULT_OFFLOAD_THRESHOLD are stored inline in the JSONL.
        Larger results are written to ``tool-results/<call_id>.txt`` and the
        trace entry carries a path + preview instead.

        Args:
            call_id: Tool call ID.
            result: Raw tool result string.
            tool_name: Tool name.
            status: "ok" or "error".
            elapsed_ms: Execution time in milliseconds.
            iteration: Current iteration number.
        """
        if len(result) > TOOL_RESULT_OFFLOAD_THRESHOLD:
            offload_dir = self.dir_path / "tool-results"
            offload_dir.mkdir(exist_ok=True)
            fname = f"{call_id}.txt"
            (offload_dir / fname).write_text(result, encoding="utf-8")
            self.write({
                "type": "tool_result",
                "iter": iteration,
                "tool": tool_name,
                "call_id": call_id,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "result_path": f"tool-results/{fname}",
                "result_preview": result[:OFFLOAD_PREVIEW_CHARS],
                "result_size": len(result),
            })
        else:
            self.write({
                "type": "tool_result",
                "iter": iteration,
                "tool": tool_name,
                "call_id": call_id,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "result": result,
            })

    def close(self) -> None:
        """Close the file handle."""
        self._file.close()

    @staticmethod
    def read(dir_path: Path) -> List[Dict[str, Any]]:
        """Read trace.jsonl and return records.

        Offloaded tool results are resolved from their on-disk files
        so the returned entries are self-contained.

        Args:
            dir_path: Directory containing trace.jsonl.

        Returns:
            List of trace records.
        """
        path = dir_path / "trace.jsonl"
        if not path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Resolve offloaded tool results
            if "result_path" in entry and "result" not in entry:
                result_file = dir_path / entry["result_path"]
                if result_file.exists():
                    try:
                        entry["result"] = result_file.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        pass

            entries.append(entry)
        return entries

    @staticmethod
    def find_trace_dir(
        run_id: str,
        runs_dir: Optional[Path] = None,
        sessions_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Find the trace directory for a given run_id.

        Checks sessions/ first (new location), then runs/ (legacy).
        Returns the directory Path if found, or None.

        Args:
            run_id: Run or session ID.
            runs_dir: Base runs directory. Defaults to agent/runs.
            sessions_dir: Base sessions directory. Defaults to agent/sessions.

        Returns:
            Path to the directory containing trace.jsonl, or None.
        """
        if sessions_dir is None:
            sessions_dir = Path(__file__).resolve().parents[2] / "sessions"
        if runs_dir is None:
            runs_dir = Path(__file__).resolve().parents[2] / "runs"

        # Prefer sessions/ first (new location)
        session_trace = sessions_dir / run_id / "trace.jsonl"
        if session_trace.exists():
            return sessions_dir / run_id

        run_trace = runs_dir / run_id / "trace.jsonl"
        if run_trace.exists():
            return runs_dir / run_id

        # Fall back to runs/ for backward compat (even if file doesn't exist yet)
        return runs_dir / run_id
