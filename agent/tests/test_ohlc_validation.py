"""Tests for the shared OHLC invariant validator and its loader wiring."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

import backtest.loaders.local_loader as local_loader
from backtest.loaders.base import validate_ohlc


def _frame(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    """Build an OHLCV frame from (open, high, low, close, volume) rows."""
    index = pd.date_range("2026-01-01", periods=len(rows), freq="D", name="trade_date")
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=index
    )


def test_validate_ohlc_drops_invariant_violations() -> None:
    """high<low, prices<=0, and high/low not bracketing open/close are dropped."""
    frame = _frame(
        [
            (10.0, 11.0, 9.0, 10.5, 1000.0),   # valid
            (10.0, 8.0, 9.0, 10.5, 1000.0),    # high < low -> invalid
            (-1.0, 11.0, 9.0, 10.5, 1000.0),   # non-positive open -> invalid
            (10.0, 10.5, 9.0, 12.0, 1000.0),   # close > high -> invalid
            (10.0, 10.0, 10.0, 10.0, 0.0),     # flat doji, zero volume -> valid
        ]
    )

    cleaned = validate_ohlc(frame)

    assert list(cleaned["close"]) == [10.5, 10.0]
    assert len(cleaned) == 2


def test_validate_ohlc_raise_strategy() -> None:
    """strategy='raise' surfaces the violation instead of silently dropping."""
    frame = _frame([(10.0, 8.0, 9.0, 10.5, 1000.0)])
    with pytest.raises(ValueError):
        validate_ohlc(frame, strategy="raise")


@pytest.mark.parametrize("allow_negative", [False, True])
@pytest.mark.parametrize(
    "prices",
    [
        (10.0, float("inf"), 9.0, 10.5),
        (float("inf"), float("inf"), 9.0, float("inf")),
        (-10.0, -9.0, float("-inf"), -10.5),
    ],
)
def test_infinite_prices_obey_validation_strategy(
    prices: tuple[float, float, float, float], allow_negative: bool,
) -> None:
    frame = _frame([(10, 11, 9, 10.5, 100), (*prices, 100)])
    cleaned = validate_ohlc(frame, allow_nonpositive_prices=allow_negative)
    assert cleaned.index.tolist() == [frame.index[0]]
    with pytest.raises(ValueError):
        validate_ohlc(frame, strategy="raise", allow_nonpositive_prices=allow_negative)
    assert validate_ohlc(
        frame, strategy="warn", allow_nonpositive_prices=allow_negative,
    ).equals(frame)


def test_local_csv_drops_infinite_high(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "infinite.csv"
    path.write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-01,10,11,9,10.5,100\n"
        "2026-01-02,10,inf,9,10.5,100\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_loader, "_load_config",
        lambda: {"sources": [{"symbol": "TEST", "type": "csv", "path": str(path)}]},
    )
    frame = local_loader.DataLoader().fetch(["TEST"], "2026-01-01", "2026-01-02")["TEST"]
    assert frame.index.tolist() == [pd.Timestamp("2026-01-01")]


def test_validate_ohlc_warn_strategy_keeps_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """strategy='warn' logs but keeps the offending rows."""
    frame = _frame([(10.0, 11.0, 9.0, 10.5, 1000.0), (10.0, 8.0, 9.0, 10.5, 1000.0)])
    with caplog.at_level(logging.WARNING, logger="backtest.loaders.base"):
        kept = validate_ohlc(frame, strategy="warn")
    assert len(kept) == 2
    assert any("ohlc" in rec.message.lower() for rec in caplog.records)


def test_validate_ohlc_passthrough_when_no_ohlc_columns() -> None:
    """A frame without OHLC columns (or empty) is returned unchanged."""
    empty = pd.DataFrame()
    assert validate_ohlc(empty).empty
    other = pd.DataFrame({"value": [1, 2, 3]})
    assert validate_ohlc(other).equals(other)


def test_local_loader_drops_dirty_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A structurally invalid bar in a local file must not reach the backtest."""
    csv_path = tmp_path / "dirty.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-01,10,11,9,10.5,1000",
                "2026-01-02,10,8,9,10.5,1500",  # high < low -> dirty
                "2026-01-03,12,13,11,12.5,1200",
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "symbol": "AAA.US",
                        "type": "csv",
                        "path": str(csv_path),
                        "columns": {
                            "date": "Date",
                            "open": "Open",
                            "high": "High",
                            "low": "Low",
                            "close": "Close",
                            "volume": "Volume",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config_path)

    frames = local_loader.DataLoader().fetch(["AAA.US"], "2026-01-01", "2026-01-03")

    df = frames["AAA.US"]
    assert list(df["close"]) == [10.5, 12.5]  # the dirty 2026-01-02 bar is gone


def test_sanitize_data_map_guards_every_source() -> None:
    """The runner's central pass drops dirty bars from any loader's frame.

    This is the catch-all boundary: a loader that never calls ``validate_ohlc``
    itself (the large majority) still cannot leak a structurally-invalid bar
    into the backtest, because every fetched map converges through here.
    """
    from backtest.runner import _sanitize_data_map

    data_map = {
        "AAA.US": _frame(
            [
                (10.0, 11.0, 9.0, 10.5, 1000.0),  # valid
                (10.0, 8.0, 9.0, 10.5, 1500.0),   # high < low -> dropped
            ]
        ),
        "BBB.US": _frame([(12.0, 13.0, 11.0, 12.5, 1200.0)]),  # all valid
    }

    cleaned = _sanitize_data_map(data_map)

    assert list(cleaned["AAA.US"]["close"]) == [10.5]  # dirty bar gone
    assert list(cleaned["BBB.US"]["close"]) == [12.5]  # untouched
    assert set(cleaned) == {"AAA.US", "BBB.US"}


@pytest.mark.parametrize("source", ["local", "auto"])
@pytest.mark.parametrize("signed_first", [False, True])
def test_backtest_keeps_signed_bars_with_separate_cache_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, signed_first: bool
) -> None:
    from backtest import runner
    from backtest.loaders import base
    from src import data_gateway
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway

    bars = _frame(
        [
            (10, 12, 9, 11, 100),
            (-10, -9, -14, -12, 100),
            (-2, 0, -3, -1, 100),  # Zero is invalid even with signed prices.
            (-2, -3, -4, -1, 100),  # High does not bracket open and close.
            (12, 14, 11, 13, 100),
        ]
    )
    csv_path = tmp_path / "prices.csv"
    bars.to_csv(csv_path)
    entry = {
        "symbol": "POWER.US",
        "type": "csv",
        "path": str(csv_path),
        "columns": {"date": "trade_date"},
    }
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"sources": [entry]})
    cache_root = tmp_path / "loader-cache"
    monkeypatch.setattr(base, "loader_cache_root", lambda: cache_root)
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    reads = []
    read_csv = local_loader._READERS["csv"]

    def counted_read(*args):
        reads.append(1)
        return read_csv(*args)

    monkeypatch.setitem(local_loader._READERS, "csv", counted_read)
    config = {
        "source": source,
        "codes": ["local:POWER.US"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-05",
    }

    def fetch(signed: bool) -> None:
        result = runner.fetch_data_map({**config, "allow_nonpositive_prices": signed})
        assert result.effective_sources == ["local"]
        expected = bars.iloc[[0, 1, 4] if signed else [0, 4]]
        actual = result.data_map["POWER.US"]
        assert actual["close"].tolist() == expected["close"].tolist()
        assert actual.index.tolist() == expected.index.tolist()

    gateway = MarketDataGateway(Config(cache_dir=tmp_path / "gateway"))
    monkeypatch.setattr(data_gateway, "_instance", gateway)
    try:
        entries = {}
        for signed in (signed_first, not signed_first):
            existing = set(cache_root.rglob("*.parquet"))
            fetch(signed)
            (entries[signed],) = set(cache_root.rglob("*.parquet")) - existing
        assert len(reads) == 2

        fetch(True)
        fetch(False)
        assert len(reads) == 2

        entries[True].write_bytes(b"invalid parquet")
        fetch(True)
        fetch(False)
        assert len(reads) == 3
    finally:
        gateway.close()


@pytest.mark.parametrize("value", ["false", "true", 1])
def test_only_json_boolean_can_enable_signed_backtests(value):
    from pydantic import ValidationError
    from backtest.runner import BacktestConfigSchema

    with pytest.raises(ValidationError, match="allow_nonpositive_prices"):
        BacktestConfigSchema(codes=["POWER.US"], start_date="2026-01-01", end_date="2026-01-02",
                             allow_nonpositive_prices=value)


def test_public_market_read_stays_strict_during_signed_backtest(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backtest.runner import fetch_data_map
    from src import data_gateway
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway
    from src.market_data import fetch_market_data

    csv_path = tmp_path / "prices.csv"
    _frame([(10, 12, 9, 11, 100), (-10, -9, -14, -12, 100)]).to_csv(csv_path)
    entry = {"type": "csv", "symbol": "POWER.US", "path": str(csv_path), "columns": {"date": "trade_date"}}
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"sources": [entry]})
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    both_reading = Barrier(2)
    read_csv = local_loader._READERS["csv"]

    def overlapping_read(*args):
        both_reading.wait(timeout=5)
        return read_csv(*args)

    gateway = MarketDataGateway(Config(cache_dir=tmp_path / "gateway"))
    monkeypatch.setattr(data_gateway, "_instance", gateway)
    config = {"source": "local", "codes": ["POWER.US"], "start_date": "2026-01-01", "end_date": "2026-01-02"}
    try:
        monkeypatch.setitem(local_loader._READERS, "csv", overlapping_read)
        with ThreadPoolExecutor(max_workers=1) as pool:
            signed = pool.submit(fetch_data_map, {**config, "allow_nonpositive_prices": True})
            public = fetch_market_data(**config, as_frames=True)
            assert signed.result(timeout=10).data_map["POWER.US"]["close"].tolist() == [11, -12]
            assert public["POWER.US"]["close"].tolist() == [11]
        monkeypatch.setitem(local_loader._READERS, "csv", read_csv)
        for options in ({}, {"allow_nonpositive_prices": "false"}):
            assert fetch_data_map({**config, **options}).data_map["POWER.US"]["close"].tolist() == [11]
    finally:
        gateway.close()


def test_backtest_price_policy_is_nested_and_restored_on_error(monkeypatch) -> None:
    from backtest import runner

    bars = _frame([(-10.0, -9.0, -14.0, -12.0, 100.0)])

    def fake_fetch_auto(codes, config, interval):
        if not config["allow_nonpositive_prices"]:
            assert validate_ohlc(bars).empty
            raise ValueError("inner failed")
        assert len(validate_ohlc(bars)) == 1
        assert validate_ohlc(bars, allow_nonpositive_prices=False).empty
        assert validate_ohlc(bars, allow_nonpositive_prices=None).empty
        with pytest.raises(ValueError, match="inner failed"):
            runner.fetch_data_map({"source": "auto", "allow_nonpositive_prices": False})
        assert len(validate_ohlc(bars)) == 1
        raise ValueError("outer failed")

    monkeypatch.setattr(runner, "_fetch_auto", fake_fetch_auto)
    with pytest.raises(ValueError, match="outer failed"):
        runner.fetch_data_map({"source": "auto", "allow_nonpositive_prices": True})
    assert validate_ohlc(bars).empty


def test_frozen_backtest_honors_explicit_price_policy(tmp_path, monkeypatch) -> None:
    import hashlib
    import json

    from backtest import runner
    from backtest.loaders.base import ohlc_price_policy

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    prices_path = tmp_path / "frozen.csv"
    manifest_path = tmp_path / "manifest.json"
    config = {
        "codes": ["POWER.US"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "frozen_data_manifest": str(manifest_path),
    }

    def write_snapshot(frame: pd.DataFrame) -> None:
        frame.to_csv(prices_path)
        entry = {
            "path": prices_path.name,
            "sha256": hashlib.sha256(prices_path.read_bytes()).hexdigest(),
        }
        manifest = {"schema_version": 1, "interval": "1D", "frames": {"POWER.US": entry}}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    signed_bars = _frame([(10, 12, 9, 11, 100), (-10, -9, -14, -12, 100)])
    write_snapshot(signed_bars)
    with ohlc_price_policy(True):
        for policy in (False, None, "false", 1):
            with pytest.raises(ValueError, match="violate OHLC"):
                runner.fetch_data_map({**config, "allow_nonpositive_prices": policy})
    result = runner.fetch_data_map({**config, "allow_nonpositive_prices": True})
    assert result.data_map["POWER.US"]["close"].tolist() == [11, -12]

    signed_bars.loc[signed_bars.index[1], "high"] = 0
    write_snapshot(signed_bars)
    with pytest.raises(ValueError, match="violate OHLC"):
        runner.fetch_data_map({**config, "allow_nonpositive_prices": True})
