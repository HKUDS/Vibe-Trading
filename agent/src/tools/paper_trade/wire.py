"""pt-v1.1 wire serialization for ``paper_trade_step`` (Step 5 / T5).

The schema-closure surface the Step 6 tool calls: assembles the frozen
:class:`~.schema.PaperTradeStepResult` / :class:`~.schema.ErrorEnvelope`
documents from engine outcomes and serializes them into the single JSON
document that travels on ``result.content[0].text``.  Success and error
share that one in-band channel (AM-5); transport-level MCP errors stay
reserved for engine-internal faults.

Frozen surfaces implemented here:

* AM-4-1 coverage object — ``received_state_hash`` is computed over the RAW
  received ``account_state`` JSON value, not the parsed dataclass
  reconstruction: a key the LLM added or dropped must break the hash exactly
  like a corrupted number, because RM compares against the hash of the
  snapshot it injected (R7-5).  ``fee_model`` enters the coverage object as
  the EFFECTIVE value (AM-4-3: RM always injects it explicitly).
* AM-4-4 — the error envelope carries ``received_state_hash`` only when the
  coverage object is computable from the raw payload (state parseable,
  market known, ids/dates present); otherwise the key is OMITTED, never null.
* VD-15/B2 — ``fills[].reason`` dual mode: orders → ``""``; strategy_path →
  the strategy reason truncated to <=200 characters without ever splitting a
  multi-byte character (:func:`strategy_fill_reason`).
* VD-4 serialization — ``sort_keys`` + compact separators + ``ensure_ascii
  =False`` + ``allow_nan=False``: byte-deterministic strict JSON, no
  timestamps anywhere (VD-7), NaN/Infinity refused.

pt-v1.2 (D8) is additive and version-gated: a request whose four new fields
are all at their defaults produces the pt-v1.1 document with the v1.2 keys
ABSENT (not empty), while a request with at least one non-default field emits
``schema_version="pt-v1.2"`` plus ``engine_fingerprint``, ``canceled_orders``
and ``events``.  AM-4-4's error-path hash follows the same rule: the new
fields join the coverage object only when non-default (D4).

Determinism (R1-1): no clock, no randomness, no I/O — every input injected.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from . import state_hash
from .schema import (
    CANCELED_REASON_CODE,
    DEFAULT_FILL_MODEL,
    DEFAULT_INTERVAL,
    DEFAULT_PATH_MODEL,
    DEFAULT_SESSION,
    ERROR_CODES,
    FILL_MODELS,
    INTERVALS,
    MARKETS,
    PATH_MODELS,
    SCHEMA_VERSIONS,
    SCHEMA_VERSION_V1_2,
    SESSION_EVENT_TYPES,
    SESSIONS,
    DateRange,
    ErrorEnvelope,
    PaperTradeSchemaError,
    PaperTradeStepResult,
    parse_account_state,
)
from .state_hash import compute_received_state_hash, effective_fee_model

if TYPE_CHECKING:
    from .engine import MatchOutcome
    from .schema import PaperTradeStepRequest

__all__ = [
    "FILL_REASON_MAX_CHARS",
    "ORDERS_FILL_REASON",
    "assemble_result",
    "build_error_payload",
    "build_success_payload",
    "dumps_payload",
    "received_state_hash_from_payload",
    "strategy_fill_reason",
]

#: VD-15/B2 frozen values: orders mode has no reason source (empty string,
#: matching the RM DDL ``paper_trades.reason TEXT NOT NULL DEFAULT ''``);
#: strategy_path mode truncates to 200 characters (code points).
ORDERS_FILL_REASON = ""
FILL_REASON_MAX_CHARS = 200


def strategy_fill_reason(reason: str | None) -> str:
    """VD-15/B2 strategy_path mode: truncate to <=200 characters, UTF-8 safe.

    Python strings slice on code points, so a multi-byte character (CJK,
    emoji) is never split and the result always encodes to well-formed
    UTF-8.  ``None`` (a strategy Order without reason text) → ``""``.
    """
    if reason is None:
        return ORDERS_FILL_REASON
    if not isinstance(reason, str):
        raise TypeError(f"fill reason must be a string, got {type(reason).__name__}")
    return reason[:FILL_REASON_MAX_CHARS]


def _payload_choices(payload: dict[str, Any]) -> dict[str, str] | None:
    """Read the four pt-v1.2 request enums from a raw payload, or ``None``.

    Absent/null is the default (D8).  A present non-string or out-of-vocabulary
    value makes the AM-4-4 coverage object not computable, exactly like a
    malformed fee_model.
    """
    choices: dict[str, str] = {}
    for key, allowed, default in (
        ("interval", INTERVALS, DEFAULT_INTERVAL),
        ("session", SESSIONS, DEFAULT_SESSION),
        ("path_model", PATH_MODELS, DEFAULT_PATH_MODEL),
        ("fill_model", FILL_MODELS, DEFAULT_FILL_MODEL),
    ):
        value = payload.get(key)
        if value is None:
            value = default
        elif not isinstance(value, str) or value not in allowed:
            return None
        choices[key] = value
    return choices


def received_state_hash_from_payload(payload: Any) -> str | None:
    """AM-4-4: hash the raw coverage fields, or ``None`` when not computable.

    Not computable = the received ``account_state`` fails the shape parse, or
    the coverage object cannot be extracted (account_id/from_date/to_date not
    strings, market outside the frozen enum, malformed fee_model, or a pt-v1.2
    field that is present but outside its vocabulary).  The error envelope then
    OMITS ``received_state_hash`` — RM reads the absence as "state unparseable"
    and must not burn its retry chain on a corrupt snapshot.  The hash covers
    the RAW ``account_state`` value (see the module docstring) with the
    effective fee model merged over the market defaults; non-default pt-v1.2
    fields join the coverage object (D4).
    """
    if not isinstance(payload, dict):
        return None
    account_id = payload.get("account_id")
    market = payload.get("market")
    from_date = payload.get("from_date")
    to_date = payload.get("to_date")
    if not all(isinstance(value, str) for value in (account_id, market, from_date, to_date)):
        return None
    if market not in MARKETS:
        return None
    raw_state = payload.get("account_state")
    try:
        parse_account_state(raw_state)
    except PaperTradeSchemaError:
        return None
    # Only a missing or explicit null fee_model defaults to {} — a PRESENT
    # falsy non-dict ([] / "" / false / 0) is malformed, not absent, and the
    # coverage object is not computable from it.
    fee_model_raw = payload.get("fee_model")
    if fee_model_raw is None:
        fee_model_raw = {}
    if not isinstance(fee_model_raw, dict):
        return None
    choices = _payload_choices(payload)
    if choices is None:
        return None
    fee_model: dict[str, float] = {}
    for key, value in fee_model_raw.items():
        if not isinstance(key, str):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            numeric = float(value)
        except OverflowError:
            return None  # integer literal beyond the double range
        if not math.isfinite(numeric):
            return None
        fee_model[key] = numeric
    try:
        return compute_received_state_hash(
            account_id=account_id,
            market=market,
            account_state=raw_state,
            fee_model=effective_fee_model(market, fee_model),
            from_date=from_date,
            to_date=to_date,
            **choices,
        )
    except (TypeError, ValueError):
        # The raw state passed the shape parse but is not JCS-canonicalizable
        # (non-str keys, non-JSON-native or non-finite values the parser does
        # not read).  AM-4-4: not computable → omit the hash, never raise out
        # of the error path.
        return None


def assemble_result(
    request: PaperTradeStepRequest,
    outcome: MatchOutcome,
    *,
    raw_account_state: Any,
) -> PaperTradeStepResult:
    """Map a successful engine outcome onto the frozen success document.

    ``raw_account_state`` MUST be the raw JSON value as received (the tool
    input's ``account_state`` member) — hashing the parsed reconstruction
    would launder LLM-introduced keys past the RM verification (AM-4-1).
    The hash and the echo share ``outcome.effective_fee_model`` so the
    covered fee model and the disclosed fee model cannot diverge.

    The pt-v1.2 out-params are read with ``getattr`` defaults so this builder
    works before T3/T4 populate ``MatchOutcome``.  A v1.2 request whose
    outcome carries no ``engine_fingerprint`` gets the D3 fingerprint of the
    declared engine parameters with an empty bar fingerprint (no bar evidence
    claimed); a v1.1 request never carries any of the three fields (D8).
    """
    if outcome.error is not None:
        raise ValueError(
            "assemble_result refuses an errored outcome: the in-band error "
            "envelope (build_error_payload) is the only error channel (AM-5)"
        )
    received = compute_received_state_hash(
        account_id=request.account_id,
        market=request.market,
        account_state=raw_account_state,
        fee_model=outcome.effective_fee_model,
        from_date=request.from_date,
        to_date=request.to_date,
        interval=request.interval,
        session=request.session,
        path_model=request.path_model,
        fill_model=request.fill_model,
    )
    version = request.schema_version
    if request.uses_v1_2:
        fingerprint = getattr(outcome, "engine_fingerprint", "")
        if not fingerprint:
            fingerprint = state_hash.engine_fingerprint(
                interval=request.interval,
                path_model=request.path_model,
                fill_model=request.fill_model,
            )
        canceled_orders = tuple(getattr(outcome, "canceled_orders", ()))
        events = tuple(getattr(outcome, "events", ()))
    else:
        fingerprint, canceled_orders, events = "", (), ()
    return PaperTradeStepResult(
        account_id=request.account_id,
        market=request.market,
        range=DateRange(from_=request.from_date, to=request.to_date),
        received_state_hash=received,
        effective_fee_model=dict(outcome.effective_fee_model),
        fills=outcome.fills,
        rejected_orders=outcome.rejected_orders,
        end_state=outcome.end_state,
        nav_series=outcome.nav_series,
        skipped_days=outcome.skipped_days,
        warnings=outcome.warnings,
        data_provenance=replace(
            outcome.data_provenance, limit_provenance=tuple(outcome.limit_provenance)
        ),
        schema_version=version,
        engine_fingerprint=fingerprint,
        canceled_orders=canceled_orders,
        events=events,
    )


def _provenance_payload(result: PaperTradeStepResult) -> dict[str, Any]:
    prov = result.data_provenance
    payload: dict[str, Any] = {"source": prov.source}
    if prov.ch_as_of is not None:
        payload["ch_as_of"] = prov.ch_as_of
    if prov.network_as_of is not None:
        payload["network_as_of"] = prov.network_as_of
    if prov.bars_as_of is not None:
        payload["bars_as_of"] = prov.bars_as_of
    if prov.corporate_actions:
        payload["corporate_actions"] = [dict(event) for event in prov.corporate_actions]
    if prov.limit_provenance:
        payload["limit_provenance"] = list(prov.limit_provenance)
    return payload


#: D3: the fingerprint is sha256 hex, always 64 lowercase characters.
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _canceled_payload(orders: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Serialize ``canceled_orders``, failing closed on the frozen token."""
    rows: list[dict[str, Any]] = []
    for row in orders:
        if row.reason_code != CANCELED_REASON_CODE:
            raise ValueError(
                f"canceled reason_code must be {CANCELED_REASON_CODE!r}, "
                f"got {row.reason_code!r}"
            )
        rows.append(
            {
                "trade_date": row.trade_date,
                "symbol": row.symbol,
                "side": row.side,
                "qty": row.qty,
                "reason_code": row.reason_code,
                "detail": row.detail,
            }
        )
    return rows


def _events_payload(events: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Serialize ``events``, failing closed on an unknown ``event_type``."""
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in SESSION_EVENT_TYPES:
            raise ValueError(
                f"event_type {event.event_type!r} is outside the pt-v1.2 "
                f"vocabulary {SESSION_EVENT_TYPES}"
            )
        rows.append(
            {
                "trade_date": event.trade_date,
                "symbol": event.symbol,
                "event_type": event.event_type,
                "detail": event.detail,
            }
        )
    return rows


def build_success_payload(result: PaperTradeStepResult) -> dict[str, Any]:
    """Serialize the success document (AMENDMENT §2.2 wire shape).

    ``range.from_`` maps to the wire key ``"from"``; optional provenance
    fields are omitted (never null) when unset; arrays keep the engine's
    frozen order (VD-10: day-ascending, then input index).

    The three pt-v1.2 keys are emitted ONLY when ``schema_version`` is
    ``pt-v1.2`` (D8), so the pt-v1.1 byte stream is untouched.  A v1.2
    document without a 64-hex fingerprint, with a cancel token other than the
    frozen one, or with an unknown event type raises (engine bug / transport
    class), never shipping a document RM cannot verify.
    """
    if result.schema_version not in SCHEMA_VERSIONS:
        raise ValueError(
            f"unknown schema_version {result.schema_version!r}; "
            f"expected one of {SCHEMA_VERSIONS}"
        )
    payload: dict[str, Any] = {
        "schema_version": result.schema_version,
        "tool": result.tool,
        "account_id": result.account_id,
        "market": result.market,
        "range": {"from": result.range.from_, "to": result.range.to},
        "received_state_hash": result.received_state_hash,
        "effective_fee_model": dict(result.effective_fee_model),
        "fills": [
            {
                "trade_date": fill.trade_date,
                "symbol": fill.symbol,
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "fee": fill.fee,
                "reason": fill.reason,
            }
            for fill in result.fills
        ],
        "rejected_orders": [
            {
                "trade_date": rejected.trade_date,
                "symbol": rejected.symbol,
                "side": rejected.side,
                "qty": rejected.qty,
                "reason_code": rejected.reason_code,
                "detail": rejected.detail,
            }
            for rejected in result.rejected_orders
        ],
        "end_state": {
            "cash": result.end_state.cash,
            "positions": [
                {"symbol": position.symbol, "qty": position.qty, "avg_cost": position.avg_cost}
                for position in result.end_state.positions
            ],
        },
        "nav_series": [
            {
                "date": point.date,
                "nav": point.nav,
                "cash": point.cash,
                "position_value": point.position_value,
            }
            for point in result.nav_series
        ],
        "skipped_days": [
            {"date": skipped.date, "reason": skipped.reason} for skipped in result.skipped_days
        ],
        "warnings": list(result.warnings),
        "data_provenance": _provenance_payload(result),
    }
    if result.schema_version == SCHEMA_VERSION_V1_2:
        if not _FINGERPRINT_RE.match(result.engine_fingerprint):
            raise ValueError(
                "a pt-v1.2 result requires a 64-character lowercase hex "
                f"engine_fingerprint (D3), got {result.engine_fingerprint!r}"
            )
        payload["engine_fingerprint"] = result.engine_fingerprint
        payload["canceled_orders"] = _canceled_payload(result.canceled_orders)
        payload["events"] = _events_payload(result.events)
    return payload


def build_error_payload(envelope: ErrorEnvelope) -> dict[str, Any]:
    """Serialize the in-band error envelope (AM-5 frozen field set).

    ``code`` outside the frozen 2-value vocabulary is an engine bug, not a
    data condition — it raises (transport class) instead of shipping an
    envelope RM cannot route.  ``received_state_hash`` is included only when
    present (AM-4-4); the key is never emitted as null.
    """
    if envelope.status != "error":
        raise ValueError(f"error envelope status must be 'error', got {envelope.status!r}")
    if envelope.code not in ERROR_CODES:
        raise ValueError(
            f"error code {envelope.code!r} is outside the frozen AM-5 vocabulary {ERROR_CODES}"
        )
    payload: dict[str, Any] = {
        "status": envelope.status,
        "code": envelope.code,
        "account_id": envelope.account_id,
        "market": envelope.market,
        "range": {"from": envelope.range.from_, "to": envelope.range.to},
        "message": envelope.message,
    }
    if envelope.received_state_hash is not None:
        payload["received_state_hash"] = envelope.received_state_hash
    return payload


def dumps_payload(payload: Any) -> str:
    """The single in-band JSON document text (VD-4 spelling, strict JSON).

    Sorted keys + compact separators make the bytes deterministic for the
    T1 goldens; ``ensure_ascii=False`` keeps UTF-8 raw; ``allow_nan=False``
    refuses NaN/Infinity instead of emitting non-standard tokens.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
