"""HSI panel assembly using shared data loaders and explicit provenance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

# Shared gateway requests have finite deadlines; a 95-symbol sequential
# provider job can exhaust one before returning any bars. Keep each acquisition
# small, preserving the existing provider/fallback contract and quantities.
PRICE_BATCH_SIZE = 5


def load_hsi_panel(
    start: str,
    end: str,
    *,
    constituents_loader: Callable,
    wide_builder: Callable,
    retry: Callable,
    min_sector_coverage: float,
) -> dict[str, Any]:
    """Build an observed-date HSI panel without changing provider quantities.

    Args:
        start: First requested ISO date, inclusive.
        end: Last requested ISO date, inclusive.
        constituents_loader: Strict, validated current-membership loader.
        wide_builder: Shared wide-panel builder from the benchmark orchestrator.
        retry: Shared bounded retry helper.
        min_sector_coverage: Minimum fraction with source sector labels.

    Returns:
        OHLCV frames and metadata disclosing source/coverage limitations.

    Raises:
        ValueError: Conflicting symbol-alias histories were returned.
        RuntimeError: Fewer than two stocks have observed closing prices.
    """
    from src.tools.hsi_universe import normalize_hk_symbol
    from backtest.loaders.registry import FALLBACK_CHAINS, resolve_loader
    from src.market_data import fetch_market_data
    from src.tools.hsi_metadata import canonical_symbol_metadata, provenance_summary

    codes, sectors, metadata = constituents_loader()
    codes = list(dict.fromkeys(normalize_hk_symbol(code) for code in codes))
    sectors = {normalize_hk_symbol(code): label for code, label in sectors.items()}
    loader = resolve_loader("hk_equity")
    response = {}
    for offset in range(0, len(codes), PRICE_BATCH_SIZE):
        batch = codes[offset : offset + PRICE_BATCH_SIZE]
        part = (
            retry(
                lambda batch=batch: fetch_market_data(
                    codes=batch,
                    start_date=start,
                    end_date=end,
                    source=loader.name,
                    max_fallback_attempts=len(FALLBACK_CHAINS["hk_equity"]),
                    include_provenance=True,
                    as_frames=True,
                )
            )
            or {}
        )
        for key, value in part.items():
            if key in {"_provenance", "_diagnostics"} and isinstance(value, dict):
                response.setdefault(key, {}).update(value)
            elif not str(key).startswith("_"):
                if key in response and isinstance(value, pd.DataFrame) and not response[key].equals(value):
                    raise ValueError("Conflicting HSI frames across acquisition batches")
                response[key] = value
    fetched, chosen_aliases = {}, {}
    for code, frame in response.items():
        if str(code).startswith("_") or not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        canonical = normalize_hk_symbol(code)
        if canonical in codes:
            bounded = frame.loc[start:end]
            if canonical in fetched and not fetched[canonical].equals(bounded):
                raise ValueError(f"Conflicting HSI price frames for aliases of {canonical}")
            if canonical not in fetched:
                fetched[canonical] = bounded
                chosen_aliases[canonical] = str(code)
    fetched = {
        code: frame
        for code, frame in fetched.items()
        if not frame.empty and "close" in frame and frame["close"].notna().any()
    }
    if len(fetched) < 2:
        raise RuntimeError("HSI prices unavailable: fewer than two instruments with observed close prices")
    raw_provenance = response.get("_provenance", {})
    provenance, provenance_conflicts = canonical_symbol_metadata(raw_provenance, codes, chosen_aliases)
    diagnostics, diagnostic_conflicts = canonical_symbol_metadata(
        response.get("_diagnostics", {}), codes, chosen_aliases, diagnostics=True
    )
    panel = wide_builder(fetched, include_amount=False)
    if all(key in panel for key in ("open", "high", "low", "close")):
        panel["vwap"] = sum(panel[key] for key in ("open", "high", "low", "close")) / 4.0
    coverage = 0.0
    if "close" in panel and len(panel["close"].columns):
        close = panel["close"]
        labels = [sectors.get(code, "") for code in close.columns]
        coverage = sum(bool(label) for label in labels) / len(labels)
        if coverage >= min_sector_coverage:
            panel["sector"] = pd.DataFrame(
                np.repeat(
                    np.array([label or "UNKNOWN" for label in labels], dtype=object)[None, :],
                    len(close.index),
                    axis=0,
                ),
                index=close.index,
                columns=close.columns,
            )
    panel["_meta"] = metadata | {
        "universe": "hsi",
        "hsi_metadata_version": 4,
        "universe_tag": "equity_hk",
        "currency": "HKD",
        "exchange_timezone": "Asia/Hong_Kong",
        "calendar": "XHKG",
        "calendar_policy": "provider-observed daily dates; no calendar reindex or fabricated bars",
        "survivorship_bias": True,
        "pit_membership": False,
        "point_in_time_membership": False,
        "missing_observations": {
            field: int(frame.isna().sum().sum())
            for field, frame in panel.items()
            if isinstance(frame, pd.DataFrame) and field != "sector"
        },
        "missing_observation_policy": "count missing cells on provider-observed union of dates; not absent whole sessions",
        "degraded": bool(metadata.get("degraded") or provenance_conflicts or len(fetched) != len(codes)),
        "price_coverage": len(fetched) / len(codes) if codes else 0,
        "requested_instruments": len(codes),
        "fetched_instruments": len(fetched),
        "missing_instruments": sorted(set(codes) - set(fetched)),
        "constituent_count": len(codes),
        "data_diagnostics": diagnostics,
        "raw_data_diagnostics": response.get("_diagnostics", {}),
        "diagnostic_alias_conflicts": diagnostic_conflicts,
        "price_provenance": provenance,
        "raw_price_provenance": raw_provenance,
        "provenance_alias_conflicts": provenance_conflicts,
        "price_sources": sorted(
            {value["source"] for code, value in provenance.items() if code in fetched and value.get("source")}
        ),
        **provenance_summary(fetched, provenance),
        "missing_data_policy": (
            "HSI panel outer-joins observed provider dates without filling cells; "
            "shared upstream adapters may already drop incomplete OHLC or fill missing volume with zero"
        ),
        "vwap_method": "OHLC arithmetic mean proxy; not traded VWAP",
        "sector_source": ("Wikipedia sector/industry/sub-index" if "sector" in panel else None),
        "sector_coverage": round(coverage, 4),
        "sector_coverage_threshold": min_sector_coverage,
        "sector_note": (
            "Current source-table labels, not harmonized with GICS/NSE classifications; "
            "omitted below the HSI coverage threshold."
        ),
    }
    return panel
