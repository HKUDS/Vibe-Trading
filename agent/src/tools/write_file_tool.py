"""Write file tool: create or overwrite files in the workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_path as _safe_path


class WriteFileTool(BaseTool):
    """Create or overwrite a workspace file, creating parent directories as needed."""

    name = "write_file"
    description = "Write content to a file in the workspace. Creates parent directories automatically."
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to run_dir"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Write content to a file.

        Args:
            **kwargs: Must include path and content. Optional run_dir.

        Returns:
            JSON string with bytes_written or an error.
        """
        file_path = kwargs["path"]
        content = kwargs["content"]
        run_dir = kwargs.get("run_dir")

        if not run_dir:
            return json.dumps({
                "status": "error",
                "error": "run_dir is required for write_file",
            }, ensure_ascii=False)

        try:
            resolved = _safe_path(file_path, Path(run_dir))
        except ValueError as exc:
            return json.dumps({
                "status": "error",
                "error": str(exc),
            }, ensure_ascii=False)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return json.dumps({
                "status": "ok",
                "path": str(resolved),
                "bytes_written": len(content.encode("utf-8")),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": str(exc),
            }, ensure_ascii=False)
