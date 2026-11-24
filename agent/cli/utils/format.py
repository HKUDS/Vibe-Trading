"""Pure formatting helpers for the CLI surface."""

from __future__ import annotations

from typing import Union

Number = Union[int, float]


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------


def format_duration(value: Number | None, *, unit: str = "ms") -> str:
    """Render a duration as a short, human-readable string."""

    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v < 0:
        return "—"

    if unit == "s":
        seconds = v
    elif unit == "ms":
        seconds = v / 1000.0
    else:
        raise ValueError(f"unit must be 'ms' or 's', got {unit!r}")

    # Compare the value as it will be printed, so 999.6ms reads "1.0s" rather
    # than "1000ms" and 59.96s reads "1m 00s" rather than "60.0s".
    if round(seconds * 1000) < 1000:
        return f"{int(round(seconds * 1000))}ms"
    if round(seconds, 1) < 60:
        # 1.4s, 12.0s — keep one decimal to communicate sub-second jitter
        return f"{seconds:.1f}s"
    minutes, rem = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {rem:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def format_tokens(count: Number | None) -> str:
    """Render a token count with a thousands-suffix."""

    if count is None:
        return "0 tokens"
    try:
        n = int(count)
    except (TypeError, ValueError):
        return "0 tokens"
    if n <= 0:
        return "0 tokens"

    if n < 1_000:
        return f"{n} tokens"
    if round(n / 1_000, 1) < 1_000:
        return f"{n / 1_000:.1f}k tokens"
    if round(n / 1_000_000, 1) < 1_000:
        return f"{n / 1_000_000:.1f}M tokens"
    return f"{n / 1_000_000_000:.1f}B tokens"


# ---------------------------------------------------------------------------
# Generic abbreviation (dollars / counts / sizes)
# ---------------------------------------------------------------------------


def abbreviate_num(value: Number | None, *, currency: str | None = None) -> str:
    """Abbreviate a number with magnitude suffix."""

    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"

    prefix = currency or ""
    sign = "-" if n < 0 else ""
    n_abs = abs(n)

    if currency is not None and n_abs < 1.0:
        # 3 decimals communicates per-token / per-call cost precision
        return f"{sign}{prefix}{n_abs:.3f}"

    if n_abs < 1_000:
        if currency is not None or not float(n_abs).is_integer():
            return f"{sign}{prefix}{n_abs:.2f}".rstrip("0").rstrip(".")
        return f"{sign}{prefix}{int(n_abs)}"

    for unit, divisor in (("k", 1_000), ("M", 1_000_000), ("B", 1_000_000_000), ("T", 1_000_000_000_000)):
        if round(n_abs / divisor, 1) < 1_000:
            return f"{sign}{prefix}{n_abs / divisor:.1f}{unit}"

    return f"{sign}{prefix}{n_abs:.1e}"


__all__ = ["format_duration", "format_tokens", "abbreviate_num"]
