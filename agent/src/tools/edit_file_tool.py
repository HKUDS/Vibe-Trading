"""Edit file tool: find-and-replace in workspace files."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import allowed_write_roots
from src.tools.path_utils import resolve_safe_path
from src.tools.redaction import redact_internal_paths


def _error(message: str) -> str:
    """Build the error envelope returned for a refused edit."""
    return json.dumps({"status": "error", "error": message}, ensure_ascii=False)


def _match_positions(content: str, old_text: str) -> int:
    """Count every position where ``old_text`` starts, overlapping ones included.

    ``str.count`` skips a match that overlaps the previous one, so ``"aa"`` in
    ``"aaa"`` counts once although it starts at two offsets. Uniqueness is
    about where the edit could apply, so it is decided on all start offsets.

    Args:
        content: The file text.
        old_text: The non-empty text to find.

    Returns:
        The number of start offsets of ``old_text`` in ``content``.
    """
    count = 0
    start = content.find(old_text)
    while start != -1:
        count += 1
        start = content.find(old_text, start + 1)
    return count


class EditFileTool(BaseTool):
    """Replace one exact, unique occurrence of a string in a workspace file."""

    name = "edit_file"
    description = (
        "Replace old_text with new_text in a file. old_text must match exactly once: "
        "if it matches several places the edit is refused and nothing changes, so "
        "include enough surrounding context to make it unique, or pass "
        "replace_all=true to replace every occurrence."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to run_dir"},
            "old_text": {
                "type": "string",
                "description": "Exact text to find; must occur exactly once unless replace_all is true",
            },
            "new_text": {"type": "string", "description": "Text to replace with; must differ from old_text"},
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence of old_text instead of requiring a unique match (default false)",
                "default": False,
            },
        },
        "required": ["path", "old_text", "new_text"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Perform find-and-replace.

        Args:
            **kwargs: Must include path, old_text, new_text. Optional run_dir and
                replace_all (bool, default False).

        Returns:
            JSON string with the operation result or an error. An ambiguous
            match (more than one occurrence without ``replace_all``) is an
            error that leaves the file untouched.
        """
        file_path = kwargs["path"]
        old_text = kwargs["old_text"]
        new_text = kwargs["new_text"]
        replace_all = kwargs.get("replace_all", False)
        run_dir = kwargs.get("run_dir")

        if not isinstance(replace_all, bool):
            return _error("replace_all must be a boolean (true or false)")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            return _error("old_text and new_text must be strings")
        if old_text == "":
            return _error("old_text must not be empty")
        if old_text == new_text:
            return _error("old_text and new_text are identical; the edit would change nothing")

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

        if not resolved.exists():
            return json.dumps(
                {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                },
                ensure_ascii=False,
            )

        try:
            # newline="" keeps every line ending as it is on disk: universal
            # newlines would rewrite a whole CRLF file as LF on any edit and
            # make an old_text containing "\r\n" unmatchable.
            with resolved.open(encoding="utf-8", newline="") as handle:
                content = handle.read()
            positions = _match_positions(content, old_text)
            if positions == 0:
                return _error(f"old_text not found in {file_path}")
            if positions > 1 and not replace_all:
                return _error(
                    f"old_text matches {positions} places in {file_path}; the edit was not applied. "
                    "Add surrounding context so old_text matches exactly once, "
                    "or pass replace_all=true to replace every occurrence."
                )
            # replace_all replaces non-overlapping occurrences left to right.
            count = content.count(old_text) if replace_all else 1
            new_content = content.replace(old_text, new_text, count)
            with resolved.open("w", encoding="utf-8", newline="") as handle:
                handle.write(new_content)
            return json.dumps(
                {
                    "status": "ok",
                    "path": str(resolved),
                    "replacements": count,
                    "message": (
                        "Edit applied successfully"
                        if count == 1
                        else f"Edit applied successfully ({count} occurrences replaced)"
                    ),
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
