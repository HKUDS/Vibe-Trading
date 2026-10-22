"""T5 — daily advance, idempotency, crash recovery, locking and catch-up.

All fakes: an injected calendar DataFrame and an injected ``step_fn``.  No
network, no clock (``today`` / ``now`` are literals), no connection to the
matching engine except the adapter test, which monkeypatches the tool surface.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.tools.paper_trade import engine_adapter, tool
from src.tools.paper_trade.account import create_account
from src.tools.paper_trade.engine_adapter import PaperDataNotReady, PaperStepRefused, StepOutcome
from src.tools.paper_trade.runner import (
    CODE_BEFORE_START_DATE,
    CODE_TRADE_DATE_IN_FUTURE,
    CODE_WATERMARK_GAP,
    STATUS_ACCOUNT_LOCKED,
    STATUS_APPLIED,
    STATUS_DATA_MISSING,
    STATUS_NON_TRADING_DAY,
    STATUS_RECOVERY_REQUIRED,
    STATUS_STEP_ALREADY_APPLIED,
    catch_up,
    step,
)
from src.tools.paper_trade.schema import AccountState, Fill, parse_request
from src.tools.paper_trade.state_hash import compute_received_state_hash, state_hash
from src.tools.paper_trade.storage_io import MANIFEST_FILE, STEP_FILE, dumps
from src.tools.paper_trade.store import AccountStore

ACCOUNT_ID = "acct_runner"
NOW = "2026-03-02T15:05:00+08:00"
MONDAY = "2026-03-02"
FIVE_DAYS = ("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06")


class FakeCalendar:
    """The structural ``TradeCalendarClient`` shape ``calendar.py`` consumes."""

    def __init__(self, open_days) -> None:
        self.open_days = set(open_days)
        self.queries: list[tuple[str, str]] = []

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        self.queries.append((start_date, end_date))
        rows = []
        day = dt.date.fromisoformat(start_date)
        last = dt.date.fromisoformat(end_date)
        while day <= last:
            text = day.isoformat()
            rows.append(
                {
                    "exchange": "SSE",
                    "cal_date": text,
                    "is_open": 1 if text in self.open_days else 0,
                    "pretrade_date": "",
                }
            )
            day += dt.timedelta(days=1)
        return pd.DataFrame(rows)


class RecordingStep:
    """Debits a fixed amount and records the exact input state per day."""

    def __init__(self, amount: float = 10.0, fingerprint: str = "fp-day") -> None:
        self.amount = amount
        self.fingerprint = fingerprint
        self.inputs: list[dict] = []
        self.days: list[str] = []

    def __call__(self, account, trade_date: str) -> StepOutcome:
        payload = account.state_payload()
        self.inputs.append(payload)
        self.days.append(trade_date)
        return StepOutcome(
            end_state=AccountState(cash=account.cash - self.amount, positions=account.positions),
            fills=(
                Fill(
                    trade_date=trade_date,
                    symbol="600519.SH",
                    side="buy",
                    qty=100,
                    price=10.0,
                    fee=0.1,
                ),
            ),
            orders=({"symbol": "600519.SH", "side": "buy", "qty": 100},),
            engine_fingerprint=self.fingerprint,
            received_state_hash=compute_received_state_hash(
                account_id=account.account_id,
                market=account.market,
                account_state=payload,
                fee_model={},
                from_date=trade_date,
                to_date=trade_date,
            ),
            effective_fee_model={},
        )


class FailingStep(RecordingStep):
    def __init__(self, fail_on: str) -> None:
        super().__init__()
        self.fail_on = fail_on

    def __call__(self, account, trade_date: str) -> StepOutcome:
        if trade_date == self.fail_on:
            raise PaperDataNotReady("PAPER_DATA_NOT_READY: stk_mins quota exhausted")
        return super().__call__(account, trade_date)


def _account(**overrides):
    kwargs = {
        "account_id": ACCOUNT_ID,
        "market": "cn_a",
        "start_date": MONDAY,
        "initial_cash": 100000.0,
        "today": MONDAY,
        "next_trading_day": "2026-03-03",
        "now": NOW,
    }
    kwargs.update(overrides)
    return create_account(**kwargs)


def _store(tmp_path: Path, **account_overrides) -> AccountStore:
    store = AccountStore(tmp_path / "paper_trade")
    store.create(_account(**account_overrides))
    return store


def _bytes(store: AccountStore) -> bytes:
    return store.account_path(ACCOUNT_ID).read_bytes()


def _run(
    store: AccountStore,
    calendar: FakeCalendar,
    step_fn,
    day: str | None,
    *,
    today: str = FIVE_DAYS[-1],
    **kwargs,
):
    return step(
        ACCOUNT_ID,
        day,
        step_fn=step_fn,
        calendar_client=calendar,
        today=today,
        now=NOW,
        store=store,
        **kwargs,
    )


# ── the 5-day chain ──


def test_five_day_chain_threads_each_output_into_the_next_input(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    step_fn = RecordingStep()

    results = [_run(store, calendar, step_fn, day) for day in FIVE_DAYS]

    assert [item.status for item in results] == [STATUS_APPLIED] * 5
    assert [item.watermark for item in results] == list(FIVE_DAYS)
    assert step_fn.days == list(FIVE_DAYS)
    for index in range(1, 5):
        previous = store.read_step(ACCOUNT_ID, FIVE_DAYS[index - 1])
        assert step_fn.inputs[index] == previous.step["end_state"]
        assert step_fn.inputs[index] == json.loads(json.dumps(previous.step["end_state"]))
        current = store.read_step(ACCOUNT_ID, FIVE_DAYS[index])
        assert current.step["input_state_hash"] == previous.step["end_state_hash"]
    assert store.load(ACCOUNT_ID).cash == 100000.0 - 5 * 10.0
    assert store.list_steps(ACCOUNT_ID) == FIVE_DAYS


def test_stored_hashes_are_the_frozen_jcs_forms(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)

    record = store.read_step(ACCOUNT_ID, MONDAY)
    assert record.step["input_state_hash"] == state_hash(record.step["input_state"])
    assert record.step["end_state_hash"] == state_hash(record.step["end_state"])
    assert record.step["counts"] == {
        "orders": 1,
        "fills": 1,
        "rejected": 0,
        "canceled": 0,
        "events": 0,
        "bars": 0,
    }
    assert store.verify_step(record) == ()


def test_step_document_records_the_account_envelope_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)

    document = store.read_step(ACCOUNT_ID, MONDAY).step
    assert document["account_schema_version"] == "pt-account-v1"
    assert document["account_schema_version"] == store.load(ACCOUNT_ID).schema_version
    assert "schema_version" not in document


def test_same_day_replay_is_a_byte_identical_no_op(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    step_fn = RecordingStep()
    for day in FIVE_DAYS:
        _run(store, calendar, step_fn, day)

    before = _bytes(store)
    replays = [_run(store, calendar, step_fn, FIVE_DAYS[-1]) for _ in range(2)]

    assert [item.status for item in replays] == [STATUS_STEP_ALREADY_APPLIED] * 2
    assert all("fp-day" in item.message for item in replays)
    assert _bytes(store) == before
    assert step_fn.days == list(FIVE_DAYS)  # the engine was not called again
    assert store.list_steps(ACCOUNT_ID) == FIVE_DAYS


def test_replay_of_an_earlier_day_is_also_a_no_op(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    step_fn = RecordingStep()
    for day in FIVE_DAYS:
        _run(store, calendar, step_fn, day)
    before = _bytes(store)
    result = _run(store, calendar, step_fn, MONDAY)
    assert result.status == STATUS_STEP_ALREADY_APPLIED
    assert result.step_dir == str(store.step_dir(ACCOUNT_ID, MONDAY))
    assert _bytes(store) == before


# ── closed days, missing data, date guards ──


def test_non_trading_day_advances_the_watermark_and_writes_no_step(tmp_path: Path) -> None:
    store = _store(tmp_path, start_date="2026-03-06", today="2026-03-06")
    calendar = FakeCalendar({"2026-03-06", "2026-03-09"})
    step_fn = RecordingStep()

    applied = _run(store, calendar, step_fn, "2026-03-06", today="2026-03-09")
    for closed in ("2026-03-07", "2026-03-08"):
        result = _run(store, calendar, step_fn, closed, today="2026-03-09")
        assert result.status == STATUS_NON_TRADING_DAY
        assert result.watermark == closed
        assert result.step_dir is None
        assert not store.step_dir(ACCOUNT_ID, closed).exists()

    account = store.load(ACCOUNT_ID)
    assert applied.status == STATUS_APPLIED
    assert account.watermark == "2026-03-08"
    assert account.non_trading_days == ("2026-03-07", "2026-03-08")
    assert account.cash == 100000.0 - 10.0
    assert step_fn.days == ["2026-03-06"]

    monday = _run(store, calendar, step_fn, "2026-03-09", today="2026-03-09")
    assert monday.status == STATUS_APPLIED
    assert step_fn.days == ["2026-03-06", "2026-03-09"]


def test_data_missing_writes_nothing_and_is_retryable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)
    before = _bytes(store)
    watermark = store.load(ACCOUNT_ID).watermark

    failed = _run(store, calendar, FailingStep(FIVE_DAYS[1]), FIVE_DAYS[1])
    assert failed.status == STATUS_DATA_MISSING
    assert failed.code == STATUS_DATA_MISSING
    assert "quota" in failed.message
    assert failed.watermark == watermark
    assert _bytes(store) == before
    assert not store.step_dir(ACCOUNT_ID, FIVE_DAYS[1]).exists()

    retried = _run(store, calendar, RecordingStep(), FIVE_DAYS[1])
    assert retried.status == STATUS_APPLIED
    assert store.load(ACCOUNT_ID).watermark == FIVE_DAYS[1]


def test_future_and_pre_start_dates_are_refused_without_writing(tmp_path: Path) -> None:
    store = _store(tmp_path, start_date="2026-03-04", today="2026-03-04")
    calendar = FakeCalendar(FIVE_DAYS)
    before = _bytes(store)

    future = _run(store, calendar, RecordingStep(), "2026-03-05", today="2026-03-04")
    assert (future.status, future.code) == (STATUS_DATA_MISSING, CODE_TRADE_DATE_IN_FUTURE)

    past = _run(store, calendar, RecordingStep(), "2026-03-03", today="2026-03-04")
    assert (past.status, past.code) == (STATUS_DATA_MISSING, CODE_BEFORE_START_DATE)
    assert store.load(ACCOUNT_ID).watermark is None
    assert store.list_steps(ACCOUNT_ID) == ()
    assert _bytes(store) == before


def test_skipping_a_trading_day_is_refused_and_points_at_catch_up(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)
    before = _bytes(store)

    gap = _run(store, calendar, RecordingStep(), FIVE_DAYS[2])
    assert (gap.status, gap.code) == (STATUS_RECOVERY_REQUIRED, CODE_WATERMARK_GAP)
    assert FIVE_DAYS[1] in gap.message and "catch_up" in gap.message
    assert _bytes(store) == before
    assert not store.step_dir(ACCOUNT_ID, FIVE_DAYS[2]).exists()


def test_step_without_a_trade_date_uses_the_injected_today(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = _run(store, FakeCalendar(FIVE_DAYS), RecordingStep(), None, today=MONDAY)
    assert result.status == STATUS_APPLIED
    assert result.trade_date == MONDAY


# ── locking ──


def test_lock_contention_returns_account_locked_without_writing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    step_fn = RecordingStep()
    before = _bytes(store)
    with store.lock(ACCOUNT_ID):
        result = _run(store, FakeCalendar(FIVE_DAYS), step_fn, MONDAY)
    assert result.status == STATUS_ACCOUNT_LOCKED
    assert result.code == "account_locked"
    assert step_fn.days == []
    assert _bytes(store) == before


def test_lock_is_released_when_step_fn_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def boom(account, trade_date):
        raise RuntimeError("engine exploded")

    with pytest.raises(RuntimeError, match="engine exploded"):
        _run(store, FakeCalendar(FIVE_DAYS), boom, MONDAY)
    assert store.list_steps(ACCOUNT_ID) == ()
    with store.lock(ACCOUNT_ID):
        pass


# ── crash recovery ──


def _crash(store: AccountStore, calendar: FakeCalendar, day: str) -> None:
    def before_account_save(account, directory):
        raise RuntimeError("simulated crash after the step write")

    with pytest.raises(RuntimeError, match="simulated crash"):
        _run(store, calendar, RecordingStep(), day, before_account_save=before_account_save)


def test_crash_after_step_write_is_adopted_by_recover(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)
    before = _bytes(store)

    _crash(store, calendar, FIVE_DAYS[1])
    crashed = store.load(ACCOUNT_ID)
    assert crashed.watermark == MONDAY
    assert store.step_dir(ACCOUNT_ID, FIVE_DAYS[1]).is_dir()
    assert _bytes(store) == before  # account.json was never replaced

    recovered = store.recover(ACCOUNT_ID, now=NOW)
    assert recovered.status == "adopted"
    assert recovered.watermark == FIVE_DAYS[1]
    assert store.load(ACCOUNT_ID).cash == 100000.0 - 2 * 10.0
    marker = json.loads(
        (store.account_dir(ACCOUNT_ID) / "recovery.json").read_text(encoding="utf-8")
    )
    assert marker["action"] == "adopted_orphaned_step"


def test_the_next_step_adopts_the_crashed_step_without_double_debiting(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    step_fn = RecordingStep()
    _run(store, calendar, step_fn, MONDAY)
    _crash(store, calendar, FIVE_DAYS[1])

    retry = _run(store, calendar, step_fn, FIVE_DAYS[1])
    assert retry.status == STATUS_STEP_ALREADY_APPLIED
    assert retry.recovered is True
    assert store.load(ACCOUNT_ID).cash == 100000.0 - 2 * 10.0
    assert step_fn.days == [MONDAY]  # the crashed day never ran the engine twice


def test_crash_with_a_diverged_ledger_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)
    _crash(store, calendar, FIVE_DAYS[1])

    store.save_account_atomic(dataclasses.replace(store.load(ACCOUNT_ID), cash=1.0))
    refused = _run(store, calendar, RecordingStep(), FIVE_DAYS[1])

    assert refused.status == STATUS_RECOVERY_REQUIRED
    assert refused.code == "state_mismatch"
    assert store.load(ACCOUNT_ID).watermark == MONDAY
    assert store.load(ACCOUNT_ID).cash == 1.0


def _rewrite_step_json(store: AccountStore, day: str, mutate) -> None:
    """Rewrite ``step.json`` and repair its manifest entry: a CONSISTENT forgery.

    Manifest verification is therefore satisfied, which is what lets the test
    reach the step's own end_state_hash check.
    """
    directory = store.step_dir(ACCOUNT_ID, day)
    step_path = directory / STEP_FILE
    document = json.loads(step_path.read_text(encoding="utf-8"))
    mutate(document)
    data = (dumps(document) + "\n").encode("utf-8")
    step_path.write_bytes(data)
    manifest_path = directory / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][STEP_FILE] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": data.count(b"\n"),
        "bytes": len(data),
    }
    manifest_path.write_text(dumps(manifest) + "\n", encoding="utf-8")


def test_adoption_refuses_a_step_whose_end_state_contradicts_its_hash(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY)
    _crash(store, calendar, FIVE_DAYS[1])
    before = _bytes(store)
    record = store.read_step(ACCOUNT_ID, FIVE_DAYS[1])
    assert record.end_state_hash == state_hash(record.step["end_state"])

    def tamper(document):
        document["end_state"]["cash"] += 1000.0

    _rewrite_step_json(store, FIVE_DAYS[1], tamper)

    refused = store.recover(ACCOUNT_ID, now=NOW)

    assert refused.status == "recovery_required"
    assert refused.code == "step_corrupt"
    assert "end_state_hash" in refused.message
    assert store.load(ACCOUNT_ID).watermark == MONDAY
    assert _bytes(store) == before


# ── catch-up ──


def test_catch_up_advances_serially_through_a_weekend(tmp_path: Path) -> None:
    store = _store(tmp_path, start_date="2026-03-06", today="2026-03-06")
    calendar = FakeCalendar({"2026-03-06", "2026-03-09"})
    step_fn = RecordingStep()

    result = catch_up(
        ACCOUNT_ID,
        step_fn=step_fn,
        calendar_client=calendar,
        today="2026-03-09",
        now=NOW,
        store=store,
    )

    assert result.status == "caught_up"
    assert result.watermark == "2026-03-09"
    assert [item.status for item in result.results] == [
        STATUS_APPLIED,
        STATUS_NON_TRADING_DAY,
        STATUS_NON_TRADING_DAY,
        STATUS_APPLIED,
    ]
    assert result.days_applied == 2
    assert step_fn.days == ["2026-03-06", "2026-03-09"]
    assert store.load(ACCOUNT_ID).non_trading_days == ("2026-03-07", "2026-03-08")


def test_catch_up_skips_the_weekend_for_a_zero_calendar_market(tmp_path: Path) -> None:
    store = _store(
        tmp_path, market="us", interval="1d",
        start_date="2026-03-06", today="2026-03-06", next_trading_day="2026-03-09")
    step_fn = RecordingStep()

    result = catch_up(
        ACCOUNT_ID,
        step_fn=step_fn,
        calendar_client=None,
        today="2026-03-09",
        now=NOW,
        store=store,
    )

    assert result.status == "caught_up"
    assert [item.status for item in result.results] == [
        STATUS_APPLIED,
        STATUS_NON_TRADING_DAY,
        STATUS_NON_TRADING_DAY,
        STATUS_APPLIED,
    ]
    assert step_fn.days == ["2026-03-06", "2026-03-09"]
    assert store.load(ACCOUNT_ID).non_trading_days == ("2026-03-07", "2026-03-08")


def test_catch_up_stops_at_the_first_data_missing_day(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    result = catch_up(
        ACCOUNT_ID,
        step_fn=FailingStep(FIVE_DAYS[2]),
        calendar_client=calendar,
        today=FIVE_DAYS[-1],
        now=NOW,
        store=store,
    )
    assert result.status == "stopped"
    assert result.code == STATUS_DATA_MISSING
    assert result.watermark == FIVE_DAYS[1]
    assert store.list_steps(ACCOUNT_ID) == FIVE_DAYS[:2]
    assert not store.step_dir(ACCOUNT_ID, FIVE_DAYS[2]).exists()


def test_catch_up_refuses_to_become_a_historical_backfill(tmp_path: Path) -> None:
    store = _store(tmp_path, start_date="2026-01-05", today="2026-01-05")
    weekdays = [
        (dt.date(2026, 1, 5) + dt.timedelta(days=offset)).isoformat() for offset in range(70)
    ]
    calendar = FakeCalendar(weekdays)
    before = _bytes(store)

    result = catch_up(
        ACCOUNT_ID,
        step_fn=RecordingStep(),
        calendar_client=calendar,
        today="2026-03-06",
        now=NOW,
        store=store,
        max_days=30,
    )
    assert result.status == "stopped"
    assert result.code == "catch_up_range_too_long"
    assert store.list_steps(ACCOUNT_ID) == ()
    assert _bytes(store) == before


def test_catch_up_is_up_to_date_when_the_watermark_reached_today(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calendar = FakeCalendar(FIVE_DAYS)
    _run(store, calendar, RecordingStep(), MONDAY, today=MONDAY)
    result = catch_up(
        ACCOUNT_ID,
        step_fn=RecordingStep(),
        calendar_client=calendar,
        today=MONDAY,
        now=NOW,
        store=store,
    )
    assert result.status == "up_to_date"
    assert result.results == ()


def test_catch_up_reports_lock_contention(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.lock(ACCOUNT_ID):
        result = catch_up(
            ACCOUNT_ID,
            step_fn=RecordingStep(),
            calendar_client=FakeCalendar(FIVE_DAYS),
            today=FIVE_DAYS[-1],
            now=NOW,
            store=store,
        )
    assert result.status == "account_locked"
    assert result.code == "account_locked"
    assert store.list_steps(ACCOUNT_ID) == ()


# ── default engine adapter ──


def _wire_success(payload):
    return json.dumps(
        {
            "account_id": payload["account_id"],
            "market": payload["market"],
            "received_state_hash": "hash-from-engine",
            "effective_fee_model": {"commission_rate": 0.00025},
            "end_state": {"cash": 999.0, "positions": []},
            "fills": [],
            "rejected_orders": [],
            "nav_series": [{"date": payload["to_date"], "nav": 999.0, "cash": 999.0, "position_value": 0.0}],
            "engine_fingerprint": "fp-from-engine",
        }
    )


def test_engine_adapter_round_trips_the_public_document(monkeypatch) -> None:
    captured = {}

    def fake(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return _wire_success(payload)

    monkeypatch.setattr(tool, "run_paper_trade_step", fake)
    orders = [{"symbol": "600519.SH", "side": "buy", "qty": 100}]
    step_fn = engine_adapter.engine_step_fn(orders_by_date={MONDAY: orders}, fee_model={"a": 1.0})
    outcome = step_fn(_account(), MONDAY)

    assert isinstance(outcome, StepOutcome)
    assert outcome.end_state == AccountState(cash=999.0)
    assert outcome.engine_fingerprint == "fp-from-engine"
    assert outcome.received_state_hash == "hash-from-engine"
    assert outcome.orders == ({"symbol": "600519.SH", "side": "buy", "qty": 100},)
    assert outcome.effective_fee_model == {"commission_rate": 0.00025}
    assert captured["payload"]["orders"] == orders
    assert captured["payload"]["from_date"] == captured["payload"]["to_date"] == MONDAY
    assert captured["payload"]["fee_model"] == {"a": 1.0}
    # A 5m account contributes its non-default contract fields; no client is
    # injected, so the tool keeps its own production resolution.
    assert captured["payload"]["interval"] == "5m"
    assert captured["payload"]["session"] == "cn_a"
    assert captured["kwargs"] == {}


def test_adapter_payload_satisfies_the_v12_request_parser(monkeypatch) -> None:
    captured = {}

    def fake(payload, **kwargs):
        captured["payload"] = payload
        return _wire_success(payload)

    monkeypatch.setattr(tool, "run_paper_trade_step", fake)
    engine_adapter.engine_step_fn()(_account(), MONDAY)

    request = parse_request(captured["payload"])
    assert (request.interval, request.session) == ("5m", "cn_a")
    assert (request.path_model, request.fill_model) == ("bar_median", "all_or_none")


def test_engine_adapter_maps_data_not_ready_to_the_retryable_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        tool,
        "run_paper_trade_step",
        lambda payload, **kwargs: json.dumps(
            {"status": "error", "code": "PAPER_DATA_NOT_READY", "message": "no rows yet"}
        ),
    )
    with pytest.raises(PaperDataNotReady, match="no rows yet") as excinfo:
        engine_adapter.engine_step_fn()(_account(), MONDAY)
    assert excinfo.value.code == STATUS_DATA_MISSING


def test_engine_adapter_raises_through_an_invalid_request(monkeypatch) -> None:
    monkeypatch.setattr(
        tool,
        "run_paper_trade_step",
        lambda payload, **kwargs: json.dumps(
            {"status": "error", "code": "INVALID_REQUEST", "message": "interval 5m is cn_a-only"}
        ),
    )
    with pytest.raises(PaperStepRefused) as excinfo:
        engine_adapter.engine_step_fn()(_account(), MONDAY)
    assert excinfo.value.code == "INVALID_REQUEST"
