from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from src.research_ledger.hash_utils import json_safe, redact_secrets


class PathTraversalError(ValueError):
    """Raised when an artifact path escapes its configured root."""


_SUSPICIOUS_DOT_CHARS = {"\u2025", "\u2026"}


def _decode_requested_path(requested: str) -> str:
    value = requested
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def safe_artifact_path(root: str | Path, requested: str) -> Path:
    root_path = Path(root).resolve()
    decoded = _decode_requested_path(requested)
    if "\x00" in decoded or any(char in decoded for char in _SUSPICIOUS_DOT_CHARS):
        raise PathTraversalError(requested)
    normalized = decoded.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise PathTraversalError(requested)
    target = (root_path / candidate).resolve(strict=False)
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise PathTraversalError(requested) from exc
    if target.exists() and target.is_symlink():
        resolved_target = target.resolve(strict=True)
        try:
            resolved_target.relative_to(root_path)
        except ValueError as exc:
            raise PathTraversalError(requested) from exc
    return target


def safe_artifact_write_json(root: str | Path, requested: str, payload: dict[str, Any]) -> Path:
    target = safe_artifact_path(root, requested)
    root_path = Path(root).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_symlink():
        raise PathTraversalError(requested)
    target.parent.resolve(strict=True).relative_to(root_path)
    body = json.dumps(
        redact_secrets(json_safe(payload)),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target
