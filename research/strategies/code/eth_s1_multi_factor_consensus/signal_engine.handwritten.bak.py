# manual: do-not-overwrite
"""ETH multi-factor consensus signal engine.

Implements strategy_eth_s1_multi_factor_consensus.yaml:
  - Indicators: funding_rate_contrarian (z_30d of OKX 8h funding),
                basis_contrarian (z_30d of OKX perp hourly close)
  - Long entry:  both 90d-percentile <= 20, 2 of last 3 bars
  - Short entry: both 90d-percentile >= 80, 2 of last 3 bars
  - Invalidation: both percentiles inside [40,60] band -> flat
  - Smoothing: sma_3 on each factor before percentile
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _ensure_research_on_syspath() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    research_dir = repo_root / "research"
    sp = str(research_dir)
    if sp not in sys.path:
        sys.path.insert(0, sp)


def _z_30d(s: pd.Series) -> pd.Series:
    mu = s.rolling(90).mean()
    sd = s.rolling(90).std().replace(0, np.nan)
    return (s - mu) / sd


def _factor_series(code: str, df: pd.DataFrame) -> pd.DataFrame:
    """Compute funding_z and basis_z aligned to df index (hourly)."""
    _ensure_research_on_syspath()
    from lib.okx_data import fetch_funding_history

    idx = df.index
    if idx.tz is not None:
        idx_naive = idx.tz_convert("UTC").tz_localize(None)
    else:
        idx_naive = idx

    start = idx_naive.min()
    now = pd.Timestamp.utcnow().tz_localize(None) if pd.Timestamp.utcnow().tzinfo else pd.Timestamp.utcnow()
    days = max(int((now - start).days) + 120, 850)

    funding = fetch_funding_history(code, days)
    if isinstance(funding.index, pd.DatetimeIndex) and funding.index.tz is not None:
        funding.index = funding.index.tz_convert("UTC").tz_localize(None)
    if "time" in funding.columns:
        funding = funding.set_index("time")
        if funding.index.tz is not None:
            funding.index = funding.index.tz_convert("UTC").tz_localize(None)
    funding = funding.sort_index()
    funding_z = _z_30d(funding["funding_rate"]).reindex(idx_naive, method="ffill")

    close = df["close"].copy()
    close.index = idx_naive
    basis_raw = close.astype(float)
    basis_z = _z_30d(basis_raw)

    out = pd.DataFrame({"funding_z": funding_z.values, "basis_z": basis_z.values}, index=idx)
    return out


class SignalEngine:
    def generate(self, data_map):
        signals = {}
        for code, df in data_map.items():
            if not isinstance(df, pd.DataFrame) or df.empty or "close" not in df.columns:
                continue
            try:
                factors = _factor_series(code, df)
            except Exception as exc:
                print(f"[signal_engine] factor compute failed for {code}: {exc}")
                signals[code] = pd.Series(0.0, index=df.index)
                continue

            f_sm = factors["funding_z"].rolling(3, min_periods=1).mean()
            b_sm = factors["basis_z"].rolling(3, min_periods=1).mean()

            window = 90 * 24
            f_pct = f_sm.rolling(window, min_periods=window // 2).rank(pct=True) * 100.0
            b_pct = b_sm.rolling(window, min_periods=window // 2).rank(pct=True) * 100.0

            long_cond = (f_pct <= 20) & (b_pct <= 20)
            short_cond = (f_pct >= 80) & (b_pct >= 80)
            mid = f_pct.between(40, 60) & b_pct.between(40, 60)

            long_persist = long_cond.rolling(3).sum() >= 2
            short_persist = short_cond.rolling(3).sum() >= 2

            event = pd.Series(np.nan, index=df.index)
            event = event.mask(long_persist, 1.0)
            event = event.mask(short_persist, -1.0)
            event = event.mask(mid, 0.0)

            state = event.ffill().fillna(0.0)
            signals[code] = state

            n_long = int((state == 1.0).sum())
            n_short = int((state == -1.0).sum())
            print(f"[signal_engine] {code}: long_bars={n_long} short_bars={n_short} total_bars={len(state)}")

        return signals
