"""pt-v1.1 / pt-v1.2 wire contract for ``paper_trade_step`` (shapes + vocabularies).

Declares the in-param, out-param and error-envelope shapes frozen by
``PAPER_TRADING_ENGINE_AMENDMENT_PT_V1.1.md`` §2 (the FROZEN summary), plus
the AM-14 closed vocabularies.  pt-v1.1 is APPROVED — G1 opened by the RM
written approval of 2026-10-19 (``PAPER_TRADING_ENGINE_APPROVAL_GRANTED_PT_V1.1.md``).
Every contract-sensitive value here is FROZEN per the approval §5
declaration: vocabulary or field-set changes are a major schema bump with
RM written confirmation; additive fields are a minor bump (REQUIREMENTS §9).

pt-v1.2 is the ADDITIVE bump for the cn_a 5m post-close step (P0 plan T2,
decision record D1-D8).  It adds four OPTIONAL request fields — ``interval``,
``session``, ``path_model``, ``fill_model`` — whose defaults reproduce the
pt-v1.1 semantics exactly, and three out-param additions —
``engine_fingerprint``, ``canceled_orders``, ``events`` — emitted ONLY for a
v1.2 call.  "v1.2 call" means at least one new request field is non-default
(D8): every call that omits them stays byte-identical to pt-v1.1, including
``received_state_hash`` (D4).  The pt-v1.1 vocabularies (``REASON_CODES``,
``SKIPPED_DAY_REASONS``, ``ERROR_CODES``) are NOT extended; the emergency
cancel token lives only inside ``canceled_orders`` (D2).

Companion artifacts:

* ``schema/tool_contracts/paper_trade_step-v1.1.json`` — frozen v1.1 out-param
  + error-envelope jsonschema (VD-13), loaded by :func:`load_contract_schema`.
* ``schema/tool_contracts/paper_trade_step-v1.2.json`` — the additive v1.2
  copy (same loader, ``version="pt-v1.2"``).
* ``state_hash.py`` — ``received_state_hash`` / ``effective_fee_model`` /
  ``engine_fingerprint``.
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
    "CANCELED_REASON_CODE",
    "DEFAULT_FILL_MODEL",
    "DEFAULT_INTERVAL",
    "DEFAULT_PATH_MODEL",
    "DEFAULT_SESSION",
    "ERROR_CODES",
    "FILL_MODELS",
    "INTERVALS",
    "MARKETS",
    "PATH_MODELS",
    "REASON_CODES",
    "SCHEMA_VERSIONS",
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_V1_2",
    "SESSION_EVENT_TYPES",
    "SESSIONS",
    "SIDES",
    "SKIPPED_DAY_REASONS",
    "TOOL_NAME",
    "AccountState",
    "CanceledOrder",
    "ErrorEnvelope",
    "Fill",
    "NavPoint",
    "Order",
    "PaperTradeSchemaError",
    "PaperTradeStepRequest",
    "PaperTradeStepResult",
    "Position",
    "RejectedOrder",
    "SessionEvent",
    "SkippedDay",
    "load_contract_schema",
    "parse_account_state",
    "parse_request",
    "validate_payload",
]

#: Wire contract version — FROZEN: pt-v1.1 is the first frozen implementation
#: version (G1 approved 2026-10-19; AMENDMENT header version-semantics ruling).
#: It stays the DEFAULT version emitted: a call that uses no pt-v1.2 field is
#: a pt-v1.1 document, byte-identical to the frozen output (D8).
#: Constant convention: backtest_summary.py:31, market_data_tool.py:71.
SCHEMA_VERSION = "pt-v1.1"

#: Additive bump version (P0 5m plan T2): emitted when at least one new
#: request field is non-default.
SCHEMA_VERSION_V1_2 = "pt-v1.2"

#: Every version this loader can resolve, oldest first.
SCHEMA_VERSIONS: tuple[str, ...] = (SCHEMA_VERSION, SCHEMA_VERSION_V1_2)

# ── pt-v1.2 additive request vocabularies (D1/D5/D8) ──
#
# Defaults are the pt-v1.1 semantics: omitting all four fields selects the
# frozen daily close-price path and leaves the wire document untouched.
#: ``interval`` — 1d keeps the frozen pt-v1.1 path; 5m is cn_a-only (D5).
INTERVALS: tuple[str, ...] = ("1d", "5m")
DEFAULT_INTERVAL = "1d"

#: ``session`` — ``auto`` resolves to cn_a for market=cn_a and is inert for
#: hk/us; ``cn_a`` with a non-cn_a market is an INVALID_REQUEST gate (D5).
SESSIONS: tuple[str, ...] = ("auto", "cn_a")
DEFAULT_SESSION = "auto"

#: ``path_model`` — how the reference price is derived from the matched bar
#: (D1). Ignored for interval=1d (which keeps the pt-v1.1 close path).
PATH_MODELS: tuple[str, ...] = ("bar_median", "bar_close")
DEFAULT_PATH_MODEL = "bar_median"

#: ``fill_model`` — the only P0 value: all-or-nothing, no partial fills.
FILL_MODELS: tuple[str, ...] = ("all_or_none",)
DEFAULT_FILL_MODEL = "all_or_none"

#: ``events[].event_type`` — pt-v1.2 session facts (T4, D2). Not an AM-14
#: vocabulary and not part of any frozen pt-v1.1 table.
SESSION_EVENT_TYPES: tuple[str, ...] = (
    "non_trading_day",
    "halted",
    "price_limit",
    "auction_window",
)

#: ``canceled_orders[].reason_code`` — the single T3 emergency-cancel token
#: (D2). Deliberately NOT a member of ``REASON_CODES``, which stays frozen.
CANCELED_REASON_CODE = "canceled_after_failed_match"

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

#: Contract jsonschemas ship INSIDE the package (``tools/paper_trade/*.json`` is
#: declared package-data) so an installed wheel or sdist resolves them without
#: the repository root.  ``schema/tool_contracts/`` keeps the published mirror;
#: a test pins the two copies byte-identical.
_CONTRACT_SCHEMA_DIR = Path(__file__).resolve().parent
_CONTRACT_SCHEMA_PATHS: dict[str, Path] = {
    SCHEMA_VERSION: _CONTRACT_SCHEMA_DIR / "paper_trade_step-v1.1.json",
    SCHEMA_VERSION_V1_2: _CONTRACT_SCHEMA_DIR / "paper_trade_step-v1.2.json",
}


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
    # pt-v1.2 additive fields (D8): defaults ARE the pt-v1.1 semantics, so an
    # absent field is indistinguishable from the default value everywhere.
    interval: str = DEFAULT_INTERVAL
    session: str = DEFAULT_SESSION
    path_model: str = DEFAULT_PATH_MODEL
    fill_model: str = DEFAULT_FILL_MODEL

    @property
    def uses_v1_2(self) -> bool:
        """Whether this call selects the additive pt-v1.2 surface (D8).

        True iff at least one new request field is non-default.  A False
        request must keep the pt-v1.1 byte-identical output and hash (D4).
        """
        return (
            self.interval != DEFAULT_INTERVAL
            or self.session != DEFAULT_SESSION
            or self.path_model != DEFAULT_PATH_MODEL
            or self.fill_model != DEFAULT_FILL_MODEL
        )

    @property
    def schema_version(self) -> str:
        """The wire ``schema_version`` this request's result must carry."""
        return SCHEMA_VERSION_V1_2 if self.uses_v1_2 else SCHEMA_VERSION


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


def _parse_choice(value: Any, path: str, allowed: tuple[str, ...], default: str) -> str:
    """Parse one pt-v1.2 optional enum: absent/null → default, else closed check.

    ``None`` is the "field not supplied" spelling (JSON null and a missing key
    are the same intent for an optional field); a PRESENT non-string or an
    out-of-vocabulary string is a contract violation, never silently defaulted.
    """
    if value is None:
        return default
    text = _require_str(value, path)
    if text not in allowed:
        raise PaperTradeSchemaError(f"{path} must be one of {allowed}, got {text!r}")
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
        interval=_parse_choice(payload.get("interval"), "interval", INTERVALS, DEFAULT_INTERVAL),
        session=_parse_choice(payload.get("session"), "session", SESSIONS, DEFAULT_SESSION),
        path_model=_parse_choice(
            payload.get("path_model"), "path_model", PATH_MODELS, DEFAULT_PATH_MODEL
        ),
        fill_model=_parse_choice(
            payload.get("fill_model"), "fill_model", FILL_MODELS, DEFAULT_FILL_MODEL
        ),
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
class CanceledOrder:
    """One pt-v1.2 emergency-cancel row (T3, D2).

    ``reason_code`` is fixed at :data:`CANCELED_REASON_CODE`; it is NOT a
    member of the frozen ``REASON_CODES`` vocabulary.
    """

    trade_date: str
    symbol: str
    side: str
    qty: float
    reason_code: str = CANCELED_REASON_CODE
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One pt-v1.2 session fact (T4, D2); ``event_type`` from
    :data:`SESSION_EVENT_TYPES`."""

    trade_date: str
    symbol: str
    event_type: str
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
    """Full success out-param document (AMENDMENT §2.2; pt-v1.2 additive fields).

    The three pt-v1.2 fields stay at their empty defaults for a v1.1 document
    and are serialized only when ``schema_version == SCHEMA_VERSION_V1_2``
    (D8).  ``engine_fingerprint`` is required in a v1.2 document (D3).
    """

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
    engine_fingerprint: str = ""
    canceled_orders: tuple[CanceledOrder, ...] = ()
    events: tuple[SessionEvent, ...] = ()


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


def load_contract_schema(
    name: str = "result", *, version: str = SCHEMA_VERSION
) -> dict[str, Any]:
    """Load one named jsonschema from a VD-13 contract file.

    ``name`` is ``"result"`` (success out-param) or ``"error_envelope"``;
    ``version`` is one of :data:`SCHEMA_VERSIONS` and defaults to the frozen
    pt-v1.1 file, so every existing caller keeps reading the same document.
    A v1.1 result validates ONLY against ``version="pt-v1.1"``; a v1.2 result
    (``engine_fingerprint`` present) validates against ``version="pt-v1.2"``.
    Read-only.
    """
    try:
        path = _CONTRACT_SCHEMA_PATHS[version]
    except KeyError:
        raise KeyError(
            f"unknown contract version {version!r}; available: {list(SCHEMA_VERSIONS)}"
        ) from None
    document = json.loads(path.read_text(encoding="utf-8"))
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
