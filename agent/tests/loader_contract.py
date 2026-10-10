"""Shared per-loader contract assertion (issue #1723).

Each loader test file pins its own canonical fixture with bespoke assertions;
the only shared schema check lived in the weekly health lane
(:mod:`backtest.loader_health`), at runtime. Nothing stopped a new loader, or
a refactor of an old one, from quietly changing the frame the rest of the
pipeline consumes.

This harness pins the *structural* contract every downstream consumer relies
on, using the same failure vocabulary as the health lane's ``check_frame``:

- the frame carries unique ``open`` / ``high`` / ``low`` / ``close`` /
  ``volume`` columns, all numeric;
- the index is a DatetimeIndex, sorted, unique, no NaT;
- prices positive, volume non-negative, high >= max(open, close, low),
  low <= min(open, close), all finite.

One call per loader test, on its canonical fixture. Fixtures are historic
(frozen dates), so freshness — the only check ``check_frame`` does that is
meaningless offline — is intentionally out of scope here; it stays in the
weekly lane.
"""

from __future__ import annotations

import pandas as pd
import pytest

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

# Structural failures that must never reach the pipeline. Same vocabulary as
# backtest.loader_health.check_frame.
_CONTRACT_REASONS = frozenset(
    {
        "empty_frame",
        "schema",
        "datetime_index",
        "index_order",
        "numeric_columns",
        "nonfinite_values",
        "invalid_prices_or_volume",
        "ohlc_order",
    }
)


def loader_contract_errors(frame: object, *, context: str = "") -> list[str]:
    """Return contract violations for a normalized OHLCV frame.

    Mirrors the structural half of ``backtest.loader_health.check_frame``
    (freshness deliberately excluded — fixtures are frozen history). Never
    raises on bad input; returns the violation list so tests can render it.
    """
    import numpy as np

    def bad(reason: str) -> list[str]:
        # The vocabulary is pinned so a typo'd reason can never slip through.
        assert reason in _CONTRACT_REASONS, f"unknown contract reason: {reason}"
        return [f"{context}: {reason}" if context else reason]

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return bad("empty_frame")
    if not frame.columns.is_unique or not set(OHLCV_COLUMNS) <= set(frame.columns):
        return bad("schema")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        return bad("datetime_index")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        return bad("index_order")
    if any(not pd.api.types.is_numeric_dtype(frame[c]) for c in OHLCV_COLUMNS):
        return bad("numeric_columns")
    values = frame[list(OHLCV_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return bad("nonfinite_values")
    if (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
        return bad("invalid_prices_or_volume")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close"]].min(axis=1)
    ).any():
        return bad("ohlc_order")
    return []


def assert_loader_contract(frame: object, *, context: str = "") -> None:
    """Assert a loader's normalized frame satisfies the shared contract.

    One call per loader test, on its canonical fixture.
    """
    errors = loader_contract_errors(frame, context=context)
    if errors:
        pytest.fail(
            "loader contract violated: " + "; ".join(errors)
            + f"\n(frame={getattr(frame, 'shape', None)})"
        )
