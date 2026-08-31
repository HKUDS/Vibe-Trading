"""Deterministic tolerance calibration from recorded reconciliation comparisons.

This module is deliberately offline.  It derives a versioned
ReconciliationTolerance from recorded local-versus-exchange comparison
samples and verifies that a tolerance bounds a recorded sample set.  A
calibrated tolerance is evidence about recorded observations only; it never
relaxes validation or touches accounting state.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence

from backtest.binance_account_reconciliation import ReconciliationTolerance


_CANONICAL_USDM_SYMBOL = re.compile(r"^[A-Z0-9]+-USDT-PERP$")


def _require_finite(name: str, value: float, *, non_negative: bool = False) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class CalibrationSample:
    """One recorded local-versus-exchange comparison sample."""

    field: str
    local_value: float
    exchange_value: float
    symbol: str | None = None

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("field must not be empty")
        _require_finite("local_value", self.local_value)
        _require_finite("exchange_value", self.exchange_value)
        if self.symbol is not None and not _CANONICAL_USDM_SYMBOL.fullmatch(self.symbol):
            raise ValueError("symbol must use canonical *-USDT-PERP form")

    @property
    def absolute_delta(self) -> float:
        return abs(self.local_value - self.exchange_value)


@dataclass(frozen=True)
class CalibratedField:
    """Per-field calibration statistics over one recorded field."""

    field: str
    sample_count: int
    max_absolute_delta: float
    proposed_absolute: float
    proposed_relative: float


@dataclass(frozen=True)
class ToleranceCalibration:
    """Versioned calibration outcome over one recorded sample set."""

    version: str
    sample_count: int
    fields: tuple[CalibratedField, ...]
    tolerance: ReconciliationTolerance


def _max_relative_delta(samples: Sequence[CalibrationSample]) -> float:
    return max(
        (
            sample.absolute_delta / max(abs(sample.local_value), abs(sample.exchange_value))
            if sample.absolute_delta != 0
            else 0.0
        )
        for sample in samples
    )


def calibrate_tolerance(
    samples: Sequence[CalibrationSample],
    *,
    version: str,
    min_samples_per_field: int = 4,
    safety_factor: float = 2.0,
    absolute_floor: float = 1e-8,
    relative_floor: float = 1e-8,
) -> ToleranceCalibration:
    """Derive a versioned tolerance that bounds the recorded sample set.

    Raises:
        ValueError: If inputs are invalid or any field group holds fewer than
            ``min_samples_per_field`` samples.
    """
    if not samples:
        raise ValueError("samples must not be empty")
    if not version:
        raise ValueError("version must not be empty")
    if min_samples_per_field < 1:
        raise ValueError("min_samples_per_field must be at least one")
    _require_finite("safety_factor", safety_factor, non_negative=True)
    if safety_factor < 1.0:
        raise ValueError("safety_factor must be at least 1.0")
    _require_finite("absolute_floor", absolute_floor, non_negative=True)
    _require_finite("relative_floor", relative_floor, non_negative=True)

    grouped: dict[str, list[CalibrationSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.field, []).append(sample)
    undercounted = sorted(field for field, group in grouped.items() if len(group) < min_samples_per_field)
    if undercounted:
        raise ValueError(f"fields below min_samples_per_field: {undercounted}")

    calibrated = []
    for field in sorted(grouped):
        group = grouped[field]
        max_absolute_delta = max(sample.absolute_delta for sample in group)
        calibrated.append(
            CalibratedField(
                field=field,
                sample_count=len(group),
                max_absolute_delta=max_absolute_delta,
                proposed_absolute=max(absolute_floor, safety_factor * max_absolute_delta),
                proposed_relative=max(relative_floor, safety_factor * _max_relative_delta(group)),
            )
        )
    tolerance = ReconciliationTolerance(
        absolute=max(item.proposed_absolute for item in calibrated),
        relative=max(item.proposed_relative for item in calibrated),
        max_timestamp_skew_seconds=0.0,
        version=version,
    )
    return ToleranceCalibration(
        version=version,
        sample_count=len(samples),
        fields=tuple(calibrated),
        tolerance=tolerance,
    )


def verify_tolerance_covers(
    tolerance: ReconciliationTolerance,
    samples: Sequence[CalibrationSample],
) -> tuple[CalibrationSample, ...]:
    """Return the recorded samples the tolerance does not bound."""
    uncovered = []
    for sample in samples:
        allowed_delta = max(
            tolerance.absolute,
            tolerance.relative * max(abs(sample.local_value), abs(sample.exchange_value)),
        )
        if sample.absolute_delta > allowed_delta:
            uncovered.append(sample)
    return tuple(uncovered)
