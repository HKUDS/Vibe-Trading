"""Atomic writer for the ``channels`` section of the raw agent JSON config.

The web configuration surface and the Feishu QR-login flow both need to persist
channel credentials into the operator's structured config without round-tripping
unrelated sections through a pydantic model.  This module owns that single
responsibility: merge a channel section into the raw JSON dict and replace the
file atomically so a reader never observes a partial record.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any, Sequence

from src.config.loader import _read_config_file
from src.config.paths import get_config_path


class ConfigNotWritableError(RuntimeError):
    """Raised when the active agent config cannot be written as JSON."""


# Serializes the read-modify-write of the whole agent.json across channels and
# across entry points (web PUT, Feishu QR login). The body is synchronous, so
# this is a threading lock, not an asyncio lock.
_WRITE_LOCK = threading.Lock()


def _resolve_config_path(config_path: Path | None) -> Path:
    """Resolve the config file to update.

    Args:
        config_path: Explicit config path, or ``None`` to use discovery.

    Returns:
        The explicit path when one is provided, otherwise the active config
        path from :func:`src.config.paths.get_config_path`.  When no config
        file exists yet, discovery yields the default ``agent.json`` under the
        runtime root so the caller can create it.
    """
    if config_path is not None:
        return config_path
    return get_config_path()


def update_channel_section(
    channel: str,
    updates: dict[str, Any],
    *,
    clears: Sequence[str] = (),
    config_path: Path | None = None,
) -> Path:
    """Merge a channel section into the raw JSON agent config.

    Operates on the raw decoded dict only: unknown top-level keys, sibling
    channel sections, and key order/casing are preserved exactly.  The file is
    written through a private same-directory temporary file and atomically
    replaced, so readers never observe a partial credential record.

    Args:
        channel: Channel section name, e.g. ``"feishu"``.
        updates: Keys to merge into ``channels.<channel>``.
        clears: Keys to remove from ``channels.<channel>`` if present; absent
            keys are ignored.
        config_path: Explicit config path.  When omitted, the active config
            path is resolved via :func:`src.config.paths.get_config_path`.

    Returns:
        The config file path that was written.

    Raises:
        ConfigNotWritableError: If the resolved config file is not JSON, cannot
            be read, or holds a non-object ``channels``/``channels.<channel>``
            section.
    """
    path = _resolve_config_path(config_path)
    with _WRITE_LOCK:
        if path.suffix.lower() != ".json":
            raise ConfigNotWritableError(
                "Agent config is not writable as JSON: "
                f"expected a .json file, got {path}. "
                "Point the runtime at ~/.vibe-trading/agent.json to persist "
                "channel credentials."
            )

        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload = _read_config_file(path)
            except (OSError, ValueError) as exc:
                raise ConfigNotWritableError(
                    f"Agent config at {path} could not be read for update: {exc}"
                ) from exc

        channels = payload.setdefault("channels", {})
        if not isinstance(channels, dict):
            raise ConfigNotWritableError("agent config 'channels' must be an object")
        section = channels.setdefault(channel, {})
        if not isinstance(section, dict):
            raise ConfigNotWritableError(
                f"agent config 'channels.{channel}' must be an object"
            )

        section.update(updates)
        for key in clears:
            section.pop(key, None)

        _write_json_atomically(path, payload)
    return path


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as pretty JSON via a private temp file + replace.

    Args:
        path: Destination config file.
        payload: Raw config dict to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(content)
                handle.flush()
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
