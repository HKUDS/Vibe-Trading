"""Validate regime detector v0 labels across bull / bear2022 / bear2018 periods.

Fetches BTC daily spot (Binance) + multi-source funding, computes regime, prints
distribution per period.

Usage:
    python research/regime_validate.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from lib.ccxt_data import fetch_ohlcv_ccxt, fetch_funding_rate_history_ccxt  # noqa: E402
from lib.regime import compute_regime, daily_close_from_hourly  # noqa: E402

PERIODS = {
    "bear2018": ("2018-02-01", "2018-12-30"),
    "bear2022": ("2021-11-08", "2022-12-31"),
    "bull2024_26": ("2024-05-14", "2026-05-13"),
}


def fetch_btc_daily_extended() -> pd.Series:
    print("fetch BTC/USDT daily (Binance spot, from 2017-08)")
    days = (datetime.now(timezone.utc) - datetime(2017, 8, 17, tzinfo=timezone.utc)).days + 1
    df = fetch_ohlcv_ccxt("binance", "BTC/USDT", days=days, timeframe="1d")
    df.index = df.index.tz_convert(None)
    print(f"  {len(df)} daily bars, {df.index.min().date()} ~ {df.index.max().date()}")
    return df["close"]


def fetch_funding_merged() -> pd.Series:
    """BitMEX (2016+) for pre-2019, Binance (2019-09+) after. Use union."""
    print("fetch funding BitMEX (since 2017-01)")
    fr_bm = fetch_funding_rate_history_ccxt(
        "bitmex",
        "BTC/USD:BTC",
        since_dt=datetime(2017, 1, 1, tzinfo=timezone.utc),
        until_dt=datetime(2019, 9, 8, tzinfo=timezone.utc),
    )
    fr_bm.index = fr_bm.index.tz_convert(None)

    print("fetch funding Binance (since 2019-09)")
    fr_bn = fetch_funding_rate_history_ccxt(
        "binance",
        "BTC/USDT:USDT",
        since_dt=datetime(2019, 9, 8, tzinfo=timezone.utc),
        until_dt=datetime.now(timezone.utc),
    )
    fr_bn.index = fr_bn.index.tz_convert(None)

    merged = pd.concat([fr_bm["funding_rate"], fr_bn["funding_rate"]]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    print(f"  merged {len(merged)} rows, {merged.index.min()} ~ {merged.index.max()}")
    return merged


def main() -> None:
    close = fetch_btc_daily_extended()
    funding = fetch_funding_merged()

    regime_v0 = compute_regime(
        close,
        funding_rate=funding,
        ema_window=100,
        slope_window=20,
        funding_window_hours=30 * 24,
    )
    regime_v1 = compute_regime(
        close,
        funding_rate=funding,
        ema_window=100,
        slope_window=20,
        funding_window_hours=30 * 24,
        bear_persistence_days=20,
        bear_persistence_threshold=0.55,
    )

    def dist(rg, name):
        print(f"\n[{name}] regime distribution per period:")
        print(f"{'period':14s}  {'days':>5s}  {'bull%':>6s}  {'bear%':>6s}  {'neutral%':>9s}  HODL%")
        for pname, (s, e) in PERIODS.items():
            sub = rg.loc[s:e]
            if sub.empty:
                continue
            counts = sub["regime"].value_counts(normalize=True) * 100
            bull = counts.get("bull", 0.0)
            bear = counts.get("bear", 0.0)
            neutral = counts.get("neutral", 0.0)
            c0 = close.loc[s:e].iloc[0]
            c1 = close.loc[s:e].iloc[-1]
            hodl = (c1 / c0 - 1) * 100
            print(f"{pname:14s}  {len(sub):>5d}  {bull:>5.1f}%  {bear:>5.1f}%  {neutral:>8.1f}%  {hodl:+.1f}%")

    dist(regime_v0, "v0")
    dist(regime_v1, "v1 (bear_persistence=30d, threshold=83%)")

    regime_df = regime_v1

    out = ROOT / "research" / "regime_labels.parquet"
    regime_df.to_parquet(out)
    print(f"\nSaved v1 labels → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
