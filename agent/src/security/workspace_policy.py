"""Security workspace policy compatibility helpers for channel adapters.

Re-exports :func:`is_path_within` from :mod:`src.channels.utils`.
"""

from __future__ import annotations

from src.channels.utils import is_path_within as _is_path_within

# Re-export for backward compat with ported channel code
is_path_within = _is_path_within
