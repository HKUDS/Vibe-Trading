"""Tests for live-runtime triggers (src/live/runtime/triggers.py, SPEC §7.5 c4).

The decision core is pure — it takes ``now_ms`` as an argument and reads no
clock — so every market-session / interval / event case is pinned to a fixed
epoch-millisecond instant and asserted deterministically.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Mapping

import pytest

from src.live.runtime import triggers
from src.live.runtime.triggers import (
    Trigger,
    TriggerKind,
    due_now,
    market_is_open,
    market_is_open_at,
)


def _ms(year: int, month: int, day: int, hour: int, minute: int, tz_name: str) -> int:
    """Epoch milliseconds for a wall-clock instant in a named timezone."""
    from zoneinfo import ZoneInfo

    dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz_name))
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Market sessions — us_equity                                                  #
# --------------------------------------------------------------------------- #

# 2026-05-29 is a Friday (regular trading day, not a holiday).
_FRI = (2026, 5, 29)
# 2026-05-30 is a Saturday.
_SAT = (2026, 5, 30)
# 2026-05-25 is Memorial Day (a holiday that falls on a weekday Monday).
_MEMORIAL = (2026, 5, 25)


@pytest.mark.parametrize(
    ("now_ms", "expected"),
    [
        # Mid-session weekday RTH.
        (_ms(*_FRI, 12, 0, "America/New_York"), True),
        # Exactly at the open bell (inclusive).
        (_ms(*_FRI, 9, 30, "America/New_York"), True),
        # One minute before open — pre-market, closed.
        (_ms(*_FRI, 9, 29, "America/New_York"), False),
        # Exactly at the close bell (exclusive) — closed.
        (_ms(*_FRI, 16, 0, "America/New_York"), False),
        # One minute before close — open.
        (_ms(*_FRI, 15, 59, "America/New_York"), True),
        # After hours — closed.
        (_ms(*_FRI, 18, 0, "America/New_York"), False),
        # Weekend (Saturday) at would-be-session time — closed.
        (_ms(*_SAT, 12, 0, "America/New_York"), False),
        # Weekday holiday (Memorial Day) at session time — closed.
        (_ms(*_MEMORIAL, 12, 0, "America/New_York"), False),
    ],
)
def test_us_equity_open_windows(now_ms: int, expected: bool) -> None:
    assert market_is_open_at("us_equity", now_ms) is expected


# 2026-11-27 is the Friday after Thanksgiving: NYSE closes at 13:00 ET.
_BF_2026 = (2026, 11, 27)
# 2026-12-24 is a Thursday Christmas Eve: NYSE closes at 13:00 ET.
_XMAS_EVE_2026 = (2026, 12, 24)
# 2027-11-26 is the Friday after Thanksgiving 2027.
_BF_2027 = (2027, 11, 26)


@pytest.mark.parametrize(
    ("now_ms", "expected"),
    [
        (_ms(*_BF_2026, 9, 30, "America/New_York"), True),
        (_ms(*_BF_2026, 12, 59, "America/New_York"), True),
        # The early bell is exclusive, same convention as the 16:00 close.
        (_ms(*_BF_2026, 13, 0, "America/New_York"), False),
        (_ms(*_BF_2026, 13, 30, "America/New_York"), False),
        (_ms(*_BF_2026, 15, 30, "America/New_York"), False),
        (_ms(*_XMAS_EVE_2026, 12, 59, "America/New_York"), True),
        (_ms(*_XMAS_EVE_2026, 13, 0, "America/New_York"), False),
        (_ms(*_BF_2027, 12, 59, "America/New_York"), True),
        (_ms(*_BF_2027, 13, 0, "America/New_York"), False),
    ],
)
def test_us_equity_early_close_windows(now_ms: int, expected: bool) -> None:
    assert market_is_open_at("us_equity", now_ms) is expected


def test_us_equity_observed_christmas_stays_a_full_closure() -> None:
    # 2027-12-24 is the observed Christmas holiday, not an early close: the
    # morning session must not trade either.
    assert market_is_open_at("us_equity", _ms(2027, 12, 24, 10, 0, "America/New_York")) is False


def test_early_close_table_is_internally_consistent() -> None:
    spec = triggers.MARKET_SPECS["us_equity"]
    for day, bell in spec.early_closes.items():
        assert day.weekday() in spec.weekdays
        assert day not in spec.holidays
        assert spec.open_time < bell < spec.close_time


def test_us_equity_uses_ny_local_not_utc() -> None:
    # 14:00 UTC on the Friday is 10:00 ET — inside RTH despite 14:00 looking
    # like afternoon if (wrongly) read as local.
    utc_1400 = _ms(*_FRI, 14, 0, "UTC")
    assert market_is_open_at("us_equity", utc_1400) is True
    # 21:00 UTC is 17:00 ET — after close.
    utc_2100 = _ms(*_FRI, 21, 0, "UTC")
    assert market_is_open_at("us_equity", utc_2100) is False


# --------------------------------------------------------------------------- #
# Market sessions — crypto (24/7)                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "now_ms",
    [
        _ms(*_FRI, 12, 0, "UTC"),  # weekday noon
        _ms(*_SAT, 3, 0, "UTC"),  # weekend small hours
        _ms(*_MEMORIAL, 0, 0, "UTC"),  # an equity holiday
        0,  # the UNIX epoch
    ],
)
def test_crypto_always_open(now_ms: int) -> None:
    assert market_is_open_at("crypto", now_ms) is True


def test_unknown_market_fails_loud() -> None:
    # An unknown market must never be silently treated as open.
    with pytest.raises(ValueError):
        market_is_open_at("forex_zzz", 0)


# --------------------------------------------------------------------------- #
# due_now — MARKET                                                             #
# --------------------------------------------------------------------------- #


def test_due_now_market_delegates_to_session() -> None:
    trig = Trigger.market("us_equity")
    assert due_now(trig, _ms(*_FRI, 12, 0, "America/New_York")) is True
    assert due_now(trig, _ms(*_SAT, 12, 0, "America/New_York")) is False


def test_market_trigger_rejects_unknown_market() -> None:
    with pytest.raises(ValueError):
        Trigger.market("nope")


def test_market_trigger_without_market_raises() -> None:
    bad = Trigger(kind=TriggerKind.MARKET, market=None)
    with pytest.raises(ValueError):
        due_now(bad, 0)


def test_non_market_triggers_leave_market_unset() -> None:
    """``market`` is ``None`` on INTERVAL/EVENT triggers, not the factory.

    ``Trigger.market`` is both a dataclass field and the MARKET constructor.
    Declared inside the class body the constructor replaces the field's
    ``None`` default before ``@dataclass`` reads it, so every INTERVAL/EVENT
    trigger carried a bound method in ``market``. That is invisible to
    :func:`due_now` (which only inspects ``market`` for MARKET triggers) but
    wrong wherever the field is read or serialised on its own.
    """
    assert Trigger.interval(60_000).market is None
    assert Trigger.event(lambda _state: True).market is None

    # The MARKET factory keeps its public name and still fills the field.
    assert Trigger.market("us_equity").market == "us_equity"


def test_interval_trigger_serialises_to_json() -> None:
    """An INTERVAL trigger must survive ``dataclasses.asdict`` + ``json.dumps``.

    No production path serialises a ``Trigger`` today — jobs persist a plain
    kind string, not the descriptor — but the first caller that does must not
    trip over a bound method in ``market``. Before the field default was
    restored, this raised ``TypeError``. Pinning the contract makes that latent
    hazard explicit.

    EVENT triggers are deliberately out of scope: their ``predicate`` is a
    callable by design, so they are not a serialisable shape in the first place.
    """
    restored = json.loads(json.dumps(dataclasses.asdict(Trigger.interval(60_000))))
    assert restored["market"] is None


def test_market_field_default_and_factory_are_both_intact() -> None:
    """Pin the mechanism, not just the observable effect.

    The recorded field default is what ``@dataclass`` wrote into ``__init__``;
    asserting on it catches a regression at the source instead of one instance
    later. The factory is pinned by name and by introspection so the MARKET
    constructor cannot quietly disappear or start reporting a private name.
    """
    import inspect

    assert Trigger.__dataclass_fields__["market"].default is None
    assert inspect.signature(Trigger).parameters["market"].default is None

    assert Trigger.market("us_equity").market == "us_equity"
    assert callable(Trigger.market)
    assert Trigger.market.__qualname__ == "Trigger.market"
    assert Trigger.market.__name__ == "market"
    # The factory is bound after the class body; the private placeholder must
    # not survive as a second public way to build a MARKET trigger.
    assert not hasattr(Trigger, "_market")


@pytest.mark.parametrize("decorate", [False, True])
def test_market_factory_binds_to_subclass(decorate: bool) -> None:
    """The deferred factory must retain normal classmethod inheritance."""

    class DerivedTrigger(Trigger):
        pass

    if decorate:
        DerivedTrigger = dataclasses.dataclass(frozen=True)(DerivedTrigger)

    trigger = DerivedTrigger.market("crypto")
    assert type(trigger) is DerivedTrigger
    assert DerivedTrigger.market.__self__ is DerivedTrigger
    assert trigger.kind is TriggerKind.MARKET
    assert trigger.market == "crypto"
    assert DerivedTrigger.interval(1).market is None
    assert DerivedTrigger.event(lambda _state: True).market is None
    assert dataclasses.replace(trigger).market == "crypto"
    assert json.loads(json.dumps(dataclasses.asdict(trigger)))["market"] == "crypto"


# --------------------------------------------------------------------------- #
# due_now — INTERVAL                                                           #
# --------------------------------------------------------------------------- #


def test_interval_due_on_exact_multiples() -> None:
    trig = Trigger.interval(60_000)  # every 60 s, anchored at epoch 0
    assert due_now(trig, 0) is True
    assert due_now(trig, 60_000) is True
    assert due_now(trig, 120_000) is True
    # Off-boundary instants are not due.
    assert due_now(trig, 59_999) is False
    assert due_now(trig, 60_001) is False


def test_interval_respects_phase_anchor() -> None:
    trig = Trigger.interval(60_000, epoch_ms=10_000)
    assert due_now(trig, 10_000) is True
    assert due_now(trig, 70_000) is True
    assert due_now(trig, 10_001) is False
    # Before the anchor it is never due.
    assert due_now(trig, 0) is False


def test_interval_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Trigger.interval(0)
    with pytest.raises(ValueError):
        Trigger.interval(-1000)
    # A hand-built malformed interval trigger also raises at evaluation.
    bad = Trigger(kind=TriggerKind.INTERVAL, interval_ms=0)
    with pytest.raises(ValueError):
        due_now(bad, 0)


# --------------------------------------------------------------------------- #
# due_now — EVENT                                                              #
# --------------------------------------------------------------------------- #


def test_event_predicate_drives_due() -> None:
    # Fire when last price crosses above a threshold supplied by the runner.
    def crossed_above(state: Mapping[str, object]) -> bool:
        return float(state.get("last_price", 0.0)) >= 150.0

    trig = Trigger.event(crossed_above)
    assert due_now(trig, 0, event_state={"last_price": 151.0}) is True
    assert due_now(trig, 0, event_state={"last_price": 149.0}) is False
    # No state supplied -> predicate sees empty mapping -> not due.
    assert due_now(trig, 0) is False


def test_event_fill_predicate() -> None:
    def has_fill(state: Mapping[str, object]) -> bool:
        return bool(state.get("filled"))

    trig = Trigger.event(has_fill)
    assert due_now(trig, 12345, event_state={"filled": True}) is True
    assert due_now(trig, 12345, event_state={"filled": False}) is False


def test_event_trigger_without_predicate_raises() -> None:
    bad = Trigger(kind=TriggerKind.EVENT, predicate=None)
    with pytest.raises(ValueError):
        due_now(bad, 0)


# --------------------------------------------------------------------------- #
# Immutability + clock wrappers                                                #
# --------------------------------------------------------------------------- #


def test_trigger_is_frozen() -> None:
    trig = Trigger.interval(1000)
    with pytest.raises(Exception):
        trig.interval_ms = 2000  # type: ignore[misc]


def test_market_is_open_wrapper_delegates_to_pure_core(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the wall clock to a known weekend instant; the wrapper must agree
    # with the pure core fed the same now_ms.
    fixed = _ms(*_SAT, 12, 0, "America/New_York")
    monkeypatch.setattr(triggers, "_now_ms", lambda: fixed)
    assert market_is_open("us_equity") is False
    assert market_is_open("us_equity") == market_is_open_at("us_equity", fixed)
    assert market_is_open("crypto") is True


def test_due_now_at_wrapper_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = _ms(*_FRI, 12, 0, "America/New_York")
    monkeypatch.setattr(triggers, "_now_ms", lambda: fixed)
    trig = Trigger.market("us_equity")
    assert triggers.due_now_at(trig) is True
    assert triggers.due_now_at(trig) == due_now(trig, fixed)


def test_now_ms_is_utc_epoch_ms() -> None:
    # Sanity: the real clock reader returns a plausible epoch-ms value.
    before = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    val = triggers._now_ms()
    after = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    assert before <= val <= after + 1000
