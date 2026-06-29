"""Security network compatibility helpers for channel adapters.

Re-exports validate_url_target / validate_resolved_url from :mod:`src.channels.utils`.
"""

from __future__ import annotations

from src.channels.utils import validate_resolved_url, validate_url_target

__all__ = ["validate_resolved_url", "validate_url_target"]
