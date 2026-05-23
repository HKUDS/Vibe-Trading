"""Build runs/s{1..4}_bear2018/ — out-of-sample bear cycle validation (2018-02 ~ 2018-12).

Why 2018-02 start: alternative.me F&G launched 2018-02-01.
Why BitMEX funding: Binance perp launched 2019-09; BitMEX XBTUSD has funding since 2016.

Caveats vs other runs:
- Funding from BitMEX (inverse, BTC-margined) instead of Binance (USDT-margined). Magnitudes
  comparable; percentile-based signal logic robust to exchange differences.
- OHLCV from Binance spot BTC/USDT (perp didn't exist in 2018).
- BitMEX funding interval: 8h at 04/12/20 UTC vs Binance 00/08/16 UTC. Rolling-window
  percentile logic in signal_engines is schedule-agnostic.

Usage:
    python research/setup_bear2018.py
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
from pipeline.config import load_config  # noqa: E402

BEAR_START = datetime(2018, 2, 1, tzinfo=timezone.utc)
BEAR_END = datetime(2018, 12, 31, tzinfo=timezone.utc)

START_STR = "2018-02-01"
END_STR = "2018-12-30"

STRATEGY_MAP = {
    "s1_bear2018": ("s1_backtest", 1.5),
    "s2_bear2018": ("s2_baseline", 2.0),
    "s3_bear2018": ("s3_baseline", 1.5),
    "s4_bear2018": ("s4_baseline", 1.5),
}


def fetch_factor_data() -> tuple:
    print(f"fetch funding (BitMEX XBTUSD) {BEAR_START.date()} ~ {BEAR_END.date()}")
    funding = fetch_funding_rate_history_ccxt(
        "bitmex", "BTC/USD:BTC", since_dt=BEAR_START, until_dt=BEAR_END
    )
    funding.index = funding.index.tz_convert(None)
    print(f"  {len(funding)} rows, range {funding.index.min()} ~ {funding.index.max()}")

    print("fetch F&G (alternative.me)")
    fng = fetch_fear_greed(days=3500)
    fng.index = fng.index.tz_convert(None)
    fng = fng[["fng"]]
    s = BEAR_START.replace(tzinfo=None)
    e = BEAR_END.replace(tzinfo=None)
    fng = fng.loc[(fng.index >= s) & (fng.index <= e)]
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

    fees = load_config().fees
    cfg = {
        "codes": ["BTC-USDT"],
        "start_date": START_STR,
        "end_date": END_STR,
        "source": "ccxt",
        "interval": "1H",
        "engine": "daily",
        "initial_cash": 1000.0,
        "leverage": leverage,
        "maker_rate": fees.maker_rate,
        "taker_rate": fees.taker_rate,
        "slippage": fees.slippage,
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
