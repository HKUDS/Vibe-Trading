"""Graceful bottleneck import with env-var override.

Bottleneck provides C-compiled moving-window operators (move_argmax,
move_argmin) that are 100-350x faster than pandas rolling().apply().

When bottleneck is unavailable or disabled via env var, the operators
fall back to the original pandas path — identical results, slower speed.

Note: ``bn.move_rank`` uses a fundamentally different normalization
(Spearman rank correlation) than our ``ts_rank`` (percentile rank),
so ``ts_rank`` uses numpy ``sliding_window_view`` instead.

``HAS_BOTTLENECK`` and ``bn`` are resolved lazily on first access via
:func:`__getattr__` so the ``VIBE_TRADING_DISABLE_BOTTLENECK`` env var
is read through :func:`get_env_config` instead of at import time.
"""

from __future__ import annotations

from typing import Any

# numpy sliding_window_view — always available (numpy >= 1.20)
from numpy.lib.stride_tricks import sliding_window_view

__all__ = ["HAS_BOTTLENECK", "bn", "sliding_window_view"]  # noqa: F822 — lazily resolved via module __getattr__ (PEP 562)

# ---------------------------------------------------------------------------
# Lazy bottleneck initialisation
# ---------------------------------------------------------------------------

_bn_initialised: bool = False
_has_bottleneck: bool = False
_bn_module: Any = None


def _ensure_bottleneck() -> None:
    """Attempt to import bottleneck on first access.

    Reads ``VIBE_TRADING_DISABLE_BOTTLENECK`` through the lazy
    :func:`get_env_config` accessor so runtime Settings API changes
    take effect before the first factor computation.
    """
    global _bn_initialised, _has_bottleneck, _bn_module  # noqa: PLW0603
    if _bn_initialised:
        return
    _bn_initialised = True
    from src.config.accessor import get_env_config

    if get_env_config().agent_tuning.vibe_trading_disable_bottleneck:
        return
    try:
        import bottleneck as _bn

        _bn_module = _bn
        _has_bottleneck = True
    except ImportError:
        pass


def __getattr__(name: str) -> Any:
    """Lazily resolve ``HAS_BOTTLENECK`` and ``bn`` on first attribute access."""
    if name == "HAS_BOTTLENECK":
        _ensure_bottleneck()
        return _has_bottleneck
    if name == "bn":
        _ensure_bottleneck()
        return _bn_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
