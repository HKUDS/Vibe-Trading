"""Graceful bottleneck import with env-var override.

Bottleneck provides C-compiled moving-window operators (move_argmax,
move_argmin) that are 100-350x faster than pandas rolling().apply().

When bottleneck is unavailable or disabled via env var, the operators
fall back to the original pandas path — identical results, slower speed.

Note: ``bn.move_rank`` uses a fundamentally different normalization
(Spearman rank correlation) than our ``ts_rank`` (percentile rank),
so ``ts_rank`` uses numpy ``sliding_window_view`` instead.
"""

from __future__ import annotations

import os

_DISABLE = os.environ.get("VIBE_TRADING_DISABLE_BOTTLENECK", "0") == "1"

HAS_BOTTLENECK: bool = False
bn = None

if not _DISABLE:
    try:
        import bottleneck as _bn

        bn = _bn
        HAS_BOTTLENECK = True
    except ImportError:
        pass

# numpy sliding_window_view — always available (numpy >= 1.20)
from numpy.lib.stride_tricks import sliding_window_view  # noqa: E402

__all__ = ["HAS_BOTTLENECK", "bn", "sliding_window_view"]
