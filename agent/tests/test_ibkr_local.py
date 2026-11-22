"""Unit tests for the local IBKR TWS / IB Gateway bridge."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.trading.connectors.ibkr import local
from src.tools.trading_connector_tool import TradingPositionsTool

pytestmark = pytest.mark.unit


class _FakeContract:
    def __init__(self) -> None:
        self.symbol = ""
        self.secType = ""
        self.exchange = ""
        self.currency = ""
        self.conId = 0
        self.localSymbol = ""


class _FakeStock(_FakeContract):
    def __init__(self, symbol: str, exchange: str, currency: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.secType = "STK"
        self.exchange = exchange
        self.currency = currency
        self.conId = 101
        self.localSymbol = symbol


class _FakeIB:
    def connect(self, host, port, *, clientId, timeout, readonly=True, account=""):
        self.host = host
        self.port = port
        self.client_id = clientId
        self.readonly = readonly
        self.account = account

    def disconnect(self):
        self.disconnected = True

    def managedAccounts(self):
        return ["DU12345"]

    def accountSummary(self, account=""):
        return [
            SimpleNamespace(account="DU12345", tag="NetLiquidation", value="100000", currency="USD", modelCode="")
        ]

    def positions(self):
        contract = SimpleNamespace(
            symbol="AAPL",
            localSymbol="AAPL",
            secType="STK",
            exchange="SMART",
            currency="USD",
            conId=265598,
        )
        return [SimpleNamespace(account="DU12345", contract=contract, position=3, avgCost=150.0)]

    def openTrades(self):
        return []

    def qualifyContracts(self, contract):
        return [contract]

    def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
        return SimpleNamespace(bid=100.0, ask=100.2, last=100.1, close=99.0, volume=1234, time="")

    def cancelMktData(self, contract):
        return None

    def sleep(self, seconds):
        return None

    def reqHistoricalData(
        self,
        contract,
        *,
        endDateTime,
        durationStr,
        barSizeSetting,
        whatToShow,
        useRTH,
        formatDate,
    ):
        return [SimpleNamespace(date="2026-05-29", open=1, high=2, low=0.5, close=1.5, volume=100)]


@pytest.fixture()
def fake_ib_async(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("ib_async")
    module.IB = _FakeIB
    module.Stock = _FakeStock
    module.Contract = _FakeContract
    monkeypatch.setitem(sys.modules, "ib_async", module)
    monkeypatch.setattr(local, "tcp_port_open", lambda *_, **__: True)
    return module


def test_config_defaults_to_paper_port() -> None:
    cfg = local.IBKRLocalConfig.from_mapping({"profile": "paper"})
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 7497
    assert cfg.readonly is True


def test_account_snapshot_reads_summary(fake_ib_async) -> None:
    cfg = local.IBKRLocalConfig()
    result = local.get_account_snapshot(cfg)

    assert result["status"] == "ok"
    assert result["accounts"] == ["DU12345"]
    assert result["summary"][0]["tag"] == "NetLiquidation"


def test_positions_are_serialized(fake_ib_async) -> None:
    result = local.get_positions(local.IBKRLocalConfig())

    assert result["positions"][0]["symbol"] == "AAPL"
    assert result["positions"][0]["position"] == 3


def test_quote_and_history_are_readonly(fake_ib_async) -> None:
    quote = local.get_quote("AAPL", config=local.IBKRLocalConfig())
    history = local.get_historical_bars("AAPL", config=local.IBKRLocalConfig())

    assert quote["quote"]["last"] == 100.1
    assert history["bars"][0]["close"] == 1.5


def test_paper_profile_rejects_live_account(monkeypatch: pytest.MonkeyPatch, fake_ib_async) -> None:
    class _LiveIB(_FakeIB):
        def managedAccounts(self):
            return ["U12345"]

        def accountSummary(self, account=""):
            return [SimpleNamespace(account="U12345", tag="NetLiquidation", value="1", currency="USD", modelCode="")]

    fake_ib_async.IB = _LiveIB

    with pytest.raises(local.IBKRProfileMismatchError):
        local.get_account_snapshot(local.IBKRLocalConfig(profile="paper"))


def test_check_status_reports_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "ib_async_available", lambda: False)
    monkeypatch.setattr(local, "tcp_port_open", lambda *_, **__: True)

    report = local.check_local_status(local.IBKRLocalConfig(), scan=False)

    assert report["status"] == "error"
    assert "ib_async" in report["error"]


def test_positions_tool_returns_json(fake_ib_async) -> None:
    payload = json.loads(TradingPositionsTool().execute(connection="ibkr-paper-local"))

    assert payload["status"] == "ok"
    assert payload["profile_id"] == "ibkr-paper-local"
    assert payload["positions"][0]["symbol"] == "AAPL"


def test_service_uses_persisted_ibkr_local_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Configured local endpoint values must survive later connector calls."""
    from src.trading import service

    monkeypatch.setattr(local, "get_runtime_root", lambda: tmp_path)
    local.save_config(
        local.IBKRLocalConfig(
            profile="paper",
            host="192.168.10.8",
            port=4002,
            client_id=123,
            account="DU999",
        )
    )
    captured: dict[str, local.IBKRLocalConfig] = {}

    def _check(cfg: local.IBKRLocalConfig) -> dict[str, object]:
        captured["cfg"] = cfg
        return {"status": "ok", "ports": [], "target": {}, "sdk": {"installed": True}}

    monkeypatch.setattr(local, "check_local_status", _check)

    assert service.check_connection("ibkr-paper-local")["status"] == "ok"

    cfg = captured["cfg"]
    assert cfg.host == "192.168.10.8"
    assert cfg.port == 4002
    assert cfg.client_id == 123
    assert cfg.account == "DU999"


def test_cli_connector_routes_to_handler() -> None:
    from cli.commands.parser import build_parser as _build_parser
    from cli.commands.connectors import _dispatch_connector

    args = _build_parser().parse_args(["connector", "check", "ibkr-paper-local", "--account", "DU12345"])
    with patch('cli.commands.connectors.cmd_connector_check', return_value=0) as handler:
        assert _dispatch_connector(args) == 0
    handler.assert_called_once_with(
        "ibkr-paper-local",
        host=None,
        port=None,
        client_id=None,
        account="DU12345",
    )


def test_cli_connector_check_passes_account_to_backend() -> None:
    from cli.commands.connectors import cmd_connector_check

    report = {"status": "ok", "ports": [], "target": {}, "sdk": {"installed": True}}
    with patch("src.trading.service.check_connection", return_value=report) as check:
        assert cmd_connector_check("ibkr-paper-local", account="DU12345") == 0
    check.assert_called_once_with(
        "ibkr-paper-local",
        host=None,
        port=None,
        client_id=None,
        account="DU12345",
    )

# -- _wait_for_tick timing regression tests ------------------------------

def test_quote_waits_for_delayed_tick_arrival(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_quote polls with ib.sleep() until the ticker receives real data."""
    from types import SimpleNamespace

    pump_count = [0]

    ticker_ns = SimpleNamespace(bid=None, ask=None, last=None, close=None, volume=None, time="")

    class _DelayedFillIB(_FakeIB):
        def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
            # Reset fields each call so tests are independent.
            ticker_ns.bid = None
            ticker_ns.ask = None
            ticker_ns.last = None
            return ticker_ns

        def sleep(self, seconds):
            pump_count[0] += 1
            # After 5 pump cycles (0.5s), populate the ticker with real data.
            if pump_count[0] >= 5:
                ticker_ns.bid = 150.25
                ticker_ns.ask = 150.50
                ticker_ns.last = 150.30

    module = types.ModuleType("ib_async")
    module.IB = _DelayedFillIB
    module.Stock = _FakeStock
    module.Contract = _FakeContract
    monkeypatch.setitem(sys.modules, "ib_async", module)
    monkeypatch.setattr(local, "tcp_port_open", lambda *_, **__: True)
    # raising=False: the pool keeps per-thread state, so on a fresh thread
    # (single-test or -k-filtered runs) these attributes do not exist yet.
    monkeypatch.setattr(local._pool._local, "refcount", 0, raising=False)
    monkeypatch.setattr(local._pool._local, "ib", None, raising=False)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))
    assert result["status"] == "ok"
    assert result["quote"]["bid"] == 150.25
    assert result["quote"]["ask"] == 150.50
    assert result["quote"]["last"] == 150.30
    # Should have pumped at least 5 times before data arrived.
    assert pump_count[0] >= 5, f"Expected >=5 pumps, got {pump_count[0]}"


def test_quote_keeps_polling_when_ticker_is_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_quote rejects NaN fields and continues polling for real data."""
    from types import SimpleNamespace

    pump_count = [0]

    ticker_ns = SimpleNamespace(
        bid=float("nan"), ask=float("nan"), last=float("nan"),
        close=None, volume=None, time="",
    )

    class _NanThenFillIB(_FakeIB):
        def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
            return ticker_ns

        def sleep(self, seconds):
            pump_count[0] += 1
            if pump_count[0] >= 8:
                ticker_ns.bid = 200.0
                ticker_ns.ask = 201.0
                ticker_ns.last = 200.5

    module = types.ModuleType("ib_async")
    module.IB = _NanThenFillIB
    module.Stock = _FakeStock
    module.Contract = _FakeContract
    monkeypatch.setitem(sys.modules, "ib_async", module)
    monkeypatch.setattr(local, "tcp_port_open", lambda *_, **__: True)
    # raising=False: the pool keeps per-thread state, so on a fresh thread
    # (single-test or -k-filtered runs) these attributes do not exist yet.
    monkeypatch.setattr(local._pool._local, "refcount", 0, raising=False)
    monkeypatch.setattr(local._pool._local, "ib", None, raising=False)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))
    assert result["status"] == "ok"
    assert result["quote"]["bid"] == 200.0
    assert pump_count[0] >= 8, f"Expected >=8 pumps (skipped NaN), got {pump_count[0]}"

def test_pool_refcount_disconnects_on_last_release(fake_ib_async) -> None:
    """disconnect() is called only when refcount reaches zero."""
    cfg = local.IBKRLocalConfig(profile="paper", client_id=77)

    # Clear any prior thread-local state from other tests.
    local._pool._local.refcount = 0
    local._pool._local.ib = None

    ib1 = local._pool.acquire(cfg)
    assert local._pool._local.refcount == 1

    ib2 = local._pool.acquire(cfg)
    assert ib2 is ib1  # Same thread → same connection
    assert local._pool._local.refcount == 2

    local._pool.release()
    assert local._pool._local.refcount == 1
    assert getattr(ib1, "disconnected", False) is False

    local._pool.release()
    assert local._pool._local.refcount == 0
    assert getattr(ib1, "disconnected", True) is True
    assert local._pool._local.ib is None


def test_pool_release_idempotent_no_connection(fake_ib_async) -> None:
    """Calling release on an empty pool is a no-op."""
    local._pool._local.refcount = 0
    local._pool._local.ib = None
    # Must not raise.
    local._pool.release()


# -- market-data tier regression tests -----------------------------------
# TWS defaults to live data (tier 1), which needs a paid per-exchange
# subscription. Without one IBKR answers error 354, no tick ever arrives, and
# get_quote used to return status "ok" with null prices — a silent failure the
# tool layer passed straight to the LLM agent.


def _install_fake_ib(monkeypatch: pytest.MonkeyPatch, ib_cls) -> None:
    module = types.ModuleType("ib_async")
    module.IB = ib_cls
    module.Stock = _FakeStock
    module.Contract = _FakeContract
    monkeypatch.setitem(sys.modules, "ib_async", module)
    monkeypatch.setattr(local, "tcp_port_open", lambda *_, **__: True)
    # raising=False: the pool keeps per-thread state, so on a fresh thread
    # (single-test or -k-filtered runs) these attributes do not exist yet.
    monkeypatch.setattr(local._pool._local, "refcount", 0, raising=False)
    monkeypatch.setattr(local._pool._local, "ib", None, raising=False)


def test_default_market_data_type_is_free_delayed() -> None:
    """Default tier must not be 1 (live), which requires a paid subscription."""
    assert local.DEFAULT_MARKET_DATA_TYPE == 3
    assert local.IBKRLocalConfig().market_data_type == 3
    assert local.MARKET_DATA_TYPES[3] == "delayed"


def test_quote_selects_tier_before_requesting_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """reqMarketDataType is called with the configured tier before reqMktData."""
    calls: list[tuple[str, object]] = []

    class _TierIB(_FakeIB):
        def reqMarketDataType(self, tier):
            calls.append(("tier", tier))

        def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
            calls.append(("mktdata", contract.symbol))
            return SimpleNamespace(bid=1.0, ask=1.1, last=1.05, close=1.0, volume=1, time="")

    _install_fake_ib(monkeypatch, _TierIB)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper", market_data_type=4))

    assert calls == [("tier", 4), ("mktdata", "AAPL")], calls
    assert result["market_data_type_requested"] == "delayed-frozen"
    assert result["market_data_type_applied"] == "delayed-frozen"
    assert "warning" not in result


def test_historical_bars_select_tier_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier hint is applied ahead of reqHistoricalData as well."""
    calls: list[str] = []

    class _TierIB(_FakeIB):
        def reqMarketDataType(self, tier):
            calls.append(f"tier:{tier}")

        def reqHistoricalData(self, contract, **kwargs):
            calls.append("history")
            return [SimpleNamespace(date="2026-05-29", open=1, high=2, low=0.5, close=1.5, volume=100)]

    _install_fake_ib(monkeypatch, _TierIB)

    local.get_historical_bars("AAPL", config=local.IBKRLocalConfig(profile="paper"))

    assert calls == ["tier:3", "history"], calls


def test_starved_ticker_reports_no_data_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ticker that never fills must not be reported as a successful quote."""

    class _StarvedIB(_FakeIB):
        def reqMarketDataType(self, tier):
            return None

        def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
            return SimpleNamespace(bid=None, ask=None, last=None, close=None, volume=None, time="")

    _install_fake_ib(monkeypatch, _StarvedIB)
    # Keep the poll short — the real default is a 5s wall-clock timeout.
    monkeypatch.setattr(local, "_wait_for_tick", lambda *_, **__: False)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))

    assert result["status"] == "no_data"
    assert result["quote"]["last"] is None
    assert "market-data subscription" in result["error"]


def test_tier_hint_is_best_effort_against_old_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stub without reqMarketDataType, or one that raises, must not break reads."""

    class _RaisingIB(_FakeIB):
        def reqMarketDataType(self, tier):
            raise RuntimeError("not supported by this SDK build")

    _install_fake_ib(monkeypatch, _RaisingIB)
    assert local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))["status"] == "ok"

    # _FakeIB itself has no reqMarketDataType at all — the getattr path.
    _install_fake_ib(monkeypatch, _FakeIB)
    assert local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))["status"] == "ok"


@pytest.mark.parametrize("sdk_kind", ["raises", "missing"])
def test_unapplied_tier_is_never_reported_as_applied(
    monkeypatch: pytest.MonkeyPatch, sdk_kind: str
) -> None:
    """A tier we failed to select must not be echoed back as the tier in force.

    A quote served on TWS's own default tier is byte-identical to one served on
    the requested tier, so claiming the requested tier was applied is the one
    thing the response must never do.
    """

    class _RaisingIB(_FakeIB):
        def reqMarketDataType(self, tier):
            raise RuntimeError("not supported by this SDK build")

    _install_fake_ib(monkeypatch, _RaisingIB if sdk_kind == "raises" else _FakeIB)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))

    assert result["status"] == "ok"
    assert result["market_data_type_requested"] == "delayed"
    assert result["market_data_type_applied"] is None
    assert "was NOT applied" in result["warning"]


def test_starved_quote_names_the_unapplied_tier_as_the_likely_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the tier never applied, that is the diagnosis — not a missing feed."""

    class _RaisingStarvedIB(_FakeIB):
        def reqMarketDataType(self, tier):
            raise RuntimeError("not supported by this SDK build")

        def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
            return SimpleNamespace(bid=None, ask=None, last=None, close=None, volume=None, time="")

    _install_fake_ib(monkeypatch, _RaisingStarvedIB)
    monkeypatch.setattr(local, "_wait_for_tick", lambda *_, **__: False)

    result = local.get_quote("AAPL", config=local.IBKRLocalConfig(profile="paper"))

    assert result["status"] == "no_data"
    assert result["market_data_type_applied"] is None
    assert "tier was not applied" in result["error"]
    assert "market-data subscription" in result["error"]


def test_historical_bars_report_tier_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """The history path carries the same requested/applied provenance as quotes."""

    class _TierIB(_FakeIB):
        def reqMarketDataType(self, tier):
            return None

        def reqHistoricalData(self, contract, **kwargs):
            return [SimpleNamespace(date="2026-05-29", open=1, high=2, low=0.5, close=1.5, volume=100)]

    _install_fake_ib(monkeypatch, _TierIB)
    applied = local.get_historical_bars("AAPL", config=local.IBKRLocalConfig(profile="paper"))
    assert applied["market_data_type_requested"] == "delayed"
    assert applied["market_data_type_applied"] == "delayed"
    assert "warning" not in applied

    class _RaisingIB(_TierIB):
        def reqMarketDataType(self, tier):
            raise RuntimeError("not supported by this SDK build")

    _install_fake_ib(monkeypatch, _RaisingIB)
    unapplied = local.get_historical_bars("AAPL", config=local.IBKRLocalConfig(profile="paper"))
    assert unapplied["status"] == "ok"
    assert unapplied["market_data_type_applied"] is None
    assert "was NOT applied" in unapplied["warning"]


@pytest.mark.parametrize("bad", [0, 5, -1, "banana", "0"])
def test_invalid_market_data_type_is_rejected(bad) -> None:
    """Config validation refuses tiers TWS does not define."""
    with pytest.raises(ValueError, match="market_data_type"):
        local.IBKRLocalConfig.from_mapping({"profile": "paper", "market_data_type": bad})


@pytest.mark.parametrize(
    ("given", "expected"),
    [("live", 1), ("frozen", 2), ("delayed", 3), ("delayed-frozen", 4), ("3", 3), (None, 3), ("", 3)],
)
def test_market_data_type_accepts_names_codes_and_blanks(given, expected) -> None:
    """Tier may be given as its TWS name or code; blank falls back to the free tier."""
    cfg = local.IBKRLocalConfig.from_mapping({"profile": "paper", "market_data_type": given})
    assert cfg.market_data_type == expected
