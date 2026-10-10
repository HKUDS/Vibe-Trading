"""Options mandate gate (#1435): disabled by default, multiplier-aware, fail-closed.

Pure checks plus the commit/load round trip and the Robinhood order guard; every
broker is a mock and no real broker is called.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.live.paths as paths
from src.live.enforcement import (
    BREACH_KIND_INSTRUMENT,
    BREACH_KIND_QUANTITATIVE,
    BREACH_KIND_UNIVERSE,
    OrderIntent,
    check_mandate,
)
from src.live.mandate.commit import CommitError, commit_mandate
from src.live.mandate.model import (
    MANDATE_SCHEMA_VERSION,
    AssetClass,
    ConsentMeta,
    HardCaps,
    InstrumentType,
    Mandate,
    OptionLimits,
    UniverseConstraint,
)
from src.live.mandate.store import load_mandate
from src.live.options import OptionLeg, OptionOrderIntent, check_option_order, option_order_risk
from src.tools.propose_mandate_tool import ProposeMandateProfilesTool
from src.trading.connectors.robinhood import mcp as robinhood_mcp

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 9)
EXPIRY = "2026-11-20"

LIMITS = OptionLimits(
    max_premium_per_order_usd=1000.0,
    max_loss_per_order_usd=1500.0,
    max_premium_per_day_usd=2000.0,
    max_loss_per_day_usd=3000.0,
)


def _mandate(*, limits: OptionLimits | None = LIMITS, instruments=(InstrumentType.EQUITY, InstrumentType.OPTION)) -> Mandate:
    return Mandate(
        schema_version=MANDATE_SCHEMA_VERSION,
        hard_caps=HardCaps(
            account_funding_usd=10_000.0,
            max_order_notional_usd=5_000.0,
            max_total_exposure_usd=10_000.0,
            max_leverage=1.0,
            allowed_instruments=tuple(instruments),
            max_trades_per_day=5,
        ),
        universe=UniverseConstraint(
            asset_classes=(AssetClass.US_EQUITY,),
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=("GME",),
        ),
        consent=ConsentMeta(
            created_at="2026-10-01T00:00:00Z",
            consent_token_sha256="0" * 64,
            broker="robinhood",
            account_ref="acct",
            expires_at="2026-10-31T00:00:00Z",
        ),
        option_limits=limits,
    )


def _leg(option_type="call", side="buy", strike=100.0, expiration=EXPIRY) -> OptionLeg:
    return OptionLeg(option_type=option_type, side=side, strike=strike, expiration=expiration)


def _order(*legs: OptionLeg, quantity=2, limit_price=2.5, price_effect="debit", multiplier=100.0, atomic=True) -> OptionOrderIntent:
    return OptionOrderIntent(
        underlying="AAPL",
        legs=legs or (_leg(),),
        quantity=quantity,
        limit_price=limit_price,
        price_effect=price_effect,
        multiplier=multiplier,
        atomic=atomic,
    )


def _check(intent: OptionOrderIntent, mandate: Mandate | None = None, **kwargs):
    params = {"daily_count": 0, "premium_used_today_usd": 0.0, "max_loss_used_today_usd": 0.0, **kwargs}
    return check_option_order(
        mandate or _mandate(), intent, broker="robinhood", remote_tool="place_option_order", today=TODAY, **params
    )


# --------------------------------------------------------------------------- #
# Multiplier and max-loss math                                                 #
# --------------------------------------------------------------------------- #


def test_long_call_premium_and_max_loss_apply_the_multiplier() -> None:
    risk = option_order_risk(_order())
    assert risk.premium_usd == pytest.approx(2.5 * 2 * 100)  # 500
    assert risk.max_loss_usd == pytest.approx(500.0)
    assert risk.naked_short is False


def test_non_standard_multiplier_is_used_not_assumed() -> None:
    risk = option_order_risk(_order(multiplier=10.0))
    assert risk.premium_usd == pytest.approx(50.0)


def test_credit_vertical_max_loss_is_width_minus_credit() -> None:
    # Sell 100 put, buy 95 put for 1.50 credit, 2 spreads: (5 - 1.5) * 100 * 2.
    spread = _order(_leg("put", "sell", 100.0), _leg("put", "buy", 95.0), limit_price=1.5, price_effect="credit")
    risk = option_order_risk(spread)
    assert risk.premium_usd == 0.0
    assert risk.max_loss_usd == pytest.approx(700.0)
    assert risk.naked_short is False


def test_debit_vertical_max_loss_is_the_debit() -> None:
    spread = _order(_leg("call", "buy", 100.0), _leg("call", "sell", 110.0), limit_price=3.0)
    assert option_order_risk(spread).max_loss_usd == pytest.approx(600.0)


def test_naked_short_put_loss_is_strike_times_multiplier_minus_credit() -> None:
    risk = option_order_risk(_order(_leg("put", "sell", 50.0), quantity=1, limit_price=2.0, price_effect="credit"))
    assert risk.naked_short is True
    assert risk.max_loss_usd == pytest.approx(50 * 100 - 200)


def test_naked_short_call_loss_is_unbounded() -> None:
    risk = option_order_risk(_order(_leg("call", "sell"), price_effect="credit"))
    assert risk.max_loss_usd is None


# --------------------------------------------------------------------------- #
# Gate decisions                                                               #
# --------------------------------------------------------------------------- #


def test_in_limit_single_leg_and_spread_are_allowed() -> None:
    assert _check(_order()) is None
    spread = _order(_leg("put", "sell", 100.0), _leg("put", "buy", 95.0), limit_price=1.5, price_effect="credit")
    assert _check(spread) is None


def test_options_disabled_by_default() -> None:
    breach = _check(_order(), _mandate(limits=None))
    assert breach.kind == BREACH_KIND_INSTRUMENT
    assert breach.limit == "option_limits"


def test_options_need_the_instrument_too() -> None:
    breach = _check(_order(), _mandate(instruments=(InstrumentType.EQUITY,)))
    assert (breach.kind, breach.limit) == (BREACH_KIND_INSTRUMENT, "allowed_instruments")


def test_excluded_underlying_is_denied() -> None:
    breach = _check(replace(_order(), underlying="gme"))
    assert breach.kind == BREACH_KIND_UNIVERSE


@pytest.mark.parametrize(
    "kwargs, limit, attempted",
    [
        # 5 contracts x 2.50 x 100 = 1250 premium > 1000.
        ({"quantity": 5}, "max_premium_per_order_usd", 1250.0),
        ({"premium_used_today_usd": 1600.0}, "max_premium_per_day_usd", 2100.0),
        ({"daily_count": 5}, "max_trades_per_day", 6.0),
    ],
)
def test_over_limit_orders_pause(kwargs, limit, attempted) -> None:
    quantity = kwargs.pop("quantity", 2)
    breach = _check(_order(quantity=quantity), **kwargs)
    assert breach.kind == BREACH_KIND_QUANTITATIVE
    assert breach.limit == limit
    assert breach.attempted_value == pytest.approx(attempted)
    assert breach.proposed_action.instrument_type is InstrumentType.OPTION


def test_credit_spread_over_max_loss_pauses_even_with_zero_premium() -> None:
    # (10 - 1) * 100 * 2 = 1800 max loss > 1500, while premium paid is 0.
    spread = _order(_leg("put", "sell", 100.0), _leg("put", "buy", 90.0), limit_price=1.0, price_effect="credit")
    breach = _check(spread)
    assert (breach.limit, breach.attempted_value) == ("max_loss_per_order_usd", pytest.approx(1800.0))
    breach = _check(_order(), max_loss_used_today_usd=2600.0)
    assert breach.limit == "max_loss_per_day_usd"


def test_naked_short_refused_unless_explicitly_allowed() -> None:
    naked_put = _order(_leg("put", "sell", 10.0), quantity=1, limit_price=0.5, price_effect="credit")
    assert _check(naked_put).limit == "allow_naked_short"
    permissive = _mandate(limits=replace(LIMITS, allow_naked_short=True))
    assert _check(naked_put, permissive) is None
    # A naked call stays refused: no limit can bound it.
    naked_call = _order(_leg("call", "sell"), price_effect="credit")
    assert _check(naked_call, permissive).limit == "option_max_loss"


@pytest.mark.parametrize(
    "intent, reason",
    [
        (_order(_leg("call", "buy", 100.0), _leg("call", "sell", 110.0), atomic=False), "atomically"),
        (_order(_leg("call", "buy"), _leg("call", "sell", 110.0, "2026-12-18")), "one expiration"),
        (_order(_leg(expiration="2026-01-16")), "expired"),
        (_order(quantity=0), "whole number"),
        (_order(quantity=1.5), "whole number"),
        (_order(limit_price=float("nan")), "positive numbers"),
        (_order(multiplier=0), "positive numbers"),
        (_order(_leg(option_type="straddle")), "call/put"),
    ],
)
def test_malformed_or_non_atomic_orders_are_denied(intent, reason) -> None:
    breach = _check(intent)
    assert breach.kind == BREACH_KIND_INSTRUMENT
    assert reason in breach.detail


def test_equity_gate_never_prices_an_option_as_shares() -> None:
    intent = OrderIntent(
        symbol="AAPL", side="buy", notional_usd=10.0, quantity=None, instrument_type=InstrumentType.OPTION
    )
    breach = check_mandate(_mandate(), intent, [], {}, broker="robinhood", remote_tool="place_equity_order", daily_count=0)
    assert breach.kind == BREACH_KIND_INSTRUMENT


# --------------------------------------------------------------------------- #
# Explicit opt-in at commit, and load round trip                               #
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


def _proposal_id() -> str:
    raw = ProposeMandateProfilesTool().execute(
        broker="robinhood",
        intent="options income",
        ceilings={
            "account_funding_usd": 5000.0,
            "max_order_usd": 1500.0,
            "max_total_exposure_usd": 5000.0,
            "daily_trade_cap": 10,
            "leverage": "none",
            "instruments": ["equity"],
        },
        session_id="s1",
    )
    return json.loads(raw)["proposal_id"]


def _commit(option_limits=None):
    return commit_mandate(
        proposal_id=_proposal_id(), ordinal=1, adjustments=None, consent_ack=True,
        broker="robinhood", account_ref="acct", option_limits=option_limits,
    )


def test_commit_without_option_limits_leaves_options_disabled(live_runtime: Path) -> None:
    _commit()
    assert load_mandate("robinhood").option_limits is None


def test_commit_with_explicit_option_limits_round_trips(live_runtime: Path) -> None:
    _commit({**LIMITS.__dict__, "allow_naked_short": False})
    assert load_mandate("robinhood").option_limits == LIMITS


@pytest.mark.parametrize(
    "bad",
    [
        {"max_premium_per_order_usd": 1.0},  # missing amounts
        {**LIMITS.__dict__, "max_loss_per_day_usd": -1.0},
        {**LIMITS.__dict__, "max_loss_per_day_usd": float("inf")},
        {**LIMITS.__dict__, "allow_naked_short": "yes"},
        {**LIMITS.__dict__, "max_contracts": 3},
    ],
)
def test_commit_rejects_invalid_option_limits(live_runtime: Path, bad) -> None:
    with pytest.raises(CommitError):
        _commit(bad)
    assert load_mandate("robinhood") is None


def test_robinhood_options_orders_flagged_unsupported() -> None:
    assert robinhood_mcp.OPTIONS_ORDERS_SUPPORTED is False
