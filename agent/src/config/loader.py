"""Structured agent config loading utilities."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from src.config.paths import get_config_path
from src.config.schema import AgentConfig, AgentConfigOverride

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def load_agent_config(config_path: Path | None = None) -> AgentConfig:
    """Load structured agent config from disk with safe fallback.

    Args:
        config_path: Optional explicit config path. When omitted, the default
            config discovery path is used.

    Returns:
        The validated agent config. Invalid or unreadable config files fall
        back to ``AgentConfig()``.
    """
    path = get_config_path(config_path)

    if not path.exists():
        return AgentConfig()

    try:
        raw = _read_config_file(path)
        return AgentConfig.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        logger.warning(
            "Failed to load agent config from %s: %s",
            path,
            type(exc).__name__,
        )
        logger.debug("Agent config load error details: %s", exc)
        return AgentConfig()


def merge_agent_config_overrides(
    config: AgentConfig,
    overrides: Mapping[str, Any] | None,
) -> AgentConfig:
    """Merge runtime overrides on top of a base config.

    Overrides are validated against a partial schema first so both snake_case
    and camelCase keys are accepted while only explicitly provided fields
    override the base config.

    Args:
        config: Base agent config loaded from disk or defaults.
        overrides: Runtime overrides, typically from session-level config.

    Returns:
        A new validated config containing the merged result.
    """
    if not overrides:
        return config

    try:
        override_model = AgentConfigOverride.model_validate(dict(overrides))
    except ValidationError as exc:
        logger.warning(
            "Ignoring invalid agent config overrides (%s): %s — using base config",
            type(exc).__name__,
            [str(e["loc"]) for e in exc.errors()],
        )
        return config

    merged = _merge_dicts(
        config.model_dump(mode="json"),
        override_model.model_dump(mode="json", exclude_unset=True),
    )
    return AgentConfig.model_validate(merged)


# Keys in session overrides that carry subprocess definitions and therefore
# require operator-level trust rather than API-caller trust.
_SESSION_RESTRICTED_KEYS: frozenset[str] = frozenset({"mcpServers", "mcp_servers"})


def sanitize_session_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Strip operator-only keys from API-caller-supplied session overrides.

    ``mcpServers`` / ``mcp_servers`` define subprocess ``command``/``args``/``env``
    and therefore grant execution-level capabilities.  They must originate from
    the operator-controlled config file on disk, not from unauthenticated or
    semi-trusted API callers.  Operators who deliberately want to allow session-
    level MCP injection can set ``ALLOW_SESSION_MCP_SERVERS=1``.

    Args:
        overrides: Raw session config dict received from the API caller.

    Returns:
        A new dict with restricted keys removed (or the original mapping
        converted to dict if the env opt-in is active).
    """
    if os.environ.get("ALLOW_SESSION_MCP_SERVERS", "").strip().lower() in {"1", "true", "yes"}:
        return dict(overrides)

    restricted_present = _SESSION_RESTRICTED_KEYS & overrides.keys()
    if restricted_present:
        logger.warning(
            "Stripped %s from session config overrides: MCP server definitions "
            "require operator-level trust (disk config). "
            "Set ALLOW_SESSION_MCP_SERVERS=1 to allow session-level injection.",
            sorted(restricted_present),
        )
    return {k: v for k, v in overrides.items() if k not in _SESSION_RESTRICTED_KEYS}


def load_runtime_agent_config(
    config_path: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> AgentConfig:
    """Load disk config and apply runtime overrides.

    Args:
        config_path: Optional explicit config file path.
        overrides: Runtime override mapping applied on top of file-based config.

    Returns:
        The merged runtime config.
    """
    config = load_agent_config(config_path)
    return merge_agent_config_overrides(config, overrides)


def _read_config_file(path: Path) -> dict[str, Any]:
    """Read a supported config file format into a dictionary.

    Args:
        path: Config file path to decode.

    Returns:
        The decoded config object as a dictionary.

    Raises:
        ValueError: If the file format is unsupported, YAML support is
            unavailable, or the decoded payload is not an object.
    """
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ValueError("YAML config is not available because PyYAML is missing")
        data = yaml.safe_load(text) or {}
    else:
        raise ValueError(f"Unsupported config file format: {suffix or '<none>'}")

    if not isinstance(data, dict):
        raise ValueError("Agent config must decode to a JSON/YAML object")
    return data


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two plain dictionaries.

    Args:
        base: Base dictionary.
        override: Override dictionary applied on top of ``base``.

    Returns:
        A merged dictionary where nested mappings are merged recursively and
        scalar values from ``override`` replace those in ``base``.
    """
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(current, value)
        else:
            merged[key] = value
    return merged