"""pt-v1.1 wire contract for ``paper_trade_step`` (dataclasses + vocabularies).

Declares the in-param, out-param and error-envelope shapes frozen by
``PAPER_TRADING_ENGINE_AMENDMENT_PT_V1.1.md`` §2 (the FROZEN summary), plus
the AM-14 closed vocabularies.  pt-v1.1 is APPROVED — G1 opened by the RM
written approval of 2026-10-19 (``PAPER_TRADING_ENGINE_APPROVAL_GRANTED_PT_V1.1.md``).
Every contract-sensitive value here is FROZEN per the approval §5
declaration: vocabulary or field-set changes are a major schema bump with
RM written confirmation; additive fields are a minor bump (REQUIREMENTS §9).

Companion artifacts:

* ``schema/tool_contracts/paper_trade_step-v1.1.json`` — finalized out-param
  + error-envelope jsonschema (VD-13), loaded by :func:`load_contract_schema`.
* ``state_hash.py`` — ``received_state_hash`` / ``effective_fee_model``.
* ``wire.py`` — success/error payload builders + deterministic JSON
  serialization (Step 5 split: this module stays shapes + boundary parsing).

``jsonschema`` is deliberately NOT imported: it is not a declared runtime
dependency (zero-new-dependency red line, REQUIREMENTS §9), so
:func:`validate_payload` implements the small keyword subset the skeleton
uses.  The JSON file stays a standard draft-2020-12 document, so RM (or a
future declared dependency) can validate it with the real library.

Out-param dataclasses are declarative wire shapes: the engine (Steps 3-5)
assembles them and owns Decimal→JSON serialization (VD-9).  In-params are
parsed at the boundary by :func:`parse_request` (parse, don't validate —
downstream code receives typed values).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ERROR_CODES",
    "MARKETS",
    "REASON_CODES",
    "SIDES",
    "SKIPPED_DAY_REASONS",
    "SCHEMA_VERSION",
    "TOOL_NAME",
    "AccountState",
    "ErrorEnvelope",
    "Fill",
    "NavPoint",
    "Order",
    "PaperTradeSchemaError",
    "PaperTradeStepRequest",
    "PaperTradeStepResult",
    "Position",
    "RejectedOrder",
    "SkippedDay",
    "load_contract_schema",
    "parse_account_state",
    "parse_request",
    "validate_payload",
]

#: Wire contract version — FROZEN: pt-v1.1 is the first frozen implementation
#: version (G1 approved 2026-10-19; AMENDMENT header version-semantics ruling).
#: Constant convention: backtest_summary.py:31, market_data_tool.py:71.
SCHEMA_VERSION = "pt-v1.1"

#: Bare MCP tool name (RM observer whitelists bare + ``vibe-trading_`` prefix).
TOOL_NAME = "paper_trade_step"

# FROZEN (G1 approved 2026-10-19): the three vocabularies below are the AM-14
# closed tables (11 reason_code + 2 skipped reason + 2 error code).  Any
# add/remove/change = major schema bump with RM written confirmation
# (REQUIREMENTS §9 / APPROVAL §5 frozen-surface declaration).
#: ``rejected_orders[].reason_code`` — closed vocabulary, 11 values (AM-14).
REASON_CODES: tuple[str, ...] = (
    "insufficient_cash",
    "insufficient_position",
    "t_plus_1",
    "limit_up",
    "limit_down",
    "suspended",
    "lot_size",
    "non_trading_day",
    "unknown_symbol",
    "corporate_action_unresolved",  # AM-2
    "limit_not_marketable",  # AM-7
)

#: ``skipped_days[].reason`` — closed vocabulary, 2 values (AM-14).
SKIPPED_DAY_REASONS: tuple[str, ...] = (
    "non_trading_day",  # cn_a only — CH trade_calendar truth (AM-6)
    "market_closed_inferred",  # hk/us only — bar-inferred, always + warning (AM-6)
)

#: In-band error envelope ``code`` — closed vocabulary, 2 values (AM-5/AM-14).
#: Transport-level MCP errors are reserved for engine-internal faults only.
ERROR_CODES: tuple[str, ...] = (
    "PAPER_DATA_NOT_READY",  # retryable — RM 30min × 3
    "INVALID_REQUEST",  # non-retryable — input contract violation
)

# FROZEN (G1 approved 2026-10-19): market/side enums per REQUIREMENTS §2.1
# (pt-v1.0 dispatched values, carried into pt-v1.1 unchanged).
MARKETS: tuple[str, ...] = ("cn_a", "hk", "us")
SIDES: tuple[str, ...] = ("buy", "sell")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Repo-root-relative location of the wire-contract jsonschema (VD-13).
_CONTRACT_SCHEMA_PATH = Path(__file__).with_name("paper_trade_step-v1.1.json")


class PaperTradeSchemaError(ValueError):
    """Raised when a tool input violates the pt-v1.1 in-param contract.

    Step 6 (tool.py) maps this to the in-band ``INVALID_REQUEST`` envelope
    (AM-5); messages are deterministic English (VD-7).
    """


# ── In-params (REQUIREMENTS §2.1 + AM-3/AM-4 revisions) ──


@dataclass(frozen=True, slots=True)
class Position:
    """One holding inside ``account_state`` / ``end_state``."""

    symbol: str
    qty: float
    avg_cost: float


@dataclass(frozen=True, slots=True)
class AccountState:
    """RM-injected ledger snapshot.  The engine trusts but echoes its hash (R7)."""

    cash: float
    positions: tuple[Position, ...] = ()


@dataclass(frozen=True, slots=True)
class Order:
    """One order of the ``orders`` array (single-day mode only, AM-3)."""

    symbol: str
    side: str
    qty: float
    limit: float | None = None


@dataclass(frozen=True, slots=True)
class PaperTradeStepRequest:
    """Parsed ``paper_trade_step`` in-params.

    ``orders`` XOR ``strategy_path`` and the orders-mode single-day rule
    (AM-3) are SEMANTIC gates owned by tool.py (Step 6, INVALID_REQUEST);
    this shape parser does not pre-empt them.
    """

    account_id: str
    market: str
    account_state: AccountState
    from_date: str
    to_date: str
    orders: tuple[Order, ...] | None = None
    strategy_path: str | None = None
    # FROZEN (AM-4-3, G1 approved): RM dispatch always injects fee_model
    # explicitly (required-at-dispatch) while the field stays schema-optional
    # for backward compatibility (AMENDMENT §2.3).
    fee_model: dict[str, float] = field(default_factory=dict)


def _require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaperTradeSchemaError(f"{path} must be a JSON number, got {type(value).__name__}")
    try:
        numeric = float(value)
    except OverflowError:
        # An integer literal beyond the double range is not a finite JSON
        # number for wire purposes (JCS interpretation stays within ±2^53
        # across implementations, state_hash.py module docstring).
        numeric = math.inf if value > 0 else -math.inf
    if not math.isfinite(numeric):
        raise PaperTradeSchemaError(f"{path} must be a finite JSON number, got {value!r}")
    return numeric


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise PaperTradeSchemaError(f"{path} must be a string, got {type(value).__name__}")
    return value


def _parse_date(value: Any, path: str) -> str:
    text = _require_str(value, path)
    if not _DATE_RE.match(text):
        raise PaperTradeSchemaError(f"{path} must be YYYY-MM-DD, got {text!r}")
    return text


def _parse_position(raw: Any, path: str) -> Position:
    if not isinstance(raw, dict):
        raise PaperTradeSchemaError(f"{path} must be an object, got {type(raw).__name__}")
    return Position(
        symbol=_require_str(raw.get("symbol"), f"{path}.symbol"),
        qty=_require_number(raw.get("qty"), f"{path}.qty"),
        avg_cost=_require_number(raw.get("avg_cost"), f"{path}.avg_cost"),
    )


def parse_account_state(raw: Any, path: str = "account_state") -> AccountState:
    """Parse ``account_state`` alone (public: the AM-4-4 error-path hash in
    ``wire.py`` gates on state parseability without a full request parse)."""
    if not isinstance(raw, dict):
        raise PaperTradeSchemaError(f"{path} must be an object, got {type(raw).__name__}")
    positions_raw = raw.get("positions", [])
    if not isinstance(positions_raw, list):
        raise PaperTradeSchemaError(f"{path}.positions must be an array")
    return AccountState(
        cash=_require_number(raw.get("cash"), f"{path}.cash"),
        positions=tuple(
            _parse_position(item, f"{path}.positions[{i}]") for i, item in enumerate(positions_raw)
        ),
    )


def _parse_order(raw: Any, path: str) -> Order:
    if not isinstance(raw, dict):
        raise PaperTradeSchemaError(f"{path} must be an object, got {type(raw).__name__}")
    side = _require_str(raw.get("side"), f"{path}.side")
    if side not in SIDES:
        raise PaperTradeSchemaError(f"{path}.side must be one of {SIDES}, got {side!r}")
    limit_raw = raw.get("limit")
    limit = None if limit_raw is None else _require_number(limit_raw, f"{path}.limit")
    return Order(
        symbol=_require_str(raw.get("symbol"), f"{path}.symbol"),
        side=side,
        qty=_require_number(raw.get("qty"), f"{path}.qty"),
        limit=limit,
    )


def parse_request(payload: dict[str, Any]) -> PaperTradeStepRequest:
    """Parse JSON-parsed tool input into the typed request contract.

    Shape-level boundary parse only: types, enums, date format.  Raises
    :class:`PaperTradeSchemaError` with a deterministic message naming the
    offending path.
    """
    if not isinstance(payload, dict):
        raise PaperTradeSchemaError(f"request must be an object, got {type(payload).__name__}")
    market = _require_str(payload.get("market"), "market")
    if market not in MARKETS:
        raise PaperTradeSchemaError(f"market must be one of {MARKETS}, got {market!r}")

    orders_raw = payload.get("orders")
    orders: tuple[Order, ...] | None = None
    if orders_raw is not None:
        if not isinstance(orders_raw, list):
            raise PaperTradeSchemaError("orders must be an array")
        orders = tuple(_parse_order(item, f"orders[{i}]") for i, item in enumerate(orders_raw))

    strategy_path = payload.get("strategy_path")
    if strategy_path is not None:
        strategy_path = _require_str(strategy_path, "strategy_path")

    # Only a missing or explicit null fee_model defaults to {} (AM-4-3 keeps
    # the field schema-optional); a PRESENT falsy non-dict ([] / "" / false /
    # 0) is a contract violation, not an absence — `or {}` would launder it.
    fee_model_raw = payload.get("fee_model")
    if fee_model_raw is None:
        fee_model_raw = {}
    if not isinstance(fee_model_raw, dict):
        raise PaperTradeSchemaError(
            f"fee_model must be an object, got {type(fee_model_raw).__name__}"
        )
    fee_model = {
        _require_str(key, "fee_model key"): _require_number(value, f"fee_model.{key}")
        for key, value in fee_model_raw.items()
    }

    return PaperTradeStepRequest(
        account_id=_require_str(payload.get("account_id"), "account_id"),
        market=market,
        account_state=parse_account_state(payload.get("account_state"), "account_state"),
        from_date=_parse_date(payload.get("from_date"), "from_date"),
        to_date=_parse_date(payload.get("to_date"), "to_date"),
        orders=orders,
        strategy_path=strategy_path,
        fee_model=fee_model,
    )


# ── Out-params (AMENDMENT §2.2) — declarative wire shapes ──


@dataclass(frozen=True, slots=True)
class DateRange:
    """``range`` — the closed [from, to] interval actually processed."""

    from_: str
    to: str


@dataclass(frozen=True, slots=True)
class Fill:
    """One executed fill.  ``reason`` dual-mode semantics FROZEN (VD-15/B2):
    orders mode = ``""``; strategy_path mode = strategy reason truncated to
    <=200 characters, UTF-8 safe (``wire.strategy_fill_reason``)."""

    trade_date: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RejectedOrder:
    """One rejected order; ``reason_code`` from the closed 11-value table."""

    trade_date: str
    symbol: str
    side: str
    qty: float
    reason_code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class NavPoint:
    """One ``nav_series`` row (skipped days produce NO row — R3)."""

    date: str
    nav: float
    cash: float
    position_value: float


@dataclass(frozen=True, slots=True)
class SkippedDay:
    """One ``skipped_days`` row; ``reason`` from the closed 2-value table."""

    date: str
    reason: str


@dataclass(frozen=True, slots=True)
class DataProvenance:
    """``data_provenance`` — extension set FINALIZED at G1: AM-9 merged-frame
    fields (cn_a), AM-2 ``corporate_actions`` events, VD-11 cn_a limit/ST/
    suspension path tokens (``limit_provenance``, ``<symbol>@<date>:<token>``).
    Further additions = minor schema bump (APPROVAL §5)."""

    source: str
    bars_as_of: str | None = None
    ch_as_of: str | None = None
    network_as_of: str | None = None
    corporate_actions: tuple[dict[str, Any], ...] = ()
    limit_provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PaperTradeStepResult:
    """Full success out-param document (AMENDMENT §2.2, pt-v1.1)."""

    account_id: str
    market: str
    range: DateRange
    received_state_hash: str
    effective_fee_model: dict[str, float]
    fills: tuple[Fill, ...] = ()
    rejected_orders: tuple[RejectedOrder, ...] = ()
    end_state: AccountState = field(default_factory=AccountState)
    nav_series: tuple[NavPoint, ...] = ()
    skipped_days: tuple[SkippedDay, ...] = ()
    warnings: tuple[str, ...] = ()  # deterministic English, no timestamps (VD-7)
    data_provenance: DataProvenance = field(
        default_factory=lambda: DataProvenance(source="")
    )
    schema_version: str = SCHEMA_VERSION
    tool: str = TOOL_NAME


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """In-band error envelope (AM-5, FROZEN field set) — same
    ``result.content[0].text`` channel as the success document, never a
    transport error; ``received_state_hash`` present only when the state was
    parseable (AM-4-4).  Serialized by ``wire.build_error_payload``."""

    code: str
    account_id: str
    market: str
    range: DateRange
    message: str
    received_state_hash: str | None = None
    status: str = "error"


# ── Contract schema loading + dependency-free subset validation ──


def load_contract_schema(name: str = "result") -> dict[str, Any]:
    """Load one named jsonschema from the VD-13 contract file.

    ``name`` is ``"result"`` (success out-param) or ``"error_envelope"``.
    Read-only; the file is the finalized pt-v1.1 contract (G1 approved
    2026-10-19).
    """
    document = json.loads(_CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    schemas = document.get("schemas", {})
    if name not in schemas:
        raise KeyError(f"unknown contract schema {name!r}; available: {sorted(schemas)}")
    return schemas[name]


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list, tuple),
    "string": (str,),
    "boolean": (bool,),
}


def _type_matches(instance: Any, json_type: str) -> bool:
    if json_type == "null":
        return instance is None
    if json_type == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if json_type == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if json_type == "boolean":
        return isinstance(instance, bool)
    expected = _TYPE_CHECKS.get(json_type)
    if expected is None or (json_type == "object" and isinstance(instance, bool)):
        return True  # unknown keyword value — not this validator's call
    return isinstance(instance, expected)


def _validate_node(instance: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    """Recursive subset validator: type/const/enum/required/properties/items/
    additionalProperties(bool).  Unknown keywords are ignored — the skeleton
    stays inside this subset so the hand-rolled pass is faithful."""
    if not isinstance(schema, dict):
        return
    json_type = schema.get("type")
    if isinstance(json_type, str) and not _type_matches(instance, json_type):
        errors.append(f"{path}: expected type {json_type!r}, got {type(instance).__name__}")
        return
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", ()):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in instance:
                _validate_node(instance[key], sub_schema, f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False and properties:
            unknown = sorted(set(instance) - set(properties))
            for key in unknown:
                errors.append(f"{path}: additional property {key!r} is not allowed")
    if isinstance(instance, (list, tuple)):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(instance):
                _validate_node(item, items_schema, f"{path}[{i}]", errors)


def validate_payload(payload: Any, schema: dict[str, Any]) -> list[str]:
    """Validate ``payload`` against a contract schema; return error strings.

    Empty list = valid.  Deterministic order: schema-declared order for
    required/properties, index order for arrays.
    """
    errors: list[str] = []
    _validate_node(payload, schema, "$", errors)
    return errors
