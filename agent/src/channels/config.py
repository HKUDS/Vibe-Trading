"""Channel config loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config.loader import load_agent_config


def load_channels_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load the operator IM channel config from the structured agent config.

    Args:
        config_path: Optional explicit config path.

    Returns:
        A plain dictionary suitable for :class:`src.channels.manager.ChannelManager`.
    """
    config = load_agent_config(config_path)
    return config.channels.model_dump(mode="json", by_alias=False)
