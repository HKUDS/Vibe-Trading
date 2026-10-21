"""Golden sample paper-trade strategy (T7 / VD-8 minimal ctx contract).

The reference strategy for the ``paper_trade_step`` strategy_path mode: an
SMA(5)/SMA(20) crossover over the served universe.  It exercises exactly the
frozen minimal ctx surface and nothing more (R-V11):

* ``ctx.account_state`` — read-only ledger after previous days have matched.
* ``ctx.symbols`` — the served universe, sorted.
* ``ctx.history(symbol)`` — OHLCV bars strictly before ``trade_date``
  (orders fill at the execution day’s close), as a copy.
* ``ctx.sma(close, period)`` — the technical_indicators pure-function surface.

Declares the optional module-level ``UNIVERSE`` literal (the strategy-universe
convention): a pure AST read (``strategy_exec.strategy_universe``, never an
execution) extracts it, the T6 tool unions it into the market-data fetch
universe, and the executor unions it into ``ctx.symbols`` — so the strategy
also serves a cash-only account whose empty position list would otherwise
prefetch nothing.  Absent or malformed declarations fall back to the served
universe (positions ∪ fetched symbols).

Contract shape (enforced by the executor): ``class SignalEngine`` with
``generate_signals(self, ctx, trade_date)`` returning a list of order objects
``{"symbol", "side", "qty", "limit"?, "reason"?}``.  The class name matters:
``SignalEngine`` is the entry the backtest AST sandbox's runtime-reachable
scrubber scans, so this file is validated by the same hardened pass as every
backtest signal engine (AM-8 — no raw import, no network/subprocess/eval/
os.environ/unsafe-open anywhere on the executed path).

Deterministic by construction: no clock, no randomness, no I/O — the same
file + ledger state + trading day always yields the same orders.
"""

UNIVERSE = ("SYNTH-4TO1",)


class SignalEngine:
    """SMA(5)/SMA(20) crossover: buy 100 on a golden cross, exit on a death cross."""

    def generate_signals(self, ctx, trade_date):
        held = {position.symbol: position.qty for position in ctx.account_state.positions}
        orders = []
        for symbol in ctx.symbols:
            close = ctx.history(symbol)["close"]
            fast = ctx.sma(close, 5)
            slow = ctx.sma(close, 20)
            if fast is None or slow is None:
                continue
            quantity = held.get(symbol, 0.0)
            if fast > slow and quantity == 0.0:
                orders.append({
                    "symbol": symbol,
                    "side": "buy",
                    "qty": 100,
                    "reason": f"golden sma5 {fast:.4f} > sma20 {slow:.4f}",
                })
            elif fast < slow and quantity > 0.0:
                orders.append({
                    "symbol": symbol,
                    "side": "sell",
                    "qty": quantity,
                    "reason": f"golden sma5 {fast:.4f} < sma20 {slow:.4f}",
                })
        return orders
