"""check_code tool: static preflight for agent-generated strategy code.

Surfaces syntax errors and the missing ``SignalEngine`` contract before a full
backtest run, so the loop does not spend minutes of backtest execution to
discover a ``SyntaxError`` the ``ast`` module reports in milliseconds.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir as _safe_run_dir

_PYFLAKES_MESSAGE_LIMIT = 20


def _run_pyflakes(source: str, filename: str) -> list[str] | None:
    """Run pyflakes over ``source`` when the package is importable.

    Returns:
        Message list, empty when the source is clean, or ``None`` when
        pyflakes is not installed (the check degrades to "skipped").
    """
    if importlib.util.find_spec("pyflakes") is None:
        return None
    from pyflakes.api import check
    from pyflakes.reporter import Reporter

    import io

    # pyflakes reporters write to text streams; capture both instead of
    # letting warnings pollute the process stderr mid-run.
    out, err = io.StringIO(), io.StringIO()
    check(source, filename, Reporter(out, err))
    return [line for line in out.getvalue().splitlines() if line.strip()]


def _signal_engine_class_present(source: str) -> bool:
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.ClassDef) and node.name == "SignalEngine"
        for node in ast.walk(tree)
    )


class CheckCodeTool(BaseTool):
    """Static preflight check for Python source in the workspace."""

    name = "check_code"
    description = (
        "Statically check Python source before running it: parse errors with "
        "line/column, optional pyflakes warnings, and - for signal_engine.py - "
        "whether a SignalEngine class is defined. Use on code/signal_engine.py "
        "right after writing it and before backtest(). Does not execute the code."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "File path relative to run_dir (e.g. 'code/signal_engine.py'). "
                    "Provide path or code, not both."
                ),
            },
            "code": {
                "type": "string",
                "description": "Inline Python source to check instead of a file.",
            },
            "run_dir": {"type": "string", "description": "Run directory for path resolution."},
        },
        "required": [],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        path_arg = kwargs.get("path")
        code_arg = kwargs.get("code")
        if bool(path_arg) == bool(code_arg):
            return json.dumps(
                {
                    "status": "error",
                    "error": "Provide exactly one of 'path' or 'code'.",
                },
                ensure_ascii=False,
            )

        source: str | None = None
        display_path = "<inline>"
        signal_engine_context = False
        if code_arg:
            source = str(code_arg)
        else:
            try:
                run_root = _safe_run_dir(str(kwargs.get("run_dir") or "."))
            except ValueError as exc:
                return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
            candidate = (run_root / str(path_arg)).resolve()
            if not candidate.is_file():
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"File not found: {path_arg}",
                    },
                    ensure_ascii=False,
                )
            display_path = str(candidate)
            signal_engine_context = "signal_engine" in candidate.name.lower()
            try:
                source = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"File is not valid UTF-8: {exc}",
                    },
                    ensure_ascii=False,
                )

        errors: list[dict[str, Any]] = []
        warnings: list[str] = []
        checks: dict[str, str] = {"syntax": "ok", "pyflakes": "skipped", "contract": "skipped"}

        try:
            ast.parse(source, filename=display_path)
        except SyntaxError as exc:
            checks["syntax"] = "error"
            errors.append(
                {
                    "line": exc.lineno,
                    "col": exc.offset,
                    "end_line": exc.end_lineno,
                    "message": exc.msg or "invalid syntax",
                }
            )
            return json.dumps(
                {
                    "status": "error",
                    "path": display_path,
                    "checks": checks,
                    "errors": errors,
                    "warnings": warnings,
                },
                ensure_ascii=False,
            )

        pyflakes_messages = _run_pyflakes(source, display_path)
        if pyflakes_messages is None:
            warnings.append(
                "pyflakes is not installed; undefined-name detection skipped "
                "(pip install pyflakes to enable)"
            )
        else:
            checks["pyflakes"] = "ok" if not pyflakes_messages else "error"
            warnings.extend(pyflakes_messages[:_PYFLAKES_MESSAGE_LIMIT])

        if signal_engine_context:
            checks["contract"] = "ok"
            if not _signal_engine_class_present(source):
                checks["contract"] = "error"
                errors.append(
                    {
                        "line": None,
                        "col": None,
                        "message": (
                            "no 'class SignalEngine' defined; the backtest engine "
                            "requires it in signal_engine.py"
                        ),
                    }
                )

        line_count = len(source.splitlines())
        status = "error" if checks["contract"] == "error" or errors else "ok"
        return json.dumps(
            {
                "status": status,
                "path": display_path,
                "checks": checks,
                "lines": line_count,
                "errors": errors,
                "warnings": warnings,
            },
            ensure_ascii=False,
        )
