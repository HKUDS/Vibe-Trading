"""Write file tool: create or overwrite files in the workspace."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import allowed_write_roots
from src.tools.path_utils import resolve_safe_path
from src.tools.redaction import redact_internal_paths


class WriteFileTool(BaseTool):
    """Create or overwrite a workspace file, creating parent directories as needed."""

    name = "write_file"
    description = (
        "Write content to a file in the workspace or configured write roots. "
        "A .pdf path renders Markdown/text to a real PDF; other paths write UTF-8 text. "
        "Creates parent directories automatically. Use the returned success/error as "
        "the authoritative outcome; include the returned download URL for PDF reports."
    )
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
        # DeepSeek-v4-pro (and some other models) sometimes emit write_file
        # with the path under an aliased key, or omit it entirely. Accept the
        # common aliases and return a correctable error instead of raising a
        # hard KeyError the model can't recover from.
        file_path = (
            kwargs.get("path")
            or kwargs.get("file_path")
            or kwargs.get("filepath")
            or kwargs.get("filename")
            or kwargs.get("file")
        )
        if not file_path:
            return json.dumps(
                {
                    "status": "error",
                    "error": "missing required argument 'path' (string): the file path relative to run_dir",
                },
                ensure_ascii=False,
            )
        content = next(
            (kwargs[key] for key in ("content", "text", "data") if kwargs.get(key) is not None),
            None,
        )
        if content is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": "missing required argument 'content' (string): the file content to write",
                },
                ensure_ascii=False,
            )
        run_dir = kwargs.get("run_dir")

        try:
            resolved = resolve_safe_path(
                file_path=file_path,
                run_dir=run_dir,
                allowed_roots=allowed_write_roots(),
                purpose="write",
            )
        except ValueError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            artifact = {}
            if resolved.suffix.lower() == ".pdf":
                from src.tools.pdf_report import render_markdown_pdf
                from src.tools.report_artifacts import publish_pdf
                render_markdown_pdf(content, resolved)
                try:
                    artifact = publish_pdf(resolved)
                except OSError as exc:
                    # The requested file exists: a staging failure must not
                    # falsely report that the user's write was refused.
                    artifact = {"media_type": "application/pdf", "download_error": redact_internal_paths(str(exc))}
            else:
                resolved.write_text(content, encoding="utf-8")
            return json.dumps(
                {
                    "status": "ok",
                    "path": str(resolved),
                    "bytes_written": resolved.stat().st_size,
                    "requested_path": str(file_path),
                    **artifact,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": redact_internal_paths(str(exc)),
                },
                ensure_ascii=False,
            )
