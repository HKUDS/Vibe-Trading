"""Read-only crypto L2 order-book depth tool (OKX / Binance spot, via ccxt).

Built to close a documented gap: ``src/swarm/presets/statistical_arbitrage_desk.yaml``
tells its microstructure analyst "There is no order-book depth or quote feed
here" because that is true for the equity data sources this project has for
free — but it is *not* true for crypto. OKX and Binance both publish full L2
order-book snapshots over public, no-auth REST, and this project already
depends on ``ccxt>=4.0.0`` (see ``pyproject.toml``) and already talks to both
venues for OHLCV (``backtest/loaders/okx.py``, ``backtest/loaders/binance_loader.py``).
This tool reuses that same connectivity — ccxt's unified ``fetch_order_book``
— instead of hand-rolling per-venue REST parsing.

Symbol convention matches the rest of this repo (see CLAUDE.md: "OKX pairs
use ``BTC-USDT`` format, hyphen, uppercase") and ``ccxt_loader._parse_ccxt_symbol``:
the caller passes ``BASE-QUOTE`` (e.g. ``BTC-USDT``), which is upper-cased and
translated to ccxt's ``BASE/QUOTE`` form before the request. Perpetuals
(``-PERP``) are out of scope here — this tool is spot-book depth only.

What ccxt's ``fetch_order_book`` actually returns (read from the installed
``ccxt==4.5.54`` source, not assumed): ``parse_order_book`` always returns
``{"symbol", "bids", "asks", "timestamp", "datetime", "nonce"}`` where
``bids`` is sorted descending by price and ``asks`` ascending — i.e. index 0
on each side is always the best price, by construction of
``Exchange.parse_order_book``. This module still re-sorts defensively before
using either side (cheap, and removes any reliance on that upstream
invariant holding for every exchange/version). ``timestamp`` is venue
end-to-end epoch milliseconds when the venue's payload carries one — for
Binance *spot* depth (``GET /api/v3/depth``) it does not: ccxt's own
``fetch_order_book`` reads a ``"T"`` field that only appears in the
futures/options response shapes (see ``ccxt.binance.fetch_order_book``
docstring examples), so ``timestamp`` comes back ``None`` for Binance spot.
When that happens this tool falls back to the local fetch time and marks
``timestamp_source`` accordingly, rather than silently passing a null-dated
snapshot to the caller (an order book is only valid for seconds — the reader
must be able to tell how fresh it is either way).

The network call is isolated in :func:`_fetch_raw_book` for exactly one
reason: tests monkeypatch that single function and never touch the network,
same pattern as ``tests/test_prediction_market_tool.py`` monkeypatching
``throttled_get_json`` on its own tool module.

Domain decisions worth being explicit about (also covered in the tests):

* **Units.** Every ``amount``/``amount_base`` is a quantity of the pair's
  BASE asset. Every ``*_notional_quote`` / ``notional_quote`` / price is in
  the pair's QUOTE asset — USDT for ``BTC-USDT``, but BTC for ``ETH-BTC``.
  These are never averaged or added together; the ``units`` block on every
  response spells this out so a caller cannot mix them by accident.
* **Mid price** is always ``(best_bid + best_ask) / 2``. If either side of
  the book is empty this tool refuses to compute a mid price (or anything
  downstream of it) rather than guessing — see the empty-book handling below.
* **Crossed book** (``best_bid >= best_ask``) is treated as a data error and
  rejected outright. A negative or zero spread is never returned.
* **Impact-cost sizing.** "A market order for $10,000 notional" is sized
  identically for both directions: ``base_qty_target = notional_quote /
  mid_price``, computed once from the pre-trade mid. The buy side then walks
  the (fully fetched, not just the displayed) ask ladder consuming that many
  base units; the sell side walks the bid ladder the same way. This keeps
  buy and sell directly comparable (same order size) instead of the sell
  side chasing a moving quote-proceeds target, which would make the two
  sides answer different questions.
* **Partial fills are always reported, never disguised as full fills.** If
  the fetched ladder (``_BOOK_FETCH_LIMIT`` levels — see below) cannot
  satisfy ``base_qty_target``, the response carries ``fully_filled: false``,
  the actual ``filled_base_qty`` / ``filled_notional_quote`` (which will be
  less than requested), and an explanatory ``note``. The average price and
  slippage are still computed over whatever *was* filled — a partial number
  is more honest than no number, as long as it is labelled partial.
* **Fetch depth vs. requested depth are different knobs.** ``levels``
  (1..``_MAX_LEVELS``) controls how many rows are echoed back in ``depth``
  and how many are used for the imbalance ratio. Impact cost always walks
  the full ``_BOOK_FETCH_LIMIT``-level ladder pulled from the exchange
  (100 levels — a valid discrete Binance depth tier and well under OKX's
  400-row default-endpoint cap), regardless of ``levels``, since a $10k
  order can easily need more rows than a human wants echoed back.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from backtest.loaders.ccxt_loader import _CCXT_TIMEOUT_MS, _ccxt_proxy_config
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

_EXCHANGES = ("okx", "binance")
_DEFAULT_EXCHANGE = "okx"

_DEFAULT_LEVELS = 10
_MAX_LEVELS = 50

# Rows pulled from the exchange per call. Fixed (not caller-configurable):
# impact-cost needs headroom beyond whatever `levels` the caller wants
# echoed back, and 100 is a valid discrete Binance order-book depth tier
# (5/10/20/50/100/500/1000/5000) while sitting comfortably under OKX's
# default-endpoint 400-row cap — one request works cleanly against both.
_BOOK_FETCH_LIMIT = 100

_DEFAULT_NOTIONAL_QUOTE = 10_000.0

_UNITS = {
    "amount_base": "quantity of the pair's BASE asset (e.g. BTC in BTC-USDT) — never a currency value",
    "price": "quote-asset price of 1 unit of base (e.g. USDT per BTC in BTC-USDT)",
    "notional_quote / *_notional_quote / filled_notional_quote": (
        "value denominated in the pair's QUOTE asset (USDT for BTC-USDT, but "
        "BTC for ETH-BTC — read the quote leg off the symbol, do not assume USD)"
    ),
    "relative_bps / slippage_bps": "basis points (1 bps = 0.01%), relative to mid_price at fetch time",
    "normalized_imbalance": (
        "(bid_notional_quote - ask_notional_quote) / (bid_notional_quote + ask_notional_quote), "
        "in [-1, 1]. Positive = more resting buy-side notional (bid-heavy), negative = ask-heavy"
    ),
}


def _fetch_raw_book(exchange_id: str, ccxt_symbol: str, limit: int) -> dict[str, Any]:
    """Fetch one L2 order-book snapshot via ccxt's public REST API.

    Isolated as its own function so tests can monkeypatch exactly this name
    and never open a socket — see the module docstring.

    Args:
        exchange_id: ``"okx"`` or ``"binance"`` (a ccxt exchange id).
        ccxt_symbol: Unified ccxt symbol, e.g. ``"BTC/USDT"``.
        limit: Number of levels per side requested from the venue.

    Returns:
        A ccxt ``OrderBook`` dict: ``{"symbol", "bids", "asks", "timestamp",
        "datetime", "nonce"}``.

    Raises:
        Exception: Whatever ccxt raises for a network, symbol, or venue error.
    """
    import ccxt

    exchange_cls = getattr(ccxt, exchange_id)
    config: dict[str, Any] = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
    proxies = _ccxt_proxy_config()
    if proxies:
        config["proxies"] = proxies
    exchange = exchange_cls(config)
    return exchange.fetch_order_book(ccxt_symbol, limit)


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _parse_symbol(raw: Any) -> tuple[str, str] | None:
    """Validate + normalize a ``BASE-QUOTE`` symbol into ``(display, ccxt)`` forms.

    Args:
        raw: Caller-supplied symbol, e.g. ``"btc-usdt"``.

    Returns:
        ``(normalized_hyphen_symbol, ccxt_slash_symbol)``, or ``None`` when
        ``raw`` is not a well-formed ``BASE-QUOTE`` string.
    """
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper()
    parts = normalized.split("-")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    if not parts[0].isalnum() or not parts[1].isalnum():
        return None
    return normalized, f"{parts[0]}/{parts[1]}"


def _coerce_int(value: Any) -> int | None:
    """Coerce a parameter to int, accepting the JSON shapes an LLM tends to send."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return int(number) if number.is_integer() else None
    return None


def _coerce_float(value: Any) -> float | None:
    """Coerce a parameter to a finite float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _clean_levels(raw: Any) -> list[tuple[float, float]]:
    """Normalize a ccxt bids/asks array into sorted-by-caller ``(price, amount)`` pairs.

    Rows with a non-positive or non-finite price/amount are dropped rather
    than propagated into downstream arithmetic (a zero-amount row would
    silently no-op through the impact walk; a negative one would corrupt it).

    Args:
        raw: The ``bids`` or ``asks`` value from a ccxt order-book dict.

    Returns:
        A list of ``(price, amount)`` float pairs, in whatever order ``raw``
        had them (the caller sorts).
    """
    out: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            price = float(row[0])
            amount = float(row[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or not math.isfinite(amount):
            continue
        if price <= 0 or amount <= 0:
            continue
        out.append((price, amount))
    return out


def _walk_book(levels: list[tuple[float, float]], base_qty_target: float) -> dict[str, Any]:
    """Consume ``levels`` (best price first) until ``base_qty_target`` base units are filled.

    Args:
        levels: ``(price, amount)`` pairs in walk order (best price first);
            the caller is responsible for that ordering.
        base_qty_target: Base-asset quantity the simulated market order wants
            to fill.

    Returns:
        ``{"filled_base_qty", "filled_notional_quote", "avg_price",
        "levels_used", "fully_filled", "unfilled_base_qty"}``. ``avg_price``
        is ``None`` only when nothing at all could be filled (e.g. the side
        was empty, though callers already reject that case upstream).
    """
    remaining = base_qty_target
    base_filled = 0.0
    quote_filled = 0.0
    levels_used = 0
    for price, amount in levels:
        if remaining <= 0:
            break
        take = min(amount, remaining)
        base_filled += take
        quote_filled += take * price
        remaining -= take
        levels_used += 1
    # Tolerance absorbs float noise from the running subtraction above; it is
    # not a relaxed pass/fail threshold on the caller's requested size.
    fully_filled = remaining <= 1e-9
    return {
        "filled_base_qty": base_filled,
        "filled_notional_quote": quote_filled,
        "avg_price": (quote_filled / base_filled) if base_filled > 0 else None,
        "levels_used": levels_used,
        "fully_filled": fully_filled,
        "unfilled_base_qty": max(remaining, 0.0),
    }


class OrderBookDepthTool(BaseTool):
    """Read-only crypto L2 order-book depth: raw levels, spread, imbalance, impact cost."""

    name = "orderbook_depth"
    repeatable = True
    is_readonly = True
    description = (
        "READ-ONLY crypto L2 order-book snapshot from OKX or Binance spot "
        "public REST (via ccxt) — the depth/quote feed equity sources here "
        "cannot provide. Returns: (1) raw bid/ask levels (price + base-asset "
        "amount, up to 'levels' per side); (2) bid-ask spread, absolute and "
        "relative in bps; (3) depth imbalance within 'levels' — "
        "bid-notional/ask-notional ratio and a normalized (B-A)/(B+A) score "
        "in [-1, 1]; (4) impact cost — for a simulated market order sized at "
        "'notional_quote' (in the pair's quote asset, e.g. USDT for "
        "BTC-USDT), the volume-weighted average fill price and slippage in "
        "bps vs. mid price, computed BOTH for a buy (walking asks) and a "
        "sell (walking bids). A snapshot is only valid for seconds — every "
        "response carries a timestamp and 'exchange'. A quote-side that "
        "can't fill the full requested notional reports 'fully_filled: "
        "false' with the actually-filled amount, never a fabricated full "
        "fill. An empty book, a one-sided-empty book, or a crossed book "
        "(best_bid >= best_ask, a data error) is refused with an explicit "
        "error rather than a guessed number. Spot only, no perpetuals. "
        'Example: {"symbol": "BTC-USDT", "exchange": "okx", "levels": 10, '
        '"notional_quote": 10000}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "BASE-QUOTE pair, hyphenated and uppercase (OKX-style), "
                    "e.g. 'BTC-USDT' or 'ETH-BTC'. Required."
                ),
            },
            "exchange": {
                "type": "string",
                "enum": list(_EXCHANGES),
                "description": "Which venue's public order book to read.",
                "default": _DEFAULT_EXCHANGE,
            },
            "levels": {
                "type": "integer",
                "description": (
                    f"Number of price levels per side to return in 'depth' "
                    f"and to use for the imbalance calculation (1-{_MAX_LEVELS})."
                ),
                "default": _DEFAULT_LEVELS,
            },
            "notional_quote": {
                "type": "number",
                "description": (
                    "Simulated market-order size, in the pair's QUOTE asset "
                    "(USDT for BTC-USDT), used for the impact-cost "
                    "calculation. Must be positive."
                ),
                "default": _DEFAULT_NOTIONAL_QUOTE,
            },
        },
        "required": ["symbol"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch one order-book snapshot and return the depth/spread/imbalance/impact envelope.

        Args:
            **kwargs: ``symbol`` (required), plus optional ``exchange``,
                ``levels``, ``notional_quote``.

        Returns:
            A JSON string. On success: ``{"ok": true, "source": "ccxt",
            "market": "crypto", "units": {...}, "data": {...}}``. On failure
            (bad params, empty/one-sided/crossed book, or a request error):
            ``{"ok": false, "error": str}``.
        """
        parsed = _parse_symbol(kwargs.get("symbol"))
        if parsed is None:
            return _error(
                "symbol is required and must be BASE-QUOTE, hyphenated and "
                "uppercase, e.g. 'BTC-USDT' (got "
                f"{kwargs.get('symbol')!r})"
            )
        display_symbol, ccxt_symbol = parsed

        exchange_id = kwargs.get("exchange", _DEFAULT_EXCHANGE)
        if exchange_id not in _EXCHANGES:
            return _error(f"exchange must be one of {list(_EXCHANGES)}, got {exchange_id!r}")

        levels_raw = kwargs.get("levels", _DEFAULT_LEVELS)
        levels = _coerce_int(levels_raw)
        if levels is None or levels < 1 or levels > _MAX_LEVELS:
            return _error(
                f"levels must be an integer between 1 and {_MAX_LEVELS} "
                f"(got {levels_raw!r})"
            )

        notional_raw = kwargs.get("notional_quote", _DEFAULT_NOTIONAL_QUOTE)
        notional_quote = _coerce_float(notional_raw)
        if notional_quote is None or notional_quote <= 0:
            return _error(f"notional_quote must be a positive number (got {notional_raw!r})")

        try:
            raw_book = _fetch_raw_book(exchange_id, ccxt_symbol, _BOOK_FETCH_LIMIT)
        except Exception as exc:  # noqa: BLE001 - surface as error envelope
            return _error(f"{exchange_id} order book request failed for {display_symbol}: {exc}")

        if not isinstance(raw_book, dict):
            return _error(f"unexpected order book payload shape from {exchange_id}")

        bids = sorted(_clean_levels(raw_book.get("bids")), key=lambda lvl: lvl[0], reverse=True)
        asks = sorted(_clean_levels(raw_book.get("asks")), key=lambda lvl: lvl[0])

        if not bids and not asks:
            return _error(f"order book for {display_symbol} on {exchange_id} is empty (no bids or asks)")
        if not bids:
            return _error(
                f"order book for {display_symbol} on {exchange_id} has no bids — "
                "refusing to compute mid price / spread from a one-sided book"
            )
        if not asks:
            return _error(
                f"order book for {display_symbol} on {exchange_id} has no asks — "
                "refusing to compute mid price / spread from a one-sided book"
            )

        best_bid_price, best_bid_qty = bids[0]
        best_ask_price, best_ask_qty = asks[0]
        if best_bid_price >= best_ask_price:
            return _error(
                f"crossed book for {display_symbol} on {exchange_id}: "
                f"best_bid {best_bid_price} >= best_ask {best_ask_price}. "
                "This is a data error — refusing to compute a spread from it."
            )

        mid_price = (best_bid_price + best_ask_price) / 2.0
        spread_abs = best_ask_price - best_bid_price
        spread_bps = (spread_abs / mid_price) * 10_000.0

        timestamp_ms = raw_book.get("timestamp")
        if isinstance(timestamp_ms, (int, float)) and not isinstance(timestamp_ms, bool):
            timestamp = (
                datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            timestamp_source = "exchange"
        else:
            # Binance spot depth carries no server timestamp field at all
            # (ccxt's parser only finds one in the futures/options response
            # shapes) — fetch time is the honest fallback, explicitly labelled
            # so a caller never mistakes it for a venue-stamped time.
            timestamp = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            timestamp_source = "local_fetch_time"

        depth_bids = bids[:levels]
        depth_asks = asks[:levels]
        bid_notional = sum(p * a for p, a in depth_bids)
        ask_notional = sum(p * a for p, a in depth_asks)
        total_notional = bid_notional + ask_notional
        normalized_imbalance = (
            (bid_notional - ask_notional) / total_notional if total_notional > 0 else 0.0
        )

        base_qty_target = notional_quote / mid_price
        buy = _walk_book(asks, base_qty_target)
        buy["notional_quote_requested"] = notional_quote
        buy["slippage_bps"] = (
            ((buy["avg_price"] - mid_price) / mid_price) * 10_000.0
            if buy["avg_price"] is not None
            else None
        )
        sell = _walk_book(bids, base_qty_target)
        sell["notional_quote_requested"] = notional_quote
        sell["slippage_bps"] = (
            ((mid_price - sell["avg_price"]) / mid_price) * 10_000.0
            if sell["avg_price"] is not None
            else None
        )
        for side_name, side in (("buy", buy), ("sell", sell)):
            if not side["fully_filled"]:
                side["note"] = (
                    f"could not fill the full {notional_quote} notional within the "
                    f"{len(asks) if side_name == 'buy' else len(bids)} "
                    f"{'ask' if side_name == 'buy' else 'bid'} level(s) fetched "
                    f"(exchange fetch limit={_BOOK_FETCH_LIMIT}); filled_notional_quote "
                    "and avg_price reflect only the partial fill actually achieved. "
                    "This may mean genuinely thin liquidity, or just that the book "
                    "goes deeper than this snapshot's fetched window."
                )

        data = {
            "exchange": exchange_id,
            "symbol": display_symbol,
            "ccxt_symbol": ccxt_symbol,
            "timestamp": timestamp,
            "timestamp_source": timestamp_source,
            "best_bid": {"price": best_bid_price, "amount_base": best_bid_qty},
            "best_ask": {"price": best_ask_price, "amount_base": best_ask_qty},
            "mid_price": mid_price,
            "spread": {"absolute_quote": spread_abs, "relative_bps": spread_bps},
            "depth": {
                "levels": levels,
                "bids": [{"price": p, "amount_base": a} for p, a in depth_bids],
                "asks": [{"price": p, "amount_base": a} for p, a in depth_asks],
            },
            "imbalance": {
                "levels": levels,
                "bid_notional_quote": bid_notional,
                "ask_notional_quote": ask_notional,
                "ratio_bid_over_ask": (bid_notional / ask_notional) if ask_notional > 0 else None,
                "normalized_imbalance": normalized_imbalance,
            },
            "impact_cost": {
                "notional_quote": notional_quote,
                "base_qty_target": base_qty_target,
                "buy": buy,
                "sell": sell,
            },
            "levels_available": {"bids": len(bids), "asks": len(asks)},
        }
        return json.dumps(
            {"ok": True, "source": "ccxt", "market": "crypto", "units": _UNITS, "data": data},
            ensure_ascii=False,
        )
