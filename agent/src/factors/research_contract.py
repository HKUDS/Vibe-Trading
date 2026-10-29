"""Structured provenance for factor-research runs.

The factor tools already expose useful metadata, but each entry point used a
slightly different set of keys.  This module defines a small additive contract
for the research stage, declared mode and factor lineage.  It deliberately
does not run statistics or enforce a policy yet; callers can adopt stricter
gates without changing the wire shape.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

RESEARCH_CONTRACT_SCHEMA = "factor-research.run/v1"

RESEARCH_MODES = ("explore", "strict", "locked")
RESEARCH_STAGES = (
    "factor_screening",
    "single_factor_evaluation",
    "neutralization",
    "combination",
    "composite_evaluation",
    "backtest",
    "monitoring",
)

__all__ = [
    "RESEARCH_CONTRACT_SCHEMA",
    "RESEARCH_MODES",
    "RESEARCH_STAGES",
    "build_bench_research_contract",
    "build_research_contract",
]


def _text(value: Any, *, name: str, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _ids(values: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        item = _text(value, name="factor id", allow_none=False)
        assert item is not None
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _records(
    values: Iterable[str | Mapping[str, Any]] | None,
    *,
    name: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in values or ():
        if isinstance(value, str):
            record = {"id": _text(value, name=f"{name} id", allow_none=False)}
        elif isinstance(value, Mapping):
            record = dict(value)
        else:
            raise ValueError(f"{name} entries must be strings or mappings")
        try:
            json.dumps(record, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} entries must be JSON-serializable") from exc
        records.append(record)
    return records


def _mapping(value: Mapping[str, Any] | None, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    result = dict(value)
    try:
        json.dumps(result, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    return result


def build_research_contract(
    *,
    mode: str = "explore",
    stage: str = "single_factor_evaluation",
    universe: str | None = None,
    period: str | None = None,
    factor_ids: Iterable[str] | None = None,
    lineage: Iterable[str | Mapping[str, Any]] | None = None,
    transformations: Iterable[str | Mapping[str, Any]] | None = None,
    evaluation: Mapping[str, Any] | None = None,
    locked_test: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe, extensible factor-research run summary.

    ``mode`` describes the intended evidence standard for the run.  It is
    metadata in this first contract version; enforcement belongs to a later
    policy layer so existing callers keep their current behaviour.

    ``lineage`` and ``transformations`` accept either a short string or a
    structured record.  Structured records let future stages add fields such
    as input artifact hashes, parameters or diagnostics without changing this
    top-level schema.
    """
    mode = _text(mode, name="research mode", allow_none=False)
    stage = _text(stage, name="research stage", allow_none=False)
    assert mode is not None and stage is not None
    if mode not in RESEARCH_MODES:
        raise ValueError(f"research mode must be one of {RESEARCH_MODES}, got {mode!r}")
    if stage not in RESEARCH_STAGES:
        raise ValueError(
            f"research stage must be one of {RESEARCH_STAGES}, got {stage!r}"
        )

    universe = _text(universe, name="universe")
    period = _text(period, name="period")
    factors = _ids(factor_ids)
    contract: dict[str, Any] = {
        "schema": RESEARCH_CONTRACT_SCHEMA,
        "mode": mode,
        "stage": stage,
        "universe": universe,
        "period": period,
        "factor_ids": factors,
        "factor_count": len(factors),
        "lineage": _records(lineage, name="lineage"),
        "transformations": _records(transformations, name="transformations"),
        "evaluation": _mapping(evaluation, name="evaluation"),
        "locked_test": _mapping(locked_test, name="locked_test"),
    }
    json.dumps(contract, ensure_ascii=True, allow_nan=False)
    return contract


def build_bench_research_contract(
    *,
    universe: str,
    period: str,
    factor_ids: Iterable[str],
    horizon: int,
    method: str,
    zoo: str | None = None,
    mode: str = "explore",
    stage: str = "single_factor_evaluation",
    oos_boundary: str | None = None,
    lineage: Iterable[str | Mapping[str, Any]] | None = None,
    transformations: Iterable[str | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the shared research summary used by alpha-bench entry points.

    Keeping bench-specific defaults here prevents the CLI, MCP wrapper and
    both runner implementations from drifting as the contract grows.
    """
    evaluation: dict[str, Any] = {
        "horizon": horizon,
        "forward_return_sampling": "non_overlapping" if horizon > 1 else "daily",
        "method": method,
    }
    if oos_boundary is not None:
        evaluation["oos_boundary"] = oos_boundary
    if lineage is None:
        source: dict[str, Any] = {"kind": "alpha_registry"}
        if zoo is not None:
            source["zoo"] = zoo
        lineage = [source]
    return build_research_contract(
        mode=mode,
        stage=stage,
        universe=universe,
        period=period,
        factor_ids=factor_ids,
        lineage=lineage,
        transformations=transformations,
        evaluation=evaluation,
    )
