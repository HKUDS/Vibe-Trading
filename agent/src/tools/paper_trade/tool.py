"""``paper_trade_step`` tool entry (pt-v1.1 Step 6 / T6, VD-12 registration).

The thin orchestration seam between the frozen wire contract and the engine:
parse the request, supply market data, run one deterministic step, and return
the single in-band JSON document.  It owns the SEMANTIC gates the shape parser
deliberately does not pre-empt (schema.py): the ``orders`` XOR ``strategy_path``
mode rule maps a violation to the in-band ``INVALID_REQUEST`` envelope.

Error discipline (AM-5 / VD-7): every input-contract violation and every
data-not-ready condition returns an in-band envelope on the SAME
``result.content[0].text`` channel as the success document — never a transport
error.  Transport-level faults stay reserved for engine-internal bugs (not external calendar unavailability, which returns PAPER_DATA_NOT_READY).  Messages are deterministic English with no timestamps.

Two registration surfaces share :func:`run_paper_trade_step` as the single
source of truth (VD-12, the backtest two-layer pattern): the auto-discovered
:class:`PaperTradeStepTool` (agent registry) and the hand-written
``@mcp.tool paper_trade_step`` wrapper in ``agent/mcp_server.py``.

Research-only red line (REQUIREMENTS R1): this tool NEVER places a real order
and never touches a broker / trading connector — it reads market data and the
injected ledger, matches on paper, and returns the result document.

Determinism (R1-1): no clock, no randomness; every date and every client is
injected or resolved from env config.  ``strategy_path`` execution is T7
(:mod:`strategy_exec`), imported lazily so this module stays importable while
T7 is in flight.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent.tools import BaseTool

from . import data, engine, wire
from .calendar import CN_A_MARKET, CalendarUnavailableError, snapshot_calendar
from .data import ClickHouseBarsClient
from .limits_cn_a import ClickHouseLimitsClient
from .schema import (
    DateRange,
    ErrorEnvelope,
    PaperTradeSchemaError,
    parse_request,
)

logger = logging.getLogger(__name__)

__all__ = ["PaperTradeStepTool", "run_paper_trade_step"]

# Sentinel distinguishing "not injected" (resolve for production) from an
# explicit None.  It MUST be data._AUTO by identity: run_paper_trade_step
# forwards ``loader``/``ch_client`` straight into data.fetch_market_data, which
# recognises its own sentinel to trigger production resolution.
_AUTO = data._AUTO

#: REQUIREMENTS R1 / VD-12 frozen description phrase — both registration
#: surfaces (BaseTool.description and the MCP wrapper docstring) carry it.
_DESCRIPTION = (
    "Run one deterministic paper-trading step for a single account: a "
    "deterministic paper-trading matching engine; never places real orders. "
    "Matches the injected orders (or a strategy_path's per-day orders, Step 7) "
    "against daily bars under the market's frozen rules (T+1, price limits, "
    "board lots, fees), and returns one in-band JSON document — the success "
    "result or an AM-5 error envelope (PAPER_DATA_NOT_READY / INVALID_REQUEST) "
    "on the same channel, never a transport error. Research-only."
)


def _as_str(value: Any) -> str:
    """Echo a raw payload field as a string, or ``""`` when it is not one.

    The error envelope's ``account_id``/``market``/``range`` come from the raw
    payload "where possible" (AM-4-4): a malformed ``market`` string is echoed
    VERBATIM (T5 decision 5 — honest reporting beats self-consistency, so the
    envelope's own market enum is the single documented degraded case), while a
    non-string field degrades to ``""`` rather than leaking a non-string onto
    the wire.
    """
    return value if isinstance(value, str) else ""


def _error_document(
    code: str,
    account_id: str,
    market: str,
    from_date: str,
    to_date: str,
    message: str,
    raw_payload: Any,
) -> str:
    """Serialize one in-band AM-5 error envelope to its wire JSON text.

    ``received_state_hash`` is computed from the RAW payload (AM-4-1/AM-4-4)
    and omitted — never null — when the coverage object is not computable.
    """
    envelope = ErrorEnvelope(
        code=code,
        account_id=account_id,
        market=market,
        range=DateRange(from_=from_date, to=to_date),
        message=message,
        received_state_hash=wire.received_state_hash_from_payload(raw_payload),
    )
    return wire.dumps_payload(wire.build_error_payload(envelope))


def _default_cn_a_connector() -> Any | None:
    """One shared ClickHouse connector for cn_a calendar+limits+bars, or None.

    Probed with an AUTHENTICATED ``SELECT 1`` — never ``health_check()``, which
    sends no credentials and 403s against a password-protected server even when
    the configured credentials are valid (issues pit 18, observed live).  An
    unreachable server degrades to None: the bar leg then falls back to the
    network source. The tool returns PAPER_DATA_NOT_READY when the calendar
    is unavailable or cannot cover the requested dates.
    """
    try:
        from src.clickhouse_connector import ClickHouseConnector

        connector = ClickHouseConnector()  # reads CLICKHOUSE_* env config
        connector.query("SELECT 1")
        return connector
    except Exception as exc:  # noqa: BLE001 — unreachable CH degrades, never crashes here
        logger.debug("paper_trade cn_a ClickHouse connector unavailable: %s", exc)
        return None


def _resolve_clients(
    market: str, calendar_client: Any, limits_client: Any, ch_client: Any
) -> tuple[Any, Any, Any]:
    """Resolve (calendar_client, limits_client, ch_client) for ``market``.

    ``_AUTO`` seams resolve from ONE shared cn_a ClickHouse connector (calendar
    = the connector itself, which structurally satisfies TradeCalendarClient;
    limits = ClickHouseLimitsClient; bars = ClickHouseBarsClient).  hk/us are
    the approved AM-6 zero-calendar design: no calendar client, no cn_a limit
    lookups, no CH bar leg — all None.  Injected seams (tests) pass through
    untouched, so no connector is ever built offline.
    """
    if market != CN_A_MARKET:
        return (
            None if calendar_client is _AUTO else calendar_client,
            None if limits_client is _AUTO else limits_client,
            None if ch_client is _AUTO else ch_client,
        )
    connector = None
    if calendar_client is _AUTO or limits_client is _AUTO or ch_client is _AUTO:
        connector = _default_cn_a_connector()
    cal = connector if calendar_client is _AUTO else calendar_client
    if limits_client is _AUTO:
        lim = ClickHouseLimitsClient(connector) if connector is not None else None
    else:
        lim = limits_client
    if ch_client is _AUTO:
        ch = ClickHouseBarsClient(connector) if connector is not None else None
    else:
        ch = ch_client
    return cal, lim, ch


def run_paper_trade_step(
    payload: Any,
    *,
    loader: Any = _AUTO,
    ch_client: Any = _AUTO,
    calendar_client: Any = _AUTO,
    limits_client: Any = _AUTO,
    corporate_action_unresolved_by_day: Any = None,
    hk_lot_sizes: Any = None,
    timeout_seconds: float | None = None,
    _orders_at_end: bool = False,
) -> str:
    """Run one paper-trading step and return the single in-band JSON document.

    Flow (T5 wire surface): ``parse_request`` → market data → ``match_orders``
    (orders mode) or the lazily-imported ``strategy_exec.run_strategy_path``
    (strategy_path mode, T7) → ``assemble_result`` → ``build_success_payload``
    → ``dumps_payload``.  A ``PaperTradeSchemaError`` or a semantic-gate
    violation returns an in-band ``INVALID_REQUEST`` envelope; a
    ``MatchOutcome.error`` returns its own in-band envelope (e.g.
    ``PAPER_DATA_NOT_READY``).  Injection seams (``loader``/``ch_client``/
    ``calendar_client``/``limits_client``/…) default to ``_AUTO`` production
    resolution; tests pass fakes so nothing touches the network.
    """
    raw_payload = payload if isinstance(payload, dict) else {}

    # 1. Boundary parse (shape contract).  A violation is non-retryable input.
    try:
        request = parse_request(payload)
    except PaperTradeSchemaError as exc:
        return _error_document(
            "INVALID_REQUEST",
            _as_str(raw_payload.get("account_id")),
            _as_str(raw_payload.get("market")),  # verbatim even when malformed
            _as_str(raw_payload.get("from_date")),
            _as_str(raw_payload.get("to_date")),
            str(exc),
            raw_payload,
        )

    # 2. Semantic gate owned by the tool (schema.py defers it): exactly one of
    #    orders / strategy_path.  ``orders=()`` (empty array) is the valid
    #    zero-order pure-valuation path, so the test is `is not None`.
    has_orders = request.orders is not None
    has_strategy = request.strategy_path is not None
    if has_orders == has_strategy:
        message = (
            "exactly one of orders or strategy_path must be provided, got both"
            if has_orders
            else "exactly one of orders or strategy_path must be provided, got neither"
        )
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date, message, raw_payload,
        )

    # 3. Market data over the frozen window (universe = positions ∪ orders;
    #    strategy_path mode ALSO unions the strategy file's declared UNIVERSE
    #    literal — a cash-only account carries no position symbols and there
    #    are no orders, so without the declaration the fetch universe would be
    #    empty.  strategy_universe is a pure AST read (never an execution) and
    #    degrades to (); the empty-declaration fallback keeps the existing
    #    behavior and T7's B1 path still owns a genuinely unusable universe.
    #    Orders mode never consults it.)
    cal, lim, ch = _resolve_clients(request.market, calendar_client, limits_client, ch_client)
    if request.market == CN_A_MARKET and cal is None:
        return _error_document(
            "PAPER_DATA_NOT_READY", request.account_id, request.market,
            request.from_date, request.to_date,
            "A-share trading calendar unavailable; configure a reachable ClickHouse trade_calendar and retry",
            raw_payload)
    if request.market == CN_A_MARKET:
        try:
            cal = snapshot_calendar(cal, request.from_date, request.to_date)
        except CalendarUnavailableError as exc:
            return _error_document(
                "PAPER_DATA_NOT_READY", request.account_id, request.market,
                request.from_date, request.to_date, str(exc), raw_payload)
    symbols = data.symbols_for_request(request.account_state, request.orders)
    if has_strategy:
        from .strategy_exec import strategy_universe

        declared = strategy_universe(request.strategy_path or "")
        if declared:
            symbols = tuple(sorted(set(symbols) | set(declared)))
    try:
        market_data = data.fetch_market_data(
            request.market, symbols, request.from_date, request.to_date,
            loader=loader, ch_client=ch,
        )
    except ValueError as exc:
        # Data-layer input guards (from_date > to_date, unknown market, a
        # clickhouse-named loader injection) are contract violations → in-band.
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date, str(exc), raw_payload,
        )

    # 4. Mode dispatch.  strategy_exec is T7 and imported lazily so this module
    #    stays importable (and the agent registry stays buildable) while T7 is
    #    in flight; both modes yield a MatchOutcome handled identically below.
    if has_strategy:
        from .strategy_exec import run_strategy_path

        outcome = run_strategy_path(
            request=request,
            market_data=market_data,
            calendar_client=cal,
            limits_client=lim,
            corporate_action_unresolved_by_day=corporate_action_unresolved_by_day,
            hk_lot_sizes=hk_lot_sizes,
            timeout_seconds=timeout_seconds,
        )
    elif _orders_at_end:
        # Saved accounts must scan every intervening day, including actions,
        # while applying explicit orders only at the chosen execution close.
        outcome = engine.run_day_loop(
            market=request.market, account_state=request.account_state,
            from_date=request.from_date, to_date=request.to_date, market_data=market_data,
            orders_by_day={request.to_date: request.orders or ()}, fee_model=request.fee_model,
            calendar_client=cal, limits_client=lim, hk_lot_sizes=hk_lot_sizes,
            corporate_action_unresolved_by_day=corporate_action_unresolved_by_day)
    else:
        outcome = engine.match_orders(
            request,
            market_data=market_data,
            calendar_client=cal,
            limits_client=lim,
            corporate_action_unresolved_by_day=corporate_action_unresolved_by_day,
            hk_lot_sizes=hk_lot_sizes,
        )

    # 5. In-band error envelope, or the success document.  The hash covers the
    #    RAW received account_state (AM-4-1), never the parsed reconstruction.
    if outcome.error is not None:
        return _error_document(
            outcome.error.code, request.account_id, request.market,
            request.from_date, request.to_date, outcome.error.message, raw_payload,
        )
    result = wire.assemble_result(
        request, outcome, raw_account_state=raw_payload.get("account_state")
    )
    return wire.dumps_payload(wire.build_success_payload(result))


class PaperTradeStepTool(BaseTool):
    """Deterministic paper-trading matching engine; never places real orders.

    Read-only research tool (REQUIREMENTS R1): it reads market data and the
    injected ledger, matches on paper under the frozen market rules, and
    returns one in-band JSON document.  It registers no broker / trading
    connector path and writes nothing.
    """

    name = "paper_trade_step"
    description = _DESCRIPTION
    parameters = {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Account identifier, echoed verbatim (R4).",
            },
            "market": {
                "type": "string",
                "enum": ["cn_a", "hk", "us"],
                "description": "Market whose frozen rules govern matching.",
            },
            "account_state": {
                "type": "object",
                "description": (
                    "RM-injected ledger snapshot {cash, positions:[{symbol, qty, "
                    "avg_cost}]}. Hashed raw for received_state_hash (AM-4-1)."
                ),
                "properties": {
                    "cash": {"type": "number"},
                    "positions": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["cash"],
            },
            "from_date": {
                "type": "string",
                "description": "Inclusive range start YYYY-MM-DD (orders mode: == to_date, AM-3).",
            },
            "to_date": {
                "type": "string",
                "description": "Inclusive range end YYYY-MM-DD (the target trading day).",
            },
            "orders": {
                "type": "array",
                "description": (
                    "Orders mode: array of {symbol, side, qty, limit?}. XOR with "
                    "strategy_path; an empty array is the pure-valuation path."
                ),
                "items": {"type": "object"},
            },
            "strategy_path": {
                "type": "string",
                "description": (
                    "Strategy mode (Step 7): path to an AST-hardened strategy whose "
                    "per-day orders are matched. XOR with orders."
                ),
            },
            "fee_model": {
                "type": "object",
                "description": (
                    "Optional per-key fee overrides merged over the market defaults "
                    "(AM-4-3: RM always injects it explicitly)."
                ),
            },
        },
        "required": ["account_id", "market", "account_state", "from_date", "to_date"],
    }
    repeatable = True
    is_readonly = True
    # Not `deterministic`: the result depends on served market data, which
    # changes between sessions, so identical args must not be served from cache.
    deterministic = False

    def execute(self, **kwargs: Any) -> str:
        """Run one step and return the single in-band JSON document string."""
        return run_paper_trade_step(dict(kwargs))
