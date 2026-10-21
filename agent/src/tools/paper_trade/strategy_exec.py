"""pt-v1.1 ``strategy_path`` execution for ``paper_trade_step`` (Step 7 / T7).

Deterministic strategy replay (REQUIREMENTS R2 / AM-8): the strategy file is
resolved once, AST-validated by the EXISTING backtest sandbox
(``backtest.runner._validate_signal_engine_source`` — import whitelist +
runtime-reachable scrubber, E10), then loaded and executed **in a spawned
child process**, never in the MCP server process.  No raw import: the child
``compile``/``exec``s the single source read the parent validated (no second
I/O ⇒ no TOCTOU between validation and execution); a rejected source never
runs.  The child is killed with SIGKILL on a per-day timeout, so a hung day
is really interrupted (busy loops and blocked sleeps alike), not abandoned.

Strategy contract (R2 "concrete shape is VT's call", VD-8 minimal ctx)::

    class SignalEngine:
        def generate_signals(self, ctx, trade_date):
            return [{"symbol": ..., "side": "buy" | "sell", "qty": ...,
                     "limit": ... | None, "reason": ... | None}, ...]

The class MUST be named ``SignalEngine``: that is the entry the runner's
runtime-reachable scrubber scans (its methods + transitively called module
helpers), so reusing the name reuses the hardened deep pass verbatim — no
second, weaker scanner.  ``ctx`` (:class:`StrategyContext`) exposes exactly
the read-only ledger after preceding days' fills, ``symbols``, and
``history(symbol)`` containing only bars strictly before the execution date.
Orders fill at the execution day's close. The parent advances a private
ledger between calls; failure discards the entire result.

Optional universe declaration: a strategy file MAY declare a module-level
literal ``UNIVERSE = ("SYM-A", "SYM-B")`` (a list/tuple of non-empty
strings).  :func:`strategy_universe` extracts it under the SAME path policy
via a pure AST literal read — the file is never executed or imported on that
path, so no top-level side effect can fire — and the T6 tool unions the
declared symbols into the market-data fetch universe (a cash-only account
carries no position symbols and strategy_path mode has no orders, so without
the declaration the served universe would be empty).  Any convention
violation — absent, non-literal, non-list/tuple, a non-string or empty-string
entry, an unreadable or syntactically invalid source, a path-policy rejection
— degrades to an empty declaration: the served universe (positions ∪ fetched
symbols) is the fallback, and a genuinely unusable universe stays owned by
the B1 whole-call failure semantics below.

B1 frozen failure semantics (VD-8): every strategy-side failure — path
policy, source syntax, validator rejection, load/discovery, a malformed
order list, a per-day exception, a per-day timeout, a child crash — returns
the WHOLE call as in-band ``INVALID_REQUEST`` material with the frozen
message ``strategy_execution_timeout:{YYYY-MM-DD}`` or
``strategy_execution_error:{YYYY-MM-DD}:{ExceptionClassName}`` and empty
fills/rejected/nav/skipped; a day-k failure never returns days 1..k-1.
Pre-execution failures anchor the date at the first matching day (the
range's ``from_date`` when the range holds none); the AM-9 readiness gate
runs BEFORE validation/execution so a retryable data fact is never masked
by a non-retryable strategy failure.  Rejection details go to the module
logger — the wire message is the frozen string, verbatim.

Determinism (R2): same strategy file + same ledger state + same trading day
= same orders.  No clock, no randomness, no network in the ctx; every input
is injected; each call spawns a fresh child (no cross-call state).

Path policy: the file must resolve (symlinks followed) INSIDE
``<runtime_root>/strategies`` (``VIBE_TRADING_HOME`` or ``~/.vibe-trading``),
end in ``.py``, be an existing regular file under the 1 MB cap, and read as
UTF-8 — rejections happen before any read/execute where possible, and syntax
errors never echo source text (the target may be a non-strategy file).
"""

from __future__ import annotations

import ast
import logging
import math
import multiprocessing
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Mapping

import pandas as pd

from . import calendar, data, schema, wire
from .engine import (
    EngineError, MatchOutcome, build_day_plan, error_outcome, readiness_error, run_day_loop)
from .limits_cn_a import CnALimitsClient
from .schema import AccountState, Order, PaperTradeStepRequest

__all__ = [
    "DEFAULT_DAY_TIMEOUT_SECONDS", "StrategyContext", "StrategyContractError", "StrategyOrder",
    "StrategyOrderError", "StrategyPathError", "StrategyProcessError", "run_strategy_path",
    "strategy_universe",
]

logger = logging.getLogger(__name__)

#: Per-day execution budget when the caller passes no ``timeout_seconds``.
DEFAULT_DAY_TIMEOUT_SECONDS = 30.0
# Child startup (spawn + package imports + strategy load + entry discovery)
# gets its own grace so a slow environment never reads as a day-1 timeout.
_STARTUP_TIMEOUT_SECONDS = 120.0
_JOIN_TIMEOUT_SECONDS = 10.0
_MAX_STRATEGY_BYTES = 1_000_000
_STRATEGIES_DIRNAME = "strategies"
_STRATEGY_MODULE_NAME = "paper_trade_strategy"
_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_UNIVERSE_NAME = "UNIVERSE"


class StrategyPathError(ValueError):
    """strategy_path violated the path policy, or the source is not valid Python."""


class StrategyContractError(ValueError):
    """The loaded module does not expose the paper-trade strategy contract."""


class StrategyOrderError(ValueError):
    """generate_signals returned a malformed order list."""


class StrategyProcessError(RuntimeError):
    """The execution child died or broke the protocol (a crash, not a strategy exception)."""


@dataclass(frozen=True, slots=True)
class StrategyOrder(Order):
    # Order + the strategy's reason text (VD-15/B2).  The engine truncates via
    # wire.strategy_fill_reason at the fill boundary; plain orders-mode Orders
    # lack the attribute and keep "".
    reason: str = ""


@dataclass(frozen=True, eq=False)
class StrategyContext:
    """Read-only current ledger and prior completed bars for close execution.

    History is copied and excludes the execution day. The child receives no
    current or future bars, including through the private frame mapping.
    """

    account_state: AccountState
    trade_date: str
    symbols: tuple[str, ...]
    _frames: Mapping[str, pd.DataFrame] = field(repr=False)

    def history(self, symbol: str) -> pd.DataFrame:
        frame = self._frames.get(symbol)
        if frame is None or frame.empty:
            return _empty_history()
        return frame.loc[frame.index < pd.Timestamp(self.trade_date)].copy()

    def sma(self, close: pd.Series, period: int) -> float | None:
        from src.tools.technical_indicator_tool import _compute_sma
        return _compute_sma(close, period)

    def ema(self, close: pd.Series, period: int) -> float | None:
        from src.tools.technical_indicator_tool import _compute_ema
        return _compute_ema(close, period)

    def rsi(self, close: pd.Series, period: int | None = None) -> float | None:
        from src.tools.technical_indicator_tool import _compute_rsi
        return _compute_rsi(close) if period is None else _compute_rsi(close, period)

    def macd(self, close: pd.Series) -> dict[str, float | None] | None:
        from src.tools.technical_indicator_tool import _compute_macd
        return _compute_macd(close)

    def bollinger(self, close: pd.Series) -> dict[str, float | None] | None:
        from src.tools.technical_indicator_tool import _compute_bollinger
        return _compute_bollinger(close)


def _empty_history() -> pd.DataFrame:
    # Fresh frame per call (never a shared mutable constant), canonical shape
    # mirroring data._empty_frame.
    columns = {column: pd.Series(dtype="float64") for column in _OHLCV_COLUMNS}
    return pd.DataFrame(columns, index=pd.DatetimeIndex([], name="trade_date"))


class _SourceView:
    # Duck-typed Path view handing the runner validator THE SINGLE READ the
    # parent performed: no second I/O ⇒ no TOCTOU between validation and the
    # source the child executes.  _validate_signal_engine_source only calls
    # .read_text(encoding=...) and str(); a future validator using more Path
    # surface fails loud (AttributeError), never open.
    def __init__(self, path: Path, source: str) -> None:
        self._path = path
        self._source = source

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._source

    def __str__(self) -> str:
        return str(self._path)

    def __fspath__(self) -> str:
        return str(self._path)


def _resolve_strategy_source(strategy_path: str) -> tuple[Path, str]:
    # Path policy BEFORE any read (lazy imports: parent-only path, keeps the
    # spawned child's module import off the config/tool chain until needed).
    from src.config.paths import get_runtime_root
    from src.tools.path_utils import safe_path

    if not strategy_path.strip():
        raise StrategyPathError("strategy_path must be a non-empty path")
    root = get_runtime_root() / _STRATEGIES_DIRNAME
    try:
        resolved = safe_path(strategy_path, root)
    except ValueError as exc:
        raise StrategyPathError(
            f"strategy_path {strategy_path!r} is outside the strategies root {root}: {exc}"
        ) from exc
    if resolved.suffix != ".py":
        raise StrategyPathError(f"strategy_path must be a .py file, got {resolved.name!r}")
    if not resolved.is_file():
        raise StrategyPathError(f"strategy_path {strategy_path!r} is not an existing regular file")
    size = resolved.stat().st_size
    if size > _MAX_STRATEGY_BYTES:
        raise StrategyPathError(
            f"strategy file exceeds the {_MAX_STRATEGY_BYTES}-byte cap ({size} bytes)")
    try:
        source = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StrategyPathError(
            f"strategy file is not readable UTF-8 text ({type(exc).__name__})") from exc
    return resolved, source


def _declared_universe(source: str) -> tuple[str, ...]:
    # The optional module-level ``UNIVERSE`` literal, sorted and deduped.
    # PURE AST read (ast.parse + ast.literal_eval): the source is never
    # executed or imported here, so a top-level side effect cannot fire on
    # this path.  Only a literal list/tuple of non-empty strings is a
    # declaration; every other shape (absent, computed/non-literal, bare
    # string, dict/set, a non-string or empty-string entry, invalid syntax)
    # degrades to () — the served universe is the fallback (module docstring).
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    value_node: ast.expr | None = None
    for statement in tree.body:  # module level only; last binding wins (Python semantics)
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == _UNIVERSE_NAME
            for target in statement.targets
        ):
            value_node = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and statement.value is not None
            and isinstance(statement.target, ast.Name)
            and statement.target.id == _UNIVERSE_NAME
        ):
            value_node = statement.value
    if value_node is None:
        return ()
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return ()  # non-literal declaration (a call, an expression, a name)
    if not isinstance(value, (list, tuple)):
        return ()
    if not all(isinstance(item, str) and item for item in value):
        return ()
    return tuple(sorted(set(value)))


def strategy_universe(strategy_path: str) -> tuple[str, ...]:
    """The strategy file's declared ``UNIVERSE`` literal, sorted and deduped.

    Reads the source under the SAME path policy as execution
    (:func:`_resolve_strategy_source` — strategies-root containment, ``.py``
    suffix, regular file, size cap, UTF-8) and extracts ONLY the module-level
    literal via :func:`_declared_universe`; the strategy is never executed or
    imported here.  Every rejection — path policy, unreadable file, invalid
    syntax, a convention-violating declaration — degrades to ``()`` so the
    caller falls back to the served universe; this helper never raises for a
    bad strategy and never weakens the execution-time validation (which runs
    unchanged in :func:`run_strategy_path`).
    """
    try:
        _path, source = _resolve_strategy_source(strategy_path)
    except (StrategyPathError, OSError):
        return ()
    return _declared_universe(source)


def _validate_source(path: Path, source: str) -> None:
    # Reuse the existing hardened validator verbatim (AM-8 / E10 anchor:
    # backtest/runner.py _validate_signal_engine_source — structural
    # import-time pass + runtime-reachable scrubber keyed on SignalEngine).
    from backtest.runner import _validate_signal_engine_source

    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        # Sanitized: never echo source text into the wire message — the target
        # may be a non-strategy file whose contents must not leak.
        raise StrategyPathError(
            f"strategy source is not valid Python (line {exc.lineno}, column {exc.offset})"
        ) from None
    _validate_signal_engine_source(_SourceView(path, source))


def _load_validated_source(source: str, filename: str) -> types.ModuleType:
    # Child-side load of the ALREADY-VALIDATED source text: compile+exec into
    # a fresh module — no raw import machinery on an untrusted path (AM-8).
    module = types.ModuleType(_STRATEGY_MODULE_NAME)
    module.__file__ = filename
    sys.modules[_STRATEGY_MODULE_NAME] = module
    try:
        exec(compile(source, filename, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(_STRATEGY_MODULE_NAME, None)
        raise
    return module


def _discover_entry(module: types.ModuleType):
    engine_cls = getattr(module, "SignalEngine", None)
    if not isinstance(engine_cls, type):
        raise StrategyContractError(
            "strategy module must define a SignalEngine class "
            "(contract: generate_signals(self, ctx, trade_date))")
    generate = getattr(engine_cls, "generate_signals", None)
    if not callable(generate):
        raise StrategyContractError(
            "SignalEngine must define a callable generate_signals(self, ctx, trade_date)")
    return engine_cls().generate_signals


def _convert_order(item: Any, day: str, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise StrategyOrderError(
            f"orders[{index}] on {day} must be an object, got {type(item).__name__}")
    try:
        # Same boundary parser as the tool input (schema.parse_request) — one
        # order-shape enforcement, not a second weaker one.
        order = schema._parse_order(item, f"strategy orders[{index}] ({day})")
    except schema.PaperTradeSchemaError as exc:
        raise StrategyOrderError(str(exc)) from exc
    reason = item.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise StrategyOrderError(
            f"orders[{index}].reason on {day} must be a string or null, "
            f"got {type(reason).__name__}")
    # Truncate in the child (bounded pipe payloads) AND at the engine's fill
    # boundary (single Fill.reason enforcement); strategy_fill_reason is
    # idempotent, so the double pass is safe.
    return {"symbol": order.symbol, "side": order.side, "qty": order.qty,
            "limit": order.limit, "reason": wire.strategy_fill_reason(reason)}


def _child_main(conn: Any, payload: dict[str, Any]) -> None:
    # Runs in the spawned child: the strategy's top-level code and every
    # generate_signals call execute HERE, never in the MCP server process
    # (AM-8).  Protocol: ("ready",) → ("day", day, orders)* → ("done",);
    # any Exception → ("error", day, class name) and exit.  KeyboardInterrupt
    # /SystemExit deliberately propagate (operator signals, not strategy
    # errors) — the parent reads the dead pipe as StrategyProcessError.
    days = payload["days"]
    try:
        module = _load_validated_source(payload["source"], payload["filename"])
        generate = _discover_entry(module)
    except Exception as exc:
        conn.send(("error", days[0], type(exc).__name__))
        return
    conn.send(("ready",))
    for day in days:
        try:
            state, frames = conn.recv()
            ctx = StrategyContext(account_state=state, trade_date=day,
                                  symbols=payload["symbols"], _frames=frames)
            raw = generate(ctx, day)
            if not isinstance(raw, (list, tuple)):
                raise StrategyOrderError(
                    f"generate_signals must return a list of order objects on {day}, "
                    f"got {type(raw).__name__}")
            orders = [_convert_order(item, day, index) for index, item in enumerate(raw)]
        except Exception as exc:
            conn.send(("error", day, type(exc).__name__))
            return
        conn.send(("day", day, orders))
    conn.send(("done",))


_TIMEOUT = object()
_EOF = object()


def _recv(conn: Any, budget: float) -> Any:
    if not conn.poll(budget):
        return _TIMEOUT
    try:
        return conn.recv()
    except Exception:
        # EOFError/OSError/unpickling: a dead or corrupt child is a crash.
        return _EOF


class _StrategyDayFailure(RuntimeError):
    # Internal carrier from _execute_days to run_strategy_path;
    # class_name None ⇒ the per-day budget expired (timeout).
    def __init__(self, day: str, class_name: str | None) -> None:
        super().__init__(f"strategy execution failed on {day}")
        self.day = day
        self.class_name = class_name


def _execute_days(
    request: PaperTradeStepRequest,
    market_data: data.MarketDataResult,
    days: tuple[str, ...],
    path: Path,
    source: str,
    day_timeout: float,
    ctx_symbols: tuple[str, ...],
    run_loop: Any,
) -> MatchOutcome:
    payload = {
        "source": source,
        "filename": str(path),
        "days": days,
        "symbols": ctx_symbols,
    }
    # spawn (never fork): forking a threaded MCP server is POSIX-undefined
    # behavior (#1355 lesson); spawn is the only start method on Windows and
    # the default on macOS, pinned here so Linux behaves identically.
    context = multiprocessing.get_context("spawn")
    parent_conn, child_conn = context.Pipe(duplex=True)
    proc = context.Process(target=_child_main, args=(child_conn, payload), daemon=True)
    started = False
    try:
        proc.start()
        started = True
        # Close the parent's duplicate child endpoint so child death reads as EOF.
        child_conn.close()
        msg = _recv(parent_conn, max(_STARTUP_TIMEOUT_SECONDS, day_timeout))
        if msg is _TIMEOUT:
            raise _StrategyDayFailure(days[0], None)
        if msg is not _EOF and msg[0] == "error":
            raise _StrategyDayFailure(msg[1], msg[2])
        if msg is _EOF or msg[0] != "ready":
            raise _StrategyDayFailure(days[0], StrategyProcessError.__name__)
        def provide_orders(day: str, state: AccountState) -> tuple[StrategyOrder, ...]:
            frames = {symbol: item.frame.loc[item.frame.index < pd.Timestamp(day)].copy()
                      for symbol, item in market_data.data.items()}
            try:
                parent_conn.send((state, frames))
            except (BrokenPipeError, EOFError, OSError) as exc:
                raise _StrategyDayFailure(day, StrategyProcessError.__name__) from exc
            msg = _recv(parent_conn, day_timeout)
            if msg is _TIMEOUT:
                raise _StrategyDayFailure(day, None)
            if msg is _EOF:
                raise _StrategyDayFailure(day, StrategyProcessError.__name__)
            if msg[0] == "error":
                raise _StrategyDayFailure(msg[1], msg[2])
            if msg[0] != "day" or msg[1] != day:
                raise _StrategyDayFailure(day, StrategyProcessError.__name__)
            return tuple(StrategyOrder(**item) for item in msg[2])
        return run_loop(order_provider=provide_orders)
    finally:
        if started:
            if proc.is_alive():
                proc.kill()  # SIGKILL: really interrupts a hung day (no cooperative unwind)
            proc.join(_JOIN_TIMEOUT_SECONDS)
            proc.close()
        parent_conn.close()
        child_conn.close()


def _resolve_timeout(timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        return DEFAULT_DAY_TIMEOUT_SECONDS
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError(
            f"timeout_seconds must be a finite positive number, got {timeout_seconds!r}")
    value = float(timeout_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"timeout_seconds must be a finite positive number, got {timeout_seconds!r}")
    return value


def _strategy_error(request: PaperTradeStepRequest,
                    market_data: data.MarketDataResult, message: str) -> MatchOutcome:
    # B1: the WHOLE call fails in-band — untouched input state, empty arrays.
    return error_outcome(EngineError("INVALID_REQUEST", message),
                         request.account_state, market_data, request.market, request.fee_model)


def run_strategy_path(
    *,
    request: PaperTradeStepRequest,
    market_data: data.MarketDataResult,
    calendar_client: calendar.TradeCalendarClient | None = None,
    limits_client: CnALimitsClient | None = None,
    corporate_action_unresolved_by_day: Mapping[str, Collection[str]] | None = None,
    hk_lot_sizes: Mapping[str, int] | None = None,
    timeout_seconds: float | None = None,
) -> MatchOutcome:
    """Generate and match each day against a private ledger; publish only success."""
    if request.strategy_path is None:
        raise ValueError(
            "run_strategy_path requires request.strategy_path "
            "(the orders XOR strategy_path gate is the tool's, Step 6)")
    if request.orders is not None:
        raise ValueError(
            "run_strategy_path is the strategy_path seam; orders must be absent")
    if market_data.market != request.market:
        raise ValueError(
            f"market_data was fetched for {market_data.market!r}, "
            f"request says {request.market!r}")
    day_timeout = _resolve_timeout(timeout_seconds)
    plan = build_day_plan(request.market, request.from_date, request.to_date,
                          market_data, calendar_client)
    # AM-9 first: a retryable data fact outranks any strategy-side failure.
    if (error := readiness_error(request.to_date, market_data, plan)) is not None:
        return error_outcome(error, request.account_state, market_data,
                             request.market, request.fee_model)
    days = tuple(entry.date for entry in plan if entry.skip_reason is None)
    anchor = days[0] if days else request.from_date
    try:
        path, source = _resolve_strategy_source(request.strategy_path)
        _validate_source(path, source)
    except Exception as exc:
        # StrategyPathError / the validator's ValueError / any parse-adjacent
        # fault: rejected BEFORE execution — the source never runs.
        logger.warning("paper_trade strategy rejected before execution (%s): %s",
                       type(exc).__name__, exc)
        return _strategy_error(request, market_data,
                               f"strategy_execution_error:{anchor}:{type(exc).__name__}")
    def run_loop(**kwargs: Any) -> MatchOutcome:
        return run_day_loop(
            market=request.market, account_state=request.account_state,
            from_date=request.from_date, to_date=request.to_date, market_data=market_data,
            orders_by_day={}, fee_model=request.fee_model,
            calendar_client=calendar_client, limits_client=limits_client,
            corporate_action_unresolved_by_day=corporate_action_unresolved_by_day,
            hk_lot_sizes=hk_lot_sizes, **kwargs)
    if days:
        # The declared UNIVERSE joins the child's ctx.symbols (sorted union
        # with the served universe), extracted from THE SAME single source
        # read — no second I/O, no TOCTOU.  A declared symbol with no served
        # data reads an empty history: the child never fetches per symbol.
        ctx_symbols = tuple(sorted(set(market_data.symbols) | set(_declared_universe(source))))
        try:
            return _execute_days(
                request, market_data, days, path, source, day_timeout, ctx_symbols, run_loop)
        except _StrategyDayFailure as failure:
            message = (f"strategy_execution_timeout:{failure.day}"
                       if failure.class_name is None
                       else f"strategy_execution_error:{failure.day}:{failure.class_name}")
            logger.warning("paper_trade strategy failed on %s (%s)", failure.day, message)
            return _strategy_error(request, market_data, message)
    return run_loop()
