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
from collections.abc import Mapping
from typing import Any

from src.agent.tools import BaseTool

from . import data, data_5m, engine, wire
from .calendar import CN_A_MARKET, CalendarUnavailableError, snapshot_calendar
from .data import ClickHouseBarsClient
from .limits_cn_a import ClickHouseLimitsClient
from .portfolio import run_portfolio_step
from .portfolio.orchestrator import OrchestrationError
from .portfolio.schema import PortfolioRequestError
from .portfolio.sessions import PortfolioSessionError
from .schema import (
    DateRange,
    ErrorEnvelope,
    PaperTradeSchemaError,
    parse_request,
)
from .tool_portfolio import (
    _LEGACY_ONLY_FIELDS as _LEGACY_ONLY_FIELDS,
    _LEGACY_PROPERTIES as _LEGACY_PROPERTIES,
    _LEGACY_REQUIRED as _LEGACY_REQUIRED,
    _ModeGateError as _ModeGateError,
    _PORTFOLIO_MARKETS as _PORTFOLIO_MARKETS,
    _PORTFOLIO_ONLY_FIELDS as _PORTFOLIO_ONLY_FIELDS,
    _dumps_document as _dumps_document,
    _portfolio_error_document as _portfolio_error_document,
    _portfolio_markets as _portfolio_markets,
    _preparse_mode as _preparse_mode,
    _published_parameters as _published_parameters,
)

logger = logging.getLogger(__name__)

__all__ = ["PaperTradeDocument", "PaperTradeStepTool", "run_paper_trade_step"]


class PaperTradeDocument(str):
    """The in-band result document text, carrying the fetch evidence when any.

    The wire contract is a JSON *string*, and this subclass IS one: ``json.loads``,
    string equality, indexing and every ``str`` operation see exactly the bytes a
    plain ``str`` would carry.  On the success path it additionally carries the
    :class:`data.MarketDataResult` that produced it.  The runner's default step
    adapter needs that evidence to write ``steps/<date>/bars/<symbol>.csv``
    (T5 gap): the wire contract deliberately does not echo bars, and re-fetching
    them would double the provider cost (``stk_mins`` is capped at 2 calls/day and
    a refused call still burns the budget — T1).  Attaching the already-fetched
    frame is the only single-fetch path to them.

    A caller that only wants the wire bytes treats this as ``str``; the attribute
    is additive and never serialized.
    """

    def __new__(cls, text: str, market_data: Any = None) -> "PaperTradeDocument":
        document = super().__new__(cls, text)
        document.market_data = market_data
        return document

# Sentinel distinguishing "not injected" (resolve for production) from an
# explicit None.  It MUST be data._AUTO by identity: run_paper_trade_step
# forwards ``loader``/``ch_client`` straight into data.fetch_market_data, which
# recognises its own sentinel to trigger production resolution.
_AUTO = data._AUTO

#: REQUIREMENTS R1 / VD-12 frozen description phrase — both registration
#: surfaces (BaseTool.description and the MCP wrapper docstring) carry it.
_DESCRIPTION = (
    "Run one deterministic paper-trading step. The default (or mode='single') "
    "is the single-market contract: a deterministic paper-trading matching "
    "engine; never places real orders. It matches injected orders (or a "
    "strategy_path's per-day orders, Step 7) against bars under the market's "
    "frozen rules (T+1, price limits, board lots, fees). mode='portfolio' with "
    "schema_version='pt-v2.0' runs one cross-market daily step over caller "
    "buckets, direct-pair FX snapshots and caller-declared sessions, with "
    "either orders or target_weights. Both branches return one in-band JSON "
    "document — success or an INVALID_REQUEST / PAPER_DATA_NOT_READY envelope "
    "on the same channel; those request/data errors are in-band, while INTERNAL "
    "engine faults and unexpected exceptions propagate as transport errors. "
    "Legacy interval/session/"
    "path_model/fill_model selectors default to pt-v1.1 daily behaviour; "
    "interval='5m' is cn_a-only. Research-only."
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


def _portfolio_dependencies(
    raw_payload: Any,
    *,
    loader: Any,
    ch_client: Any,
    calendar_client: Any,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Resolve the internal step's per-market loaders and cn_a calendar.

    ``loader``/``ch_client`` accept either one shared injection (legacy test
    seam) or a per-market mapping.  ``_AUTO`` resolves the existing raw network
    loaders and ClickHouse helpers only; a missing source stays ``None`` so the
    fetch reports data-not-ready instead of becoming an input error.
    """
    markets = _portfolio_markets(raw_payload)
    connector = None
    if "cn_a" in markets and (
        loader is _AUTO or ch_client is _AUTO or calendar_client is _AUTO
    ):
        connector = _default_cn_a_connector()

    if isinstance(loader, Mapping):
        loaders = {market: loader.get(market) for market in markets}
    elif loader is _AUTO:
        loaders = {}
        for market in markets:
            try:
                loaders[market] = data._resolve_network_loader(
                    data.MARKET_LOADER_KEYS[market],
                    exclude=frozenset({"clickhouse"}) if market == CN_A_MARKET else frozenset(),
                )
            except Exception as exc:  # noqa: BLE001 — unavailable source degrades to data-not-ready
                logger.debug("paper_trade portfolio loader unavailable for %s: %s", market, exc)
                loaders[market] = None
    else:
        loaders = {market: loader for market in markets}

    if isinstance(ch_client, Mapping):
        ch_clients = {market: ch_client.get(market) for market in markets}
    elif ch_client is _AUTO:
        ch_clients = {
            market: (
                ClickHouseBarsClient(connector)
                if market == CN_A_MARKET and connector is not None
                else None
            )
            for market in markets
        }
    elif ch_client is None:
        ch_clients = {market: None for market in markets}
    else:
        ch_clients = {
            market: ch_client if market == CN_A_MARKET else None
            for market in markets
        }

    return loaders, ch_clients, connector if calendar_client is _AUTO else calendar_client


def _execute_portfolio_step(
    payload: Any,
    *,
    loader: Any,
    ch_client: Any,
    calendar_client: Any,
    hk_lot_sizes: Any,
) -> str:
    """Run the internal seam and return only its public document bytes."""
    raw_payload = payload if isinstance(payload, dict) else {}
    try:
        loaders, ch_clients, cal = _portfolio_dependencies(
            raw_payload,
            loader=loader,
            ch_client=ch_client,
            calendar_client=calendar_client,
        )
        result = run_portfolio_step(
            payload,
            loaders=loaders,
            calendar_client=cal,
            ch_clients=ch_clients,
            hk_lot_sizes=None if hk_lot_sizes is _AUTO else hk_lot_sizes,
        )
    except PortfolioRequestError as exc:
        return _portfolio_error_document(
            "INVALID_REQUEST",
            raw_payload,
            reason=exc.reason,
            path=exc.path,
            detail=exc.detail or str(exc),
            bucket_id=exc.bucket_id,
        )
    except PortfolioSessionError as exc:
        return _portfolio_error_document(
            exc.code,
            raw_payload,
            reason=exc.reason,
            path=exc.path,
            detail=exc.detail or str(exc),
            bucket_id=exc.bucket_id,
        )
    except OrchestrationError as exc:
        if exc.code == "INTERNAL":
            raise
        return _portfolio_error_document(
            exc.code,
            raw_payload,
            reason=exc.reason,
            path=exc.path,
            detail=exc.detail or str(exc),
            bucket_id=exc.bucket_id,
        )
    document = result.document
    if isinstance(document, str):
        return document
    if isinstance(document, dict):
        return _dumps_document(document)
    return _dumps_document(document.model_dump(mode="json", by_alias=True, exclude_none=True))


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

    The returned :class:`PaperTradeDocument` is the wire string plus the
    fetched :class:`data.MarketDataResult` (``None`` on every error envelope),
    so an in-process caller can record the day's bars without a second fetch.

    A raw ``mode``/``schema_version`` gate runs before the legacy parser:
    omitted or ``single`` mode follows the existing pipeline unchanged, while
    ``mode="portfolio"`` plus ``schema_version="pt-v2.0"`` dispatches only to
    the internal portfolio seam.
    """
    dispatch, error = _preparse_mode(payload)
    if dispatch == "error":
        assert error is not None
        return PaperTradeDocument(
            _portfolio_error_document(
                "INVALID_REQUEST",
                payload,
                reason=error.reason,
                path=error.path,
                detail=error.detail,
            ),
            None,
        )
    if dispatch == "portfolio":
        return PaperTradeDocument(
            _execute_portfolio_step(
                payload,
                loader=loader,
                ch_client=ch_client,
                calendar_client=calendar_client,
                hk_lot_sizes=hk_lot_sizes,
            ),
            None,
        )
    document, market_data = _execute_step(
        payload,
        loader=loader,
        ch_client=ch_client,
        calendar_client=calendar_client,
        limits_client=limits_client,
        corporate_action_unresolved_by_day=corporate_action_unresolved_by_day,
        hk_lot_sizes=hk_lot_sizes,
        timeout_seconds=timeout_seconds,
        orders_at_end=_orders_at_end,
    )
    return PaperTradeDocument(document, market_data)


def _execute_step(
    payload: Any,
    *,
    loader: Any,
    ch_client: Any,
    calendar_client: Any,
    limits_client: Any,
    corporate_action_unresolved_by_day: Any,
    hk_lot_sizes: Any,
    timeout_seconds: float | None,
    orders_at_end: bool,
) -> tuple[str, Any | None]:
    """The step pipeline: ``(wire document text, fetched market data or None)``."""
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
        ), None

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
        ), None

    # 2b. pt-v1.2/pt-v1.3 cross-field gates (D5).  Shape/vocabulary checks
    #     already ran in parse_request; these are the market-combination rules
    #     the shape parser cannot own.  All stay in-band and non-retryable.
    if request.fill_model == "volume_share" and (
        request.interval != "5m" or request.market != CN_A_MARKET
    ):
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date,
            "fill_model 'volume_share' is a 5m cn_a-only policy; "
            f"got interval={request.interval!r} market={request.market!r}",
            raw_payload,
        ), None
    if request.interval == "5m" and request.market != CN_A_MARKET:
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date,
            "interval 5m is cn_a-only in pt-v1.2", raw_payload,
        ), None
    if request.session == "cn_a" and request.market != CN_A_MARKET:
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date,
            "session cn_a requires market cn_a in pt-v1.2", raw_payload,
        ), None
    if request.interval == "5m" and request.from_date != request.to_date:
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date,
            "interval 5m supports one trading day per step; the runner advances one day at a time",
            raw_payload,
        ), None

    # 3. Market data over the frozen window (universe = positions ∪ orders;
    #    strategy_path mode ALSO unions the strategy file's declared UNIVERSE
    #    literal — a cash-only account carries no position symbols and there
    #    are no orders, so without the declaration the fetch universe would be
    #    empty.  strategy_universe is a pure AST read (never an execution) and
    #    degrades to (); the empty-declaration fallback keeps the existing
    #    behavior and T7's B1 path still owns a genuinely unusable universe.
    #    Orders mode never consults it.  Every 5m gate below runs BEFORE the
    #    fetch, so a refusal never spends provider budget.)
    cal, lim, ch = _resolve_clients(request.market, calendar_client, limits_client, ch_client)
    if request.market == CN_A_MARKET and cal is None:
        return _error_document(
            "PAPER_DATA_NOT_READY", request.account_id, request.market,
            request.from_date, request.to_date,
            "A-share trading calendar unavailable; configure a reachable ClickHouse trade_calendar and retry",
            raw_payload), None
    if request.market == CN_A_MARKET:
        try:
            cal = snapshot_calendar(cal, request.from_date, request.to_date)
        except CalendarUnavailableError as exc:
            return _error_document(
                "PAPER_DATA_NOT_READY", request.account_id, request.market,
                request.from_date, request.to_date, str(exc), raw_payload), None
    symbols = data.symbols_for_request(request.account_state, request.orders)
    declared: tuple[str, ...] = ()
    if has_strategy:
        from .strategy_exec import strategy_universe

        declared = strategy_universe(request.strategy_path or "")
        if declared:
            symbols = tuple(sorted(set(symbols) | set(declared)))
        five_minute_symbols = declared
    else:
        five_minute_symbols = tuple(
            dict.fromkeys(order.symbol for order in request.orders or ()))
    if request.interval == "5m":
        # 3a. Strategy mode needs an explicit 5m universe.  Falling back to the
        #     positions would hide every order the strategy places on a symbol
        #     it does not hold, and a silent empty universe rejects EVERY order
        #     as `suspended` while the step still succeeds (N1).  This is the
        #     one place the empty-declaration fallback must not apply.
        if has_strategy and not declared:
            return _error_document(
                "INVALID_REQUEST", request.account_id, request.market,
                request.from_date, request.to_date,
                "interval 5m strategy mode requires an explicit non-empty UNIVERSE "
                "in the strategy source",
                raw_payload,
            ), None
        # 3b. The provider budget, not a nicety: stk_mins is measured at
        #     1 call/minute, 1/hour and 2 calls/day, and the loader issues one
        #     call per code.  A second symbol in the SAME step is rate-limited
        #     immediately (and the refused call still burns the 2/day budget),
        #     so it could never complete on a retry either (N2/F2R3-1).
        limit = data_5m.MAX_FIVE_MINUTE_SYMBOLS
        if len(five_minute_symbols) > limit:
            return _error_document(
                "INVALID_REQUEST", request.account_id, request.market,
                request.from_date, request.to_date,
                f"interval 5m supports at most {limit} "
                f"symbol{'s' if limit != 1 else ''} per step (measured stk_mins "
                "budget: 1 call/minute, 1/hour, 2/day); split the orders across "
                f"steps or use 1d (received {len(five_minute_symbols)}: "
                f"{', '.join(five_minute_symbols)})",
                raw_payload,
            ), None
        unsupported = [
            symbol for symbol in five_minute_symbols
            if not data_5m.is_supported_five_minute_symbol(symbol)
        ]
        if unsupported:
            return _error_document(
                "INVALID_REQUEST", request.account_id, request.market,
                request.from_date, request.to_date,
                f"interval 5m does not support {', '.join(unsupported)}: stk_mins serves cn_a "
                "stocks only (SH 600/601/603/605/688/689, SZ 000/001/002/003/300/301); "
                "ETFs, funds and indices have no 5m leg",
                raw_payload,
            ), None
    try:
        market_data = data.fetch_market_data(
            request.market, symbols, request.from_date, request.to_date,
            loader=loader, ch_client=ch,
            interval=request.interval,
            five_minute_symbols=(
                five_minute_symbols if request.interval == "5m" else None),
        )
    except ValueError as exc:
        # Data-layer input guards (from_date > to_date, unknown market, a
        # clickhouse-named loader injection) are contract violations → in-band.
        return _error_document(
            "INVALID_REQUEST", request.account_id, request.market,
            request.from_date, request.to_date, str(exc), raw_payload,
        ), None
    except Exception as exc:  # noqa: BLE001 — provider fault (network/quota/permission)
        # U6: a fetch fault that is NOT an input-contract violation is late
        # data, never a transport crash and never a halt.  The message carries
        # the exception CLASS only — provider text can embed hosts, quotes and
        # timings, and the envelope must stay deterministic (VD-7).
        logger.warning("paper_trade market data fetch failed: %s", type(exc).__name__)
        return _error_document(
            "PAPER_DATA_NOT_READY", request.account_id, request.market,
            request.from_date, request.to_date,
            f"market data fetch failed ({type(exc).__name__}); the step is data-not-ready, "
            "retry later",
            raw_payload,
        ), None

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
    elif orders_at_end:
        # Saved accounts must scan every intervening day, including actions,
        # while applying explicit orders only at the chosen execution close.
        outcome = engine.run_day_loop(
            market=request.market, account_state=request.account_state,
            from_date=request.from_date, to_date=request.to_date, market_data=market_data,
            orders_by_day={request.to_date: request.orders or ()}, fee_model=request.fee_model,
            calendar_client=cal, limits_client=lim, hk_lot_sizes=hk_lot_sizes,
            corporate_action_unresolved_by_day=corporate_action_unresolved_by_day,
            path_model=request.path_model, fill_model=request.fill_model,
            order_volume_ratio=request.order_volume_ratio)
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
        ), None
    result = wire.assemble_result(
        request, outcome, raw_account_state=raw_payload.get("account_state")
    )
    return wire.dumps_payload(wire.build_success_payload(result)), market_data


class PaperTradeStepTool(BaseTool):
    """Deterministic paper-trading matching engine; never places real orders.

    Read-only research tool (REQUIREMENTS R1): it reads market data and the
    injected ledger, matches on paper under the frozen market rules, and
    returns one in-band JSON document. The same name serves the default/explicit
    single-market contract and the pt-v2.0 portfolio branch selected by
    ``mode='portfolio'`` + ``schema_version='pt-v2.0'``. It registers no broker /
    trading connector path and writes nothing.
    """

    name = "paper_trade_step"
    description = _DESCRIPTION
    parameters = _published_parameters()
    repeatable = True
    is_readonly = True
    # Not `deterministic`: the result depends on served market data, which
    # changes between sessions, so identical args must not be served from cache.
    deterministic = False

    def execute(self, **kwargs: Any) -> str:
        """Run one step and return the single in-band JSON document string."""
        return run_paper_trade_step(dict(kwargs))
