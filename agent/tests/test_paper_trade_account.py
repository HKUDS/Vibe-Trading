"""T5 — incremental account model (``account.py``).

Pure in-memory tests: the start-date rule is decided from INJECTED ``today`` /
``next_trading_day`` values (never a clock), the document round-trips losslessly,
and the two ledger transitions refuse to move the watermark backwards.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.tools.paper_trade.account import (
    ACCOUNT_SCHEMA_VERSION,
    INVALID_ACCOUNT,
    INVALID_INITIAL_POSITIONS,
    START_DATE_IN_PAST,
    START_DATE_NOT_ADMISSIBLE,
    AccountError,
    PaperTradeAccount,
    create_account,
    require_date,
)
from src.tools.paper_trade.schema import AccountState, Position
from src.tools.paper_trade.state_hash import state_hash

TODAY = "2026-03-02"  # Monday
NEXT_TRADING_DAY = "2026-03-03"
NOW = "2026-03-02T15:05:00+08:00"


def _create(**overrides):
    kwargs = {
        "account_id": "acct_t5",
        "market": "cn_a",
        "start_date": TODAY,
        "initial_cash": 100000.0,
        "initial_positions": (),
        "today": TODAY,
        "next_trading_day": NEXT_TRADING_DAY,
        "now": NOW,
    }
    kwargs.update(overrides)
    return create_account(**kwargs)


def test_start_date_today_is_admissible() -> None:
    account = _create()
    assert (account.account_id, account.market, account.start_date) == ("acct_t5", "cn_a", TODAY)
    assert account.cash == account.initial_cash == 100000.0
    assert account.positions == account.initial_positions == ()
    assert account.watermark is None
    assert account.interval == "5m"
    assert account.schema_version == ACCOUNT_SCHEMA_VERSION


def test_from_dict_refuses_a_market_interval_mismatch() -> None:
    document = _create(market="us", interval="1d").to_dict()
    document["interval"] = "5m"

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "cn_a-only" in caught.value.message


def test_from_dict_refuses_duplicate_position_symbols() -> None:
    document = _create().to_dict()
    document["positions"] = [
        {"symbol": "600519.SH", "qty": 100.0, "avg_cost": 1400.0},
        {"symbol": "600519.SH", "qty": 100.0, "avg_cost": 1400.0},
    ]

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "same symbol twice" in caught.value.message


def test_from_dict_refuses_a_non_positive_position() -> None:
    document = _create().to_dict()
    document["positions"] = [{"symbol": "600519.SH", "qty": 0.0, "avg_cost": 1400.0}]

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "qty must be > 0" in caught.value.message


def test_from_dict_refuses_an_unknown_path_model() -> None:
    document = _create().to_dict()
    document["path_model"] = "vwap"

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "path_model" in caught.value.message


def test_start_date_next_trading_day_is_admissible() -> None:
    account = _create(start_date=NEXT_TRADING_DAY)
    assert account.start_date == NEXT_TRADING_DAY
    assert account.watermark is None


def test_start_date_in_the_past_is_refused_with_a_stable_code() -> None:
    with pytest.raises(AccountError) as excinfo:
        _create(start_date="2026-02-27")
    assert excinfo.value.code == START_DATE_IN_PAST
    assert "backtest" in excinfo.value.message


@pytest.mark.parametrize("start_date", ["2026-03-04", "2026-04-01"])
def test_start_date_beyond_the_next_trading_day_is_not_admissible(start_date: str) -> None:
    with pytest.raises(AccountError) as excinfo:
        _create(start_date=start_date)
    assert excinfo.value.code == START_DATE_NOT_ADMISSIBLE


@pytest.mark.parametrize("account_id", ["", "../escape", "a/b", ".hidden", "x" * 65])
def test_account_id_must_be_a_safe_single_path_segment(account_id: str) -> None:
    with pytest.raises(AccountError) as excinfo:
        _create(account_id=account_id)
    assert excinfo.value.code == INVALID_ACCOUNT


def test_unknown_market_and_negative_cash_are_refused() -> None:
    with pytest.raises(AccountError) as market_error:
        _create(market="crypto")
    assert market_error.value.code == INVALID_ACCOUNT
    with pytest.raises(AccountError) as cash_error:
        _create(initial_cash=-1.0)
    assert cash_error.value.code == INVALID_ACCOUNT


def test_duplicate_and_degenerate_initial_positions_are_refused() -> None:
    duplicate = (
        Position("600519.SH", 100, 1500.0),
        Position("600519.SH", 200, 1510.0),
    )
    with pytest.raises(AccountError) as duplicate_error:
        _create(initial_positions=duplicate)
    assert duplicate_error.value.code == INVALID_INITIAL_POSITIONS

    with pytest.raises(AccountError) as qty_error:
        _create(initial_positions=(Position("600519.SH", 0, 1500.0),))
    assert qty_error.value.code == INVALID_INITIAL_POSITIONS

    with pytest.raises(AccountError) as cost_error:
        _create(initial_positions=(Position("600519.SH", 100, -1.0),))
    assert cost_error.value.code == INVALID_INITIAL_POSITIONS


def test_five_minute_interval_is_cn_a_only() -> None:
    with pytest.raises(AccountError) as excinfo:
        _create(market="us")
    assert excinfo.value.code == INVALID_ACCOUNT
    assert "cn_a-only" in excinfo.value.message
    assert _create(market="us", interval="1d").request_fields() == {}


def test_initial_positions_are_carried_into_the_live_ledger() -> None:
    account = _create(initial_positions=[{"symbol": "600519.SH", "qty": 100, "avg_cost": 1500.0}])
    assert account.initial_positions == account.positions
    assert account.state() == AccountState(cash=100000.0, positions=account.positions)
    assert account.state_payload() == {
        "cash": 100000.0,
        "positions": [{"symbol": "600519.SH", "qty": 100.0, "avg_cost": 1500.0}],
    }


def test_document_round_trip_is_lossless_and_ignores_unknown_keys() -> None:
    account = _create(initial_positions=(Position("600519.SH", 100, 1500.0),))
    document = account.to_dict()
    assert document["schema_version"] == ACCOUNT_SCHEMA_VERSION
    assert PaperTradeAccount.from_dict(document) == account

    document["a_field_from_a_newer_writer"] = {"ignored": True}
    assert PaperTradeAccount.from_dict(document) == account


def test_document_with_an_unknown_schema_version_is_refused() -> None:
    document = _create().to_dict()
    document["schema_version"] = "pt-account-v99"
    with pytest.raises(AccountError) as excinfo:
        PaperTradeAccount.from_dict(document)
    assert excinfo.value.code == INVALID_ACCOUNT


def test_state_digest_is_the_frozen_jcs_state_hash() -> None:
    account = _create()
    assert account.state_digest() == state_hash(account.state_payload())


def test_request_fields_are_emitted_only_when_non_default() -> None:
    assert _create(interval="1d").request_fields() == {}
    assert _create().request_fields() == {
        "interval": "5m",
        "path_model": "bar_median",
        "fill_model": "all_or_none",
        "session": "cn_a",
    }


def test_advance_replaces_the_ledger_and_moves_the_watermark_forward() -> None:
    account = _create(initial_positions=(Position("600519.SH", 100, 1500.0),))
    advanced = account.with_advance(
        end_state=AccountState(cash=90000.0, positions=(Position("600519.SH", 50, 1500.0),)),
        watermark=TODAY,
        engine_fingerprint="fp-day-1",
    )
    assert advanced.cash == 90000.0
    assert advanced.positions == (Position("600519.SH", 50, 1500.0),)
    assert advanced.initial_positions == account.initial_positions
    assert advanced.watermark == TODAY
    assert advanced.engine_fingerprint == "fp-day-1"


def test_advance_refuses_to_move_the_watermark_backwards() -> None:
    account = _create().with_advance(
        end_state=AccountState(cash=100000.0), watermark=NEXT_TRADING_DAY
    )
    with pytest.raises(ValueError, match="watermark must move forward"):
        account.with_advance(end_state=AccountState(cash=1.0), watermark=NEXT_TRADING_DAY)
    with pytest.raises(ValueError, match="watermark must move forward"):
        account.with_non_trading_day(TODAY)


def test_non_trading_day_advances_without_touching_the_ledger() -> None:
    account = _create()
    skipped = account.with_non_trading_day(TODAY)
    assert skipped.watermark == TODAY
    assert skipped.non_trading_days == (TODAY,)
    assert (skipped.cash, skipped.positions) == (account.cash, account.positions)
    # Recording the same closed day twice must not duplicate the evidence.
    assert skipped.with_non_trading_day(NEXT_TRADING_DAY).non_trading_days == (TODAY, NEXT_TRADING_DAY)


@pytest.mark.parametrize("value", ["2026-3-2", "20260302", "2026-13-01", "", None])
def test_require_date_rejects_loose_spellings(value) -> None:
    with pytest.raises(AccountError):
        require_date(value, "value")


def test_account_is_frozen() -> None:
    account = _create()
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.cash = 1.0  # type: ignore[misc]


def test_fee_model_is_locked_and_round_trips() -> None:
    account = _create(fee_model={"transfer_fee": 0.00001, "commission_rate": 0.00025})
    assert dict(account.fee_model) == {
        "commission_rate": 0.00025, "transfer_fee": 0.00001,
    }
    assert PaperTradeAccount.from_dict(account.to_dict()) == account


def test_fee_model_rejects_a_negative_value() -> None:
    with pytest.raises(AccountError) as caught:
        _create(fee_model={"commission_rate": -0.0001})
    assert caught.value.code == INVALID_ACCOUNT
    assert "fee_model[commission_rate]" in caught.value.message


def test_from_dict_requires_interval() -> None:
    document = _create().to_dict()
    del document["interval"]

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "interval is required" in caught.value.message


def test_from_dict_requires_path_model() -> None:
    document = _create().to_dict()
    del document["path_model"]

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "path_model is required" in caught.value.message


def test_from_dict_requires_fill_model() -> None:
    document = _create().to_dict()
    del document["fill_model"]

    with pytest.raises(AccountError) as caught:
        PaperTradeAccount.from_dict(document)
    assert caught.value.code == INVALID_ACCOUNT
    assert "fill_model is required" in caught.value.message
