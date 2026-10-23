"""Daily advance / catch-up over a persistent paper-trade account (T5).

``step`` performs EXACTLY ONE calendar day and is the only writer of a step;
``catch_up`` walks a gap one day at a time and never merges two days into one
step (planbook §5).  Both take an injected ``step_fn`` and trading calendar, so no
clock, network or connector lives here.  Days are never merged because the ledger
is sequentially dependent — and ``catch_up`` therefore refuses a range longer
than ``max_days`` instead of silently becoming a historical backfill.

Failure discipline (fail closed, nothing half-applied):

* ``trade_date <= watermark`` → ``step_already_applied``; no file is touched.
* closed day → watermark advances, ``non_trading_day``, NO step directory.
* ``step_fn`` raises ``PaperDataNotReady`` → ``data_missing``; the watermark and
  ``account.json`` stay byte-identical.
* a trading day would be skipped → ``recovery_required`` / ``watermark_gap``; the
  caller must use ``catch_up`` so no ledger day is jumped.
* crash after the step, before the account write → the next call adopts the
  orphaned step when its input state hashes to the stored ledger, otherwise it
  returns ``recovery_required`` / ``state_mismatch``.  Never a silent mismatch.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .account import PaperTradeAccount, account_state_payload, require_date
from .engine_adapter import (
    DATA_MISSING,
    PaperDataNotReady,
    PaperStepRefused,
    StepFn,
    StepOutcome,
)
from .schema import AccountState, parse_account_state
from .state_hash import state_hash
from .store import AccountLocked, AccountStore, StepRecord
from .trading_days import (
    calendar_days,
    is_open_day,
    latest_completed_trading_day,
    next_day,
    previous_day,
    trading_days_between,
)

__all__ = [
    "CODE_BEFORE_START_DATE",
    "CODE_TRADE_DATE_IN_FUTURE",
    "CODE_WATERMARK_GAP",
    "STATUS_ACCOUNT_LOCKED",
    "STATUS_APPLIED",
    "STATUS_DATA_MISSING",
    "STATUS_NON_TRADING_DAY",
    "STATUS_RECOVERY_REQUIRED",
    "STATUS_STEP_ALREADY_APPLIED",
    "CatchUpResult",
    "PaperDataNotReady",
    "PaperStepRefused",
    "StepFn",
    "StepOutcome",
    "StepResult",
    "catch_up",
    "latest_completed_trading_day",
    "step",
]

STATUS_APPLIED = "applied"
STATUS_NON_TRADING_DAY = "non_trading_day"
STATUS_STEP_ALREADY_APPLIED = "step_already_applied"
STATUS_DATA_MISSING = DATA_MISSING
STATUS_ACCOUNT_LOCKED = "account_locked"
STATUS_RECOVERY_REQUIRED = "recovery_required"

CODE_TRADE_DATE_IN_FUTURE = "trade_date_in_future"
CODE_BEFORE_START_DATE = "before_start_date"
CODE_WATERMARK_GAP = "watermark_gap"


@dataclass(frozen=True, slots=True)
class StepResult:
    """One day's verdict.  ``step_dir`` is set only when a step was materialized."""

    status: str
    trade_date: str | None
    step_dir: str | None
    code: str
    message: str
    watermark: str | None = None
    engine_fingerprint: str = ""
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class CatchUpResult:
    """A serial catch-up run: one :class:`StepResult` per calendar day visited."""

    account_id: str
    status: str
    watermark: str | None
    latest_trading_day: str | None
    results: tuple[StepResult, ...]
    code: str = ""
    message: str = ""

    @property
    def days_applied(self) -> int:
        return sum(1 for item in self.results if item.status == STATUS_APPLIED)


def _as_state(value: Any) -> AccountState:
    if isinstance(value, AccountState):
        return value
    return parse_account_state(value, "step_fn.end_state")


def _rows(values: Sequence[Any]) -> list[Any]:
    return [
        dict(item) if isinstance(item, Mapping) else dataclasses.asdict(item) for item in values
    ]


def _stored_step(store: AccountStore, account_id: str, day: str) -> StepRecord | None:
    try:
        return store.read_step(account_id, day)
    except Exception:  # noqa: BLE001 — only the message detail is lost when a step is absent
        return None


def step(
    account_id: str,
    trade_date: str | None = None,
    *,
    step_fn: StepFn,
    calendar_client: Any,
    today: str,
    now: str,
    store: AccountStore | None = None,
    before_account_save: Callable[[PaperTradeAccount, Any], None] | None = None,
) -> StepResult:
    """Advance ``account_id`` by exactly one calendar day.

    ``trade_date`` defaults to ``today``.  ``today`` and ``now`` are injected —
    this function reads no clock.  ``before_account_save`` is the crash-injection
    seam: it runs AFTER the step directory is durable and BEFORE ``account.json``
    is replaced, which is exactly the window recovery exists for.
    """
    store = store or AccountStore()
    target = require_date(today if trade_date is None else trade_date, "trade_date")
    today_text = require_date(today, "today")
    try:
        with store.lock(account_id):
            return _step_locked(
                store=store,
                account_id=account_id,
                target=target,
                today_text=today_text,
                now=now,
                step_fn=step_fn,
                calendar_client=calendar_client,
                before_account_save=before_account_save,
            )
    except AccountLocked as exc:
        return StepResult(STATUS_ACCOUNT_LOCKED, target, None, exc.code, exc.message)


def _step_locked(
    *,
    store: AccountStore,
    account_id: str,
    target: str,
    today_text: str,
    now: str,
    step_fn: StepFn,
    calendar_client: Any,
    before_account_save: Callable[[PaperTradeAccount, Any], None] | None,
) -> StepResult:
    account = store.load(account_id)
    recovery = store.recover(account_id, now=now, lock_held=True)
    if recovery.status == "recovery_required":
        return StepResult(
            STATUS_RECOVERY_REQUIRED,
            target,
            None,
            recovery.code,
            recovery.message,
            watermark=account.watermark,
        )
    account = recovery.account
    recovered = recovery.status == "adopted"

    def result(
        status: str,
        code: str,
        message: str,
        *,
        step_dir: str | None = None,
        watermark: str | None = None,
        engine_fingerprint: str = "",
    ) -> StepResult:
        return StepResult(
            status,
            target,
            step_dir,
            code,
            message,
            watermark=account.watermark if watermark is None else watermark,
            engine_fingerprint=engine_fingerprint,
            recovered=recovered,
        )

    if target < account.start_date:
        return result(
            STATUS_DATA_MISSING,
            CODE_BEFORE_START_DATE,
            f"{target} precedes the account start {account.start_date}; nothing to advance",
        )
    if target > today_text:
        return result(
            STATUS_DATA_MISSING,
            CODE_TRADE_DATE_IN_FUTURE,
            f"{target} is after today {today_text}; the session has not happened yet, retry later",
        )
    if account.watermark is not None and target <= account.watermark:
        record = _stored_step(store, account_id, target)
        fingerprint = record.engine_fingerprint if record is not None else ""
        detail = f"; stored engine_fingerprint={fingerprint}" if fingerprint else ""
        return result(
            STATUS_STEP_ALREADY_APPLIED,
            "",
            f"{target} is at or before watermark {account.watermark}; nothing re-applied{detail}",
            step_dir=str(record.directory) if record is not None else None,
            engine_fingerprint=fingerprint,
        )

    first_candidate = (
        account.start_date if account.watermark is None else next_day(account.watermark)
    )
    skipped = trading_days_between(
        calendar_client, account.market, first_candidate, previous_day(target)
    )
    if skipped:
        return result(
            STATUS_RECOVERY_REQUIRED,
            CODE_WATERMARK_GAP,
            f"{target} would skip {len(skipped)} unprocessed trading day(s) "
            f"({', '.join(skipped)}); the watermark is {account.watermark!r}. Advance serially "
            "with catch_up — a ledger must not jump a session",
        )

    if not is_open_day(calendar_client, account.market, target):
        store.save_account_atomic(account.with_non_trading_day(target))
        return result(
            STATUS_NON_TRADING_DAY,
            "",
            f"{target} is a non-trading day; watermark advanced to {target}, no step written",
            watermark=target,
        )

    input_payload = account.state_payload()
    input_digest = account.state_digest()
    try:
        outcome = step_fn(account, target)
    except PaperDataNotReady as exc:
        return result(
            STATUS_DATA_MISSING,
            exc.code,
            str(exc) or f"market data for {target} is not ready; retry later",
        )

    end_state = _as_state(outcome.end_state)
    end_payload = account_state_payload(end_state)
    document = {
        "account_id": account_id,
        "market": account.market,
        "trade_date": target,
        "account_schema_version": account.schema_version,
        "interval": account.interval,
        "path_model": account.path_model,
        "fill_model": account.fill_model,
        "engine_fingerprint": outcome.engine_fingerprint,
        "received_state_hash": outcome.received_state_hash,
        "input_state": input_payload,
        "input_state_hash": input_digest,
        "end_state": end_payload,
        "end_state_hash": state_hash(end_payload),
        "effective_fee_model": dict(outcome.effective_fee_model or {}),
        "data_provenance": dict(outcome.data_provenance or {}),
        "nav_series": _rows(outcome.nav_series),
        "warnings": list(outcome.warnings),
        "five_minute_source": outcome.five_minute_source,
        "skipped_days": _rows(outcome.skipped_days),
        "counts": {
            "orders": len(outcome.orders),
            "fills": len(outcome.fills),
            "rejected": len(outcome.rejected_orders),
            "canceled": len(outcome.canceled_orders),
            "events": len(outcome.events),
            "bars": len(outcome.bars),
        },
        "created_at": now,
    }
    record = store.write_step(
        account_id,
        target,
        step=document,
        orders=outcome.orders,
        fills=outcome.fills,
        rejected=outcome.rejected_orders,
        canceled=outcome.canceled_orders,
        positions=[{"trade_date": target, **row} for row in end_payload["positions"]],
        events=outcome.events,
        bars=outcome.bars,
    )
    if before_account_save is not None:
        # The step is durable; raising here leaves the account on its previous
        # watermark, and recover()/the next step adopts the step if it chains.
        before_account_save(account, record.directory)
    advanced = account.with_advance(
        end_state=end_state,
        watermark=target,
        engine_fingerprint=outcome.engine_fingerprint or None,
    )
    if not advanced.fee_model and outcome.request_fee_model:
        # HIL6 backfill: a legacy account locks the parameters of its first
        # successful step, so every later day is provably priced the same way.
        advanced = dataclasses.replace(
            advanced, fee_model=dict(sorted(outcome.request_fee_model.items())))
    store.save_account_atomic(advanced)
    return result(
        STATUS_APPLIED,
        "",
        f"applied {target}: fills={len(outcome.fills)} rejected={len(outcome.rejected_orders)} "
        f"canceled={len(outcome.canceled_orders)} end_cash={end_state.cash}",
        step_dir=str(record.directory),
        watermark=target,
        engine_fingerprint=outcome.engine_fingerprint,
    )


def catch_up(
    account_id: str,
    *,
    step_fn: StepFn,
    calendar_client: Any,
    today: str,
    now: str,
    store: AccountStore | None = None,
    max_days: int = 30,
) -> CatchUpResult:
    """Advance serially from the watermark to the latest completed trading day.

    Each visited calendar day is its own :func:`step` call under its own lock
    acquisition and its own step directory — days are never merged.  The run
    stops at the first day that is not applied / skipped / already applied and
    returns that day's status and message, so the operator sees where the chain
    stopped.
    """
    store = store or AccountStore()
    account = store.load(account_id)
    today_text = require_date(today, "today")
    latest = latest_completed_trading_day(
        calendar_client=calendar_client, market=account.market, today=today_text
    )
    start = account.start_date if account.watermark is None else next_day(account.watermark)

    if latest is None:
        return CatchUpResult(
            account_id,
            "stopped",
            account.watermark,
            None,
            (),
            "calendar_empty",
            "the calendar reports no trading day in the lookback window; refusing to guess",
        )
    if start > latest:
        return CatchUpResult(
            account_id,
            "up_to_date",
            account.watermark,
            latest,
            (),
            "",
            f"watermark {account.watermark!r} already covers the latest trading day {latest}",
        )
    span = (dt.date.fromisoformat(latest) - dt.date.fromisoformat(start)).days + 1
    if span > max_days:
        return CatchUpResult(
            account_id,
            "stopped",
            account.watermark,
            latest,
            (),
            "catch_up_range_too_long",
            f"{span} calendar days ({start}..{latest}) exceed max_days={max_days}; catch_up "
            "covers outages, not a historical backfill",
        )

    results: list[StepResult] = []
    for day in calendar_days(start, latest):
        item = step(
            account_id,
            day,
            step_fn=step_fn,
            calendar_client=calendar_client,
            today=today_text,
            now=now,
            store=store,
        )
        results.append(item)
        if item.status not in (
            STATUS_APPLIED,
            STATUS_NON_TRADING_DAY,
            STATUS_STEP_ALREADY_APPLIED,
        ):
            status = STATUS_ACCOUNT_LOCKED if item.status == STATUS_ACCOUNT_LOCKED else "stopped"
            return CatchUpResult(
                account_id, status, item.watermark, latest, tuple(results), item.code, item.message
            )
    final = results[-1].watermark if results else account.watermark
    return CatchUpResult(
        account_id,
        "caught_up",
        final,
        latest,
        tuple(results),
        "",
        f"advanced {len(results)} calendar day(s) one at a time through {latest}",
    )
