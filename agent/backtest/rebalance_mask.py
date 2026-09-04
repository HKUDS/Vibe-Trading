"""Execution-date contract for calendar-triggered portfolio rebalancing."""

from __future__ import annotations

from bisect import bisect_left
from datetime import date
from typing import TypeAlias, cast

import pandas as pd
from pandas.tseries.frequencies import to_offset

RebalanceMask: TypeAlias = str | list[str] | None


def validate_rebalance_mask(value: RebalanceMask) -> RebalanceMask:
    """Validate the configured schedule without consulting a trading calendar."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("rebalance_mask offset alias must not be empty")
        try:
            _ = to_offset(value)
        except ValueError:
            raise ValueError(
                f"rebalance_mask must be a pandas offset alias or ISO date list, got {value!r}"
            ) from None
        return value
    if not isinstance(value, list) or not value:
        raise ValueError(
            "rebalance_mask must be a non-empty pandas offset alias or ISO date list"
        )
    for item in value:
        if not isinstance(item, str):
            raise ValueError("rebalance_mask date entries must be ISO date strings")
        try:
            parsed = date.fromisoformat(item)
        except ValueError:
            raise ValueError(f"invalid rebalance_mask date: {item!r}") from None
        if parsed.isoformat() != item:
            raise ValueError(
                f"invalid rebalance_mask date: {item!r} (expected YYYY-MM-DD)"
            )
    return value


def resolve_rebalance_dates(
    value: RebalanceMask,
    dates: pd.DatetimeIndex,
) -> frozenset[pd.Timestamp] | None:
    """Resolve an optional schedule to executable bars in the aligned calendar."""
    validated = validate_rebalance_mask(value)
    if validated is None:
        return None
    if len(dates) == 0:
        raise ValueError("rebalance_mask does not intersect the aligned trading dates")

    if isinstance(validated, str):
        offset = to_offset(validated)
        bounds: list[int] = dates.asi8.tolist()
        spacings = [
            current - previous
            for previous, current in zip(bounds, bounds[1:])
            if current > previous
        ]
        if spacings:
            minimum_spacing = min(spacings)
            try:
                offset_nanos = offset.nanos
            except ValueError:
                first_bar = cast(pd.Timestamp, dates[0])
                next_boundary = cast(pd.Timestamp, first_bar + offset)
                offset_nanos = next_boundary.value - first_bar.value
            if 0 < offset_nanos < minimum_spacing:
                raise ValueError(
                    "rebalance_mask offset alias must not be finer than "
                    "the aligned bar spacing"
                )
        observed = pd.Series(dates, index=dates)
        selected = []
        for item in observed.resample(validated).first().dropna().tolist():
            timestamp = cast(pd.Timestamp, pd.Timestamp(item))
            selected.append(timestamp)
    else:
        selected = []
        bounds: list[int] = dates.asi8.tolist()
        for item in validated:
            requested = cast(pd.Timestamp, pd.Timestamp(item))
            if dates.tz is not None:
                requested = requested.tz_localize(dates.tz)
            index = bisect_left(bounds, requested.value)
            if index < len(dates):
                timestamp = cast(pd.Timestamp, dates[index])
                selected.append(timestamp)

    execution_dates = frozenset(selected)
    if not execution_dates:
        raise ValueError("rebalance_mask does not intersect the aligned trading dates")
    return execution_dates
