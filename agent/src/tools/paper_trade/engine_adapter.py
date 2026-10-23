"""Default ``step_fn``: adapt the public ``paper_trade_step`` wire document (T5).

The account layer must not depend on the engine's internal dataclasses — T2/T3/T4
own those and change them additively.  This adapter therefore round-trips the
frozen JSON document instead: a request is built from the account, the tool is
called, and the single in-band result document is normalized back into a
:class:`StepOutcome`.

Error mapping is the D6 contract:

* ``PAPER_DATA_NOT_READY`` → :class:`PaperDataNotReady` (retryable; the runner
  leaves the watermark and the account bytes untouched);
* ``INVALID_REQUEST`` → :class:`PaperStepRefused` (a misconfigured account, not
  late data — raised through so it cannot become an infinite retry loop).

The engine is imported on the FIRST step, never at module import, so importing
``runner``/``store`` still builds no connector and touches no loader.  Only
injection seams the caller actually supplied are forwarded; an omitted client
keeps the tool's own production resolution.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .account import PaperTradeAccount
from .schema import AccountState, parse_account_state

__all__ = [
    "PaperDataNotReady",
    "PaperStepRefused",
    "StepFn",
    "StepOutcome",
    "engine_step_fn",
]

StepFn = Callable[[PaperTradeAccount, str], "StepOutcome"]

#: Status the runner maps :class:`PaperDataNotReady` to.  Held as a literal so
#: this module does not import ``runner`` (which imports this one); the runner's
#: test suite pins the two names together.
DATA_MISSING = "data_missing"


class PaperDataNotReady(RuntimeError):
    """``step_fn`` signal: this day's data is not available yet (D6, retryable).

    The runner maps it to ``data_missing``: nothing is written and the watermark
    does not move, so a later retry starts from exactly the same ledger.
    """

    code = DATA_MISSING


class PaperStepRefused(RuntimeError):
    """``step_fn`` signal: the step cannot be performed at all (not retried).

    An ``INVALID_REQUEST`` from the engine means the ACCOUNT is misconfigured
    (unsupported interval, bad fee model), not that data is late.  Converting
    that into ``data_missing`` would invite an infinite retry loop, so it is
    raised through and stays loud.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What one day's ``step_fn`` produced (the engine's result, normalized).

    ``end_state`` is the ledger after the day.  ``received_state_hash`` is the
    engine's frozen AM-4-1 coverage hash, recorded verbatim for audit; the chain
    key used by crash recovery is the runner's own ``input_state_hash`` (a hash
    of the pure ``account_state`` payload), because the coverage object also
    contains the fee model and dates and therefore cannot be recomputed from the
    account alone.

    ``orders`` are attached by the adapter from the schedule it submitted.
    ``bars`` is the day's continuous 5m CSV per symbol, serialized from the
    ``MarketDataResult`` the tool carried alongside its document — the wire
    contract does not echo bars, and a second fetch would burn the provider's
    2-calls-per-day ``stk_mins`` budget (T1).
    """

    end_state: AccountState | Mapping[str, Any]
    fills: tuple[Any, ...] = ()
    rejected_orders: tuple[Any, ...] = ()
    canceled_orders: tuple[Any, ...] = ()
    events: tuple[Any, ...] = ()
    data_provenance: Mapping[str, Any] | None = None
    engine_fingerprint: str = ""
    received_state_hash: str = ""
    orders: tuple[Any, ...] = ()
    bars: Mapping[str, str] = field(default_factory=dict)
    effective_fee_model: Mapping[str, float] | None = None
    nav_series: tuple[Any, ...] = ()
    #: Wire ``warnings``/``skipped_days`` carried verbatim.  They are the only
    #: durable record of 5m session coverage ("30/48 continuous bars") and of
    #: the zero-calendar skip reasons, so the runner persists them with the step.
    warnings: tuple[str, ...] = ()
    skipped_days: tuple[Any, ...] = ()
    five_minute_source: str = ""

    @classmethod
    def from_wire(
        cls,
        document: Mapping[str, Any],
        *,
        orders: Sequence[Any] = (),
        bars: Mapping[str, str] | None = None,
        five_minute_source: str = "",
    ) -> "StepOutcome":
        """Build an outcome from one success document of ``paper_trade_step``."""
        return cls(
            end_state=parse_account_state(document.get("end_state"), "end_state"),
            fills=tuple(document.get("fills") or ()),
            rejected_orders=tuple(document.get("rejected_orders") or ()),
            canceled_orders=tuple(document.get("canceled_orders") or ()),
            events=tuple(document.get("events") or ()),
            data_provenance=dict(document.get("data_provenance") or {}),
            engine_fingerprint=str(document.get("engine_fingerprint") or ""),
            received_state_hash=str(document.get("received_state_hash") or ""),
            orders=tuple(orders),
            bars=dict(bars or {}),
            effective_fee_model=dict(document.get("effective_fee_model") or {}),
            nav_series=tuple(document.get("nav_series") or ()),
            warnings=tuple(document.get("warnings") or ()),
            skipped_days=tuple(document.get("skipped_days") or ()),
            five_minute_source=five_minute_source,
        )


#: Header of a step bar file; matches ``DataFrame.to_csv()`` on the canonical
#: 5m frame (the index is the bar END label, T1).
_BARS_HEADER = "bar_time,open,high,low,close,volume\n"


def _bars_csv(market_data: Any, trade_date: str) -> dict[str, str]:
    """Serialize the trade date's CONTINUOUS 5m bars, one CSV per symbol.

    The frames come from the engine's own session split, so the 09:30 opening
    auction print and any auction-window label are already excluded — this is
    the evidence the engine matched, not a re-derivation.  A symbol with no
    continuous bar that day (halted) gets a header-only file: the step then
    records "zero bars" explicitly instead of leaving a reader unable to tell
    an absent symbol from a lost file.
    """
    if market_data is None or getattr(market_data, "interval", "1d") != "5m":
        return {}
    bars: dict[str, str] = {}
    for symbol in market_data.symbols:
        frame = market_data.data[symbol].bars_5m.get(trade_date)
        bars[symbol] = _BARS_HEADER if frame is None or frame.empty else frame.to_csv()
    return bars


def engine_step_fn(
    *,
    orders_by_date: Mapping[str, Sequence[Any]] | None = None,
    fee_model: Mapping[str, float] | None = None,
    loader: Any = None,
    ch_client: Any = None,
    calendar_client: Any = None,
    limits_client: Any = None,
    request_fields: Mapping[str, Any] | None = None,
) -> StepFn:
    """Adapt the public ``paper_trade_step`` tool into a ``step_fn``."""
    schedule = orders_by_date or {}
    overrides = dict(request_fields or {})

    def step_fn(account: PaperTradeAccount, trade_date: str) -> StepOutcome:
        from .tool import run_paper_trade_step

        # The tool derives the 5m fetch universe from exactly these order
        # symbols; positions are valued from the daily leg, so a positions-only
        # day issues no stk_mins call (one call per symbol and 2/day budget).
        orders = [
            dict(item) if isinstance(item, Mapping) else dataclasses.asdict(item)
            for item in schedule.get(trade_date, ())
        ]
        # The fee parameters are part of the account contract (HIL6).  An
        # injected mapping must match a locked one, but an OMITTED mapping is
        # not "empty": it means "use what the account already locked".  Only an
        # explicit, different mapping is refused; a legacy account with no lock
        # forwards the explicit mapping (or nothing) and lets the engine echo
        # the effective model, which the runner then locks on the first step.
        effective_fee = dict(fee_model) if fee_model is not None else dict(account.fee_model)
        if (
            fee_model is not None
            and account.fee_model
            and dict(fee_model) != dict(account.fee_model)
        ):
            raise PaperStepRefused(
                "fee_model_mismatch",
                "the injected fee_model differs from the one locked on the "
                f"account at creation ({dict(account.fee_model)}); refusing to step",
            )
        payload: dict[str, Any] = {
            "account_id": account.account_id,
            "market": account.market,
            "account_state": account.state_payload(),
            "orders": orders,
            "from_date": trade_date,
            "to_date": trade_date,
        }
        payload.update(account.request_fields())
        payload.update(overrides)
        if effective_fee:
            payload["fee_model"] = effective_fee
        kwargs = {
            name: value
            for name, value in (
                ("loader", loader),
                ("ch_client", ch_client),
                ("calendar_client", calendar_client),
                ("limits_client", limits_client),
            )
            if value is not None
        }
        raw = run_paper_trade_step(payload, **kwargs)
        market_data = getattr(raw, "market_data", None)
        document = json.loads(raw)
        if not isinstance(document, Mapping):
            raise PaperStepRefused(
                "invalid_engine_document", "paper_trade_step returned a non-object document"
            )
        if document.get("status") == "error":
            code = str(document.get("code") or "engine_refused")
            message = str(document.get("message") or "paper_trade_step refused the step")
            if code == "PAPER_DATA_NOT_READY":
                raise PaperDataNotReady(message)
            raise PaperStepRefused(code, message)
        return StepOutcome.from_wire(
            document,
            orders=orders,
            bars=_bars_csv(market_data, trade_date),
            five_minute_source=getattr(market_data, "five_minute_source", ""),
        )

    return step_fn
