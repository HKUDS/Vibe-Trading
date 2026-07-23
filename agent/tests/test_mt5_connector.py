"""MetaTrader 5 connector tests (Exness-style brokers, Windows-only SDK).

Mirrors ``test_sdk_connectors.py`` conventions: the real ``MetaTrader5``
package is never imported (it does not install on CI's ubuntu runner) — every
test drives the connector through a ``FakeMT5`` namespace injected at the
single ``_client._require_mt5`` seam. Symbol classification is pure and needs
no fake at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.live.mandate.model import AssetClass, InstrumentType
from src.trading.connectors.mt5.symbols import (
    classify_mt5_symbol,
    is_forex_pair,
    normalize_base,
    split_suffix,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# FakeMT5 — stands in for the Windows-only MetaTrader5 package                 #
# --------------------------------------------------------------------------- #


def _symbol(
    name: str,
    *,
    base: str,
    profit: str,
    contract_size: float = 100_000.0,
    volume_min: float = 0.01,
    volume_max: float = 100.0,
    volume_step: float = 0.01,
    filling_mode: int = 3,  # FOK|IOC bitmask
    spread: int = 6,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        currency_base=base,
        currency_profit=profit,
        trade_contract_size=contract_size,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
        filling_mode=filling_mode,
        spread=spread,
    )


class FakeMT5:
    """Configurable in-memory stand-in exposing the MetaTrader5 module surface."""

    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_REMOVE = 8
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_TIME_DAY = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408
    TIMEFRAME_W1 = 32769
    TIMEFRAME_MN1 = 49153

    def __init__(self) -> None:
        self.initialize_result = True
        self.initialize_calls: list[dict[str, Any]] = []
        self.shutdown_calls = 0
        self.account = SimpleNamespace(
            login=12345,
            trade_mode=self.ACCOUNT_TRADE_MODE_DEMO,
            balance=10_000.0,
            equity=10_050.0,
            margin=120.0,
            margin_free=9_930.0,
            margin_level=8375.0,
            leverage=200,
            currency="USD",
            server="Exness-MT5Trial8",
            name="Demo User",
        )
        self.symbols: dict[str, SimpleNamespace] = {
            "EURUSDm": _symbol("EURUSDm", base="EUR", profit="USD"),
            "USDJPYm": _symbol("USDJPYm", base="USD", profit="JPY"),
            "EURJPYm": _symbol("EURJPYm", base="EUR", profit="JPY"),
            "XAUUSDm": _symbol("XAUUSDm", base="XAU", profit="USD", contract_size=100.0),
        }
        self.ticks: dict[str, SimpleNamespace] = {
            "EURUSDm": SimpleNamespace(bid=1.0799, ask=1.0801, last=0.0, time=1_750_000_000),
            "USDJPYm": SimpleNamespace(bid=156.10, ask=156.14, last=0.0, time=1_750_000_000),
            "XAUUSDm": SimpleNamespace(bid=2399.5, ask=2400.5, last=0.0, time=1_750_000_000),
        }
        self.positions: list[SimpleNamespace] = []
        self.pending_orders: list[SimpleNamespace] = []
        self.deals: list[SimpleNamespace] = []
        self.rates: dict[str, list[dict[str, Any]]] = {}
        self.rates_calls: list[tuple[str, int, int, int]] = []
        self.order_check_requests: list[dict[str, Any]] = []
        self.order_check_result: Any = SimpleNamespace(retcode=0, comment="ok")
        self.order_send_requests: list[dict[str, Any]] = []
        self.order_send_result: Any = SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=424242,
            deal=515151,
            volume=0.05,
            price=1.0801,
            comment="done",
        )
        self.last_error_value: tuple[int, str] = (1, "Success")

    # -- lifecycle ----------------------------------------------------------
    def initialize(self, *args: Any, **kwargs: Any) -> bool:
        self.initialize_calls.append({"args": args, "kwargs": kwargs})
        return self.initialize_result

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def last_error(self) -> tuple[int, str]:
        return self.last_error_value

    # -- account/reads ------------------------------------------------------
    def account_info(self) -> Any:
        return self.account

    def positions_get(self, ticket: int | None = None, **_: Any) -> tuple | None:
        rows = self.positions
        if ticket is not None:
            rows = [p for p in rows if p.ticket == ticket]
        return tuple(rows)

    def orders_get(self, ticket: int | None = None, **_: Any) -> tuple | None:
        rows = self.pending_orders
        if ticket is not None:
            rows = [o for o in rows if o.ticket == ticket]
        return tuple(rows)

    def history_deals_get(self, *_args: Any, **_kwargs: Any) -> tuple:
        return tuple(self.deals)

    def symbol_info(self, name: str) -> Any:
        return self.symbols.get(name)

    def symbol_info_tick(self, name: str) -> Any:
        return self.ticks.get(name)

    def symbol_select(self, name: str, enable: bool = True) -> bool:
        return name in self.symbols

    def symbols_get(self, group: str | None = None) -> tuple:
        if not group:
            return tuple(self.symbols.values())
        prefix = group.strip("*")
        return tuple(info for name, info in self.symbols.items() if name.upper().startswith(prefix.upper()))

    def copy_rates_from_pos(self, name: str, timeframe: int, start: int, count: int):
        self.rates_calls.append((name, timeframe, start, count))
        return self.rates.get(name)

    # -- orders --------------------------------------------------------------
    def order_check(self, request: dict[str, Any]) -> Any:
        self.order_check_requests.append(dict(request))
        return self.order_check_result

    def order_send(self, request: dict[str, Any]) -> Any:
        self.order_send_requests.append(dict(request))
        return self.order_send_result


@pytest.fixture
def fake_mt5(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeMT5:
    from src.trading.connectors.mt5 import _client

    fake = FakeMT5()
    monkeypatch.setattr(_client, "_require_mt5", lambda: fake)
    monkeypatch.setattr(_client, "get_runtime_root", lambda: tmp_path)
    return fake


def _paper_config(**extra: Any):
    from src.trading.connectors.mt5._client import MT5Config

    payload: dict[str, Any] = {
        "login": 12345,
        "password": "hunter2secret",
        "server": "Exness-MT5Trial8",
        "symbol_suffix": "m",
        "profile": "paper",
    }
    payload.update(extra)
    return MT5Config.from_mapping(payload)


# --------------------------------------------------------------------------- #
# Pure symbol classification (no SDK)                                          #
# --------------------------------------------------------------------------- #


class TestNormalizeBase:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("EUR/USD", "EURUSD"),
            ("eur-usd", "EURUSD"),
            ("EUR USD", "EURUSD"),
            ("EURUSD.FX", "EURUSD"),
            ("eurusd", "EURUSD"),
            ("XAU/USD", "XAUUSD"),
            ("EURUSDm", "EURUSDM"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_base(raw) == expected

    def test_blank_stays_blank(self) -> None:
        assert normalize_base("  ") == ""


class TestSplitSuffix:
    def test_splits_broker_suffix(self) -> None:
        assert split_suffix("EURUSDM") == ("EURUSD", "M")

    def test_no_suffix(self) -> None:
        assert split_suffix("EURUSD") == ("EURUSD", "")

    def test_long_tail_not_a_suffix(self) -> None:
        # More than 4 trailing chars is a different instrument, not a suffix.
        assert split_suffix("EURUSDMICRO") == ("EURUSDMICRO", "")

    def test_metal_prefix_never_splits(self) -> None:
        # XAU is not an ISO currency here, so XAUUSDM must not be treated as
        # a suffixed forex pair.
        assert split_suffix("XAUUSDM") == ("XAUUSDM", "")


class TestIsForexPair:
    @pytest.mark.parametrize("token", ["EURUSD", "USDJPY", "GBPAUD", "EURUSDM"])
    def test_true_for_currency_pairs(self, token: str) -> None:
        assert is_forex_pair(token)

    @pytest.mark.parametrize("token", ["XAUUSD", "US30", "USTEC", "BTCUSD", "", "AAPL"])
    def test_false_for_everything_else(self, token: str) -> None:
        assert not is_forex_pair(token)


class TestClassifyMt5Symbol:
    @pytest.mark.parametrize("symbol", ["EUR/USD", "EURUSD", "EURUSDm", "eurusd", "USDJPY"])
    def test_forex_pairs(self, symbol: str) -> None:
        assert classify_mt5_symbol(symbol) == (InstrumentType.FOREX, AssetClass.FOREX)

    @pytest.mark.parametrize("symbol", ["XAUUSD", "XAUUSDm", "US30", "USTEC", "BTCUSD", "DE40"])
    def test_everything_else_is_cfd(self, symbol: str) -> None:
        # Fail-safe: unrecognized symbols classify as CFD, which the mandate
        # admits only when "cfd" is explicitly allowed.
        assert classify_mt5_symbol(symbol) == (InstrumentType.CFD, None)

    def test_blank_is_cfd(self) -> None:
        assert classify_mt5_symbol("") == (InstrumentType.CFD, None)


# --------------------------------------------------------------------------- #
# Config + availability + redaction                                            #
# --------------------------------------------------------------------------- #


class TestConfig:
    def test_from_mapping_defaults(self) -> None:
        from src.trading.connectors.mt5._client import MT5Config

        cfg = MT5Config.from_mapping({})
        assert cfg.profile == "paper"
        assert cfg.environment == "paper"
        assert cfg.is_demo is True
        assert cfg.login == 0
        assert cfg.deviation_points == 20
        assert cfg.max_order_volume == pytest.approx(1.0)
        assert cfg.max_order_notional_usd == pytest.approx(10_000.0)

    def test_from_mapping_rejects_unknown_profile(self) -> None:
        from src.trading.connectors.mt5._client import MT5Config, MT5ConfigError

        with pytest.raises(MT5ConfigError):
            MT5Config.from_mapping({"profile": "yolo"})

    def test_live_profiles_map_to_live_environment(self) -> None:
        from src.trading.connectors.mt5._client import MT5Config

        assert MT5Config.from_mapping({"profile": "live"}).environment == "live"
        assert MT5Config.from_mapping({"profile": "live-readonly"}).environment == "live"
        assert MT5Config.from_mapping({"profile": "live"}).is_demo is False

    def test_build_config_precedence(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import _client

        _client.save_config(_paper_config())
        cfg = _client.build_config({"profile": "live-readonly"}, {"server": "Exness-MT5Real2"})
        assert cfg.login == 12345  # from saved file
        assert cfg.profile == "live-readonly"  # profile default overrides file
        assert cfg.server == "Exness-MT5Real2"  # explicit override wins

    def test_save_and_load_round_trip(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import _client

        path = _client.save_config(_paper_config())
        assert path.name == "mt5.json"
        loaded = _client.load_config()
        assert loaded.login == 12345
        assert loaded.server == "Exness-MT5Trial8"
        assert loaded.symbol_suffix == "m"

    def test_public_config_redacts_secrets(self) -> None:
        from src.trading.connectors.mt5._client import _public_config

        public = _public_config(_paper_config())
        text = str(public)
        assert "hunter2secret" not in text
        assert public["password"] == "***redacted***"
        assert "12345" not in str(public.get("login", ""))


class TestAvailability:
    def test_mt5_available_false_when_import_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.trading.connectors.mt5 import _client

        def _missing() -> Any:
            raise _client.MT5DependencyError("MetaTrader5 is not installed")

        monkeypatch.setattr(_client, "_require_mt5", _missing)
        assert _client.mt5_available() is False

    def test_reads_return_error_envelope_when_sdk_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from src.trading.connectors.mt5 import _client, sdk

        def _missing() -> Any:
            raise _client.MT5DependencyError("MetaTrader5 is not installed (Windows-only)")

        monkeypatch.setattr(_client, "_require_mt5", _missing)
        monkeypatch.setattr(_client, "get_runtime_root", lambda: tmp_path)
        result = sdk.get_positions(_paper_config())
        assert result["status"] == "error"
        assert "MetaTrader5" in result["error"]

    def test_check_status_reports_unconfigured(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        report = sdk.check_status(sdk.build_config({"profile": "paper"}))
        assert report["status"] == "error"
        assert "not configured" in report["error"]

    def test_check_status_happy_path(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        report = sdk.check_status(_paper_config())
        assert report["status"] == "ok"
        assert report["account"]["is_demo"] is True
        assert report["account"]["server"] == "Exness-MT5Trial8"
        assert fake_mt5.shutdown_calls >= 1


# --------------------------------------------------------------------------- #
# Identity guard (bidirectional, fail-closed)                                  #
# --------------------------------------------------------------------------- #


class TestIdentityGuard:
    def _positions_via(self, cfg) -> dict[str, Any]:
        from src.trading.connectors.mt5 import sdk

        return sdk.get_positions(cfg)

    def test_paper_profile_rejects_real_account(self, fake_mt5: FakeMT5) -> None:
        fake_mt5.account.trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL
        result = self._positions_via(_paper_config())
        assert result["status"] == "error"
        assert "demo" in result["error"].lower()

    def test_paper_profile_rejects_contest_account(self, fake_mt5: FakeMT5) -> None:
        fake_mt5.account.trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_CONTEST
        result = self._positions_via(_paper_config())
        assert result["status"] == "error"

    def test_live_profile_rejects_demo_account(self, fake_mt5: FakeMT5) -> None:
        result = self._positions_via(_paper_config(profile="live-readonly"))
        assert result["status"] == "error"
        assert "real" in result["error"].lower() or "live" in result["error"].lower()

    def test_login_pin_mismatch_rejected(self, fake_mt5: FakeMT5) -> None:
        result = self._positions_via(_paper_config(login=99999))
        assert result["status"] == "error"
        assert "login" in result["error"].lower()

    def test_matching_demo_account_passes(self, fake_mt5: FakeMT5) -> None:
        result = self._positions_via(_paper_config())
        assert result["status"] == "ok"
        assert fake_mt5.shutdown_calls == 1  # every op passes through _session


# --------------------------------------------------------------------------- #
# USD sizing (the lot-semantics fix)                                           #
# --------------------------------------------------------------------------- #


class TestQuantityNotionalUsd:
    def _size(self, symbol: str, lots: float) -> float | None:
        from src.trading.connectors.mt5 import sdk

        return sdk.quantity_notional_usd(_paper_config(), symbol, lots)

    def test_quote_usd_pair(self, fake_mt5: FakeMT5) -> None:
        # 0.1 lots EURUSD = 10,000 EUR ~= 10,800 USD at mid 1.08.
        assert self._size("EURUSD", 0.1) == pytest.approx(10_800.0)

    def test_base_usd_pair(self, fake_mt5: FakeMT5) -> None:
        # 0.1 lots USDJPY = 10,000 USD exactly.
        assert self._size("USDJPY", 0.1) == pytest.approx(10_000.0)

    def test_metal_cfd(self, fake_mt5: FakeMT5) -> None:
        # 0.1 lots XAUUSD = 10 oz * 2400 mid = 24,000 USD.
        assert self._size("XAUUSD", 0.1) == pytest.approx(24_000.0)

    def test_cross_pair_via_base_usd_conversion(self, fake_mt5: FakeMT5) -> None:
        # EURJPY: 0.1 lots = 10,000 EUR, converted through EURUSDm mid 1.08.
        assert self._size("EURJPY", 0.1) == pytest.approx(10_800.0)

    def test_unresolvable_cross_fails_closed(self, fake_mt5: FakeMT5) -> None:
        fake_mt5.symbols["GBPJPYm"] = _symbol("GBPJPYm", base="GBP", profit="JPY")
        assert self._size("GBPJPY", 0.1) is None

    def test_missing_tick_fails_closed(self, fake_mt5: FakeMT5) -> None:
        del fake_mt5.ticks["EURUSDm"]
        assert self._size("EURUSD", 0.1) is None


# --------------------------------------------------------------------------- #
# Reads                                                                        #
# --------------------------------------------------------------------------- #


class TestReads:
    def test_account_snapshot_fields(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        result = sdk.get_account_snapshot(_paper_config())
        assert result["status"] == "ok"
        account = result["account"]
        assert account["login"] == 12345
        assert account["balance"] == pytest.approx(10_000.0)
        assert account["equity"] == pytest.approx(10_050.0)
        assert account["leverage"] == 200
        assert account["is_demo"] is True

    def test_positions_carry_usd_market_value(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.positions = [
            SimpleNamespace(
                ticket=777, symbol="EURUSDm", type=FakeMT5.POSITION_TYPE_BUY,
                volume=0.1, price_open=1.0750, price_current=1.0800,
                sl=1.0700, tp=1.0900, swap=-0.5, profit=50.0, time=1_750_000_000,
            )
        ]
        result = sdk.get_positions(_paper_config())
        assert result["status"] == "ok"
        row = result["positions"][0]
        assert row["ticket"] == 777
        assert row["side"] == "buy"
        assert row["market_value"] == pytest.approx(10_800.0)

    def test_position_market_value_none_when_unpriceable(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.positions = [
            SimpleNamespace(
                ticket=778, symbol="EURUSDm", type=FakeMT5.POSITION_TYPE_SELL,
                volume=0.1, price_open=1.0750, price_current=1.0800,
                sl=0.0, tp=0.0, swap=0.0, profit=-10.0, time=1_750_000_000,
            )
        ]
        del fake_mt5.ticks["EURUSDm"]
        result = sdk.get_positions(_paper_config())
        # Row present, value None → gate exposure math fails closed downstream.
        assert result["positions"][0]["market_value"] is None

    def test_quote_omits_zero_last(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        result = sdk.get_quote("EUR/USD", config=_paper_config())
        assert result["status"] == "ok"
        assert result["resolved_symbol"] == "EURUSDm"
        quote = result["quote"]
        assert quote["bid"] == pytest.approx(1.0799)
        assert quote["ask"] == pytest.approx(1.0801)
        assert "last" not in quote

    def test_history_maps_rows_and_timeframes(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.rates["EURUSDm"] = [
            {"time": 1_750_000_000, "open": 1.07, "high": 1.09, "low": 1.06,
             "close": 1.08, "tick_volume": 1200, "spread": 6, "real_volume": 0},
        ]
        result = sdk.get_historical_bars("EURUSD", config=_paper_config(), period="1h", limit=10)
        assert result["status"] == "ok"
        bar = result["bars"][0]
        assert bar["close"] == pytest.approx(1.08)
        assert bar["volume"] == 1200
        assert fake_mt5.rates_calls[-1][1] == FakeMT5.TIMEFRAME_H1

    def test_minute_and_month_periods_differ(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.rates["EURUSDm"] = []
        sdk.get_historical_bars("EURUSD", config=_paper_config(), period="1m", limit=5)
        sdk.get_historical_bars("EURUSD", config=_paper_config(), period="1M", limit=5)
        assert fake_mt5.rates_calls[-2][1] == FakeMT5.TIMEFRAME_M1
        assert fake_mt5.rates_calls[-1][1] == FakeMT5.TIMEFRAME_MN1

    def test_pending_orders_read(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.pending_orders = [
            SimpleNamespace(
                ticket=888, symbol="EURUSDm", type=FakeMT5.ORDER_TYPE_BUY_LIMIT,
                volume_initial=0.05, volume_current=0.05, price_open=1.0500,
                sl=0.0, tp=0.0, time_setup=1_750_000_000, state=1,
            )
        ]
        result = sdk.get_open_orders(_paper_config())
        assert result["status"] == "ok"
        assert result["open_orders"][0]["order_id"] == "888"


# --------------------------------------------------------------------------- #
# place_order                                                                  #
# --------------------------------------------------------------------------- #


class TestPlaceOrder:
    def _place(self, fake: FakeMT5, **kwargs: Any) -> dict[str, Any]:
        from src.trading.connectors.mt5 import sdk

        defaults: dict[str, Any] = {
            "symbol": "EURUSD", "side": "buy", "quantity": 0.05,
            "notional": None, "order_type": "market",
            "limit_price": None, "time_in_force": "day",
        }
        defaults.update(kwargs)
        return sdk.place_order(_paper_config(), **defaults)

    def test_market_buy_request_shape(self, fake_mt5: FakeMT5) -> None:
        result = self._place(fake_mt5)
        assert result["status"] == "ok"
        assert result["order_id"] == "424242"
        request = fake_mt5.order_send_requests[-1]
        assert request["action"] == FakeMT5.TRADE_ACTION_DEAL
        assert request["type"] == FakeMT5.ORDER_TYPE_BUY
        assert request["symbol"] == "EURUSDm"
        assert request["volume"] == pytest.approx(0.05)
        assert request["price"] == pytest.approx(1.0801)  # buy at ask
        assert request["deviation"] == 20
        assert request["type_filling"] == FakeMT5.ORDER_FILLING_IOC

    def test_market_sell_priced_at_bid(self, fake_mt5: FakeMT5) -> None:
        self._place(fake_mt5, side="sell")
        assert fake_mt5.order_send_requests[-1]["price"] == pytest.approx(1.0799)
        assert fake_mt5.order_send_requests[-1]["type"] == FakeMT5.ORDER_TYPE_SELL

    def test_limit_order_is_pending_with_tif(self, fake_mt5: FakeMT5) -> None:
        self._place(fake_mt5, order_type="limit", limit_price=1.05, time_in_force="gtc")
        request = fake_mt5.order_send_requests[-1]
        assert request["action"] == FakeMT5.TRADE_ACTION_PENDING
        assert request["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT
        assert request["price"] == pytest.approx(1.05)
        assert request["type_time"] == FakeMT5.ORDER_TIME_GTC

    def test_rejected_retcode_surfaces_error(self, fake_mt5: FakeMT5) -> None:
        fake_mt5.order_send_result = SimpleNamespace(
            retcode=10018, order=0, deal=0, volume=0.0, price=0.0, comment="Market closed"
        )
        result = self._place(fake_mt5)
        assert result["status"] == "error"
        assert "10018" in result["error"]
        assert "Market closed" in result["error"]

    def test_order_check_failure_blocks_send(self, fake_mt5: FakeMT5) -> None:
        fake_mt5.order_check_result = SimpleNamespace(retcode=10019, comment="No money")
        result = self._place(fake_mt5)
        assert result["status"] == "error"
        assert fake_mt5.order_send_requests == []

    def test_volume_guard_blocks_before_sdk(self, fake_mt5: FakeMT5) -> None:
        result = self._place(fake_mt5, quantity=1.5)  # max_order_volume = 1.0
        assert result["status"] == "error"
        assert "max_order_volume" in result["error"]
        assert fake_mt5.order_send_requests == []

    def test_notional_guard_blocks_before_sdk(self, fake_mt5: FakeMT5) -> None:
        # 0.5 lots EURUSD ~= 54,000 USD > default 10,000 cap.
        result = self._place(fake_mt5, quantity=0.5)
        assert result["status"] == "error"
        assert "max_order_notional_usd" in result["error"]
        assert fake_mt5.order_send_requests == []

    def test_notional_sizing_floors_to_volume_step(self, fake_mt5: FakeMT5) -> None:
        # 5000 USD / (100k * 1.08 per lot) = 0.0463 lots → floors to 0.04.
        result = self._place(fake_mt5, quantity=None, notional=5000.0)
        assert result["status"] == "ok"
        assert fake_mt5.order_send_requests[-1]["volume"] == pytest.approx(0.04)

    def test_notional_below_min_volume_errors(self, fake_mt5: FakeMT5) -> None:
        result = self._place(fake_mt5, quantity=None, notional=500.0)  # < 0.01 lots
        assert result["status"] == "error"
        assert fake_mt5.order_send_requests == []

    def test_exactly_one_size_required(self, fake_mt5: FakeMT5) -> None:
        assert self._place(fake_mt5, quantity=None, notional=None)["status"] == "error"
        assert self._place(fake_mt5, quantity=0.05, notional=1000.0)["status"] == "error"

    def test_unconfigured_errors_before_sdk(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        result = sdk.place_order(
            sdk.build_config({"profile": "paper"}),
            symbol="EURUSD", side="buy", quantity=0.05, notional=None,
            order_type="market", limit_price=None, time_in_force="day",
        )
        assert result["status"] == "error"
        assert "not configured" in result["error"]
        assert fake_mt5.order_send_requests == []

    def test_unknown_symbol_lists_candidates(self, fake_mt5: FakeMT5) -> None:
        result = self._place(fake_mt5, symbol="NZDCAD")
        assert result["status"] == "error"
        assert fake_mt5.order_send_requests == []


# --------------------------------------------------------------------------- #
# cancel_order / close_position (risk-reducing dual semantics)                 #
# --------------------------------------------------------------------------- #


class TestCancelOrder:
    def test_pending_ticket_removed(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.pending_orders = [
            SimpleNamespace(
                ticket=888, symbol="EURUSDm", type=FakeMT5.ORDER_TYPE_BUY_LIMIT,
                volume_initial=0.05, volume_current=0.05, price_open=1.05,
                sl=0.0, tp=0.0, time_setup=0, state=1,
            )
        ]
        result = sdk.cancel_order(_paper_config(), "888")
        assert result["status"] == "ok"
        assert result["action"] == "order_cancelled"
        request = fake_mt5.order_send_requests[-1]
        assert request["action"] == FakeMT5.TRADE_ACTION_REMOVE
        assert request["order"] == 888

    def test_position_ticket_closed_with_opposite_deal(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.positions = [
            SimpleNamespace(
                ticket=777, symbol="EURUSDm", type=FakeMT5.POSITION_TYPE_BUY,
                volume=0.1, price_open=1.0750, price_current=1.0800,
                sl=0.0, tp=0.0, swap=0.0, profit=0.0, time=0,
            )
        ]
        result = sdk.cancel_order(_paper_config(), "777")
        assert result["status"] == "ok"
        assert result["action"] == "position_closed"
        request = fake_mt5.order_send_requests[-1]
        assert request["action"] == FakeMT5.TRADE_ACTION_DEAL
        assert request["type"] == FakeMT5.ORDER_TYPE_SELL  # opposite of long
        assert request["position"] == 777
        assert request["volume"] == pytest.approx(0.1)

    def test_close_volume_capped_at_position(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        fake_mt5.positions = [
            SimpleNamespace(
                ticket=777, symbol="EURUSDm", type=FakeMT5.POSITION_TYPE_SELL,
                volume=0.1, price_open=1.08, price_current=1.07,
                sl=0.0, tp=0.0, swap=0.0, profit=0.0, time=0,
            )
        ]
        result = sdk.close_position(_paper_config(), 777, volume=5.0)
        assert result["status"] == "ok"
        request = fake_mt5.order_send_requests[-1]
        assert request["volume"] == pytest.approx(0.1)  # never more than the position
        assert request["type"] == FakeMT5.ORDER_TYPE_BUY  # opposite of short

    def test_unknown_ticket_errors(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        result = sdk.cancel_order(_paper_config(), "31337")
        assert result["status"] == "error"
        assert fake_mt5.order_send_requests == []

    def test_non_integer_ticket_errors(self, fake_mt5: FakeMT5) -> None:
        from src.trading.connectors.mt5 import sdk

        result = sdk.cancel_order(_paper_config(), "abc")
        assert result["status"] == "error"
        assert fake_mt5.order_send_requests == []


# --------------------------------------------------------------------------- #
# _rate_to_dict numpy serialization regression (Issue #774)                     #
# --------------------------------------------------------------------------- #


class TestRateToDictSerialization:
    def test_rate_to_dict_numpy_serializable(self) -> None:
        """Verify _rate_to_dict converts numpy scalars to native Python types."""
        import json

        import numpy as np

        from src.trading.connectors.mt5.reads import _rate_to_dict

        # Simulate a numpy structured array row as returned by MT5 SDK.
        dt = np.dtype([
            ("time", "<i8"), ("open", "<f8"), ("high", "<f8"),
            ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<i8"),
            ("spread", "<i4"), ("real_volume", "<i8"),
        ])
        row = np.array(
            [(1_750_000_000, 1.0700, 1.0900, 1.0600, 1.0800, 1200, 6, 0)],
            dtype=dt,
        )[0]

        result = _rate_to_dict(row)

        # Must be JSON-serializable without raising.
        serialized = json.dumps(result)
        assert serialized  # non-empty string

        # All numeric values must be native Python types, not numpy scalars.
        for key in ("time", "volume", "spread", "real_volume"):
            assert type(result[key]) is int, f"{key} should be int, got {type(result[key])}"
        for key in ("open", "high", "low", "close"):
            assert type(result[key]) is float, f"{key} should be float, got {type(result[key])}"

        # Verify values are correct.
        assert result["time"] == 1_750_000_000
        assert result["close"] == 1.08
        assert result["volume"] == 1200

    def test_rate_to_dict_mapping_types(self) -> None:
        """Plain dict input produces native Python types and is JSON-serializable."""
        import json

        from src.trading.connectors.mt5.reads import _rate_to_dict

        rate = {
            "time": 1_750_000_000,
            "open": 1.07,
            "high": 1.09,
            "low": 1.06,
            "close": 1.08,
            "tick_volume": 1200,
            "spread": 6,
            "real_volume": 0,
        }

        result = _rate_to_dict(rate)
        json.dumps(result)  # must not raise

        assert type(result["time"]) is int
        assert type(result["close"]) is float
        assert type(result["volume"]) is int
        assert type(result["spread"]) is int
        assert type(result["real_volume"]) is int

    def test_rate_to_dict_handles_none_values(self) -> None:
        """None values pass through without raising and remain JSON-serializable."""
        import json

        from src.trading.connectors.mt5.reads import _rate_to_dict

        rate = {
            "time": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "tick_volume": None,
            "spread": None,
            "real_volume": None,
        }

        result = _rate_to_dict(rate)
        json.dumps(result)  # must not raise

        assert result["time"] is None
        assert result["open"] is None
        assert result["volume"] is None


# --------------------------------------------------------------------------- #
# Profiles, classification, service registration                               #
# --------------------------------------------------------------------------- #


class TestProfilesAndRegistration:
    def test_four_profiles_registered(self) -> None:
        from src.trading.profiles import list_profiles
        from src.trading.types import READ_CAPABILITIES

        profiles = {p.id: p for p in list_profiles()}
        for pid in ("mt5-paper-sdk", "mt5-live-sdk-readonly", "mt5-paper-trade", "mt5-live-trade"):
            assert pid in profiles, f"{pid} missing from BUILTIN_PROFILES"
            assert profiles[pid].connector == "mt5"
            assert profiles[pid].transport == "broker_sdk"

        assert profiles["mt5-paper-sdk"].readonly is True
        assert profiles["mt5-paper-sdk"].capabilities == READ_CAPABILITIES
        assert profiles["mt5-live-sdk-readonly"].environment == "live"
        assert profiles["mt5-live-sdk-readonly"].readonly is True
        assert profiles["mt5-paper-trade"].readonly is False
        assert "orders.place" in profiles["mt5-paper-trade"].capabilities
        assert profiles["mt5-live-trade"].readonly is False
        assert "orders.place.requires_mandate" in profiles["mt5-live-trade"].capabilities

    def test_check_connection_unconfigured_degrades(self, fake_mt5: FakeMT5) -> None:
        from src.trading import service

        report = service.check_connection("mt5-paper-sdk")
        assert report["status"] == "error"
        assert "not configured" in report["error"]
        assert report["connector"] == "mt5"
        assert report["transport"] == "broker_sdk"

    def test_order_classification_forex_and_cfd(self) -> None:
        from src.trading.service import _order_classification

        assert _order_classification("mt5", "EURUSDm") == (InstrumentType.FOREX, AssetClass.FOREX)
        assert _order_classification("mt5", "EUR/USD") == (InstrumentType.FOREX, AssetClass.FOREX)
        assert _order_classification("mt5", "XAUUSD") == (InstrumentType.CFD, None)

    def test_classification_map_fail_closed(self) -> None:
        from src.live import registry
        from src.live.classification import ToolClass, classify_tool
        from src.trading.connectors.mt5.classification import MT5_TOOL_CLASS

        assert registry._BROKER_CURATED_MAPS["mt5"] is MT5_TOOL_CLASS
        for op in ("order_send", "order_check", "place_order", "cancel_order", "close_position"):
            assert MT5_TOOL_CLASS[op] is ToolClass.WRITE
        assert classify_tool("order_send", None, MT5_TOOL_CLASS) is ToolClass.WRITE
        # Unknown ops must never resolve READ (fail-closed).
        assert classify_tool("mystery_op", None, MT5_TOOL_CLASS) is not ToolClass.READ

    def test_paper_place_via_service(self, fake_mt5: FakeMT5) -> None:
        from src.trading import service
        from src.trading.connectors.mt5 import _client

        _client.save_config(_paper_config())
        result = service.place_order("EURUSD", "mt5-paper-trade", side="buy", quantity=0.05)
        assert result["status"] == "ok"
        assert result["environment"] == "paper"
        assert len(fake_mt5.order_send_requests) == 1

    def test_live_place_blocked_without_mandate(self, fake_mt5: FakeMT5, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.trading import service
        from src.trading.connectors.mt5 import _client

        _client.save_config(_paper_config(profile="live"))
        monkeypatch.setattr("src.live.sdk_order_gate.load_mandate", lambda broker: None)
        result = service.place_order("EURUSD", "mt5-live-trade", side="buy", quantity=0.05)
        assert result["status"] == "blocked"
        assert fake_mt5.order_send_requests == []  # gate blocks before any SDK call
