"""Write helpers for the structured agent config.

The loader side (``src.config.loader``) only reads; these helpers cover the
small write surface the Web UI needs. Writes stay JSON-only: ``agent.yaml``
round-trips through ``yaml.safe_load``/``safe_dump`` lose comments and key
order, so YAML configs are refused loudly instead of rewritten.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.config.paths import get_config_path


class AgentConfigWriteError(Exception):
    """Raised when the agent config cannot be written safely."""


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as JSON atomically with owner-only permissions.

    The file carries channel credentials, so it gets the same treatment as
    the settings dotenv: 0600 and a sibling-temp-file swap.
    """
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".agent.json.", suffix=".tmp")
    try:
        os.write(fd, data)
        os.fsync(fd)
    except OSError:
        os.close(fd)
        raise
    else:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def save_channel_config_section(
    name: str,
    updates: dict[str, Any],
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Merge *updates* into ``channels.<name>`` and persist the agent config.

    Args:
        name: Channel section key (e.g. ``"dingtalk"``).
        updates: Field-level merge patch applied on top of the stored section.
        config_path: Optional explicit config path, mainly for tests.

    Returns:
        The merged channel section as stored.

    Raises:
        AgentConfigWriteError: If the active config is not JSON, the existing
            file is unreadable, or section shapes are not mappings.
    """
    path = get_config_path(config_path)
    if path.suffix.lower() != ".json":
        raise AgentConfigWriteError(
            f"Web UI channel writes only support JSON agent configs; "
            f"active config is {path.name}. Merge channels.{name} into it by hand."
        )

    raw: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AgentConfigWriteError(
                f"Cannot parse {path}; refusing to overwrite it: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise AgentConfigWriteError(f"{path} must decode to a JSON object")
        raw = loaded

    channels = raw.setdefault("channels", {})
    if not isinstance(channels, dict):
        raise AgentConfigWriteError(f"{path}: 'channels' must be a JSON object")
    section = channels.get(name)
    if section is not None and not isinstance(section, dict):
        raise AgentConfigWriteError(f"{path}: 'channels.{name}' must be a JSON object")

    merged = {**(section or {}), **updates}
    channels[name] = merged
    _atomic_write_json(path, raw)
    return merged
