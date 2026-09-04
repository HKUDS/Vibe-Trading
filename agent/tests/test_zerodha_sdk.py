"""Zerodha Kite Connect SDK unit tests (no network, no real SDK).

Covers the behaviors that regressed in review: IST day-bar dating (no -1 day
shift), 4h fail-closed, interval-aware windows/pagination (no duplicate
boundary bars), cred-gated availability, and the per-exchange instrument
cache. Mirrors the loader-test style: fake SDK injected, no real creds.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime, timedelta, timezone
from typing import Any

from src.trading.connectors.zerodha import sdk as zsdk


def _ist(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=zsdk._IST)


class _FakeKite:
    """Minimal kiteconnect stand-in recording calls."""

    def __init__(self) -> None:
        self._instruments = [
            {"tradingsymbol": "RELIANCE", "instrument_token": "12345"},
            {"tradingsymbol": "500325", "instrument_token": "67890"},
        ]
        self.instruments_calls = 0
        self.historical_calls: list[dict] = []

    def instruments(self, exchange: str = "NSE"):
        self.instruments_calls += 1
        return self._instruments

    def margins(self):
        return {
            "equity": {
                "net": 123456.0,
                "available": {"cash": 50000.0, "collateral": 70000.0, "intraday_payin": 1000.0},
                "utilised": {"margins": 6543.0, "debits": 0.0},
            },
            "commodity": {},
        }

    def positions(self):
        return {
            "day": [
                {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC",
                 "quantity": 5, "average_price": 1500.0, "last_price": 1600.0,
                 "unrealised": 500.0, "realised": 0.0, "overnight_quantity": 0, "multiplier": 1},
            ],
            "net": [
                {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC",
                 "quantity": 5, "average_price": 1500.0, "last_price": 1600.0,
                 "unrealised": 500.0, "realised": 0.0, "overnight_quantity": 0, "multiplier": 1},
            ],
        }

    def orders(self):
        return [
            {"order_id": "1001", "tradingsymbol": "RELIANCE", "exchange": "NSE",
             "transaction_type": "BUY", "status": "OPEN", "order_type": "LIMIT",
             "quantity": 10, "filled_quantity": 0, "price": 1550.0, "product": "CNC"},
            {"order_id": "1002", "tradingsymbol": "TCS", "exchange": "NSE",
             "transaction_type": "SELL", "status": "COMPLETE", "order_type": "MARKET",
             "quantity": 5, "filled_quantity": 5, "price": 4200.0, "product": "CNC"},
        ]

    def historical_data(self, instrument_token, from_date, to_date, interval):
        self.historical_calls.append({
            "instrument_token": instrument_token,
            "from_date": from_date,
            "to_date": to_date,
            "interval": interval,
        })
        # One candle at the chunk start, IST-dated, so any chunk overlap
        # surfaces as a duplicated epoch in the merged output.
        return [{
            "date": _ist(from_date.year, from_date.month, from_date.day),
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10,
        }]


def _patch_kite(monkeypatch, fake: Any) -> None:
    monkeypatch.setattr(zsdk, "_login", lambda cfg: fake)
    # Fresh cache per test so instruments_calls is deterministic.
    monkeypatch.setattr(zsdk, "_INSTRUMENT_CACHE", {})


def _cfg() -> zsdk.ZerodhaConfig:
    return zsdk.ZerodhaConfig(api_key="k", access_token="t")


# ---------------------------------------------------------------------------
# Timezone: day bars keep their IST calendar date
# ---------------------------------------------------------------------------

def test_day_bar_keeps_ist_calendar_date() -> None:
    # 2024-04-01 00:00 IST == 2024-03-31 18:30 UTC. The bar must be dated
    # 2024-04-01 (midnight UTC), never shifted back a day.
    epoch = zsdk._bar_epoch(_ist(2024, 4, 1), day_bar=True)
    assert epoch == int(datetime(2024, 4, 1, tzinfo=timezone.utc).timestamp())


def test_intraday_bar_keeps_exact_instant() -> None:
    # 09:15 IST == 03:45 UTC the same day (real instant, no date shift).
    epoch = zsdk._bar_epoch(_ist(2024, 4, 1, 9, 15), day_bar=False)
    assert epoch == int(datetime(2024, 4, 1, 3, 45, tzinfo=timezone.utc).timestamp())


def test_bar_epoch_tolerates_naive_and_missing_input() -> None:
    naive = datetime(2024, 4, 1)  # defensive: assume IST, like kiteconnect
    assert zsdk._bar_epoch(naive, day_bar=True) == int(
        datetime(2024, 4, 1, tzinfo=timezone.utc).timestamp()
    )
    assert zsdk._bar_epoch(None, day_bar=True) is None


def test_loader_alignment_no_first_day_loss(monkeypatch) -> None:
    """End-to-end: a window starting on a trading day keeps that day's bar."""
    from backtest.loaders.india_broker_loader import _bars_to_frame
    # One daily bar dated 2024-04-01 midnight IST (the Kite convention).
    bars = [{"time": zsdk._bar_epoch(_ist(2024, 4, 1), day_bar=True),
             "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}]
    frame = _bars_to_frame(bars, "2024-04-01", "2024-04-30")
    assert frame is not None
    assert len(frame) == 1  # the 04-01 bar survives the clip (previously dropped)
    assert frame.index[0] == dt.datetime(2024, 4, 1)


# ---------------------------------------------------------------------------
# Interval handling
# ---------------------------------------------------------------------------

def test_4h_rejected_not_aliased_to_daily() -> None:
    out = zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="4h")
    assert out["status"] == "error"
    assert "unsupported period" in out["error"]
    out2 = zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="4H")
    assert out2["status"] == "error"


def test_1h_window_no_longer_truncated_to_5_days(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    out = zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1h", limit=90)
    assert out["status"] == "ok"
    span = fake.historical_calls[0]["to_date"] - fake.historical_calls[0]["from_date"]
    # 90 bars * 2x trading-day headroom = 180 days (previously a hardcoded 5).
    assert 170 <= span.days <= 190


def test_minute_window_bounded_by_kite_cap(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1m", limit=2000)
    span = fake.historical_calls[0]["to_date"] - fake.historical_calls[0]["from_date"]
    assert span.days == 60  # Kite's 1-minute per-request cap


def test_pagination_advances_past_boundary_no_duplicates(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    # limit=2000 daily -> 4000-day window -> two 2000-day chunks.
    out = zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1d", limit=2000)
    assert out["status"] == "ok"
    assert len(fake.historical_calls) == 2
    # Second chunk must start the day AFTER the first chunk's end (Kite ranges
    # are inclusive), so the boundary candle is fetched exactly once.
    assert fake.historical_calls[1]["from_date"] == (
        fake.historical_calls[0]["to_date"] + timedelta(days=1)
    )
    times = [b["time"] for b in out["bars"]]
    assert len(times) == len(set(times))


def test_instrument_dump_cached_per_exchange(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1d", limit=90)
    zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1d", limit=90)
    assert fake.instruments_calls == 1


def test_token_resolved_once_before_pagination(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    zsdk.get_historical_bars("RELIANCE", config=_cfg(), period="1d", limit=2000)
    assert fake.instruments_calls == 1  # not once per chunk


# ---------------------------------------------------------------------------
# Availability gating
# ---------------------------------------------------------------------------

def test_available_requires_import_and_creds(monkeypatch) -> None:
    class _DummyKite:
        pass

    def _raise_dep():
        raise zsdk.ZerodhaDependencyError("not installed")

    monkeypatch.setattr(zsdk, "_require_kite", lambda: _DummyKite)
    monkeypatch.setattr(zsdk, "load_config", lambda: _cfg())
    assert zsdk.zerodha_available() is True

    monkeypatch.setattr(zsdk, "load_config", lambda: zsdk.ZerodhaConfig(api_key="k"))
    assert zsdk.zerodha_available() is False  # import alone is not enough

    monkeypatch.setattr(zsdk, "load_config", lambda: _cfg())
    monkeypatch.setattr(zsdk, "_require_kite", _raise_dep)
    assert zsdk.zerodha_available() is False  # missing package is not enough


# ---------------------------------------------------------------------------
# Service-layer surface (service.py broker_sdk dispatch)
# ---------------------------------------------------------------------------

def test_get_account_snapshot_maps_kite_margins(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    out = zsdk.get_account_snapshot(_cfg())
    assert out["status"] == "ok"
    assert out["account"]["currency"] == "INR"
    assert out["account"]["cash"] == 50000.0
    assert out["account"]["margin_available"] == 123456.0
    assert out["account"]["margin_used"] == 6543.0
    assert out["account"]["collateral"] == 70000.0


def test_get_positions_maps_net_rows(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    out = zsdk.get_positions(_cfg())
    assert out["status"] == "ok"
    assert len(out["positions"]) == 1
    row = out["positions"][0]
    assert row["symbol"] == "RELIANCE"
    assert row["quantity"] == 5
    assert row["average_cost"] == 1500.0
    assert row["unrealized_pnl"] == 500.0
    assert row["multiplier"] == 1


def test_get_open_orders_filters_and_optional_executions(monkeypatch) -> None:
    fake = _FakeKite()
    _patch_kite(monkeypatch, fake)
    out = zsdk.get_open_orders(_cfg())
    assert out["status"] == "ok"
    assert [o["order_id"] for o in out["open_orders"]] == ["1001"]
    assert "executions" not in out

    out2 = zsdk.get_open_orders(_cfg(), include_executions=True)
    assert [o["order_id"] for o in out2["executions"]] == ["1002"]
    assert out2["executions"][0]["side"] == "sell"


def test_read_ops_error_envelope_on_broker_failure(monkeypatch) -> None:
    class _FailingKite:
        def margins(self):
            raise RuntimeError("kite down")

        def positions(self):
            raise RuntimeError("kite down")

        def orders(self):
            raise RuntimeError("kite down")

    _patch_kite(monkeypatch, _FailingKite())
    for out in (zsdk.get_account_snapshot(_cfg()),
                zsdk.get_positions(_cfg()),
                zsdk.get_open_orders(_cfg())):
        assert out["status"] == "error"
        assert out["error"] == "kite down"


def test_place_order_accepts_service_surface_kwargs() -> None:
    # service.py passes notional/time_in_force for every broker_sdk connector.
    out = zsdk.place_order(
        _cfg(), symbol="RELIANCE", side="buy", quantity=10,
        notional=15000.0, time_in_force="day",
    )
    assert out["status"] == "ok"
    assert out["is_paper"] is True


def test_cancel_order_paper_only_and_validation() -> None:
    out = zsdk.cancel_order(_cfg(), "PAPER-RELIANCE-B-10")
    assert out["status"] == "ok"
    assert out["cancelled"] is True

    out2 = zsdk.cancel_order(_cfg(), "")
    assert out2["status"] == "error"

    live = zsdk.ZerodhaConfig(api_key="k", access_token="t", profile="live")
    out3 = zsdk.cancel_order(live, "PAPER-RELIANCE-B-10")
    assert out3["status"] == "error"
    assert "paper" in out3["error"]


def test_service_dispatch_reaches_zerodha_sdk(monkeypatch) -> None:
    """check_connection('zerodha-paper-sdk') must route to the zerodha SDK
    (previously ValueError), returning the SDK's missing-config error."""
    # Deterministic: empty config regardless of any real zerodha.json on disk.
    monkeypatch.setattr(zsdk, "load_config", lambda: zsdk.ZerodhaConfig())
    from src.trading.service import check_connection

    out = check_connection("zerodha-paper-sdk")
    assert out["status"] == "error"
    assert "not configured" in out["error"]
    assert out["connector"] == "zerodha"
    assert out["profile_id"] == "zerodha-paper-sdk"
