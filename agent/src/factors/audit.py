"""Reproducible factor contract checks, separate from return-performance claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.factors.registry import Registry, RegistryError, SkipAlpha


def reference_panel(bars: int = 1200, symbols: int = 24) -> dict[str, pd.DataFrame]:
    """Build deterministic synthetic inputs; no market data or network is used.

    Args:
        bars: Number of ordered observations.
        symbols: Cross-section size.

    Returns:
        Aligned price, sector, fundamental, valuation and factor-return frames.
    """
    rng = np.random.default_rng(2177)
    index = pd.bdate_range("2020-01-01", periods=bars)
    columns = [f"S{i}" for i in range(symbols)]
    shape = (bars, symbols)

    def frame(values):
        return pd.DataFrame(values, index=index, columns=columns)

    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, shape), axis=0))
    opening = close * np.exp(rng.normal(0, 0.005, shape))
    high = np.maximum(close, opening) * (1 + rng.uniform(0, 0.01, shape))
    low = np.minimum(close, opening) * (1 - rng.uniform(0, 0.01, shape))
    panel = {
        "close": frame(close),
        "open": frame(opening),
        "high": frame(high),
        "low": frame(low),
        "volume": frame(rng.uniform(1e5, 1e6, shape)),
        "vwap": frame((high + low + 2 * close) / 4),
    }
    panel["amount"] = panel["vwap"] * panel["volume"]
    panel["sector"] = frame(np.tile(np.arange(symbols) % 3, (bars, 1)))
    registry = Registry()
    for identifier in registry.list():
        meta = registry.get(identifier).meta
        for name in meta.get("columns_required", []) + meta.get("extras_required", []):
            if name not in panel:
                panel[name] = frame(
                    rng.normal(0, 0.01, shape) if name in {"mkt_ret", "smb", "hml"} else rng.uniform(0.5, 1.5, shape)
                )
    return panel


def audit_factors(alpha_ids: list[str] | None = None) -> dict:
    """Check source pins, reconciled minimum history and actual output eligibility.

    This is a synthetic implementation-contract audit, not a backtest or a
    certification that every published formula has an unambiguous definition.
    Source pins deliberately fail when a factor changes without reconciliation.

    Args:
        alpha_ids: Optional subset; by default every registered alpha is checked.

    Returns:
        Per-factor findings, initialization policy and versioned source hashes.
    """
    registry = Registry()
    contracts_path = Path(__file__).with_name("warmup_contracts.json")
    document = json.loads(contracts_path.read_text())
    contracts = document["contracts"]
    operators_changed = (
        hashlib.sha256(Path(__file__).with_name("base.py").read_bytes()).hexdigest() != document["operators_sha256"]
    )
    identifiers = list(dict.fromkeys(alpha_ids or registry.list()))
    for identifier in identifiers:
        registry.get(identifier)
    panel = reference_panel()
    rows = []
    for identifier in identifiers:
        meta = registry.get(identifier).meta
        source = registry.get_source(identifier)
        contract = contracts.get(identifier)
        findings = []
        if operators_changed:
            findings.append("shared operator source changed since contract reconciliation")
        if contract is None:
            findings.append("source has no reconciled contract")
            contract = {"minimum_bars": meta["min_warmup_bars"], "policy": "full_window", "basis": "unreviewed"}
        if hashlib.sha256(source.encode()).hexdigest() != contract.get("source_sha256"):
            findings.append("source changed since contract reconciliation")
        if meta["min_warmup_bars"] != contract["minimum_bars"]:
            findings.append("metadata and minimum-history contract disagree")
        observed = None
        try:
            out = registry.compute(identifier, panel)
            finite = np.isfinite(out.to_numpy(dtype=float))
            first = np.flatnonzero(finite.any(axis=1))
            observed = int(first[0] + 1) if len(first) else None
            if finite[: max(0, contract["minimum_bars"] - 1)].any():
                findings.append("an ineligible warmup output can enter factor analysis")
            if observed is None:
                findings.append("no finite output on the reference panel")
        except (ValueError, RuntimeError, RegistryError, SkipAlpha) as exc:
            findings.append(str(exc))
        rows.append(
            {
                "id": identifier,
                "minimum_bars": contract["minimum_bars"],
                "policy": contract["policy"],
                "basis": contract["basis"],
                "first_observed_bar": observed,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "valid": not findings,
                "findings": findings,
                "notes": meta.get("notes", ""),
            }
        )
    return {
        "kind": "factor_audit",
        "schema_version": 1,
        "count": len(rows),
        "finding_count": sum(not row["valid"] for row in rows),
        "rows": rows,
        "data_kind": "deterministic_synthetic",
        "reference_bars": len(panel["close"]),
        "scope": "Source and history contracts plus executable output checks; not a return-performance or complete formula-equivalence claim.",
        "contract_sha256": hashlib.sha256(contracts_path.read_bytes()).hexdigest(),
    }
