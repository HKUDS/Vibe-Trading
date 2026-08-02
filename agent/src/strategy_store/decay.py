"""Decay state machine — pure logic for evaluating factor/strategy health."""

from __future__ import annotations

from dataclasses import dataclass

from src.strategy_store.models import (
    ArtifactStatus,
    DecaySignal,
)


@dataclass(frozen=True)
class DecayThresholds:
    """Configurable thresholds for decay evaluation."""

    # IC Ratio (rolling / baseline) thresholds
    ic_ratio_healthy: float = 0.7
    ic_ratio_warning: float = 0.5
    ic_ratio_decayed: float = 0.3

    # IR (rolling window) thresholds
    ir_healthy: float = 1.0
    ir_warning: float = 0.5
    ir_decayed: float = 0.1

    # IC Positive Ratio thresholds
    ic_pos_ratio_healthy: float = 0.55
    ic_pos_ratio_warning: float = 0.45
    ic_pos_ratio_decayed: float = 0.35

    # Sharpe thresholds (for strategies)
    sharpe_healthy: float = 1.0
    sharpe_warning: float = 0.5
    sharpe_decayed: float = 0.0

    # Consecutive signal counts for state transitions
    warnings_for_monitoring: int = 3  # active → monitoring
    warnings_for_decayed: int = 2  # monitoring → decayed (additional)
    critical_for_disabled: int = 3  # decayed → disabled


# Ordered worst → best for comparison
_SIGNAL_ORDER: list[DecaySignal] = [
    DecaySignal.CRITICAL,
    DecaySignal.DECAYED,
    DecaySignal.WARNING,
    DecaySignal.HEALTHY,
]


def _worst(a: DecaySignal, b: DecaySignal) -> DecaySignal:
    """Return the worse of two signals."""
    return a if _SIGNAL_ORDER.index(a) <= _SIGNAL_ORDER.index(b) else b


def _classify(
    value: float,
    healthy: float,
    warning: float,
    decayed: float,
) -> DecaySignal:
    """Classify a single metric value against three descending thresholds.

    Thresholds are ordered high→low (healthy > warning > decayed).
    A value at or above `healthy` is HEALTHY; between healthy and warning
    is WARNING; between warning and decayed is DECAYED; below decayed
    is CRITICAL.
    """
    if value >= healthy:
        return DecaySignal.HEALTHY
    if value >= warning:
        return DecaySignal.WARNING
    if value >= decayed:
        return DecaySignal.DECAYED
    return DecaySignal.CRITICAL


class DecayEvaluator:
    """Evaluates factor/strategy health and determines status transitions.

    Pure logic — no I/O, no database access. Feed it metrics and get decisions.
    """

    def __init__(self, thresholds: DecayThresholds | None = None) -> None:
        self._t = thresholds or DecayThresholds()

    def evaluate_decay(
        self,
        *,
        ic_ratio: float | None = None,
        ir: float | None = None,
        ic_positive_ratio: float | None = None,
        sharpe: float | None = None,
    ) -> DecaySignal:
        """Evaluate a single set of metrics and return the decay signal.

        Uses the WORST signal across all provided metrics.
        For factors: uses ic_ratio, ir, ic_positive_ratio.
        For strategies: uses sharpe (and optionally ic_ratio if available).

        Args:
            ic_ratio: rolling_ic_mean / baseline_ic_mean (factor health).
            ir: Information Ratio over rolling window.
            ic_positive_ratio: fraction of periods with positive IC.
            sharpe: Sharpe ratio (strategy health).

        Returns:
            DecaySignal: HEALTHY, WARNING, DECAYED, or CRITICAL.
        """
        signals: list[DecaySignal] = []

        if ic_ratio is not None:
            signals.append(
                _classify(
                    ic_ratio,
                    self._t.ic_ratio_healthy,
                    self._t.ic_ratio_warning,
                    self._t.ic_ratio_decayed,
                )
            )

        if ir is not None:
            signals.append(
                _classify(
                    ir,
                    self._t.ir_healthy,
                    self._t.ir_warning,
                    self._t.ir_decayed,
                )
            )

        if ic_positive_ratio is not None:
            signals.append(
                _classify(
                    ic_positive_ratio,
                    self._t.ic_pos_ratio_healthy,
                    self._t.ic_pos_ratio_warning,
                    self._t.ic_pos_ratio_decayed,
                )
            )

        if sharpe is not None:
            signals.append(
                _classify(
                    sharpe,
                    self._t.sharpe_healthy,
                    self._t.sharpe_warning,
                    self._t.sharpe_decayed,
                )
            )

        if not signals:
            return DecaySignal.HEALTHY

        result = signals[0]
        for s in signals[1:]:
            result = _worst(result, s)
        return result

    def should_transition(
        self,
        current_status: ArtifactStatus,
        consecutive_signals: list[DecaySignal],
    ) -> ArtifactStatus | None:
        """Determine if a status transition should occur.

        Args:
            current_status: Current artifact status.
            consecutive_signals: Recent decay signals (newest last).

        Returns:
            New ArtifactStatus if transition should occur, None otherwise.

        Transition rules:
        - active → monitoring: WARNING or worse for ``warnings_for_monitoring``
          consecutive readings.
        - monitoring → decayed: DECAYED or worse for ``warnings_for_decayed``
          consecutive readings.
        - monitoring → active: HEALTHY for 1 reading (recovery).
        - decayed → disabled: CRITICAL for ``critical_for_disabled``
          consecutive readings.
        """
        if not consecutive_signals:
            return None

        if current_status == ArtifactStatus.ACTIVE:
            return self._check_active_to_monitoring(consecutive_signals)

        if current_status == ArtifactStatus.MONITORING:
            return self._check_monitoring_transition(consecutive_signals)

        if current_status == ArtifactStatus.DECAYED:
            return self._check_decayed_to_disabled(consecutive_signals)

        return None

    def _check_active_to_monitoring(self, signals: list[DecaySignal]) -> ArtifactStatus | None:
        """active → monitoring: WARNING+ for warnings_for_monitoring consecutive."""
        needed = self._t.warnings_for_monitoring
        tail = signals[-needed:] if len(signals) >= needed else signals
        if len(tail) < needed:
            return None
        if all(s != DecaySignal.HEALTHY for s in tail):
            return ArtifactStatus.MONITORING
        return None

    def _check_monitoring_transition(self, signals: list[DecaySignal]) -> ArtifactStatus | None:
        """monitoring → active (recovery) or monitoring → decayed."""
        latest = signals[-1]

        # Recovery: single HEALTHY reading
        if latest == DecaySignal.HEALTHY:
            return ArtifactStatus.ACTIVE

        # Decay: DECAYED or worse for warnings_for_decayed consecutive
        needed = self._t.warnings_for_decayed
        tail = signals[-needed:] if len(signals) >= needed else signals
        if len(tail) < needed:
            return None
        if all(s in (DecaySignal.DECAYED, DecaySignal.CRITICAL) for s in tail):
            return ArtifactStatus.DECAYED
        return None

    def _check_decayed_to_disabled(self, signals: list[DecaySignal]) -> ArtifactStatus | None:
        """decayed → disabled: CRITICAL for critical_for_disabled consecutive."""
        needed = self._t.critical_for_disabled
        tail = signals[-needed:] if len(signals) >= needed else signals
        if len(tail) < needed:
            return None
        if all(s == DecaySignal.CRITICAL for s in tail):
            return ArtifactStatus.DISABLED
        return None

    def evaluate_and_transition(
        self,
        current_status: ArtifactStatus,
        *,
        ic_ratio: float | None = None,
        ir: float | None = None,
        ic_positive_ratio: float | None = None,
        sharpe: float | None = None,
        prior_signals: list[DecaySignal] | None = None,
    ) -> tuple[DecaySignal, ArtifactStatus | None]:
        """Convenience: evaluate metrics and determine transition in one call.

        Args:
            current_status: Current artifact status.
            ic_ratio: rolling_ic_mean / baseline_ic_mean.
            ir: Information Ratio over rolling window.
            ic_positive_ratio: fraction of periods with positive IC.
            sharpe: Sharpe ratio.
            prior_signals: Previously accumulated signals (new signal appended).

        Returns:
            Tuple of (decay_signal, new_status_or_None).
        """
        signal = self.evaluate_decay(
            ic_ratio=ic_ratio,
            ir=ir,
            ic_positive_ratio=ic_positive_ratio,
            sharpe=sharpe,
        )
        history = list(prior_signals or [])
        history.append(signal)
        new_status = self.should_transition(current_status, history)
        return signal, new_status
