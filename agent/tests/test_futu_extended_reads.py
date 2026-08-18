"""Tests for the extended read-only Futu (moomoo) connector endpoints.

These endpoints — rehab factors, capital flow, capital distribution, history
deals, account cash flow, financials, and earnings calendar — are exposed by
the Futu broker_sdk connector via ``futu-api``. The connector wraps each SDK
call with a fail-closed envelope; these tests pin the contract so future
refactors can't silently change parameter routing or break the agent tool
surface.

The tests mock the SDK (``futu``) and the OpenD context objects via
``monkeypatch``. No real OpenD, no real Futu credentials, no network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.trading.connectors.futu import sdk as futu_sdk
from src.trading.connectors.futu import profiles as futu_profiles


# ---------------------------------------------------------------------------
# Shared test fixtures: a fake Futu SDK + OpenD contexts.
# ---------------------------------------------------------------------------


class _FakeKLType:
    K_1M = "K_1M"
    K_DAY = "K_DAY"


class _FakeFutu:
    KLType = _FakeKLType
    RET_OK = 0

    class Market:
        US = "US"
        HK = "HK"


class _FakeQuoteCtx:
    def __init__(self, *, handlers: dict[tuple[str, ...], Any] | None = None) -> None:
        self.handlers = handlers or {}
        self.calls: list[tuple[str, tuple]] = []

    def get_rehab(self, code):
        self.calls.append(("get_rehab", (code,)))
        return self.handlers.get(("get_rehab", code))

    def get_capital_flow(self, code, period_type=None):
        self.calls.append(("get_capital_flow", (code, period_type)))
        return self.handlers.get(("get_capital_flow", code))

    def get_capital_distribution(self, code):
        self.calls.append(("get_capital_distribution", (code,)))
        return self.handlers.get(("get_capital_distribution", code))

    def get_financials_statements(self, code, statement_type=None, num=None):
        self.calls.append(("get_financials_statements", (code, statement_type, num)))
        return self.handlers.get(("get_financials_statements", code))

    def get_earnings_calendar(self, market=None, begin_date=None, end_date=None):
        self.calls.append(("get_earnings_calendar", (market, begin_date, end_date)))
        return self.handlers.get(("get_earnings_calendar",))


class _FakeTradeCtx:
    def __init__(self, *, handlers: dict[tuple[str, ...], Any] | None = None) -> None:
        self.handlers = handlers or {}
        self.calls: list[tuple[str, tuple]] = []

    def history_deal_list_query(self, start=None, end=None, trd_env=None, acc_id=None, code=""):
        self.calls.append(("history_deal_list_query", (start, end, trd_env, acc_id, code)))
        return self.handlers.get(("history_deal_list_query", code))

    def get_acc_cash_flow(self, clearing_date=None, trd_env=None, acc_id=None):
        self.calls.append(("get_acc_cash_flow", (clearing_date, trd_env, acc_id)))
        return self.handlers.get(("get_acc_cash_flow", clearing_date))


@pytest.fixture
def base_futu_cfg(monkeypatch) -> futu_sdk.FutuConfig:
    """A FutuConfig that skips the gateway TCP probe in every test."""
    monkeypatch.setattr(futu_sdk, "_assert_gateway", lambda cfg: None)
    return futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="live-readonly")


@pytest.fixture
def patched_futu(monkeypatch):
    """Install a minimal fake ``futu`` module so ``_require_futu()`` succeeds."""
    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _FakeFutu)
    return _FakeFutu


# ---------------------------------------------------------------------------
# get_rehab
# ---------------------------------------------------------------------------


def test_get_rehab_returns_status_ok_with_events(base_futu_cfg, patched_futu, monkeypatch) -> None:
    """get_rehab unwraps the SDK tuple and copies ``ex_dividend_events`` through."""
    payload = [{"ex_div_date": "2025-05-15", "per_cash_div": 1.5}]
    quote_ctx = _FakeQuoteCtx(handlers={("get_rehab", "HK.00700"): (0, payload)})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    result = futu_sdk.get_rehab("HK.00700", config=base_futu_cfg)

    assert result["status"] == "ok"
    assert result["symbol"] == "HK.00700"
    assert result["ex_dividend_events"] == payload
    assert quote_ctx.calls == [("get_rehab", ("HK.00700",))]


def test_get_rehab_handles_empty_payload(base_futu_cfg, patched_futu, monkeypatch) -> None:
    """No adjustment events (the common case) returns an empty list, not null."""
    quote_ctx = _FakeQuoteCtx(handlers={("get_rehab", "HK.03690"): (0, [])})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    result = futu_sdk.get_rehab("HK.03690", config=base_futu_cfg)

    assert result["status"] == "ok"
    assert result["ex_dividend_events"] == []


# ---------------------------------------------------------------------------
# get_capital_flow
# ---------------------------------------------------------------------------


def test_get_capital_flow_passes_period_type_through(base_futu_cfg, patched_futu, monkeypatch) -> None:
    """Period token (INTRADAY/DAY/WEEK/MONTH) is forwarded to the SDK verbatim."""
    quote_ctx = _FakeQuoteCtx(handlers={("get_capital_flow", "HK.03690"): (0, [])})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    futu_sdk.get_capital_flow("HK.03690", config=base_futu_cfg, period_type="WEEK")

    assert quote_ctx.calls == [("get_capital_flow", ("HK.03690", "WEEK"))]


def test_get_capital_flow_defaults_to_intraday(base_futu_cfg, patched_futu, monkeypatch) -> None:
    quote_ctx = _FakeQuoteCtx(handlers={("get_capital_flow", "US.AAPL"): (0, [])})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    futu_sdk.get_capital_flow("US.AAPL", config=base_futu_cfg)

    assert quote_ctx.calls[0][1][1] == "INTRADAY"


# ---------------------------------------------------------------------------
# get_capital_distribution
# ---------------------------------------------------------------------------


def test_get_capital_distribution_returns_single_row_snapshot(base_futu_cfg, patched_futu, monkeypatch) -> None:
    row = {"capital_in_super": 1.0, "capital_out_small": 2.0, "update_time": "2026-08-18T10:00:00"}
    quote_ctx = _FakeQuoteCtx(handlers={("get_capital_distribution", "HK.00700"): (0, [row])})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    result = futu_sdk.get_capital_distribution("HK.00700", config=base_futu_cfg)

    assert result["status"] == "ok"
    assert result["symbol"] == "HK.00700"
    assert result["distribution"] == [row]


# ---------------------------------------------------------------------------
# get_history_deals
# ---------------------------------------------------------------------------


def test_get_history_deals_resolves_account_and_passes_dates(base_futu_cfg, patched_futu, monkeypatch) -> None:
    deal = {"deal_id": "abc", "code": "HK.00700", "qty": 100.0, "price": 350.0, "trd_side": "BUY"}
    trade_ctx = _FakeTradeCtx(handlers={("history_deal_list_query", ""): (0, [deal])})
    monkeypatch.setattr(futu_sdk, "_trade_ctx", lambda cfg: trade_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)
    monkeypatch.setattr(futu_sdk, "_resolve_acc_id", lambda cfg, ctx: 1001)
    monkeypatch.setattr(futu_sdk, "_trd_env_enum", lambda cfg: _FakeFutu.KLType.K_DAY)  # any sentinel

    result = futu_sdk.get_history_deals("2026-01-01", "2026-08-18", config=base_futu_cfg)

    assert result["status"] == "ok"
    assert result["start"] == "2026-01-01"
    assert result["end"] == "2026-08-18"
    # Don't pin the exact row shape: _deal_to_dict enriches each row with
    # fields like order_id / create_time that we didn't mock. Just assert one
    # of our seed fields survived the round-trip.
    assert len(result["deals"]) == 1
    assert result["deals"][0]["code"] == "HK.00700"
    assert result["deals"][0]["trd_side"] == "BUY"


def test_get_history_deals_scopes_by_code_when_provided(base_futu_cfg, patched_futu, monkeypatch) -> None:
    trade_ctx = _FakeTradeCtx(handlers={("history_deal_list_query", "HK.00700"): (0, [])})
    monkeypatch.setattr(futu_sdk, "_trade_ctx", lambda cfg: trade_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)
    monkeypatch.setattr(futu_sdk, "_resolve_acc_id", lambda cfg, ctx: 1001)
    monkeypatch.setattr(futu_sdk, "_trd_env_enum", lambda cfg: None)

    futu_sdk.get_history_deals("2026-01-01", "2026-08-18", config=base_futu_cfg, code="HK.00700")

    # code should be uppercased and passed through
    assert trade_ctx.calls == [
        ("history_deal_list_query", ("2026-01-01", "2026-08-18", None, 1001, "HK.00700"))
    ]


# ---------------------------------------------------------------------------
# get_acc_cash_flow
# ---------------------------------------------------------------------------


def test_get_acc_cash_flow_routes_to_trade_context(base_futu_cfg, patched_futu, monkeypatch) -> None:
    flow = {"cashflow_type": "DEPOSIT", "cashflow_amount": 10000.0, "currency": "HKD"}
    trade_ctx = _FakeTradeCtx(handlers={("get_acc_cash_flow", "2026-08-01"): (0, [flow])})
    monkeypatch.setattr(futu_sdk, "_trade_ctx", lambda cfg: trade_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)
    monkeypatch.setattr(futu_sdk, "_resolve_acc_id", lambda cfg, ctx: 1001)
    monkeypatch.setattr(futu_sdk, "_trd_env_enum", lambda cfg: None)

    result = futu_sdk.get_acc_cash_flow("2026-08-01", config=base_futu_cfg)

    assert result["status"] == "ok"
    assert result["clearing_date"] == "2026-08-01"
    assert result["cash_flows"] == [flow]


# ---------------------------------------------------------------------------
# get_financials
# ---------------------------------------------------------------------------


def test_get_financials_maps_statement_type_tokens_to_int_codes(base_futu_cfg, patched_futu, monkeypatch) -> None:
    """INCOME / BALANCE / CASH_FLOW map to 1 / 2 / 3 on the SDK wire."""
    quote_ctx = _FakeQuoteCtx(handlers={("get_financials_statements", "HK.00700"): (0, {"structure_list": [], "report_list": []})})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    futu_sdk.get_financials("HK.00700", config=base_futu_cfg, statement_type="BALANCE")

    # statement_type 2 == BALANCE
    assert quote_ctx.calls[0][1][1] == 2


def test_get_financials_unknown_statement_type_defaults_to_income(base_futu_cfg, patched_futu, monkeypatch) -> None:
    quote_ctx = _FakeQuoteCtx(handlers={("get_financials_statements", "HK.00700"): (0, {"structure_list": [], "report_list": []})})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    futu_sdk.get_financials("HK.00700", config=base_futu_cfg, statement_type="BOGUS")

    assert quote_ctx.calls[0][1][1] == 1  # INCOME default


# ---------------------------------------------------------------------------
# get_earnings_calendar
# ---------------------------------------------------------------------------


def test_get_earnings_calendar_passes_market_and_dates(base_futu_cfg, patched_futu, monkeypatch) -> None:
    quote_ctx = _FakeQuoteCtx(handlers={("get_earnings_calendar",): (0, [])})
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: quote_ctx)
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)

    futu_sdk.get_earnings_calendar(
        config=base_futu_cfg, market="US", begin_date="2026-08-19", end_date="2026-08-25"
    )

    assert quote_ctx.calls == [
        ("get_earnings_calendar", ("US", "2026-08-19", "2026-08-25"))
    ]


# ---------------------------------------------------------------------------
# Profiles: every profile advertises the extended read capabilities so the
# agent loop's profile-picker sees them; runtime is still profile-aware via the
# service layer's "unsupported" envelope.
# ---------------------------------------------------------------------------


def test_all_futu_profiles_advertise_extended_read_capabilities() -> None:
    from src.trading.types import FUTU_EXTENDED_READ_CAPABILITIES

    for profile in futu_profiles.FUTU_PROFILES:
        for cap in FUTU_EXTENDED_READ_CAPABILITIES:
            assert cap in profile.capabilities, (
                f"{profile.id} missing capability {cap}"
            )


# ---------------------------------------------------------------------------
# Service-layer envelope: an SDK connector that does NOT implement one of
# the new endpoints must return a clean "unsupported" payload, not raise.
# ---------------------------------------------------------------------------


def test_service_returns_unsupported_when_sdk_function_missing(monkeypatch) -> None:
    """Other SDK connectors (IBKR, Alpaca, etc.) don't expose ``get_rehab``.

    The service layer should return ``{"status": "error", ...}`` instead of
    crashing the agent loop when an unsupported capability is requested.
    """
    # We monkeypatch _sdk_module to a fake alpaca module with no get_rehab.
    import src.trading.service as service

    class _FakeAlpacaModule:
        RET_OK = 0

        @staticmethod
        def build_config(profile_config, overrides=None):
            return object()

        @staticmethod
        def get_account_snapshot(config):
            return {"status": "ok"}

    monkeypatch.setattr(service, "_sdk_module", lambda connector: _FakeAlpacaModule)

    from src.trading.profiles import list_profiles

    # pick an alpaca profile, fall back to first broker_sdk profile
    profile_id = next(p.id for p in list_profiles() if p.connector == "alpaca")
    result = service.get_rehab("US.AAPL", profile_id=profile_id)

    assert result["status"] == "error"
    assert "rehab.read" in result.get("error", "") or "unsupported" in json.dumps(result).lower()


# ---------------------------------------------------------------------------
# Capability metadata: types.FUTU_EXTENDED_READ_CAPABILITIES is a flat tuple of
# the seven expected strings.
# ---------------------------------------------------------------------------


def test_futu_extended_capabilities_are_exactly_seven() -> None:
    from src.trading.types import FUTU_EXTENDED_READ_CAPABILITIES

    assert len(FUTU_EXTENDED_READ_CAPABILITIES) == 7
    assert set(FUTU_EXTENDED_READ_CAPABILITIES) == {
        "rehab.read",
        "capital_flow.read",
        "capital_distribution.read",
        "history_deals.read",
        "acc_cash_flow.read",
        "financials.read",
        "earnings_calendar.read",
    }