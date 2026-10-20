"""VD-14 offline fixture-loadability tests (Step 1 / T1.5).

Proves the paper-trade market fixtures load fully OFFLINE, self-describe
their provenance (source / caliber / window), and that the tamper-evident
manifest matches the on-disk bytes — the same sha256 idea the repo already
uses for run cards (test_run_card.py:330-353).

This file must pass under ``pytest --disable-socket``: it starts no
network, never imports ``record_market_fixtures.py`` (a MANUAL recording
tool that lives beside the fixtures), and validates only committed bytes.

Scope honesty: the VD-14 ``cn_a`` leg (ClickHouse export) is BLOCKED on the
open ClickHouse HIL and is intentionally absent — these tests never claim
three-market fixture coverage, and no network source is substituted for it.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "market"
_MANIFEST_NAME = "MANIFEST.json"
_FIXTURE_SCHEMA = "paper_trade.market_fixture/v1"

#: The two legs VD-14 pins to a network recording source, with the identity
#: each fixture file must carry.
RECORDED_FIXTURES: dict[str, dict[str, str]] = {
    "hk_00700_tencent.json": {
        "market": "hk_equity",
        "symbol": "00700.HK",
        "source": "tencent",
        "request_url_prefix": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?",
    },
    "us_AAPL_sina.json": {
        "market": "us_equity",
        "symbol": "AAPL.US",
        "source": "sina",
        "request_url_prefix": "https://stock.finance.sina.com.cn/usstock/api/",
    },
}
SYNTHETIC_FIXTURES: dict[str, dict[str, str]] = {
    "synthetic_split_4to1.json": {"market": "us_equity", "symbol": "SYNTH-4TO1"},
    "synthetic_holiday_gap.json": {"market": "us_equity", "symbol": "SYNTH-GAP"},
}
ALL_FIXTURES = set(RECORDED_FIXTURES) | set(SYNTHETIC_FIXTURES)

_CORE_KEYS = {
    "schema",
    "market",
    "symbol",
    "source",
    "price_caliber",
    "window",
    "bars",
    "caliber_note",
}
_RECORDED_EXTRA_KEYS = {
    "volume_unit",
    "request_url",
    "request_headers",
    "recorded_at_utc",
    "drop_stats",
}
_SYNTHETIC_EXTRA_KEYS = {"volume_unit", "synthetic_construction"}
_BAR_KEYS = {"date", "open", "high", "low", "close", "volume"}
_WINDOW_START, _WINDOW_END = "2025-10-01", "2026-10-16"

#: VD-6 frozen split-detector thresholds: {2, 3, 4, 5, 10, 3:2} and their
#: reciprocals.  Pinned here verbatim from the plan; the detector (Step 4)
#: must read the same set.
_FROZEN_SPLIT_RATIOS = [
    2.0,
    3.0,
    4.0,
    5.0,
    10.0,
    1.5,
    1 / 2,
    1 / 3,
    1 / 4,
    1 / 5,
    2 / 3,
]

_US_CALIBER_NOTE_SUBSTRING = (
    "raw / unadjusted — no split scaling applied by the source; a "
    "close-to-close read across the 2020-08-31 4:1 ex-date reads ~0.2585"
)


def _load(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_manifest() -> dict[str, Any]:
    return _load(_MANIFEST_NAME)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_iso_date(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_fixture_file_exists(name: str) -> None:
    assert (_FIXTURE_DIR / name).is_file(), f"missing committed fixture {name}"


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_fixture_parses_with_documented_keys(name: str) -> None:
    doc = _load(name)
    expected = _CORE_KEYS | (_RECORDED_EXTRA_KEYS if name in RECORDED_FIXTURES else _SYNTHETIC_EXTRA_KEYS)
    missing = expected - doc.keys()
    assert not missing, f"{name}: missing documented keys {sorted(missing)}"
    assert doc["schema"] == _FIXTURE_SCHEMA
    identity = RECORDED_FIXTURES.get(name) or SYNTHETIC_FIXTURES[name]
    assert doc["market"] == identity["market"]
    assert doc["symbol"] == identity["symbol"]
    if name in RECORDED_FIXTURES:
        assert doc["source"] == identity["source"]
        assert doc["request_url"].startswith(identity["request_url_prefix"])
        assert doc["recorded_at_utc"].endswith("Z")
        assert doc["price_caliber"] == "raw"
        assert doc["window"] == {"start": _WINDOW_START, "end": _WINDOW_END}
    else:
        assert doc["source"] == "synthetic"
        assert isinstance(doc["synthetic_construction"], str) and doc["synthetic_construction"]


@pytest.mark.parametrize("name", sorted(ALL_FIXTURES))
def test_bars_sorted_unique_and_ohlc_sane(name: str) -> None:
    doc = _load(name)
    bars = doc["bars"]
    assert bars, f"{name}: fixture must carry at least one bar"
    window = doc["window"]
    dates = [bar["date"] for bar in bars]
    assert all(_valid_iso_date(d) for d in dates)
    assert dates == sorted(dates), f"{name}: bars are not ascending by date"
    assert len(set(dates)) == len(dates), f"{name}: duplicate bar dates"
    assert window["start"] <= dates[0] and dates[-1] <= window["end"]
    for bar in bars:
        assert set(bar) == _BAR_KEYS, f"{name} {bar.get('date')}: unexpected bar keys"
        op, hi, lo, cl = (bar["open"], bar["high"], bar["low"], bar["close"])
        assert all(_is_number(v) for v in (op, hi, lo, cl, bar["volume"]))
        assert all(math.isfinite(v) for v in (op, hi, lo, cl, bar["volume"]))
        assert min(op, hi, lo, cl) > 0, f"{name} {bar['date']}: non-positive OHLC"
        assert hi >= max(op, cl, lo), f"{name} {bar['date']}: high violates OHLC bracket"
        assert lo <= min(op, cl, hi), f"{name} {bar['date']}: low violates OHLC bracket"
        assert _is_number(bar["volume"]) and bar["volume"] >= 0


def test_recorded_window_ends_on_last_completed_trade_date() -> None:
    for name in RECORDED_FIXTURES:
        bars = _load(name)["bars"]
        assert bars[-1]["date"] == _WINDOW_END, f"{name}: does not end on {_WINDOW_END}"


def test_recorded_drop_stats_are_clean() -> None:
    for name in RECORDED_FIXTURES:
        stats = _load(name)["drop_stats"]
        assert stats["dropped_dirty_ohlc"] == 0, f"{name}: recorded series had dirty bars dropped"
        assert stats["dropped_duplicate_dates"] == 0, f"{name}: recorded series had duplicate dates"
        assert stats["dropped_unparseable"] == 0, f"{name}: wire rows failed to parse"
        assert stats["wire_rows"] >= len(_load(name)["bars"])


def test_sina_window_clip_is_the_only_drop_on_the_us_leg() -> None:
    stats = _load("us_AAPL_sina.json")["drop_stats"]
    # sina serves the full history with no window parameter; the clip is the
    # one expected reduction, matching sina_loader.py:115-118.
    assert stats["dropped_out_of_window"] == stats["wire_rows"] - len(_load("us_AAPL_sina.json")["bars"])


def test_us_fixture_documents_the_raw_unadjusted_caliber() -> None:
    doc = _load("us_AAPL_sina.json")
    assert doc["price_caliber"] == "raw"
    assert _US_CALIBER_NOTE_SUBSTRING in doc["caliber_note"]
    manifest_entry = next(f for f in _load_manifest()["fixtures"] if f["file"] == "us_AAPL_sina.json")
    assert _US_CALIBER_NOTE_SUBSTRING in manifest_entry["caliber_note"]
    assert doc["volume_unit"] is None, "sina declares no volume unit (sina_loader has no volume_units)"


def test_hk_fixture_declares_share_volume_units_and_raw_caliber() -> None:
    doc = _load("hk_00700_tencent.json")
    assert doc["price_caliber"] == "raw"
    assert doc["volume_unit"] == "shares"
    assert "day" in doc["caliber_note"] and "qfq" in doc["caliber_note"]


def test_manifest_covers_exactly_the_fixture_files() -> None:
    manifest = _load_manifest()
    files = {entry["file"] for entry in manifest["fixtures"]}
    on_disk = {p.name for p in _FIXTURE_DIR.glob("*.json") if p.name != _MANIFEST_NAME}
    assert files == on_disk == ALL_FIXTURES


def test_manifest_sha256_bytes_and_counts_match_reality() -> None:
    manifest = _load_manifest()
    assert manifest["schema"] == "paper_trade.market_manifest/v1"
    for entry in manifest["fixtures"]:
        path = _FIXTURE_DIR / entry["file"]
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert entry["sha256"] == digest, f"{entry['file']}: manifest sha256 drifted from bytes"
        assert entry["bytes"] == len(raw)
        doc = json.loads(raw)
        assert entry["rows"] == len(doc["bars"])
        assert entry["first_date"] == doc["bars"][0]["date"]
        assert entry["last_date"] == doc["bars"][-1]["date"]
        assert entry["market"] == doc["market"]
        assert entry["symbol"] == doc["symbol"]


def test_manifest_recorded_entries_carry_full_provenance() -> None:
    for name, identity in RECORDED_FIXTURES.items():
        entry = next(f for f in _load_manifest()["fixtures"] if f["file"] == name)
        assert entry["request_url"] == _load(name)["request_url"]
        assert entry["window"] == {"start": _WINDOW_START, "end": _WINDOW_END}
        assert entry["recorded_at_utc"] == _load(name)["recorded_at_utc"]
        assert entry["source"] == identity["source"]
        assert entry["price_caliber"] == "raw"


def test_split_fixture_contains_one_frozen_ratio_break() -> None:
    bars = _load("synthetic_split_4to1.json")["bars"]
    hits = []
    for i in range(1, len(bars)):
        ratio = bars[i]["close"] / bars[i - 1]["close"]
        for threshold in _FROZEN_SPLIT_RATIOS:
            if math.isclose(ratio, threshold, rel_tol=1e-12):
                hits.append((i, ratio))
                break
    assert len(hits) == 1, f"synthetic split fixture must contain exactly one frozen-ratio break, got {hits}"
    index, ratio = hits[0]
    assert ratio == 0.25, "the single break must be the clean 4:1 split (close ratio exactly 0.25)"
    vol_ratio = bars[index]["volume"] / bars[index - 1]["volume"]
    assert vol_ratio >= 2.0, "split break needs a same-direction volume multiple for VD-6 confirmation"
    event = _load("synthetic_split_4to1.json")["split_event"]
    assert event["ex_date"] == bars[index]["date"]
    assert event["bar_index"] == index
    assert event["close_before"] == bars[index - 1]["close"]
    assert event["close_after"] == bars[index]["close"]


def test_split_fixture_keeps_the_event_inside_a_K120_lookback_edge() -> None:
    # VD-6/B3: the fetch window is [from_date - K trading days, to_date];
    # 120 bars after the ex-date put the event exactly at the K=120 edge.
    doc = _load("synthetic_split_4to1.json")
    assert doc["split_event"]["bars_after_ex"] == 120
    assert len(doc["bars"]) == doc["split_event"]["bar_index"] + 121


def test_holiday_gap_fixture_gaps_match_bars() -> None:
    doc = _load("synthetic_holiday_gap.json")
    bars = doc["bars"]
    dates = [bar["date"] for bar in bars]
    samples = doc["gap_samples"]
    assert len(samples) >= 2, "fixture must carry at least two gap samples"
    assert any(len(s["missing_weekdays"]) >= 3 for s in samples), "one gap must be multi-day"
    for sample in samples:
        after, resume = sample["after_date"], sample["resume_date"]
        assert after in dates and resume in dates
        between = [d for d in dates if after < d < resume]
        assert not between, f"{sample['label']}: bars leaked into the authored gap {after}..{resume}"
        expected = [d for d in _weekdays_between(after, resume) if d not in dates]
        assert sorted(expected) == sorted(sample["missing_weekdays"])


def _weekdays_between(start: str, end: str) -> list[str]:
    """Weekday dates strictly between two ISO dates (gap audit helper)."""
    day = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    out: list[str] = []
    day = date.fromordinal(day.toordinal() + 1)
    while day < stop:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day = date.fromordinal(day.toordinal() + 1)
    return out
