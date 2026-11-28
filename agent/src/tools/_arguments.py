"""Shared coercion for tool arguments received from JSON callers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def boolean_argument(value: Any, *, field: str) -> bool:
    """Parse an optional boolean without treating non-empty strings as true.

    Args:
        value: Boolean, null, zero/one, or an explicit boolean spelling.
        field: Argument name to include in a validation error.

    Returns:
        The parsed boolean; null retains the historical false value.

    Raises:
        ValueError: If the input is ambiguous or malformed. In particular,
            an unknown dry-run string must never silently enable writes.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "1", "yes", "on"}:
            return True
        if token in {"false", "0", "no", "off"}:
            return False
    elif isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{field} must be a boolean (true or false)")


def normalize_tool_run_dir(args: dict[str, Any], memory_run_dir: str | None) -> dict[str, Any]:
    """Normalize ``run_dir`` in tool args to an absolute path when possible.

    If the model supplies a relative ``run_dir`` (for example ``"."`` or
    ``"risk_parity_run"``), resolve it against the active run directory.
    """
    normalized = dict(args)
    if not memory_run_dir:
        return normalized

    if "run_dir" not in normalized:
        normalized["run_dir"] = memory_run_dir
        return normalized

    run_dir_value = str(normalized["run_dir"]).strip()
    if not run_dir_value:
        normalized["run_dir"] = memory_run_dir
        return normalized

    candidate = Path(run_dir_value)
    if not candidate.is_absolute():
        normalized["run_dir"] = str((Path(memory_run_dir) / candidate).resolve())
    return normalized
