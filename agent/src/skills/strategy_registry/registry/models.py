"""Strategy registry data models: Scenario enum and StrategyEntry Pydantic model."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Scenario(str, Enum):
    """Market regime scenario for strategy effectiveness classification."""

    BEAR_MARKET_DEFENSE = "bear_market_defense"
    BULL_MARKET_MOMENTUM = "bull_market_momentum"
    STRUCTURAL_MARKET = "structural_market"
    HIGH_VOLATILITY_REGIME = "high_volatility_regime"
    REGIME_AGNOSTIC = "regime_agnostic"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM_CONTINUATION = "momentum_continuation"
    VALUE_ROTATION = "value_rotation"
    SECTOR_ROTATION = "sector_rotation"


StrategyArea = Literal["timing", "factor", "rotation", "value", "combination"]
StrategySource = Literal["builtin", "sdm", "user"]

_STRATEGY_ID_RE = r"^[a-z][a-z0-9_]{0,63}$"

# Map ArtifactType → StrategyArea
_TYPE_TO_AREA: dict[str, StrategyArea] = {
    "factor": "factor",
    "strategy": "combination",
}


class StrategyEntry(BaseModel):
    """Immutable registry entry for a quant strategy.

    Design contract:
        - ``strategy_id`` must match ``_STRATEGY_ID_RE`` (max 64 chars, lowercase + digits + underscore).
        - ``description`` max 5 000 chars.
        - ``tuning_hints`` max 10 items, each max 500 chars.
        - ``extra="forbid"`` — no unregistered fields allowed.
    """

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(pattern=_STRATEGY_ID_RE)
    name: str
    source: StrategySource
    area: StrategyArea
    description: str = Field(max_length=5000)
    effective_scenarios: list[Scenario] = Field(default_factory=list)
    failure_scenarios: list[Scenario] = Field(default_factory=list)
    tuning_hints: list[str] = Field(
        default_factory=list, max_length=10
    )
    benchmark_results: dict[str, Any] | None = None
    implementation: dict[str, Any] | None = None

    @classmethod
    def from_artifact(cls, artifact: Any) -> StrategyEntry:
        """Reconstruct a ``StrategyEntry`` from a strategy-store ``Artifact``.

        Lazy-imports ``Artifact`` to avoid a module-level dependency on
        ``strategy_store``.

        Mapping rules:
            - ``artifact.id`` → ``strategy_id``
            - ``artifact.name`` → ``name``
            - ``source`` is always ``"sdm"``
            - ``artifact.type`` → ``area`` (FACTOR→factor, STRATEGY→combination)
            - ``artifact.theme`` (tuple of str) → ``effective_scenarios``
              (any value that matches a ``Scenario`` enum member)
            - ``artifact.source_paper``, ``source_url``, ``universe`` →
              ``implementation`` dict
        """
        from src.strategy_store.models import Artifact, ArtifactType

        if not isinstance(artifact, Artifact):
            raise TypeError(f"expected Artifact, got {type(artifact).__name__}")

        # Parse scenarios from theme tuple
        themes: tuple[str, ...] = artifact.theme if artifact.theme else ()
        effective: list[Scenario] = []
        for t in themes:
            try:
                effective.append(Scenario(t))
            except ValueError:
                continue

        # Map ArtifactType → StrategyArea
        area: StrategyArea = _TYPE_TO_AREA.get(
            artifact.type.value if isinstance(artifact.type, ArtifactType) else str(artifact.type),
            "combination",
        )

        # Build implementation metadata
        impl: dict[str, Any] = {}
        if artifact.source_paper:
            impl["source_paper"] = artifact.source_paper
        if artifact.source_url:
            impl["source_url"] = artifact.source_url
        if artifact.universe:
            impl["universe"] = artifact.universe

        return cls(
            strategy_id=artifact.id,
            name=artifact.name,
            source="sdm",
            area=area,
            description=artifact.name,
            effective_scenarios=effective,
            failure_scenarios=[],
            implementation=impl if impl else None,
        )