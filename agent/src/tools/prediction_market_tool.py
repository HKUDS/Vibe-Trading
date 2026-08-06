"""Read-only prediction-market (event-contract) data tool.

Prediction markets quote binary event contracts: each outcome is a token that
settles at $1 if the event happens and $0 otherwise. The live share price is
therefore the market's *implied probability* of that outcome, which makes these
venues an alternative data feed for event-driven research — rate decisions,
elections, geopolitical events, earnings-adjacent questions.

Data comes from two public, no-auth Polymarket services (both verified
reachable; every field name below was read off a live response, not inferred):

* Gamma (``https://gamma-api.polymarket.com``) — catalogue and current quotes.
  - ``GET /public-search?q=&limit_per_type=&events_status=`` returns
    ``{"events": [...], "pagination": {"hasMore", "totalResults"}}``.
    ``events_status=active`` keeps only ``closed == false`` events and
    ``events_status=resolved`` only ``closed == true``; any other value is
    effectively unfiltered.
  - ``GET /events/<numeric id>`` returns one event object; a miss is HTTP 404
    with ``{"type": "not found error", "error": "id not found"}``.
  - ``GET /events?slug=<exact slug>`` returns a list (empty on a partial slug —
    the match is exact, not prefix).
  - ``GET /markets/<numeric id>`` returns one market object.
  Event objects carry ``id, ticker, slug, title, description, startDate,
  endDate, closedTime, active, closed, archived, liquidity, volume,
  volume24hr, markets``.
  Market objects carry ``id, question, conditionId, slug, endDate, closed,
  active, archived, acceptingOrders, outcomes, outcomePrices, clobTokenIds,
  bestBid, bestAsk, lastTradePrice, spread, oneDayPriceChange, volumeNum,
  liquidityNum, closedTime, resolvedBy, umaResolutionStatus,
  umaResolutionStatuses``.

* CLOB (``https://clob.polymarket.com``) — order book and price history.
  - ``GET /book?token_id=<clob token id>`` returns ``{bids, asks, asset_id,
    market, hash, last_trade_price, min_order_size, neg_risk, tick_size,
    timestamp}``. ``bids``/``asks`` are ``{"price", "size"}`` pairs with string
    values; bids arrive ascending and asks descending, so the *last* element of
    each is the top of book.
  - ``GET /markets/<conditionId>`` returns ``tokens: [{token_id, outcome,
    price, winner}]``. ``winner`` is the venue's own settlement flag and is the
    strongest resolution evidence either API exposes.
  - ``GET /prices-history?market=<clob token id>&interval=&fidelity=`` returns
    ``{"history": [{"t": epoch_seconds, "p": price}]}``.

Gotchas this module compensates for:

* Gamma serializes ``outcomes``, ``outcomePrices`` and ``clobTokenIds`` as JSON
  *strings*, not arrays. They must be decoded before use.
* The history ``interval`` grammar is ``1h, 6h, 1d, 1w, 1m, max`` — and ``1m``
  means one **month**, not one minute (an ``interval=1m`` probe returned 31
  daily points spanning a month). ``fidelity`` is the bar width in *minutes*.
  The server rejects unknown intervals with an explicit "Known values" error.
* ``prices-history`` is keyed by a CLOB token id (one series per outcome), not
  by the market id, so a market id has to be resolved to a token first.

Closing and resolving are two different upstream events, and this module keeps
them in two different fields. Every record therefore carries a lifecycle
``status`` *and* a separate ``resolution`` block, and the two never substitute
for each other:

* ``status`` — ``open`` (trading), ``closed`` (trading ended), ``resolved``
  (trading ended *and* a resolution record exists), ``inactive``
  (``active == false``) or ``archived`` (delisted from the catalogue;
  ``archived`` is reported ahead of the others because it describes the
  catalogue entry rather than the contract).
* ``resolution.state`` — ``unresolved`` (still trading), ``pending`` (trading
  closed but nothing in the payload states the outcome) or ``resolved``.
  ``pending`` means *unknown to this tool*, not *no winner*.

Evidence used for ``resolved``, strongest first, with the winner named only
when the payload actually identifies one:

1. CLOB ``tokens[].winner`` — exactly one token flagged. Direct venue
   statement; available on the ``0x`` condition-id path.
2. Gamma ``umaResolutionStatus`` in ``{"resolved", "settled"}``. Observed
   values of that field across a live sample are ``null`` (702/800),
   ``"resolved"`` (93), ``"settled"`` (4) and ``"proposed"`` (1); ``proposed``
   means an answer was submitted to the oracle but is not final, so it maps to
   ``pending``. The sibling ``umaResolutionStatuses`` (plural) is a JSON string
   that was ``"[]"`` on 799 of those 800 markets and is not used.

Things deliberately *not* treated as settlement evidence:

* ``closed == true`` on its own. It means trading ended. 400 sampled closed
  markets included pre-oracle 2020 markets whose ``outcomePrices`` are
  ``["0", "0"]`` — closed for five years, with no outcome recorded anywhere.
* An outcome price at or above ``_SETTLED_PRICE_FLOOR``. 115 of 400 sampled
  *open* markets had a price >= 0.99, so a pinned price is a probability, not a
  settlement. On a closed market it is reported as ``implied_winning_outcome``
  and explicitly labelled an inference; it never promotes ``state``.
* ``resolvedBy``. It is the resolver contract address and is populated on open
  markets too (market 2774056, ``closed == false``, carries one).
* A settled market keeps ``active == true``, so ``active`` says nothing about
  settlement either.

The two directions this costs and pays: two markets in a 300-market sample of
recently closed markets carry ``umaResolutionStatus == "resolved"`` with prices
``["0.5", "0.5"]`` (a void/tie resolution). They are reported ``resolved`` with
``winning_outcome`` null, where a price-only rule would have called them
unresolved. Conversely a pre-oracle closed market with a price pinned at
0.9999996 is reported ``pending`` with an ``implied_winning_outcome``, where
the old rule asserted it as settled.

This tool is strictly read-only: it issues GET requests against public data
endpoints only and has no order, position or account surface of any kind.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backtest.loaders._http import resolve_min_interval, throttled_get_json
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

_GAMMA_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
_GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
_GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
_CLOB_BOOK_URL = "https://clob.polymarket.com/book"
_CLOB_MARKETS_URL = "https://clob.polymarket.com/markets"
_CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"

# Separate throttle buckets: the catalogue and the book are different hosts and
# must not share a rate budget.
_GAMMA_HOST_KEY = "polymarket_gamma"
_CLOB_HOST_KEY = "polymarket_clob"
_MIN_INTERVAL_ENV = "VIBE_TRADING_POLYMARKET_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL = 0.35
_TIMEOUT_S = 20.0

_MODES = ("search", "event", "market", "history")

# Defensive caps so a payload can never blow up the LLM context.
_MAX_IDS = 10
_MAX_SEARCH_LIMIT = 25
_DEFAULT_SEARCH_LIMIT = 10
_MAX_MARKETS_PER_EVENT = 30
_MAX_OUTCOMES_PER_MARKET = 20
_MAX_BOOK_TOKENS = 4
_MAX_DEPTH = 20
_MAX_POINTS = 1000
_DEFAULT_POINTS = 200

# Server-accepted history windows. "1m" is one month; "max" is the full series.
_INTERVALS = ("1h", "6h", "1d", "1w", "1m", "max")
# Bar width in minutes per window, chosen so a default request lands well under
# _MAX_POINTS while keeping the window's shape readable.
_FIDELITY_MINUTES = {"1h": 1, "6h": 10, "1d": 60, "1w": 360, "1m": 1440, "max": 1440}

# Lifecycle labels. Shared by event and market records so the two record types
# cannot describe the same upstream flags with different words.
_STATUS_OPEN = "open"
_STATUS_CLOSED = "closed"
_STATUS_RESOLVED = "resolved"
_STATUS_INACTIVE = "inactive"
_STATUS_ARCHIVED = "archived"
_STATUSES = (_STATUS_OPEN, _STATUS_CLOSED, _STATUS_RESOLVED, _STATUS_INACTIVE, _STATUS_ARCHIVED)

# Settlement states, kept separate from the lifecycle label. "pending" is the
# honest bucket: trading ended and nothing in the payload states the outcome.
_RESOLUTION_UNRESOLVED = "unresolved"
_RESOLUTION_PENDING = "pending"
_RESOLUTION_RESOLVED = "resolved"

# umaResolutionStatus values that mean the oracle answer is final. Every other
# non-null value is an in-flight record, not a settlement: the one observed live
# is "proposed", an answer submitted to the oracle and still challengeable.
_UMA_FINAL = frozenset({"resolved", "settled"})

# An outcome price at or above this level in a closed market *implies* a winner
# but does not establish one; settled binaries print ~0.9999996 / ~4e-7, so the
# floor is not tight. Used only for `implied_winning_outcome`, and to name the
# winner once some other field has already established that a resolution exists.
_SETTLED_PRICE_FLOOR = 0.99

# Id-space bounds used to tell a CLOB outcome token from a gamma catalogue id
# without guessing at digit counts. See _is_clob_token_id.
_UINT256_MAX = 2**256 - 1
_MAX_DATABASE_ID = 2**63 - 1

_UNITS = {
    "implied_probability": (
        "fraction in 0-1. This is the outcome share price, which settles at $1 "
        "if the outcome occurs and $0 otherwise, so the price IS the market's "
        "implied probability. 0.63 means a 63% chance, NOT $0.63 of exposure."
    ),
    "implied_probability_pct": "percent in 0-100, same quantity times 100",
    "price_usd": "USD price of one outcome share, numerically equal to the probability",
    "volume_usd": "cumulative traded notional in USD",
    "liquidity_usd": "resting book/AMM liquidity in USD",
    "size": "number of outcome shares",
}

# Shipped on every envelope so a consumer never has to guess what a label
# licenses it to say. Kept in lockstep with _lifecycle_status/_market_resolution.
_VOCABULARY = {
    "status": {
        _STATUS_OPEN: "trading; not closed and not settled",
        _STATUS_CLOSED: (
            "trading has ended and NO resolution record was found. Does not mean "
            "the outcome is known — see resolution.state"
        ),
        _STATUS_RESOLVED: "a resolution record exists; see resolution.state_basis for which one",
        _STATUS_INACTIVE: "upstream 'active' flag is false while trading has not closed",
        _STATUS_ARCHIVED: (
            "delisted from the catalogue. Describes the listing, not the contract, so "
            "read resolution.state for settlement"
        ),
    },
    "resolution.state": {
        _RESOLUTION_UNRESOLVED: "still trading, so no settlement can have happened",
        _RESOLUTION_PENDING: (
            "trading ended but no resolution record is present. This is 'unknown to this "
            "tool', NOT 'no winner'. Do not report a winner from a pending record"
        ),
        _RESOLUTION_RESOLVED: (
            "a resolution record is present. winning_outcome is filled only when the "
            "payload names one; a null winner on a resolved market means a void or "
            "split resolution, not a missing lookup"
        ),
    },
}


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _get_json(url: str, *, host_key: str, params: dict[str, Any] | None = None) -> Any:
    """Throttled GET returning decoded JSON.

    Args:
        url: Fully-qualified endpoint URL.
        host_key: Throttle bucket, one of the module's two host keys.
        params: Optional query parameters.

    Returns:
        The decoded JSON body.

    Raises:
        requests.RequestException: Propagated from the shared HTTP layer.
    """
    return throttled_get_json(
        url,
        host_key=host_key,
        min_interval=resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL),
        params=params,
        timeout=_TIMEOUT_S,
    )


def _json_list(value: Any) -> list[Any]:
    """Decode a gamma field that may arrive as a JSON string or a real list.

    Args:
        value: Raw field value (``'["Yes", "No"]'`` or ``["Yes", "No"]``).

    Returns:
        The decoded list, or ``[]`` when the value is absent or malformed.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _to_float(value: Any) -> float | None:
    """Coerce a possibly-string numeric field to float.

    Args:
        value: Raw value from a payload.

    Returns:
        The float, or ``None`` when the value is missing or non-numeric.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _probability(value: Any) -> dict[str, float] | None:
    """Convert a raw outcome share price into a labelled probability pair.

    Args:
        value: Raw price, string or number, nominally within ``[0, 1]``.

    Returns:
        ``{"implied_probability", "implied_probability_pct", "price_usd"}``, or
        ``None`` when the price is unparseable.
    """
    price = _to_float(value)
    if price is None:
        return None
    return {
        "implied_probability": round(price, 6),
        "implied_probability_pct": round(price * 100.0, 4),
        "price_usd": round(price, 6),
    }


def _is_clob_token_id(value: str) -> bool:
    """Decide whether an identifier is a CLOB outcome token id.

    The two id spaces are disjoint by construction rather than by convention:
    a CLOB token id is an ERC-1155 position id, i.e. a keccak-derived
    ``uint256`` (74-78 decimal digits across a live sample of 372 tokens, every
    one of them above ``2**63`` and below ``2**256``), while a gamma catalogue
    id is a sequential database row id that cannot exceed a signed 64-bit
    column. So the boundary is the signed-64-bit ceiling, and a decimal string
    larger than ``uint256`` is not a token id at all — it is out of domain.

    Args:
        value: A caller-supplied identifier, already stripped.

    Returns:
        True when the value lies in the CLOB token id domain.
    """
    # isascii() before isdigit(): str.isdigit() is true for superscripts such as
    # "²", which int() then rejects with ValueError. Both id spaces are
    # ASCII decimal, so anything else is out of domain rather than an exception.
    if not (value.isascii() and value.isdigit()):
        return False
    number = int(value)
    return _MAX_DATABASE_ID < number <= _UINT256_MAX


def _market_resolution(raw: dict[str, Any], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a market's settlement state from resolution evidence only.

    Trading closure is never treated as settlement. See the module docstring
    for the evidence hierarchy and for what is deliberately excluded from it.

    Args:
        raw: A gamma market object, or a CLOB market object already re-keyed by
            :func:`_clob_market_to_gamma_shape`.
        outcomes: Normalized outcome records in ``outcomes`` order, each with
            ``outcome`` and, when priced, ``implied_probability``.

    Returns:
        ``{"state", "state_basis", "winning_outcome", ...}`` where ``state`` is
        ``unresolved``, ``pending`` or ``resolved``. ``winning_outcome`` is
        non-null only when the payload names a winner; on a ``pending`` market
        whose prices merely imply one, the guess travels as
        ``implied_winning_outcome`` and is labelled an inference.
    """
    names = [o.get("outcome") for o in outcomes]
    flagged = [i for i, o in enumerate(outcomes) if o.get("is_winner") is True]
    if len(flagged) == 1:
        return {
            "state": _RESOLUTION_RESOLVED,
            "state_basis": "clob_winner_flag: the venue flags this outcome as the winner",
            "winning_outcome": names[flagged[0]],
            "winning_outcome_basis": "clob_winner_flag",
        }

    uma = raw.get("umaResolutionStatus")
    uma = uma.strip().lower() if isinstance(uma, str) and uma.strip() else None
    pinned = [
        i
        for i, o in enumerate(outcomes)
        if (o.get("implied_probability") or 0.0) >= _SETTLED_PRICE_FLOOR
    ]

    if uma in _UMA_FINAL:
        record: dict[str, Any] = {
            "state": _RESOLUTION_RESOLVED,
            "state_basis": f"uma_resolution_status={uma}: the oracle answer is final",
        }
        if len(pinned) == 1:
            record["winning_outcome"] = names[pinned[0]]
            record["winning_outcome_basis"] = (
                f"settled_outcome_price: exactly one outcome pays >= {_SETTLED_PRICE_FLOOR}"
            )
        else:
            record["winning_outcome"] = None
            record["winning_outcome_basis"] = (
                "unavailable: the oracle answer is final but no single outcome price is "
                f">= {_SETTLED_PRICE_FLOOR}, which is what a void or split resolution "
                "looks like"
            )
        return record

    if raw.get("closed"):
        record = {
            "state": _RESOLUTION_PENDING,
            "state_basis": (
                f"uma_resolution_status={uma}: an oracle record exists but is not final"
                if uma
                else "trading closed, and the payload carries no resolution record"
            ),
            "winning_outcome": None,
        }
        if len(pinned) == 1:
            record["implied_winning_outcome"] = names[pinned[0]]
            record["implied_winning_outcome_basis"] = (
                f"INFERENCE ONLY: exactly one outcome is priced >= {_SETTLED_PRICE_FLOOR} "
                "in a market whose trading has closed. This is not a settlement record "
                "and must not be reported as the resolved outcome."
            )
        return record

    if uma is not None:
        return {
            "state": _RESOLUTION_PENDING,
            "state_basis": (
                f"uma_resolution_status={uma}: an oracle record exists but is not final"
            ),
            "winning_outcome": None,
        }

    return {
        "state": _RESOLUTION_UNRESOLVED,
        "state_basis": "still trading: the upstream closed flag is false",
        "winning_outcome": None,
    }


def _lifecycle_status(raw: dict[str, Any], resolution_state: str) -> str:
    """Map upstream flags plus a settlement state onto one lifecycle label.

    ``archived`` is checked first because it describes the catalogue entry
    rather than the contract; settlement is still reported independently in the
    ``resolution`` block, so a delisted settled market is not misread.

    Args:
        raw: A gamma event or market object.
        resolution_state: The ``state`` produced by the matching resolution
            helper.

    Returns:
        One of :data:`_STATUSES`.
    """
    if raw.get("archived"):
        return _STATUS_ARCHIVED
    if resolution_state == _RESOLUTION_RESOLVED:
        return _STATUS_RESOLVED
    if raw.get("closed"):
        return _STATUS_CLOSED
    if raw.get("active") is False:
        return _STATUS_INACTIVE
    return _STATUS_OPEN


def _event_resolution(
    raw: dict[str, Any], markets: list[dict[str, Any]], *, total: int
) -> dict[str, Any]:
    """Derive an event's settlement state from the markets beneath it.

    An event carries no prices, no oracle status and no winner flag of its own,
    so its only resolution evidence is its markets'. A closed event with no
    resolved market is ``pending``, never ``resolved``.

    ``total`` is the event's *untruncated* market count, which is not
    ``len(markets)``: the payload is capped at :data:`_MAX_MARKETS_PER_EVENT`.
    Reading the resolved count against the truncated list would call an event
    with 32 markets ``resolved`` on the strength of the first 30, which is the
    same "closed enough, call it resolved" error this module exists to remove.
    An event whose markets were not all inspected can therefore never reach
    ``resolved``.

    Args:
        raw: A gamma event object.
        markets: Normalized market records belonging to the event; empty when
            the payload exposes none.
        total: Number of markets the event actually lists, before the cap.

    Returns:
        ``{"state", "state_basis", "markets_resolved", "markets_total",
        "markets_inspected"}``.
    """
    inspected = len(markets)
    resolved = sum(
        1 for m in markets if (m.get("resolution") or {}).get("state") == _RESOLUTION_RESOLVED
    )
    counts = {
        "markets_resolved": resolved,
        "markets_total": total,
        "markets_inspected": inspected,
    }
    uninspected = total - inspected

    if total and inspected == total and resolved == total:
        return {
            "state": _RESOLUTION_RESOLVED,
            "state_basis": f"every one of the {total} market(s) under this event is resolved",
            **counts,
        }
    if raw.get("closed"):
        if not total:
            basis = "trading closed; this payload exposes no markets to check"
        elif uninspected > 0:
            basis = (
                f"trading closed; {resolved} of the {inspected} market(s) inspected carry a "
                f"resolution record, and {uninspected} of this event's {total} markets were "
                f"not inspected because the payload is capped at {_MAX_MARKETS_PER_EVENT}. "
                "Settlement of the whole event is therefore unknown"
            )
        else:
            basis = (
                f"trading closed; {resolved} of {total} markets under this event carry a "
                "resolution record"
            )
        return {"state": _RESOLUTION_PENDING, "state_basis": basis, **counts}
    return {
        "state": _RESOLUTION_UNRESOLVED,
        "state_basis": "still trading: the upstream closed flag is false",
        **counts,
    }


def _normalize_market(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape one gamma market object into the tool's market record.

    Args:
        raw: A gamma market object as returned under ``events[].markets`` or by
            ``/markets/<id>``.

    Returns:
        A market record carrying identifiers, the lifecycle ``status``, a
        separate ``resolution`` block, per-outcome implied probabilities and
        top-of-book quote fields.
    """
    names = [str(n) for n in _json_list(raw.get("outcomes"))][:_MAX_OUTCOMES_PER_MARKET]
    prices = _json_list(raw.get("outcomePrices"))[:_MAX_OUTCOMES_PER_MARKET]
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))][:_MAX_OUTCOMES_PER_MARKET]
    # Only CLOB payloads carry per-outcome winner flags; gamma has none.
    winners = _json_list(raw.get("outcomeWinners"))[:_MAX_OUTCOMES_PER_MARKET]

    outcomes: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        record: dict[str, Any] = {"outcome": name}
        probability = _probability(prices[index] if index < len(prices) else None)
        if probability is not None:
            record.update(probability)
        if index < len(tokens):
            record["clob_token_id"] = tokens[index]
        if index < len(winners) and isinstance(winners[index], bool):
            record["is_winner"] = winners[index]
        outcomes.append(record)

    resolution = _market_resolution(raw, outcomes)

    return {
        "market_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "question": raw.get("question"),
        "slug": raw.get("slug"),
        "condition_id": raw.get("conditionId"),
        "status": _lifecycle_status(raw, resolution["state"]),
        # The raw upstream flag, under a name that says what it actually means.
        # It used to travel as `settled`, which asserted a settlement that
        # `closed` does not establish; settlement now lives in `resolution`.
        "trading_closed": bool(raw.get("closed")),
        "resolution": resolution,
        "end_date": raw.get("endDate"),
        "closed_time": raw.get("closedTime"),
        "outcomes": outcomes,
        "volume_usd": _to_float(raw.get("volumeNum")),
        "liquidity_usd": _to_float(raw.get("liquidityNum")),
        "best_bid": _to_float(raw.get("bestBid")),
        "best_ask": _to_float(raw.get("bestAsk")),
        "spread": _to_float(raw.get("spread")),
        "last_trade_price": _to_float(raw.get("lastTradePrice")),
        "one_day_probability_change": _to_float(raw.get("oneDayPriceChange")),
    }


def _normalize_event(raw: dict[str, Any], *, with_markets: bool) -> dict[str, Any]:
    """Shape one gamma event object into the tool's event record.

    Args:
        raw: A gamma event object.
        with_markets: Whether to expand the nested market records.

    Returns:
        An event record with the lifecycle ``status``, a ``resolution`` block
        derived from the markets beneath it, dates and, optionally, those
        normalized markets.
    """
    raw_markets = raw.get("markets")
    raw_markets = raw_markets if isinstance(raw_markets, list) else []
    # Normalized whatever `with_markets` says: the event's own resolution has no
    # other evidence to stand on, and a closed event must not inherit the word
    # "resolved" from its `closed` flag the way it used to.
    usable = [m for m in raw_markets if isinstance(m, dict)]
    markets = [_normalize_market(m) for m in usable[:_MAX_MARKETS_PER_EVENT]]
    # The true count, so a capped payload cannot be read as a complete one.
    resolution = _event_resolution(raw, markets, total=len(usable))

    event: dict[str, Any] = {
        "event_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "title": raw.get("title"),
        "slug": raw.get("slug"),
        "ticker": raw.get("ticker"),
        "status": _lifecycle_status(raw, resolution["state"]),
        # Same vocabulary as markets, from the same upstream flag, so the two
        # record types cannot disagree about what closing and resolving mean.
        "trading_closed": bool(raw.get("closed")),
        "resolution": resolution,
        "start_date": raw.get("startDate"),
        "end_date": raw.get("endDate"),
        "closed_time": raw.get("closedTime"),
        "resolution_source": raw.get("resolutionSource"),
        "volume_usd": _to_float(raw.get("volume")),
        "volume_24h_usd": _to_float(raw.get("volume24hr")),
        "liquidity_usd": _to_float(raw.get("liquidity")),
    }
    if isinstance(raw.get("markets"), list):
        event["market_count"] = len(raw_markets)
        if with_markets:
            event["markets"] = markets
    return event


def _fetch_event(identifier: str) -> dict[str, Any]:
    """Fetch one event by numeric id or by exact slug.

    Args:
        identifier: Gamma event id (digits) or the event's exact slug.

    Returns:
        A normalized event record, or ``{"error": ...}``. Never raises.
    """
    try:
        if identifier.isdigit():
            payload = _get_json(f"{_GAMMA_EVENTS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY)
        else:
            payload = _get_json(
                _GAMMA_EVENTS_URL, host_key=_GAMMA_HOST_KEY, params={"slug": identifier}
            )
            if not isinstance(payload, list) or not payload:
                return {"id": identifier, "error": "no event matches this slug (match is exact)"}
            payload = payload[0]
    except Exception as exc:  # noqa: BLE001 - one bad id must not kill the batch
        logger.warning("polymarket event fetch failed for %s: %s", identifier, exc)
        return {"id": identifier, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"id": identifier, "error": "unexpected event payload shape"}
    return _normalize_event(payload, with_markets=True)


def _fetch_book(token_id: str, depth: int) -> dict[str, Any]:
    """Fetch the top ``depth`` levels of one outcome token's order book.

    Args:
        token_id: CLOB token id identifying a single outcome series.
        depth: Number of price levels to keep per side.

    Returns:
        ``{"bids": [...], "asks": [...], "tick_size", "min_order_size"}`` or
        ``{"error": ...}``. Never raises.
    """
    try:
        payload = _get_json(
            _CLOB_BOOK_URL, host_key=_CLOB_HOST_KEY, params={"token_id": token_id}
        )
    except Exception as exc:  # noqa: BLE001 - book depth is best-effort
        logger.warning("polymarket book fetch failed for %s: %s", token_id, exc)
        return {"error": str(exc)}
    if not isinstance(payload, dict):
        return {"error": "unexpected book payload shape"}

    def levels(key: str) -> list[dict[str, Any]]:
        """Take the ``depth`` levels nearest the touch, best price first."""
        raw = payload.get(key)
        if not isinstance(raw, list):
            return []
        # Both sides arrive worst-price-first, so the touch is at the tail.
        near = [lvl for lvl in reversed(raw) if isinstance(lvl, dict)][:depth]
        out: list[dict[str, Any]] = []
        for lvl in near:
            probability = _probability(lvl.get("price"))
            if probability is None:
                continue
            probability["size"] = _to_float(lvl.get("size"))
            out.append(probability)
        return out

    return {
        "bids": levels("bids"),
        "asks": levels("asks"),
        "tick_size": _to_float(payload.get("tick_size")),
        "min_order_size": _to_float(payload.get("min_order_size")),
    }


def _fetch_market(identifier: str, depth: int) -> dict[str, Any]:
    """Fetch one market's current quote, optionally with book depth.

    Args:
        identifier: Gamma market id (digits) or a ``0x``-prefixed condition id.
        depth: Book levels per side; ``0`` skips the CLOB round-trips.

    Returns:
        A normalized market record, or ``{"error": ...}``. Never raises.
    """
    try:
        if identifier.lower().startswith("0x"):
            payload = _get_json(f"{_CLOB_MARKETS_URL}/{identifier}", host_key=_CLOB_HOST_KEY)
            if not isinstance(payload, dict):
                return {"id": identifier, "error": "unexpected market payload shape"}
            payload = _clob_market_to_gamma_shape(payload)
        else:
            payload = _get_json(f"{_GAMMA_MARKETS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY)
    except Exception as exc:  # noqa: BLE001 - one bad id must not kill the batch
        logger.warning("polymarket market fetch failed for %s: %s", identifier, exc)
        return {"id": identifier, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"id": identifier, "error": "unexpected market payload shape"}

    market = _normalize_market(payload)
    if depth > 0:
        for outcome in market["outcomes"][:_MAX_BOOK_TOKENS]:
            token_id = outcome.get("clob_token_id")
            if token_id:
                outcome["book"] = _fetch_book(token_id, depth)
    return market


def _clob_market_to_gamma_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-key a CLOB market object onto the gamma field names.

    The CLOB ``/markets/<conditionId>`` response uses snake_case and nests
    outcomes under ``tokens``; normalizing once here keeps a single downstream
    shaping path.

    Args:
        payload: A CLOB market object.

    Returns:
        A dict using the gamma market field names.
    """
    tokens = [t for t in payload.get("tokens", []) if isinstance(t, dict)]
    return {
        # CLOB does not expose gamma's numeric market id. Emitting the slug here
        # would hand back a `market_id` that gamma's /markets/<id> rejects with
        # HTTP 422, so the id stays absent and the slug travels as `slug`.
        "id": None,
        "question": payload.get("question"),
        "slug": payload.get("market_slug"),
        "conditionId": payload.get("condition_id"),
        "endDate": payload.get("end_date_iso"),
        "closed": payload.get("closed"),
        "active": payload.get("active"),
        "archived": payload.get("archived"),
        "outcomes": [str(t.get("outcome")) for t in tokens],
        "outcomePrices": [t.get("price") for t in tokens],
        "clobTokenIds": [str(t.get("token_id")) for t in tokens],
        # Gamma has no equivalent, so this key exists only on the CLOB path. It
        # is the venue's own settlement flag and outranks every other signal.
        "outcomeWinners": [t.get("winner") for t in tokens],
    }


def _resolve_history_token(identifier: str, outcome: str | None) -> tuple[str, dict[str, Any]]:
    """Resolve a user-supplied id to a single CLOB token id for a price series.

    Args:
        identifier: A CLOB token id (see :func:`_is_clob_token_id`), a ``0x``
            condition id, or a gamma market id.
        outcome: Outcome name to select (case-insensitive); defaults to the
            first outcome when omitted.

    Returns:
        ``(token_id, context)`` where context carries whatever identifying
        metadata was resolved along the way.

    Raises:
        ValueError: The id cannot be resolved to an outcome token.
        requests.RequestException: Propagated from the HTTP layer.
    """
    if _is_clob_token_id(identifier):
        return identifier, {"clob_token_id": identifier}

    if identifier.lower().startswith("0x"):
        payload = _get_json(f"{_CLOB_MARKETS_URL}/{identifier}", host_key=_CLOB_HOST_KEY)
        raw = _clob_market_to_gamma_shape(payload) if isinstance(payload, dict) else {}
    else:
        raw = _get_json(f"{_GAMMA_MARKETS_URL}/{identifier}", host_key=_GAMMA_HOST_KEY)
        if not isinstance(raw, dict):
            raise ValueError("unexpected market payload shape")

    names = [str(n) for n in _json_list(raw.get("outcomes"))]
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))]
    if not tokens:
        raise ValueError("market exposes no CLOB outcome tokens")

    index = 0
    if outcome is not None:
        matches = [i for i, n in enumerate(names) if n.lower() == outcome.lower()]
        if not matches:
            raise ValueError(f"outcome '{outcome}' not in {names}")
        index = matches[0]
    if index >= len(tokens):
        raise ValueError("outcome has no matching CLOB token")

    return tokens[index], {
        "market_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "question": raw.get("question"),
        "condition_id": raw.get("conditionId"),
        "outcome": names[index] if index < len(names) else None,
        "clob_token_id": tokens[index],
    }


def _fetch_history(
    identifier: str, *, interval: str, outcome: str | None, max_points: int
) -> dict[str, Any]:
    """Fetch one outcome's implied-probability time series.

    Args:
        identifier: CLOB token id, condition id, or gamma market id.
        interval: One of ``1h``, ``6h``, ``1d``, ``1w``, ``1m`` (one month) or
            ``max``.
        outcome: Outcome name to select when the id names a whole market.
        max_points: Cap on returned points; the most recent are kept.

    Returns:
        A record with ``points`` on success or ``error`` on failure. Never
        raises.
    """
    try:
        token_id, context = _resolve_history_token(identifier, outcome)
    except Exception as exc:  # noqa: BLE001 - one bad id must not kill the batch
        logger.warning("polymarket history resolution failed for %s: %s", identifier, exc)
        return {"id": identifier, "error": str(exc)}

    try:
        payload = _get_json(
            _CLOB_HISTORY_URL,
            host_key=_CLOB_HOST_KEY,
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": _FIDELITY_MINUTES[interval],
            },
        )
    except Exception as exc:  # noqa: BLE001 - one bad id must not kill the batch
        logger.warning("polymarket history fetch failed for %s: %s", identifier, exc)
        return {"id": identifier, **context, "error": str(exc)}

    raw_points = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(raw_points, list):
        return {"id": identifier, **context, "error": "unexpected history payload shape"}

    points: list[dict[str, Any]] = []
    for entry in raw_points:
        if not isinstance(entry, dict):
            continue
        probability = _probability(entry.get("p"))
        epoch = _to_float(entry.get("t"))
        if probability is None or epoch is None:
            continue
        probability["timestamp"] = datetime.fromtimestamp(
            epoch, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")
        points.append(probability)

    return {
        "id": identifier,
        **context,
        "interval": interval,
        "bar_minutes": _FIDELITY_MINUTES[interval],
        "points": points[-max_points:],
        "count": min(len(points), max_points),
    }


def _search_events(query: str, limit: int, status: str) -> dict[str, Any]:
    """Search the event catalogue by keyword.

    Args:
        query: Free-text keyword(s).
        limit: Maximum events to return.
        status: ``"open"``, ``"closed"`` or ``"any"``, already canonicalized.

    Returns:
        ``{"events": [...], "total_results": int, "has_more": bool,
        "status_filter_basis": str}``.

    Raises:
        requests.RequestException: Propagated from the HTTP layer.
    """
    params: dict[str, Any] = {"q": query, "limit_per_type": limit}
    # Only these two values actually discriminate; anything else is unfiltered.
    # Upstream calls the second one "resolved", but a probe of both showed it
    # selects `closed == true` and nothing more — it cannot filter on
    # settlement — so the tool exposes it under the name it earns.
    basis = "no upstream filter applied"
    if status == "open":
        params["events_status"] = "active"
        basis = "events_status=active upstream, which selects closed == false"
    elif status == "closed":
        params["events_status"] = "resolved"
        basis = (
            "events_status=resolved upstream, which selects closed == true only; "
            "it does NOT filter on settlement, so read each event's resolution.state"
        )

    payload = _get_json(_GAMMA_SEARCH_URL, host_key=_GAMMA_HOST_KEY, params=params)
    if not isinstance(payload, dict):
        return {
            "events": [],
            "total_results": 0,
            "has_more": False,
            "status_filter_basis": basis,
        }

    raw_events = payload.get("events")
    events = [
        _normalize_event(e, with_markets=False)
        for e in (raw_events if isinstance(raw_events, list) else [])[:limit]
        if isinstance(e, dict)
    ]
    pagination = payload.get("pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    return {
        "events": events,
        "total_results": pagination.get("totalResults"),
        "has_more": bool(pagination.get("hasMore")),
        "status_filter_basis": basis,
    }


def _coerce_int(value: Any) -> int | None:
    """Coerce a parameter to an int, accepting the JSON shapes callers emit.

    An LLM filling a tool call routinely sends ``"10"`` or ``10.0`` where the
    schema says integer. Those name exactly one integer each, so rejecting them
    fails a call that was never ambiguous. A fractional number is a different
    case — it names no integer — and is rejected rather than silently rounded.

    Args:
        value: Raw parameter value: int, float, or numeric string.

    Returns:
        The integer, or ``None`` when the value does not name one. Booleans are
        rejected: ``True`` is an int in Python but never means 1 here.
    """
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


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int | None:
    """Validate and clamp an integer parameter.

    Args:
        value: Raw parameter value; ``None`` selects the default. Numeric
            strings and integral floats are accepted, see :func:`_coerce_int`.
        default: Value used when the parameter is absent.
        low: Minimum accepted value.
        high: Maximum accepted value; larger inputs are clamped down.

    Returns:
        The clamped integer, or ``None`` when the input does not name a valid
        integer at or above ``low``.
    """
    if value is None:
        return default
    number = _coerce_int(value)
    if number is None or number < low:
        return None
    return min(number, high)


class PredictionMarketTool(BaseTool):
    """Read prediction-market event contracts: search, quotes and probability history."""

    name = "prediction_market"
    repeatable = True
    is_readonly = True
    description = (
        "READ-ONLY prediction-market (event-contract) data from Polymarket's "
        "public endpoints — alternative data for event-driven research. Each "
        "outcome share settles at $1 or $0, so its price IS the market-implied "
        "probability: a 0.63 quote means a 63% chance, never $0.63 of exposure. "
        "Every quote is returned as 'implied_probability' (0-1) plus "
        "'implied_probability_pct' (0-100). Modes: 'search' (find events by "
        "keyword), 'event' (one or more events with the markets beneath them), "
        "'market' (current top-of-book quote and probabilities, optional order-"
        "book depth), 'history' (implied-probability time series for one "
        "outcome). CLOSED AND RESOLVED ARE DIFFERENT: every record carries a "
        f"lifecycle 'status' ({' / '.join(_STATUSES)}) AND a separate "
        "'resolution' block whose 'state' is 'unresolved' (still trading), "
        "'pending' (trading ended but nothing states the outcome) or 'resolved' "
        "(a resolution record exists, named in 'resolution.state_basis'). Never "
        "report a market as settled on 'status' alone, and never report "
        "'implied_winning_outcome' as the result — it is a price inference, not "
        "a settlement. This tool cannot trade and exposes no order or account "
        "surface. Examples: "
        '{"mode": "search", "query": "fed rate cut", "status": "open"} · '
        '{"mode": "market", "ids": ["2774056"], "depth": 5} · '
        '{"mode": "history", "ids": ["2774056"], "interval": "1m", '
        '"outcome": "Yes"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(_MODES),
                "description": (
                    "'search' = keyword event search; 'event' = event detail "
                    "including its markets; 'market' = one market's current "
                    "implied probabilities and quote; 'history' = one outcome's "
                    "implied-probability time series."
                ),
            },
            "query": {
                "type": "string",
                "description": "Keyword(s) for mode='search', e.g. 'fed rate cut'.",
            },
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "For mode='event': event ids (numeric) or exact event slugs. "
                    "For mode='market' and mode='history': market ids (numeric), "
                    "'0x'-prefixed condition ids, or — for history only — CLOB "
                    f"token ids. Up to {_MAX_IDS} per call — a longer list is "
                    "truncated and the envelope reports 'ids_dropped'. One "
                    "failing id is reported in place and does not abort the batch."
                ),
            },
            "status": {
                "type": "string",
                "enum": ["open", "closed", "any"],
                "description": (
                    "mode='search' filter, on TRADING state — the catalogue "
                    "cannot filter on settlement. 'open' = still trading, "
                    "'closed' = trading ended (which is NOT the same as "
                    "resolved: check each result's resolution.state), 'any' = "
                    "no filter. 'resolved' is accepted as a legacy alias for "
                    "'closed' and behaves identically."
                ),
                "default": "open",
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"mode='search' result cap (1-{_MAX_SEARCH_LIMIT})."
                ),
                "default": _DEFAULT_SEARCH_LIMIT,
            },
            "depth": {
                "type": "integer",
                "description": (
                    "mode='market' order-book levels per side "
                    f"(0-{_MAX_DEPTH}). 0 (the default) skips the extra book "
                    "requests; best bid/ask and spread are always returned "
                    "regardless."
                ),
                "default": 0,
            },
            "interval": {
                "type": "string",
                "enum": list(_INTERVALS),
                "description": (
                    "mode='history' lookback window. NOTE '1m' means one MONTH, "
                    "not one minute; 'max' is the full series. Bar width is "
                    "chosen per window so the series stays compact."
                ),
                "default": "1m",
            },
            "outcome": {
                "type": "string",
                "description": (
                    "mode='history' outcome name to chart, e.g. 'Yes'. Defaults "
                    "to the market's first outcome. Ignored when the id is "
                    "already a CLOB token id."
                ),
            },
            "max_points": {
                "type": "integer",
                "description": (
                    f"mode='history' cap on returned points (1-{_MAX_POINTS}); "
                    "the most recent are kept."
                ),
                "default": _DEFAULT_POINTS,
            },
        },
        "required": ["mode"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Dispatch one of the four read modes and return a JSON envelope.

        Args:
            **kwargs: ``mode`` (required) plus the mode's parameters — ``query``
                / ``status`` / ``limit`` for search, ``ids`` for event, ``ids``
                / ``depth`` for market, and ``ids`` / ``interval`` / ``outcome``
                / ``max_points`` for history.

        Returns:
            A JSON string ``{"ok": true, "source": "polymarket", "mode": ...,
            "units": {...}, "vocabulary": {...}, "data": {...}}`` on success, or
            ``{"ok": false, "error": ...}`` on a request-level failure.
            ``vocabulary`` defines every ``status`` and ``resolution.state``
            value the payload can carry. Per-id failures are reported inside
            ``data`` and never abort the batch.
        """
        mode = kwargs.get("mode")
        if mode not in _MODES:
            return _error(f"mode must be one of {list(_MODES)}")

        if mode == "search":
            query = kwargs.get("query")
            if not isinstance(query, str) or not query.strip():
                return _error("mode='search' requires a non-empty 'query'")
            status = kwargs.get("status", "open")
            # 'resolved' is upstream's own name for this filter and was this
            # tool's public enum value, so it keeps working — mapped onto the
            # trading-state word it actually means.
            status = "closed" if status == "resolved" else status
            if status not in ("open", "closed", "any"):
                return _error("status must be one of ['open', 'closed', 'any']")
            limit = _clamp_int(
                kwargs.get("limit"),
                default=_DEFAULT_SEARCH_LIMIT,
                low=1,
                high=_MAX_SEARCH_LIMIT,
            )
            if limit is None:
                return _error("limit must be a positive integer")
            try:
                data = _search_events(query.strip(), limit, status)
            except Exception as exc:  # noqa: BLE001 - surface as envelope
                return _error(f"prediction-market search failed: {exc}")
            data["query"] = query.strip()
            data["status_filter"] = status
            return self._envelope(mode, data)

        ids = kwargs.get("ids")
        if not isinstance(ids, list) or not ids:
            return _error(f"mode='{mode}' requires a non-empty 'ids' list")
        if any(not isinstance(i, str) or not i.strip() for i in ids):
            return _error("every id must be a non-empty string")
        cleaned = [i.strip() for i in ids][:_MAX_IDS]
        # Over-long id lists are capped, but silently dropping the tail would let
        # a caller believe it got an answer for every id it asked about.
        overflow: dict[str, Any] = (
            {"ids_dropped": len(ids) - len(cleaned)} if len(ids) > len(cleaned) else {}
        )

        if mode == "event":
            return self._envelope(
                mode, {"events": [_fetch_event(i) for i in cleaned], **overflow}
            )

        if mode == "market":
            depth = _clamp_int(kwargs.get("depth"), default=0, low=0, high=_MAX_DEPTH)
            if depth is None:
                return _error("depth must be a non-negative integer")
            return self._envelope(
                mode,
                {
                    "markets": [_fetch_market(i, depth) for i in cleaned],
                    "depth": depth,
                    **overflow,
                },
            )

        interval = kwargs.get("interval", "1m")
        if interval not in _INTERVALS:
            return _error(f"interval must be one of {list(_INTERVALS)}")
        outcome = kwargs.get("outcome")
        if outcome is not None and (not isinstance(outcome, str) or not outcome.strip()):
            return _error("outcome must be a non-empty string when provided")
        max_points = _clamp_int(
            kwargs.get("max_points"), default=_DEFAULT_POINTS, low=1, high=_MAX_POINTS
        )
        if max_points is None:
            return _error("max_points must be a positive integer")
        series = [
            _fetch_history(
                i,
                interval=interval,
                outcome=outcome.strip() if isinstance(outcome, str) else None,
                max_points=max_points,
            )
            for i in cleaned
        ]
        return self._envelope(mode, {"series": series, "interval": interval, **overflow})

    @staticmethod
    def _envelope(mode: str, data: dict[str, Any]) -> str:
        """Wrap mode output in the shared success envelope.

        Args:
            mode: The dispatched mode name.
            data: Mode-specific payload.

        Returns:
            The serialized success envelope.
        """
        return json.dumps(
            {
                "ok": True,
                "source": "polymarket",
                "market": "prediction_market",
                "mode": mode,
                "units": _UNITS,
                "vocabulary": _VOCABULARY,
                "data": data,
            },
            ensure_ascii=False,
        )
