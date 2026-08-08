"""Data models for strategy development artifacts and decay monitoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ArtifactType(str, Enum):
    """Type of research artifact."""

    FACTOR = "factor"
    STRATEGY = "strategy"


class ArtifactStatus(str, Enum):
    """Lifecycle states for a research artifact."""

    CREATED = "created"
    BENCHING = "benching"
    ACTIVE = "active"
    MONITORING = "monitoring"
    DECAYED = "decayed"
    DISABLED = "disabled"


class DecaySignal(str, Enum):
    """Decay health signal for an artifact."""

    HEALTHY = "healthy"
    WARNING = "warning"
    DECAYED = "decayed"
    CRITICAL = "critical"


class BenchCategory(str, Enum):
    """Backtest evaluation category."""

    ALIVE = "alive"
    REVERSED = "reversed"
    DEAD = "dead"
    CONFIRMED_ALIVE = "confirmed_alive"
    NOISE = "noise"


class ModelTier(str, Enum):
    """Model materiality/risk tier — governs the required validation rigor.

    Mirrors the tiering used in bank model-risk-management policies (e.g.
    SR 11-7): higher tiers demand deeper independent validation before a
    model can be marked ``ValidationStatus.APPROVED``.
    """

    TIER_1_CRITICAL = "tier_1_critical"
    TIER_2_SIGNIFICANT = "tier_2_significant"
    TIER_3_LIMITED = "tier_3_limited"


class ValidationStatus(str, Enum):
    """Independent-validation lifecycle for a registered model.

    Intended progression::

        UNVALIDATED -> IN_VALIDATION -> VALIDATED -> APPROVED
                                                   \\-> REJECTED

    ``APPROVED`` is only reachable from ``VALIDATED`` (or ``APPROVED``
    itself, for an idempotent re-approval) — see
    ``validate_validation_status_transition``. An unvalidated model can
    never be marked approved.
    """

    UNVALIDATED = "unvalidated"
    IN_VALIDATION = "in_validation"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Artifact:
    """Persisted research artifact record."""

    id: str
    type: ArtifactType
    name: str
    universe: str
    source_paper: str | None = None
    source_url: str | None = None
    # Factor-specific
    formula_latex: str | None = None
    theme: tuple[str, ...] = ()
    columns_required: tuple[str, ...] = ()
    decay_horizon: int = 20
    # Strategy-specific
    signal_definition: str | None = None
    entry_rules: str | None = None
    exit_rules: str | None = None
    position_sizing: str | None = None
    # Common
    signal_engine_path: str | None = None
    run_dir: str | None = None
    hypothesis_id: str | None = None
    # Lifecycle
    status: ArtifactStatus = ArtifactStatus.CREATED
    created_at: str = ""
    updated_at: str = ""
    disabled_at: str | None = None
    disabled_reason: str | None = None
    # Model governance (2026-08-06) — makes each artifact expressible as a
    # registered model under a firm's model-risk-management policy: who
    # built it, who owns it, who independently validated it, who signed
    # off, at what version, at what materiality tier, for what declared
    # use, with what known limitations. Every field here is optional at the
    # dataclass level so pre-existing bare Artifact construction (factors/
    # strategies registered before this governance layer existed, and the
    # SDM tools that still build bare artifacts) keeps working unchanged.
    # Use ``validate_model_registration`` to enforce the non-empty
    # intended_use/limitations rule when a caller wants full governance
    # rigor, and ``validate_validation_status_transition`` to guard the
    # unvalidated-can't-become-approved state machine.
    developer: str | None = None
    owner: str | None = None
    validator: str | None = None
    approver: str | None = None
    model_version: str | None = None
    artifact_version: str | None = None
    model_tier: ModelTier | None = None
    intended_use: str | None = None
    limitations: str | None = None
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    validation_date: str | None = None


@dataclass(frozen=True)
class BenchResult:
    """Backtest result for an artifact."""

    id: int | None = None
    artifact_id: str = ""
    bench_type: str = "initial"
    # Factor metrics
    ic_mean: float | None = None
    ic_std: float | None = None
    ir: float | None = None
    ic_positive_ratio: float | None = None
    t_stat: float | None = None
    # Strategy metrics
    sharpe: float | None = None
    annual_return: float | None = None
    max_drawdown: float | None = None
    calmar: float | None = None
    # Evaluation
    category: BenchCategory | None = None
    # Time window
    train_start: str | None = None
    train_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    run_dir: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class DecaySnapshot:
    """Point-in-time decay monitoring snapshot."""

    id: int | None = None
    artifact_id: str = ""
    rolling_ic_mean: float | None = None
    rolling_ir: float | None = None
    baseline_ic_mean: float | None = None
    ic_ratio: float | None = None
    decay_signal: DecaySignal | None = None
    consecutive_warnings: int = 0
    detail: str | None = None
    created_at: str = ""


# ---------------------------------------------------------------------------
# Model-governance validation helpers
# ---------------------------------------------------------------------------
#
# Pure functions — no I/O, no datetime.now(). All timestamps (validation_date
# included) are supplied by the caller, same convention as created_at/
# updated_at elsewhere in this module.


def is_four_eyes_violation(artifact: Artifact) -> bool:
    """Report whether *artifact* was both developed and approved by the same person.

    The four-eyes (maker-checker) principle requires the developer and
    approver roles to be held by different people. This function only
    *detects* the condition — it does not raise or block, since whether to
    reject a same-person dev/approve pair is a firm-policy decision, not a
    library decision.

    Args:
        artifact: The artifact/model record to inspect.

    Returns:
        True when both ``developer`` and ``approver`` are set and refer to
        the same person (case-insensitive, whitespace-trimmed comparison).
        False when either role is unset (nothing to compare) or they differ.
    """
    if not artifact.developer or not artifact.approver:
        return False
    return artifact.developer.strip().casefold() == artifact.approver.strip().casefold()


def validate_validation_status_transition(
    current: ValidationStatus, new: ValidationStatus
) -> None:
    """Guard the model-validation state machine.

    The only hard rule: a model cannot be marked ``APPROVED`` unless it is
    already ``VALIDATED`` (re-approving an already-``APPROVED`` model is a
    harmless no-op transition). Every other transition is left to caller
    discretion.

    Args:
        current: The model's validation status before the change.
        new: The requested validation status.

    Raises:
        ValueError: if *new* is ``APPROVED`` while *current* is anything
            other than ``VALIDATED`` or ``APPROVED``.
    """
    if new is ValidationStatus.APPROVED and current not in (
        ValidationStatus.VALIDATED,
        ValidationStatus.APPROVED,
    ):
        raise ValueError(
            "cannot mark a model APPROVED from validation_status="
            f"{current.value!r}; it must reach VALIDATED first"
        )


def validate_model_registration(artifact: Artifact) -> None:
    """Validate that *artifact* carries the minimum model-registration fields.

    A model registration without a stated intended use or a stated
    limitation is, for governance purposes, not actually registered — so
    both fields are required and must be non-blank.

    Args:
        artifact: The artifact/model record to validate.

    Raises:
        ValueError: if ``intended_use`` or ``limitations`` is missing or
            consists only of whitespace.
    """
    if not artifact.intended_use or not artifact.intended_use.strip():
        raise ValueError("intended_use is required and must be non-empty")
    if not artifact.limitations or not artifact.limitations.strip():
        raise ValueError("limitations is required and must be non-empty")
