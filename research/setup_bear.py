"""Build runs/s{1..4}_bear/ — replay 4 baseline strategies on 2021-11 ~ 2023-01 BTC bear cycle.

Steps:
1. Fetch funding (Binance ccxt) + F&G for bear range
2. For each strategy S1..S4: copy code/signal_engine.py from baseline run, write config.json,
   write factor_data parquets.

Usage:
    python research/setup_bear.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from lib.ccxt_data import fetch_funding_rate_history_ccxt  # noqa: E402
from lib.sentiment import fetch_fear_greed  # noqa: E402

BEAR_START = datetime(2021, 11, 8, tzinfo=timezone.utc)
BEAR_END = datetime(2023, 1, 1, tzinfo=timezone.utc)

START_STR = "2021-11-08"
END_STR = "2022-12-31"

STRATEGY_MAP = {
    "s1_bear": ("s1_backtest", 1.5),
    "s2_bear": ("s2_baseline", 2.0),
    "s3_bear": ("s3_baseline", 1.5),
    "s4_bear": ("s4_baseline", 1.5),
}


def fetch_factor_data() -> tuple:
    print(f"fetch funding (Binance ccxt) {BEAR_START.date()} ~ {BEAR_END.date()}")
    funding = fetch_funding_rate_history_ccxt(
        "binance", "BTC/USDT:USDT", since_dt=BEAR_START, until_dt=BEAR_END
    )
    funding.index = funding.index.tz_convert(None)
    print(f"  {len(funding)} rows, range {funding.index.min()} ~ {funding.index.max()}")

    print("fetch F&G (alternative.me, limit=2000, then slice)")
    fng = fetch_fear_greed(days=2000)
    fng.index = fng.index.tz_convert(None)
    fng = fng[["fng"]]
    bear_start_naive = BEAR_START.replace(tzinfo=None)
    bear_end_naive = BEAR_END.replace(tzinfo=None)
    fng = fng.loc[(fng.index >= bear_start_naive) & (fng.index <= bear_end_naive)]
    print(f"  {len(fng)} rows, range {fng.index.min()} ~ {fng.index.max()}")

    return funding, fng


def build_run(run_name: str, baseline_name: str, leverage: float, funding, fng) -> None:
    src = ROOT / "runs" / baseline_name
    dst = ROOT / "runs" / run_name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    (dst / "code").mkdir()
    shutil.copy(src / "code" / "signal_engine.py", dst / "code" / "signal_engine.py")

    (dst / "factor_data").mkdir()
    funding.to_parquet(dst / "factor_data" / "funding.parquet")
    fng.to_parquet(dst / "factor_data" / "fng.parquet")

    cfg = {
        "codes": ["BTC-USDT"],
        "start_date": START_STR,
        "end_date": END_STR,
        "source": "ccxt",
        "interval": "1H",
        "engine": "daily",
        "initial_cash": 1000.0,
        "leverage": leverage,
        "maker_rate": 0.0002,
        "taker_rate": 0.00055,
        "slippage": 0.0005,
        "margin_mode": "isolated",
        "benchmark": "BTC-USDT",
    }
    (dst / "config.json").write_text(json.dumps(cfg, indent=2))
    print(f"  built {dst.relative_to(ROOT)} (leverage={leverage})")


def main() -> None:
    funding, fng = fetch_factor_data()
    print()
    for run_name, (baseline, lev) in STRATEGY_MAP.items():
        build_run(run_name, baseline, lev, funding, fng)
    print("\nDone. Run each with:")
    for name in STRATEGY_MAP:
        print(f"  python -m backtest.runner runs/{name}")


if __name__ == "__main__":
    main()
