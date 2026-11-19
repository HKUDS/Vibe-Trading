"""Historical FX valuation and dated HK board-lot input, without network calls.

FX observations are local currency units per USD. `close_at` and `available_at`
are separate UTC instants: a previous close cannot be used before publication.
Callers acquire daily USD/HKD (e.g. HKD=X) through the shared market-data layer
and retain its provenance; this module never treats today's display FX as history.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import numpy as np
import pandas as pd


# IRD historical rates, then the 2023-11-17 restoration of 0.1% on EACH note:
# https://www.ird.gov.hk/eng/pdf/sd_stock_rates.pdf
# https://www.ird.gov.hk/eng/ppr/archives/23111501.htm
# HKEX: round duty UP to a whole HK dollar on both buyer and seller:
# https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-(Hong-Kong)/Trading/Transaction?sc_lang=en
# Exemptions and non-HKD counters require their own declared policy; this is
# the ordinary HKD-equity contract, not a complete historical fee certification.
def hk_stamp_duty(size, price, timestamp=None, *, rate_override=None) -> float:
    """Return bilateral, per-note duty, optionally using an explicit run override.

    An undated direct engine call retains the current 0.1% default. Actual
    backtest fills carry their session timestamp. The dated default is supported
    from 2001-09-01; earlier runs must supply a researched explicit override.
    """
    if rate_override is None:
        rate = Decimal("0.001")
        if timestamp is not None:
            stamp = pd.Timestamp(timestamp)
            if pd.isna(stamp):
                raise ValueError("HK duty requires a valid session date")
            day = (
                stamp.tz_convert("Asia/Hong_Kong").date()
                if stamp.tzinfo
                else stamp.date()
            )
            if day < date(2001, 9, 1):
                raise ValueError(
                    "HK duty before 2001-09-01 requires an explicit rate override"
                )
            if date(2021, 8, 1) <= day < date(2023, 11, 17):
                rate = Decimal("0.0013")
    else:
        rate = Decimal(str(rate_override))
    quantity, px = Decimal(str(size)), Decimal(str(price))
    if not all(value.is_finite() and value >= 0 for value in (quantity, px, rate)):
        raise ValueError("HK duty inputs must be finite and nonnegative")
    return float((quantity * px * rate).to_integral_value(rounding=ROUND_CEILING))


def load_hk_board_lots(path: str | Path) -> tuple[dict[str, int], dict]:
    """Read an explicitly supplied dated HKEX CSV; reject aliases/conflicts/gaps.

    This input is a current snapshot unless separately evidenced historical
    validity is supplied. Retrieval time is not an effective-from date.
    """
    from backtest.engines.global_equity import _hk_lot_key

    lots, retrieved, sources, hashes = {}, set(), set(), set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = _hk_lot_key(row["symbol"])
            lot = int(row["board_lot"])
            if (
                not symbol.endswith(".HK")
                or not symbol[:-3].isdigit()
                or not 0 < int(symbol[:-3]) < 100000
                or lot <= 0
            ):
                raise ValueError("Invalid HK board-lot record")
            if symbol in lots:
                raise ValueError(f"Duplicate HK board-lot instrument: {symbol}")
            if (
                not row.get("pulled_at")
                or not row.get("source")
                or not row.get("source_sha256")
            ):
                raise ValueError(
                    "HK board lots require retrieval time, source URL and source hash"
                )
            lots[symbol] = lot
            retrieved.add(row["pulled_at"])
            sources.add(row["source"])
            hashes.add(row["source_sha256"])
    if not lots or len(retrieved) != 1 or len(sources) != 1 or len(hashes) != 1:
        raise ValueError(
            "HK board-lot CSV must contain one coherent dated source snapshot"
        )
    return lots, {
        "retrieved_at": retrieved.pop(),
        "source": sources.pop(),
        "source_sha256": hashes.pop(),
        "historical_lots_verified": False,
    }


def previous_close_fx(
    valuation_times, observations: pd.DataFrame, *, max_age="7D"
) -> pd.DataFrame:
    """Select the last available FX CLOSE strictly before each valuation instant.

    Required columns: close_at, available_at (timezone-aware), rate (>0).
    Future/unpublished rates never participate. Missing/stale observations fail
    closed rather than backfill. The returned timestamps make each choice auditable.
    """
    instants = pd.DatetimeIndex(valuation_times)
    if (
        instants.tz is None
        or instants.hasnans
        or instants.has_duplicates
        or not instants.is_monotonic_increasing
    ):
        raise ValueError(
            "Valuation instants must be unique, increasing and timezone-aware"
        )
    quotes = observations.copy()
    if quotes.empty:
        raise ValueError("No FX close observations")
    for field in ("close_at", "available_at"):
        parsed = pd.DatetimeIndex(quotes[field])
        if parsed.tz is None or parsed.hasnans:
            raise ValueError(f"FX {field} must be timezone-aware")
        quotes[field] = parsed.tz_convert("UTC")
    quotes["rate"] = pd.to_numeric(quotes["rate"], errors="raise")
    if not np.isfinite(quotes["rate"]).all() or (quotes["rate"] <= 0).any():
        raise ValueError("FX rates must be finite and positive")
    if (
        quotes["close_at"].duplicated().any()
        or (quotes["available_at"] < quotes["close_at"]).any()
    ):
        raise ValueError(
            "FX closes must be unique and cannot be available before their close"
        )
    age_limit = pd.Timedelta(max_age)
    if pd.isna(age_limit) or age_limit <= pd.Timedelta(0):
        raise ValueError("FX maximum age must be positive")
    result = []
    for at in instants.tz_convert("UTC"):
        known = quotes[
            (quotes["close_at"] < at) & (quotes["available_at"] < at)
        ].sort_values("close_at")
        if known.empty or at - known.iloc[-1]["close_at"] > age_limit:
            raise ValueError(f"Missing or stale prior FX close at {at.isoformat()}")
        result.append(known.iloc[-1][["rate", "close_at", "available_at"]].to_dict())
    return pd.DataFrame(result, index=instants)


def local_and_usd_returns(
    local_values: pd.Series, observations: pd.DataFrame, *, max_age="7D"
) -> pd.DataFrame:
    """Report local and unhedged USD returns from the same portfolio value path.

    Divide by local-currency-per-USD before computing pct_change. No cashbook,
    hedge implementation, FX forward fill or daily-return addition is implied.
    """
    if not np.isfinite(local_values).all() or (local_values <= 0).any():
        raise ValueError("Portfolio values must be finite and positive")
    selected = previous_close_fx(local_values.index, observations, max_age=max_age)
    values_usd = local_values / selected["rate"]
    return selected.assign(
        value_local=local_values,
        value_usd=values_usd,
        return_local=local_values.pct_change(fill_method=None),
        return_usd=values_usd.pct_change(fill_method=None),
    )
