#!/usr/bin/env python3
"""Record the real-market paper-trade fixtures (VD-14, Step 1 / T1.5).

MANUAL RECORDING TOOL — NEVER IMPORT OR EXECUTE THIS FROM A TEST.

The repository's unit-test discipline for the paper-trade suite is 单测禁网
(plan VD-14): tests only read frozen fixture files.  This script is the one
documented place where those files are produced: it performs live HTTP
fetches against the two sources the plan pins (hk_equity = tencent,
us_equity = sina), snapshots the upstream reply into a byte-stable JSON
fixture, and rebuilds ``market/MANIFEST.json`` (sha256 tamper-evidence over
every recorded fixture, synthetic ones included).

Contract with the consumers:

* Numbers are preserved exactly as the wire served them — parse ``float``
  from the source string, no rescale, no rounding, no "fixing" of the raw
  (unadjusted) US series.  The raw caliber is the whole point of the T7
  split-detection fixture (registry.py:296, live-confirmed 2026-10-18).
* Bars are sorted ascending, dates unique; a dirty bar (failed the OHLC
  bracket check) or a duplicate date is DROPPED WITH A WARNING and counted
  in ``drop_stats`` — never silently.
* Output is deterministic given the same upstream payload: fixed key order
  (plain dict insertion order), ``json.dumps(indent=2, ensure_ascii=False)``
  plus a trailing newline, written via temp file + atomic ``os.replace``.
* Existing fixtures are never silently overwritten: re-recording requires
  an explicit ``--force``.

The ``cn_a`` leg of VD-14 is NOT handled here and must never be sourced
from the network: it is pinned to a ClickHouse export.  The ClickHouse
instance (``172.24.165.51:8123``) is private-VPC-only and currently
unreachable (open HIL), so that leg stays blocked — see the plan Step 1.

Usage (manual, from the repository root):

    conda run -n legonanobot python \
        agent/tests/fixtures/paper_trade/record_market_fixtures.py --force
    conda run -n legonanobot python \
        agent/tests/fixtures/paper_trade/record_market_fixtures.py --manifest-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FIXTURE_SCHEMA = "paper_trade.market_fixture/v1"
MANIFEST_SCHEMA = "paper_trade.market_manifest/v1"

#: Recording window frozen by the T1.5 task: a full year ending on the last
#: completed trade date observed by the Step 0 lanes (2026-10-16, Friday).
WINDOW_START = "2025-10-01"
WINDOW_END = "2026-10-16"

LOG = logging.getLogger("record_market_fixtures")

_HERE = Path(__file__).resolve().parent

# JSONP scaffolding, identical to backtest/loaders/sina_loader.py:41.
_JSONP_ARRAY_RE = re.compile(r"(\[.*\])", re.DOTALL)

_US_CALIBER_NOTE = (
    "raw / unadjusted — no split scaling applied by the source; a "
    "close-to-close read across the 2020-08-31 4:1 ex-date reads ~0.2585. "
    "Pinned by registry.py PRICE_CALIBER_BY_SOURCE['sina']='raw' and "
    "live-confirmed 2026-10-18 (STEP0-LANE-A A1/A2); the recorded window "
    "itself does not contain that ex-date."
)
_HK_CALIBER_NOTE = (
    "raw — Tencent serves no adjusted HK series: the fqkline reply carries "
    "only 'day' (never 'qfqday', #1493 / registry.py ('tencent',hk_equity)="
    "'raw'), so the ',qfq' request parameter changes nothing. Row layout is "
    "[date, open, close, high, low, volume]; a 7th event-dict element is "
    "ignored exactly like tencent_loader.py:206-217 (parses 6 fields)."
)


def _utcnow_iso() -> str:
    """Second-resolution UTC stamp for ``recorded_at_utc`` (manual tool only)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(url: str, headers: dict[str, str]) -> str:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _parse_tencent_rows(text: str, symbol_key: str) -> list[dict[str, Any]]:
    """Return raw bars from a Tencent fqkline reply, loader-faithful.

    Mirrors tencent_loader.py: ``qfqday or day`` key selection and the
    6-field row layout ``[date, open, close, high, low, volume]``; anything
    past the sixth field (e.g. a buy-back event dict) is ignored.
    """
    data = json.loads(text)
    if data.get("code") not in (0, None) and not data.get("data"):
        raise ValueError(f"tencent fqkline error reply: code={data.get('code')}")
    stock_data = data.get("data") or {}
    block = stock_data.get(symbol_key) or {}
    klines = block.get("qfqday") or block.get("day")
    if not klines:
        raise ValueError(f"tencent reply carries no day/qfqday rows for {symbol_key}")
    rows: list[dict[str, Any]] = []
    for k in klines:
        if not isinstance(k, (list, tuple)) or len(k) < 6:
            rows.append({"date": None})
            continue
        rows.append(
            {
                "date": str(k[0]),
                "open": k[1],
                "high": k[3],
                "low": k[4],
                "close": k[2],
                "volume": k[5],
            }
        )
    return rows


def _parse_sina_bars(text: str) -> list[dict[str, Any]]:
    """Return raw bars from the sina JSONP reply (d/o/h/l/c/v; 'a' ignored)."""
    match = _JSONP_ARRAY_RE.search(text.strip())
    if not match:
        raise ValueError("no JSON array found in Sina JSONP response")
    payload = json.loads(match.group(1))
    if not isinstance(payload, list):
        raise ValueError("Sina JSONP payload is not a list of bars")
    rows: list[dict[str, Any]] = []
    for bar in payload:
        if not isinstance(bar, dict) or not all(f in bar for f in ("d", "o", "h", "l", "c", "v")):
            rows.append({"date": None})
            continue
        rows.append(
            {
                "date": str(bar["d"]),
                "open": bar["o"],
                "high": bar["h"],
                "low": bar["l"],
                "close": bar["c"],
                "volume": bar["v"],
            }
        )
    return rows


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(
    raw_rows: list[dict[str, Any]], start_date: str, end_date: str, label: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Clip to the window, dedup dates, drop dirty bars — each with a warning.

    Returns ``(bars, drop_stats)``; ``bars`` is ascending by date with unique
    dates and every bar passes ``high >= max(o,c,l)`` / ``low <= min(o,c,h)``
    with strictly positive, finite OHLC prices.
    """
    stats = {
        "wire_rows": len(raw_rows),
        "dropped_unparseable": 0,
        "dropped_out_of_window": 0,
        "dropped_duplicate_dates": 0,
        "dropped_dirty_ohlc": 0,
    }
    by_date: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        date = row.get("date")
        values = {k: _to_float(row.get(k)) for k in ("open", "high", "low", "close", "volume")}
        if not date or any(v is None for v in values.values()):
            stats["dropped_unparseable"] += 1
            LOG.warning("%s: dropped unparseable wire row %r", label, row)
            continue
        if not (start_date <= date <= end_date):
            stats["dropped_out_of_window"] += 1
            continue
        op, hi, lo, cl = values["open"], values["high"], values["low"], values["close"]
        finite = all(math.isfinite(v) for v in (op, hi, lo, cl, values["volume"]))
        if not finite or min(op, hi, lo, cl) <= 0 or hi < max(op, cl, lo) or lo > min(op, cl, hi):
            stats["dropped_dirty_ohlc"] += 1
            LOG.warning("%s: dropped dirty bar %s (o,h,l,c=%s)", label, date, (op, hi, lo, cl))
            continue
        if date in by_date:
            stats["dropped_duplicate_dates"] += 1
            LOG.warning("%s: dropped duplicate date %s (keeping first)", label, date)
            continue
        by_date[date] = {
            "date": date,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": values["volume"],
        }
    bars = [by_date[date] for date in sorted(by_date)]
    return bars, stats


#: The two legs VD-14 pins to a network source (cn_a is NOT here: it is a
#: ClickHouse export, blocked on the HIL — never substitute a network source).
SPECS: tuple[dict[str, Any], ...] = (
    {
        "file": "hk_00700_tencent.json",
        "market": "hk_equity",
        "symbol": "00700.HK",
        "source": "tencent",
        "price_caliber": "raw",
        "volume_unit": "shares",
        "volume_unit_note": (
            "tencent_loader.py:70 volume_units: a_share=lots, hk_equity=shares"
        ),
        "request_url": (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk00700,"
            f"day,{WINDOW_START},{WINDOW_END},500,qfq"
        ),
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://web.ifzq.gtimg.cn/",
        },
        "parser": lambda text: _parse_tencent_rows(text, "hk00700"),
        "window_note": (
            "single request: the window holds fewer than the 500-bar page cap,"
            " and Tencent honours the start clamp for such windows"
            " (tencent_loader.py:36-42)."
        ),
        "caliber_note": _HK_CALIBER_NOTE,
    },
    {
        "file": "us_AAPL_sina.json",
        "market": "us_equity",
        "symbol": "AAPL.US",
        "source": "sina",
        "price_caliber": "raw",
        "volume_unit": None,
        "volume_unit_note": (
            "the sina loader declares no volume_units; US bars carry "
            "volume_unit=None (sina_loader.py has no such class attribute)"
        ),
        "request_url": (
            "https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
            "var%20x=/US_MinKService.getDailyK?symbol=AAPL"
        ),
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://stock.finance.sina.com.cn/",
        },
        "parser": _parse_sina_bars,
        "window_note": (
            "sina serves the full history (1984-09-07 onward) with no window "
            "parameter; bars are clipped to the window at record time, the "
            "same clip as sina_loader.py:115-118."
        ),
        "caliber_note": _US_CALIBER_NOTE,
    },
)


def _write_atomic(path: Path, document: dict[str, Any]) -> None:
    payload = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        # mkstemp creates 0600; fixtures are normal readable data files.
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def record_spec(spec: dict[str, Any], market_dir: Path, force: bool) -> Optional[Path]:
    path = market_dir / spec["file"]
    if path.exists() and not force:
        LOG.info("exists, skipping (use --force to re-record): %s", path.name)
        return None
    text = _http_get(spec["request_url"], spec["headers"])
    raw_rows: list[dict[str, Any]] = spec["parser"](text)
    bars, stats = _normalize(raw_rows, WINDOW_START, WINDOW_END, spec["file"])
    if not bars:
        raise RuntimeError(f"{spec['file']}: upstream produced no usable bars")
    fixture: dict[str, Any] = {
        "schema": FIXTURE_SCHEMA,
        "market": spec["market"],
        "symbol": spec["symbol"],
        "source": spec["source"],
        "price_caliber": spec["price_caliber"],
        "volume_unit": spec["volume_unit"],
        "volume_unit_note": spec["volume_unit_note"],
        "request_url": spec["request_url"],
        "request_headers": spec["headers"],
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "window_note": spec["window_note"],
        "recorded_at_utc": _utcnow_iso(),
        "caliber_note": spec["caliber_note"],
        "drop_stats": stats,
        "bars": bars,
    }
    _write_atomic(path, fixture)
    LOG.info("wrote %s: %d bars %s..%s", path.name, len(bars), bars[0]["date"], bars[-1]["date"])
    return path


def build_manifest(market_dir: Path) -> Path:
    """Recompute MANIFEST.json from the fixture files on disk (byte hashes)."""
    entries: list[dict[str, Any]] = []
    for path in sorted(market_dir.glob("*.json")):
        if path.name == "MANIFEST.json":
            continue
        raw = path.read_bytes()
        document: dict[str, Any] = json.loads(raw)
        bars: list[dict[str, Any]] = document.get("bars", [])
        entries.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "rows": len(bars),
                "first_date": bars[0]["date"] if bars else None,
                "last_date": bars[-1]["date"] if bars else None,
                "market": document.get("market"),
                "symbol": document.get("symbol"),
                "source": document.get("source"),
                "price_caliber": document.get("price_caliber"),
                "volume_unit": document.get("volume_unit"),
                "request_url": document.get("request_url"),
                "window": document.get("window"),
                "recorded_at_utc": document.get("recorded_at_utc"),
                "drop_stats": document.get("drop_stats"),
                "caliber_note": document.get("caliber_note"),
                "construction": document.get("synthetic_construction"),
            }
        )
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generator": "record_market_fixtures.py (manual tool; tests never run it)",
        "description": (
            "Tamper-evident index over agent/tests/fixtures/paper_trade/market/*.json."
            " sha256 is of the exact on-disk bytes; test_paper_trade_fixtures.py"
            " re-verifies them. Recorded fixtures are byte-frozen snapshots of the"
            " listed request_url replies (VD-14); synthetic fixtures are authored,"
            " engine-facing inputs for T7/T5, and their construction is documented"
            " per file."
        ),
        "fixtures": entries,
    }
    path = market_dir / "MANIFEST.json"
    _write_atomic(path, manifest)
    LOG.info("rebuilt %s over %d fixtures", path.name, len(entries))
    return path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--market-dir",
        type=Path,
        default=_HERE / "market",
        help="fixture directory (default: ./market next to this script)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-record and overwrite existing real fixtures (needs live network)",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="skip all HTTP; only rebuild MANIFEST.json from the files on disk",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    market_dir: Path = args.market_dir
    market_dir.mkdir(parents=True, exist_ok=True)

    if not args.manifest_only:
        for spec in SPECS:
            record_spec(spec, market_dir, args.force)

    build_manifest(market_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
