"""TraceWriter: crash-safe JSONL trace writer.

One JSON record per line; append + flush guarantees no data loss on crash.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List


class TraceWriter:
    """JSONL trace writer, one record per line, crash-safe.

    Attributes:
        path: Path to the trace.jsonl file.
    """

    def __init__(self, run_dir: Path) -> None:
        """Initialize TraceWriter.

        Args:
            run_dir: Run directory; trace.jsonl is written here.
        """
        self.path = run_dir / "trace.jsonl"
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

    def close(self) -> None:
        """Close the file handle."""
        self._file.close()

    @staticmethod
    def read(run_dir: Path) -> List[Dict[str, Any]]:
        """Read trace.jsonl and return records.

        Args:
            run_dir: Run directory.

        Returns:
            List of trace records.
        """
        path = run_dir / "trace.jsonl"
        if not path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries
