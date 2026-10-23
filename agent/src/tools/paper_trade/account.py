"""Incremental paper-trade account model (P0 cn_a 5m, T5).

The engine (``engine.py`` / ``tool.py``) is stateless by contract: it receives a
ledger snapshot and returns the next one.  This module owns the *persistent*
half — the account that carries that snapshot from day to day — and nothing
about matching.

Design rules:

* **No clock.**  ``today``, ``next_trading_day`` and ``now`` are injected by the
  caller (``runner.py`` threads them from its own injected arguments), so the
  same creation call always produces the same account document.
* **Start date is the only temporal input that matters.**  Per planbook §0.2 /
  the execution plan, a paper account starts TODAY or on the NEXT trading day;
  a past date is a backtest, not a paper trade, and returns the stable code
  ``start_date_in_past``.
* **The watermark only moves forward** (``with_advance`` / ``with_non_trading_day``
  refuse a backwards write), which is what makes a replayed day a no-op instead
  of a double debit.
* **The on-disk shape is versioned independently of the wire contract.**  A
  ``pt-account-v1`` document describes the account envelope; ``step.json``
  echoes that envelope version as ``account_schema_version`` so a reader can
  tell which layout produced the step.  The wire contract version is a property
  of the wire document itself (``schema_version``) and is never written to the
  store: coupling the two would force an account migration every time the tool
  contract gains an additive field.

``initial_cash`` / ``initial_positions`` are frozen at creation for audit; the
mutable ledger is ``cash`` / ``positions``.  ``positions`` is an ordered tuple,
never a set: the engine treats element order as semantic (AM-4-1).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .schema import (
    FILL_MODELS,
    INTERVALS,
    MARKETS,
    PATH_MODELS,
    AccountState,
    PaperTradeSchemaError,
    Position,
    parse_account_state,
)

__all__ = [
    "ACCOUNT_ID_MAX_LEN",
    "ACCOUNT_SCHEMA_VERSION",
    "INVALID_ACCOUNT",
    "INVALID_INITIAL_POSITIONS",
    "START_DATE_IN_PAST",
    "START_DATE_NOT_ADMISSIBLE",
    "AccountError",
    "PaperTradeAccount",
    "account_state_payload",
    "create_account",
    "require_date",
    "validate_account_id",
]

#: Version of the ``account.json`` envelope (independent of the
#: ``paper_trade_step`` wire contract, which travels on the wire document).
#: A reader refuses anything else.
ACCOUNT_SCHEMA_VERSION = "pt-account-v1"

#: Stable creation error codes (contract surface — callers switch on these).
START_DATE_IN_PAST = "start_date_in_past"
START_DATE_NOT_ADMISSIBLE = "start_date_not_admissible"
INVALID_ACCOUNT = "invalid_account"
INVALID_INITIAL_POSITIONS = "invalid_initial_positions"

ACCOUNT_ID_MAX_LEN = 64
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AccountError(ValueError):
    """A creation/parsing violation carrying a stable ``code``.

    ``code`` is the machine-readable surface; ``message`` is deterministic
    English (VD-7 discipline) and never contains a timestamp.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_account_id(account_id: str) -> str:
    """Return ``account_id`` if it is a safe single path segment.

    The id becomes a directory name under ``accounts/``, so a separator, a
    ``..`` segment or a leading dot is a path-traversal attempt and is refused
    here rather than being normalised into a surprise location.
    """
    if not isinstance(account_id, str) or not account_id:
        raise AccountError(INVALID_ACCOUNT, "account_id must be a non-empty string")
    if len(account_id) > ACCOUNT_ID_MAX_LEN:
        raise AccountError(
            INVALID_ACCOUNT,
            f"account_id must be at most {ACCOUNT_ID_MAX_LEN} characters, got {len(account_id)}",
        )
    if not _ACCOUNT_ID_RE.match(account_id):
        raise AccountError(
            INVALID_ACCOUNT,
            "account_id must match [A-Za-z0-9][A-Za-z0-9._-]* "
            f"(no path separators, no leading dot), got {account_id!r}",
        )
    return account_id


def require_date(value: Any, path: str) -> str:
    """Return ``value`` as a strict ``YYYY-MM-DD`` date string.

    Exact-format regex first: ``datetime.date.fromisoformat`` in 3.11 accepts
    looser spellings (``2026-1-2``), and a ledger keyed on two spellings of the
    same day is not a ledger.
    """
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise AccountError(INVALID_ACCOUNT, f"{path} must be YYYY-MM-DD, got {value!r}")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise AccountError(INVALID_ACCOUNT, f"{path} is not a calendar date: {value!r}") from exc
    return value


def _require_number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AccountError(INVALID_ACCOUNT, f"{path} must be a number, got {type(value).__name__}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise AccountError(INVALID_ACCOUNT, f"{path} must be finite, got {value!r}")
    if minimum is not None and numeric < minimum:
        raise AccountError(INVALID_ACCOUNT, f"{path} must be >= {minimum}, got {numeric}")
    return numeric


def _positions(raw: Any, path: str) -> tuple[Position, ...]:
    """Parse a position list (``Position`` objects or wire dicts) via ``schema``."""
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise AccountError(INVALID_ACCOUNT, f"{path} must be an array")
    items = [
        {"symbol": item.symbol, "qty": item.qty, "avg_cost": item.avg_cost}
        if isinstance(item, Position)
        else item
        for item in raw
    ]
    try:
        return parse_account_state({"cash": 0.0, "positions": items}, path).positions
    except PaperTradeSchemaError as exc:
        raise AccountError(INVALID_ACCOUNT, str(exc)) from exc


def _position_rows(positions: tuple[Position, ...]) -> list[dict[str, Any]]:
    return [
        {"symbol": item.symbol, "qty": item.qty, "avg_cost": item.avg_cost}
        for item in positions
    ]


def account_state_payload(state: AccountState) -> dict[str, Any]:
    """Canonical JSON ``account_state`` payload (the adoption-key pre-image).

    ``account.json``'s digest, ``step.json``'s ``input_state``/``end_state`` and
    the recovery chain all hash THIS shape, so a stored hash can be recomputed
    from either side of the write without a second normalizer.
    """
    return {"cash": state.cash, "positions": _position_rows(state.positions)}


@dataclass(frozen=True, slots=True)
class PaperTradeAccount:
    """One incremental paper-trade account (plan T5 data model).

    ``initial_*`` are the immutable creation snapshot; ``cash`` / ``positions``
    are the current ledger; ``watermark`` is the last trade_date the account has
    processed (``None`` before the first advance).  ``non_trading_days`` records
    every closed day the watermark walked over, so "no step" is auditable
    without a step directory.
    """

    account_id: str
    market: str
    start_date: str
    initial_cash: float
    initial_positions: tuple[Position, ...]
    cash: float
    positions: tuple[Position, ...]
    watermark: str | None
    engine_fingerprint: str
    created_at: str
    interval: str = "5m"
    path_model: str = "bar_median"
    fill_model: str = "all_or_none"
    schema_version: str = ACCOUNT_SCHEMA_VERSION
    non_trading_days: tuple[str, ...] = ()
    #: Fee parameters locked at creation (HIL6).  Empty on an account written
    #: before this field existed; the first successful step backfills it.
    fee_model: Mapping[str, float] = field(default_factory=dict)

    # ── ledger views ──

    def state(self) -> AccountState:
        """The engine's input shape for the *current* ledger."""
        return AccountState(cash=self.cash, positions=self.positions)

    def state_payload(self) -> dict[str, Any]:
        """The JSON account_state shape (exactly what the wire parser reads).

        This is the value the engine hashes for ``received_state_hash``, so it
        must stay identical in shape to ``schema.parse_account_state`` input —
        which is why the runner also hashes it for step adoption.
        """
        return account_state_payload(self.state())

    def state_digest(self) -> str:
        """``sha256(JCS(state_payload()))`` — the chain/adoption key."""
        from .state_hash import state_hash

        return state_hash(self.state_payload())

    def request_fields(self) -> dict[str, Any]:
        """Wire fields this account adds to a ``paper_trade_step`` request.

        Only NON-DEFAULT values are emitted (D4 spirit): a v1.1-shaped account
        produces no extra keys, so its requests stay byte-identical to pt-v1.1.
        """
        fields: dict[str, Any] = {}
        if self.interval != "1d":
            fields["interval"] = self.interval
            fields["path_model"] = self.path_model
            fields["fill_model"] = self.fill_model
            fields["session"] = "cn_a"
        return fields

    # ── monotone transitions ──

    def with_advance(
        self,
        *,
        end_state: AccountState,
        watermark: str,
        engine_fingerprint: str | None = None,
    ) -> "PaperTradeAccount":
        """Return the account after applying one day's ``end_state``.

        ``engine_fingerprint=None`` keeps the current fingerprint (the caller
        did not observe one); a string replaces it.  A watermark that does not
        move forward is a programming error, not a data condition — it would
        make the next replay check silently wrong.
        """
        require_date(watermark, "watermark")
        if self.watermark is not None and watermark <= self.watermark:
            raise ValueError(
                f"watermark must move forward: current {self.watermark}, requested {watermark}"
            )
        return replace(
            self,
            cash=end_state.cash,
            positions=tuple(end_state.positions),
            watermark=watermark,
            engine_fingerprint=(
                self.engine_fingerprint if engine_fingerprint is None else engine_fingerprint
            ),
        )

    def with_non_trading_day(self, trade_date: str) -> "PaperTradeAccount":
        """Advance the watermark over a closed day without touching the ledger."""
        require_date(trade_date, "trade_date")
        if self.watermark is not None and trade_date <= self.watermark:
            raise ValueError(
                f"watermark must move forward: current {self.watermark}, requested {trade_date}"
            )
        days = self.non_trading_days
        if trade_date not in days:
            days = days + (trade_date,)
        return replace(self, watermark=trade_date, non_trading_days=days)

    # ── document shape ──

    def to_dict(self) -> dict[str, Any]:
        """The ``account.json`` document (deterministic key set)."""
        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "market": self.market,
            "start_date": self.start_date,
            "initial_cash": self.initial_cash,
            "initial_positions": _position_rows(self.initial_positions),
            "cash": self.cash,
            "positions": _position_rows(self.positions),
            "watermark": self.watermark,
            "engine_fingerprint": self.engine_fingerprint,
            "created_at": self.created_at,
            "interval": self.interval,
            "path_model": self.path_model,
            "fill_model": self.fill_model,
            "fee_model": dict(self.fee_model),
            "non_trading_days": list(self.non_trading_days),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "PaperTradeAccount":
        """Parse an ``account.json`` document.

        Unknown keys are ignored (a newer writer's additive field must not brick
        an older reader); a different ``schema_version`` is refused, because the
        fields this reader understands may no longer mean the same thing.
        """
        if not isinstance(document, Mapping):
            raise AccountError(INVALID_ACCOUNT, "account document must be an object")
        version = document.get("schema_version", ACCOUNT_SCHEMA_VERSION)
        if version != ACCOUNT_SCHEMA_VERSION:
            raise AccountError(
                INVALID_ACCOUNT,
                f"unsupported account schema_version {version!r}; "
                f"this reader understands {ACCOUNT_SCHEMA_VERSION!r}",
            )
        account_id = validate_account_id(document.get("account_id"))
        market = document.get("market")
        if market not in MARKETS:
            raise AccountError(INVALID_ACCOUNT, f"market must be one of {MARKETS}, got {market!r}")
        watermark = document.get("watermark")
        if watermark is not None:
            watermark = require_date(watermark, "watermark")
        non_trading_days = document.get("non_trading_days") or []
        if not isinstance(non_trading_days, (list, tuple)):
            raise AccountError(INVALID_ACCOUNT, "non_trading_days must be an array")
        days: list[str] = []
        for index, day in enumerate(non_trading_days):
            days.append(require_date(day, f"non_trading_days[{index}]"))
        fee_model = _fee_model(document.get("fee_model"), "fee_model")
        interval = str(document.get("interval") or "5m")
        path_model = str(document.get("path_model") or "bar_median")
        fill_model = str(document.get("fill_model") or "all_or_none")
        _validate_tracking_choices(market, interval, path_model, fill_model)
        initial_positions = _positions(document.get("initial_positions"), "initial_positions")
        positions = _positions(document.get("positions"), "positions")
        _validate_position_rows(initial_positions, "initial_positions", INVALID_ACCOUNT)
        _validate_position_rows(positions, "positions", INVALID_ACCOUNT)
        return cls(
            account_id=account_id,
            market=market,
            start_date=require_date(document.get("start_date"), "start_date"),
            initial_cash=_require_number(document.get("initial_cash"), "initial_cash", minimum=0.0),
            initial_positions=initial_positions,
            cash=_require_number(document.get("cash"), "cash", minimum=0.0),
            positions=positions,
            watermark=watermark,
            engine_fingerprint=str(document.get("engine_fingerprint") or ""),
            created_at=str(document.get("created_at") or ""),
            interval=interval,
            path_model=path_model,
            fill_model=fill_model,
            schema_version=version,
            non_trading_days=tuple(days),
            fee_model=fee_model,
        )


def _fee_model(value: Any, name: str) -> dict[str, float]:
    """Parse a fee-parameter mapping into a sorted ``{str: float}`` dict.

    ``None`` is an empty model (the legacy account shape).  Every value must be
    a finite non-negative number; the mapping is stored as given so a later
    step can prove the same parameters were used.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AccountError(INVALID_ACCOUNT, f"{name} must be an object")
    parsed: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            raise AccountError(INVALID_ACCOUNT, f"{name} keys must be non-empty strings")
        parsed[key] = _require_number(raw, f"{name}[{key}]", minimum=0.0)
    return dict(sorted(parsed.items()))


def _validate_position_rows(positions: Any, field: str, code: str) -> None:
    """Reject duplicate symbols and non-positive rows in either position list."""
    symbols = [item.symbol for item in positions]
    if len(symbols) != len(set(symbols)):
        raise AccountError(
            code,
            f"{field} must not list the same symbol twice: "
            f"{sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})}",
        )
    for index, item in enumerate(positions):
        if item.qty <= 0:
            raise AccountError(code, f"{field}[{index}].qty must be > 0, got {item.qty}")
        if item.avg_cost < 0:
            raise AccountError(
                code, f"{field}[{index}].avg_cost must be >= 0, got {item.avg_cost}"
            )


def _validate_tracking_choices(
    market: str, interval: str, path_model: str, fill_model: str
) -> None:
    """Market/interval/model coherence, shared by creation and reload.

    A document that only fails at the FIRST STEP leaves the operator believing
    the account exists and is tradable, so the reader enforces the same rules
    the writer does.
    """
    if interval not in INTERVALS:
        raise AccountError(
            INVALID_ACCOUNT, f"interval must be one of {INTERVALS}, got {interval!r}"
        )
    if interval == "5m" and market != "cn_a":
        raise AccountError(
            INVALID_ACCOUNT, f"interval 5m is cn_a-only in pt-v1.2, got market {market!r}"
        )
    if path_model not in PATH_MODELS:
        raise AccountError(
            INVALID_ACCOUNT, f"path_model must be one of {PATH_MODELS}, got {path_model!r}"
        )
    if fill_model not in FILL_MODELS:
        raise AccountError(
            INVALID_ACCOUNT, f"fill_model must be one of {FILL_MODELS}, got {fill_model!r}"
        )


def create_account(
    *,
    account_id: str,
    market: str,
    start_date: str,
    initial_cash: float,
    initial_positions: Any = (),
    today: str,
    next_trading_day: str,
    now: str,
    engine_fingerprint: str = "",
    interval: str = "5m",
    path_model: str = "bar_median",
    fill_model: str = "all_or_none",
    fee_model: Mapping[str, Any] | None = None,
) -> PaperTradeAccount:
    """Build a fresh account, enforcing the start-date rule (planbook §0.2).

    ``today`` and ``next_trading_day`` are BOTH injected — this function never
    reads a clock, so "today" is whatever the caller says it is and the same
    call is reproducible in tests and in production.

    Raises :class:`AccountError` with ``code`` in
    ``{start_date_in_past, start_date_not_admissible, invalid_account,
    invalid_initial_positions}``.
    """
    account_id = validate_account_id(account_id)
    if market not in MARKETS:
        raise AccountError(INVALID_ACCOUNT, f"market must be one of {MARKETS}, got {market!r}")
    start = require_date(start_date, "start_date")
    today_ = require_date(today, "today")
    next_day = require_date(next_trading_day, "next_trading_day")
    if not isinstance(now, str) or not now:
        raise AccountError(INVALID_ACCOUNT, "now must be a non-empty ISO-8601 string")

    if start < today_:
        raise AccountError(
            START_DATE_IN_PAST,
            f"start_date {start} precedes today {today_}: a past start is a backtest, "
            "not a paper trade (planbook §0.2)",
        )
    if start > today_ and start != next_day:
        raise AccountError(
            START_DATE_NOT_ADMISSIBLE,
            f"start_date {start} must be today {today_} or the next trading day {next_day}; "
            "an arbitrary future date is not an admissible tracking start",
        )

    cash = _require_number(initial_cash, "initial_cash", minimum=0.0)
    positions = _positions(list(initial_positions or ()), "initial_positions")
    _validate_position_rows(positions, "initial_positions", INVALID_INITIAL_POSITIONS)
    _validate_tracking_choices(market, interval, path_model, fill_model)
    locked_fees = _fee_model(fee_model, "fee_model")

    return PaperTradeAccount(
        account_id=account_id,
        market=market,
        start_date=start,
        initial_cash=cash,
        initial_positions=positions,
        cash=cash,
        positions=positions,
        watermark=None,
        engine_fingerprint=str(engine_fingerprint or ""),
        created_at=now,
        interval=interval,
        path_model=path_model,
        fill_model=fill_model,
        non_trading_days=(),
        fee_model=locked_fees,
    )
