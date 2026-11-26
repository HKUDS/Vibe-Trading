"""Canonical HK metadata without silently changing price or quantity values."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from typing import Any

from src.tools.hsi_universe import normalize_hk_symbol


def canonical_symbol_metadata(
    values: object,
    requested: Collection[str],
    preferred: Mapping[str, str],
    *,
    diagnostics: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return canonical records and preserved alias conflicts for requested stocks.

    An exact metadata entry for the alias that supplied the selected frame wins.
    Otherwise, only a single or identical set of alias entries is unambiguous.
    All conflicting entries remain visible; unknown provenance is never guessed.

    Args:
        values: Provider metadata keyed by potentially aliased symbols.
        requested: Canonical securities included in the request.
        preferred: The actual source alias chosen for each price frame.
        diagnostics: Retain all alias diagnostic entries when available.

    Returns:
        Canonical metadata and a separate mapping of conflicting aliases.
    """
    groups = {}
    if not isinstance(values, Mapping):
        return {}, {}
    for alias, value in values.items():
        try:
            code = normalize_hk_symbol(alias)
        except ValueError:
            continue
        if code in requested:
            groups.setdefault(code, {})[str(alias)] = value
    result, conflicts = {}, {}
    for code, entries in groups.items():
        fingerprints = {json.dumps(value, sort_keys=True, default=str) for value in entries.values()}
        conflict = len(fingerprints) > 1
        chosen = preferred.get(code)
        if chosen in entries:
            value = entries[chosen]
        elif not conflict:
            value = next(iter(entries.values()))
        else:
            value = {}
        record = dict(value) if isinstance(value, Mapping) else {"raw_value": value}
        if conflict:
            conflicts[code] = entries
            record["alias_metadata_conflict"] = True
        if diagnostics and len(entries) > 1:
            record["alias_diagnostics"] = entries
        result[code] = record
    return result, conflicts


def provenance_summary(codes: Collection[str], provenance: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Disclose provider-native adjustment/volume bases without transforming bars.

    Args:
        codes: Canonical securities with observed price frames.
        provenance: Canonical provider metadata for those securities.

    Returns:
        Adjustment/unit identities and explicit review warnings.
    """
    adjustments = {code: provenance.get(code, {}).get("adjustment") or "unknown" for code in codes}
    units = {code: provenance.get(code, {}).get("volume_unit") for code in codes}
    warnings = []
    if len(set(adjustments.values())) > 1:
        warnings.append("Price adjustment bases differ between instruments.")
    if any(value != "split_dividend" for value in adjustments.values()):
        warnings.append(
            "At least one price series is not declared split/dividend adjusted; "
            "returns and cross-market comparisons need adjustment-basis review."
        )
    if any(value != "shares" for value in units.values()):
        warnings.append(
            "At least one volume unit is unknown or not declared in shares; "
            "no board-lot multiplier or implicit unit conversion was applied."
        )
    return {
        "price_adjustment_policy": "provider-native; not harmonized by HSI loader",
        "price_adjustments": adjustments,
        "mixed_price_adjustments": len(set(adjustments.values())) > 1,
        "volume_units": units,
        "volume_normalization": "none; preserve declared provider quantities",
        "data_quality_warnings": warnings,
    }
