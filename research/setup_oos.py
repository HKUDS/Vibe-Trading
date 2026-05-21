"""Out-of-sample walk-forward — v2 ensemble on never-trained regimes.

Periods:
- covid_altbull: 2020-01-01 ~ 2021-10-31 (covid crash + alt-bull, BTC 7k→4k→65k)
- post_ftx:     2023-01-01 ~ 2024-05-13 (post-FTX recovery / chop)

For each period: build base + stress run. v2 engine (w=48, h=2).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from lib.ccxt_data import fetch_funding_rate_history_ccxt  # noqa: E402
from lib.sentiment import fetch_fear_greed  # noqa: E402

TEMPLATE = ROOT / "runs" / "_templates" / "signal_engine_ensemble_v2.py"
REGIME_PARQUET = ROOT / "research" / "regime_labels.parquet"
STRESS_MULT = 3.0

PERIODS = [
    ("covid_altbull", datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2021, 10, 31, tzinfo=timezone.utc), "2020-01-01", "2021-10-30"),
    ("post_ftx",      datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2024, 5, 13, tzinfo=timezone.utc), "2023-01-01", "2024-05-12"),
]


def fetch_period(start_dt: datetime, end_dt: datetime) -> tuple:
    print(f"  funding (Binance) {start_dt.date()} ~ {end_dt.date()}")
    fund = fetch_funding_rate_history_ccxt("binance", "BTC/USDT:USDT", since_dt=start_dt, until_dt=end_dt)
    fund.index = fund.index.tz_convert(None)
    print(f"    {len(fund)} rows, range {fund.index.min()} ~ {fund.index.max()}")

    fng = fetch_fear_greed(days=3500)
    fng.index = fng.index.tz_convert(None)
    fng = fng[["fng"]]
    s = start_dt.replace(tzinfo=None)
    e = end_dt.replace(tzinfo=None)
    fng = fng.loc[(fng.index >= s) & (fng.index <= e)]
    print(f"    F&G {len(fng)} rows")
    return fund, fng


def build(period_name, start_str, end_str, fund, fng, regime_full, stress=False):
    suffix = "_stress" if stress else ""
    dst = ROOT / "runs" / f"oos_{period_name}{suffix}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / "code").mkdir()
    shutil.copy(TEMPLATE, dst / "code" / "signal_engine.py")
    (dst / "factor_data").mkdir()
    fund.to_parquet(dst / "factor_data" / "funding.parquet")
    fng.to_parquet(dst / "factor_data" / "fng.parquet")
    rg = regime_full.loc[start_str:end_str][["regime"]]
    rg.to_parquet(dst / "factor_data" / "regime.parquet")

    cfg = {
        "codes": ["BTC-USDT"],
        "start_date": start_str,
        "end_date": end_str,
        "source": "ccxt",
        "interval": "1H",
        "engine": "daily",
        "initial_cash": 1000.0,
        "leverage": 1.5,
        "maker_rate": 0.0002,
        "taker_rate": 0.00055,
        "slippage": 0.0005,
        "margin_mode": "isolated",
        "benchmark": "BTC-USDT",
    }
    if stress:
        cfg["maker_rate"] = round(cfg["maker_rate"] * STRESS_MULT, 6)
        cfg["taker_rate"] = round(cfg["taker_rate"] * STRESS_MULT, 6)
        cfg["slippage"] = round(cfg["slippage"] * STRESS_MULT, 6)
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    bear_pct = (rg['regime'] == 'bear').mean() * 100
    print(f"  built {dst.relative_to(ROOT)}  bear%={bear_pct:.1f} stress={stress}")


def main():
    regime = pd.read_parquet(REGIME_PARQUET)
    for name, sd, ed, ss, es in PERIODS:
        print(f"\n=== {name} ===")
        fund, fng = fetch_period(sd, ed)
        build(name, ss, es, fund, fng, regime, stress=False)
        build(name, ss, es, fund, fng, regime, stress=True)


if __name__ == "__main__":
    main()
