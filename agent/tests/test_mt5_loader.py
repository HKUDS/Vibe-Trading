"""MT5 backtest data loader tests (Windows-only SDK, faked here).

The real ``MetaTrader5`` package never installs on CI's ubuntu runner; the
loader lazy-imports it, so tests inject a fake module via ``sys.modules`` and
exercise symbol resolution, interval mapping, the frame contract, config
plumbing, and graceful degradation (init failure → unavailable → registry
fallback engages).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import backtest.loaders.mt5_loader as mt5_loader
from backtest.loaders.mt5_loader import DataLoader, _to_query_base

pytestmark = pytest.mark.unit


_RATES_DTYPE = [
    ("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
    ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i4"), ("real_volume", "<i8"),
]

#: 2026-06-02 00:00 UTC and the next two days, hourly-ish spacing irrelevant.
_T0 = 1_780_358_400


def _rates(*rows: tuple) -> np.ndarray:
    return np.array(list(rows), dtype=_RATES_DTYPE)


def _default_rates() -> np.ndarray:
    return _rates(
        (_T0, 1.07, 1.09, 1.06, 1.08, 1200, 6, 0),
        (_T0 + 86_400, 1.08, 1.10, 1.07, 1.09, 1300, 6, 0),
        (_T0 + 2 * 86_400, 1.09, 1.11, 1.08, 1.10, 1400, 6, 0),
    )


class _FakeMT5Module:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408

    def __init__(self) -> None:
        self.initialize_result = True
        self.initialize_calls: list[dict[str, Any]] = []
        self.symbol_names = ["EURUSDm", "EURUSDz", "XAUUSDm", "USDJPYm"]
        self.rates: dict[str, np.ndarray | None] = {}
        self.rates_calls: list[tuple[str, int, Any, Any]] = []

    def initialize(self, *args: Any, **kwargs: Any) -> bool:
        self.initialize_calls.append({"args": args, "kwargs": kwargs})
        return self.initialize_result

    def shutdown(self) -> None:  # pragma: no cover - not called by the loader
        pass

    def last_error(self) -> tuple[int, str]:
        return (-6, "Terminal: Authorization failed") if not self.initialize_result else (1, "Success")

    def symbol_info(self, name: str) -> Any:
        return SimpleNamespace(name=name) if name in self.symbol_names else None

    def symbol_select(self, name: str, enable: bool = True) -> bool:
        return name in self.symbol_names

    def symbols_get(self, group: str | None = None) -> tuple:
        if not group:
            return tuple(SimpleNamespace(name=n) for n in self.symbol_names)
        prefix = group.strip("*").upper()
        return tuple(SimpleNamespace(name=n) for n in self.symbol_names if n.upper().startswith(prefix))

    def copy_rates_range(self, name: str, timeframe: int, date_from: Any, date_to: Any):
        self.rates_calls.append((name, timeframe, date_from, date_to))
        return self.rates.get(name)


@pytest.fixture
def fake_mod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _FakeMT5Module:
    fake = _FakeMT5Module()
    fake.rates["EURUSDm"] = _default_rates()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setattr(mt5_loader, "_MT5_CONFIG_PATH", tmp_path / "mt5.json")
    monkeypatch.setattr(mt5_loader, "_init_state", None)
    monkeypatch.setattr(mt5_loader, "_symbol_cache", {})
    return fake


# --------------------------------------------------------------------------- #
# Symbol normalization + resolution                                            #
# --------------------------------------------------------------------------- #


class TestQueryBase:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("EUR/USD", "EURUSD"),
            ("EURUSD.FX", "EURUSD"),
            ("XAU/USD", "XAUUSD"),
            ("eurusd", "EURUSD"),
            ("EURUSDm", "EURUSDM"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert _to_query_base(raw) == expected


class TestResolution:
    def test_suffix_discovery_prefers_shortest_then_alpha(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        frames = loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10")
        # EURUSDm and EURUSDz both match EURUSD*; deterministic pick is EURUSDm.
        assert fake_mod.rates_calls[0][0] == "EURUSDm"
        assert "EUR/USD" in frames

    def test_exact_symbol_wins_over_suffix(self, fake_mod: _FakeMT5Module) -> None:
        fake_mod.symbol_names.append("EURUSD")
        fake_mod.rates["EURUSD"] = _default_rates()
        loader = DataLoader()
        loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10")
        assert fake_mod.rates_calls[0][0] == "EURUSD"

    def test_raw_broker_symbol_passes_through(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        loader.fetch(["EURUSDm"], "2026-06-01", "2026-06-10")
        assert fake_mod.rates_calls[0][0] == "EURUSDm"

    def test_unresolvable_symbol_skipped_without_raise(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        frames = loader.fetch(["NZD/CAD", "EUR/USD"], "2026-06-01", "2026-06-10")
        assert "NZD/CAD" not in frames
        assert "EUR/USD" in frames  # one bad symbol never poisons the batch


# --------------------------------------------------------------------------- #
# Intervals + frame contract                                                   #
# --------------------------------------------------------------------------- #


class TestIntervalsAndFrames:
    def test_interval_mapping(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10", interval="1H")
        assert fake_mod.rates_calls[-1][1] == _FakeMT5Module.TIMEFRAME_H1

    def test_lowercase_1h_maps_to_h1_not_daily(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10", interval="1h")
        assert fake_mod.rates_calls[-1][1] == _FakeMT5Module.TIMEFRAME_H1

    def test_unknown_interval_is_rejected_not_rewritten_to_daily(
        self, fake_mod: _FakeMT5Module
    ) -> None:
        loader = DataLoader()
        before = len(fake_mod.rates_calls)
        frames = loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10", interval="7z")
        assert frames == {}
        assert len(fake_mod.rates_calls) == before

    def test_frame_contract(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        frames = loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10")
        frame = frames["EUR/USD"]  # keyed by the ORIGINAL input code
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.name == "trade_date"
        assert frame["volume"].tolist() == [1200, 1300, 1400]  # tick_volume
        assert frame["close"].iloc[-1] == pytest.approx(1.10)

    def test_range_clipped(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        frames = loader.fetch(["EUR/USD"], "2026-06-02", "2026-06-03")
        # Third bar (2026-06-04) falls outside the requested end date.
        assert len(frames["EUR/USD"]) == 2

    def test_tz_aware_range_passed_to_terminal(self, fake_mod: _FakeMT5Module) -> None:
        loader = DataLoader()
        loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10")
        _, _, date_from, date_to = fake_mod.rates_calls[-1]
        # Naive datetimes get shifted by local tz inside the MT5 API.
        assert date_from.tzinfo is not None
        assert date_to.tzinfo is not None
        assert date_to > date_from


# --------------------------------------------------------------------------- #
# Availability + config                                                        #
# --------------------------------------------------------------------------- #


class TestAvailability:
    def test_available_when_initialized(self, fake_mod: _FakeMT5Module) -> None:
        assert DataLoader().is_available() is True

    def test_init_failure_negative_cached(self, fake_mod: _FakeMT5Module) -> None:
        fake_mod.initialize_result = False
        loader = DataLoader()
        assert loader.is_available() is False
        assert loader.fetch(["EUR/USD"], "2026-06-01", "2026-06-10") == {}
        assert loader.is_available() is False
        assert len(fake_mod.initialize_calls) == 1  # one attempt per process

    def test_missing_package_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "MetaTrader5", None)
        monkeypatch.setattr(mt5_loader, "_init_state", None)
        assert DataLoader().is_available() is False

    def test_config_file_feeds_initialize(
        self, fake_mod: _FakeMT5Module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "mt5.json"
        config.write_text(
            json.dumps({"login": 12345, "password": "pw", "server": "Exness-MT5Trial8"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(mt5_loader, "_MT5_CONFIG_PATH", config)
        DataLoader().is_available()
        kwargs = fake_mod.initialize_calls[0]["kwargs"]
        assert kwargs["login"] == 12345
        assert kwargs["server"] == "Exness-MT5Trial8"

    def test_no_config_attaches_bare(self, fake_mod: _FakeMT5Module) -> None:
        DataLoader().is_available()
        call = fake_mod.initialize_calls[0]
        assert call["args"] == ()
        assert "login" not in call["kwargs"]


# --------------------------------------------------------------------------- #
# Registry + routing                                                           #
# --------------------------------------------------------------------------- #


class TestRegistryWiring:
    def test_mt5_in_valid_sources(self) -> None:
        from backtest.loaders.registry import VALID_SOURCES

        assert "mt5" in VALID_SOURCES

    def test_mt5_registered(self) -> None:
        from backtest.loaders.registry import LOADER_REGISTRY, _ensure_registered

        _ensure_registered()
        assert "mt5" in LOADER_REGISTRY

    def test_mt5_heads_forex_chain(self) -> None:
        from backtest.loaders.registry import FALLBACK_CHAINS

        assert FALLBACK_CHAINS["forex"][0] == "mt5"
        assert "akshare" in FALLBACK_CHAINS["forex"]  # degradation path intact

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("EUR/USD", "mt5"),
            ("XAU/USD", "mt5"),
            ("EURUSD.FX", "mt5"),
            ("XAUUSD.FX", "mt5"),
            ("BTC-USDT", "okx"),  # unchanged
            ("ETH/USDT", "ccxt"),  # 4-letter quote must not match the forex rule
        ],
    )
    def test_detect_source_forex(self, code: str, expected: str) -> None:
        from src.market_data import detect_source

        assert detect_source(code) == expected
