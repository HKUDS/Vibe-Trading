"""Models the local Claude Code login can run, as the settings page lists them.

The list comes from the CLI's ``initialize`` control request, which starts no
model turn and costs nothing.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.providers.claude_cli import (
    CLAUDE_CLI_EFFORT_LEVELS,
    ISOLATION_ARGS,
    child_env,
    resolve_claude_cli,
)

_MODEL_LIST_TIMEOUT_S = 30
_MODEL_LIST_TTL_S = 300


@dataclass(frozen=True)
class ClaudeCliModel:
    """One model the local login can run, with the effort levels it accepts.

    Attributes:
        model_id: Full model name, as passed to ``--model``.
        effort_levels: Levels the model accepts; empty when it takes none.
    """

    model_id: str
    effort_levels: tuple[str, ...]


_model_cache: dict[str, tuple[float, tuple[ClaudeCliModel, ...]]] = {}
# One CLI launch at a time: a settings page opened twice, or an auto-load racing
# a manual refresh, should wait for the first answer instead of spawning another.
_model_cache_lock = threading.Lock()


def list_claude_cli_models(*, refresh: bool = False) -> tuple[ClaudeCliModel, ...]:
    """Return the models the local Claude Code login can run.

    Asks the CLI with an ``initialize`` control request, which starts no model
    turn. Aliases such as ``opus`` and ``default`` resolve to the same full name,
    so entries are de-duplicated on that name: a saved full name stays pinned
    instead of following whatever an alias points to after a CLI update.

    Args:
        refresh: Skip the cached list and ask the CLI again.

    Returns:
        One entry per distinct full model name, in the CLI's order.

    Raises:
        RuntimeError: The CLI is missing, failed, or returned no models.
    """
    executable = resolve_claude_cli()
    with _model_cache_lock:
        cached = _model_cache.get(executable)
        if cached and not refresh and time.monotonic() - cached[0] < _MODEL_LIST_TTL_S:
            return cached[1]
        models = _query_claude_cli_models(executable)
        _model_cache[executable] = (time.monotonic(), models)
        return models


def _query_claude_cli_models(executable: str) -> tuple[ClaudeCliModel, ...]:
    request = {
        "type": "control_request",
        "request_id": f"models_{uuid.uuid4().hex[:8]}",
        "request": {"subtype": "initialize"},
    }
    try:
        result = subprocess.run(
            [
                executable,
                "-p",
                *ISOLATION_ARGS,
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
            ],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_MODEL_LIST_TIMEOUT_S,
            env=child_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"claude model list unavailable: {type(exc).__name__}"
        ) from exc
    raw_models: list[Any] = []
    for line in (result.stdout or "").splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("type") == "control_response":
            outer = message.get("response")
            inner = outer.get("response") if isinstance(outer, dict) else None
            models_field = inner.get("models") if isinstance(inner, dict) else None
            raw_models = models_field if isinstance(models_field, list) else []
            break
    models: list[ClaudeCliModel] = []
    seen: set[str] = set()
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("resolvedModel") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        levels = (
            (entry.get("supportedEffortLevels") or [])
            if entry.get("supportsEffort")
            else []
        )
        models.append(
            ClaudeCliModel(
                model_id=model_id,
                effort_levels=tuple(
                    level for level in levels if level in CLAUDE_CLI_EFFORT_LEVELS
                ),
            )
        )
    if not models:
        raise RuntimeError(
            f"claude model list unavailable (exit {result.returncode}): "
            f"{(result.stderr or '')[:300]}"
        )
    return tuple(models)
