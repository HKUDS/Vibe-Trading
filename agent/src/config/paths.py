"""Path helpers for agent-level structured config."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_FILENAMES = ("agent.json", "agent.yaml", "agent.yml")

_HOME_ENV_VAR = "VIBE_TRADING_HOME"


def get_runtime_root(config_path: Path | None = None) -> Path:
    """Return the runtime root directory for user-level agent state.

    Args:
        config_path: Optional explicit config file path. When provided, the
            runtime root is derived from that file's parent directory.

    Returns:
        The directory containing the explicit structured config file when one
        is provided, otherwise the ``VIBE_TRADING_HOME`` environment override,
        otherwise the default ``~/.vibe-trading`` runtime root.
    """
    if config_path is not None:
        return config_path.expanduser().parent
    env_root = os.environ.get(_HOME_ENV_VAR, "").strip()
    if env_root:
        if env_root.startswith(("//", "\\\\")):
            raise ValueError(
                f"{_HOME_ENV_VAR} must not be a UNC path: {env_root!r}"
            )
        return Path(env_root).expanduser()
    return Path.home() / ".vibe-trading"


def get_sessions_dir() -> Path:
    """Return the user-level directory holding chat session records."""
    return get_runtime_root() / "sessions"


def get_runs_dir() -> Path:
    """Return the user-level directory holding run artifacts."""
    return get_runtime_root() / "runs"


def get_swarm_runs_dir() -> Path:
    """Return the user-level directory holding swarm run records."""
    return get_runtime_root() / "swarm" / "runs"


def get_uploads_dir() -> Path:
    """Return the user-level directory holding uploaded files."""
    return get_runtime_root() / "uploads"


def get_config_candidates(config_path: Path | None = None) -> list[Path]:
    """Return supported config path candidates in lookup order.

    Returns:
        Candidate config paths ordered by lookup priority. When an explicit
        config path is provided, only that path is returned.
    """
    if config_path is not None:
        return [config_path.expanduser()]
    root = get_runtime_root()
    return [root / filename for filename in _DEFAULT_FILENAMES]


def get_config_path(config_path: Path | None = None) -> Path:
    """Return the active config file path.

    Prefers the first existing candidate. If an explicit path is provided,
    returns that path directly. If no candidate exists yet, returns the
    recommended default JSON path.

    Args:
        config_path: Optional explicit config file path.

    Returns:
        The selected config file path for the current runtime context.
    """
    candidates = get_config_candidates(config_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def get_data_dir(config_path: Path | None = None) -> Path:
    """Return and create the runtime data directory derived from config path.

    Args:
        config_path: Optional explicit config file path.

    Returns:
        The directory containing the active config file. The directory is
        created when it does not already exist.
    """
    data_dir = get_config_path(config_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_workspace_path() -> Path:
    """Return the workspace path for channel state data.

    For channel adapters that need to persist state (e.g. conversation
    references, auth tokens), this returns ``~/.vibe-trading/workspace``.
    """
    p = get_runtime_root() / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p