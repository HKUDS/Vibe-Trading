"""Read-only OpenAlgo REST transport with explicit analyzer/live provenance.

OpenAlgo (https://github.com/marketcalls/openalgo) is a self-hosted server that
fronts one Indian broker account behind a single ``/api/v1`` REST API. Every
endpoint is ``POST`` with a JSON body carrying ``apikey``. Request and response
shapes are pinned to OpenAlgo ``OPENALGO_CONTRACT`` (``restx_api/`` and
``services/`` at that commit, plus ``docs/api/``). OpenAlgo does not report its
version over the API, so the pin is a documented contract, not a runtime check.

Provenance: OpenAlgo's analyzer mode is a server-wide, mutable setting. While it
is on, account reads are answered by OpenAlgo's sandbox and every such response
carries ``"mode": "analyze"``; live broker responses carry no ``mode`` key. Each
book returned here records ``openalgo_mode`` from the response that produced it,
and a read that combines two books refuses to mix an analyzer book with a live
one. Quotes and history always come from the broker's market data.

Writes: there is no write path. ``place_order``/``cancel_order`` refuse before any
network operation, and the transport accepts only a fixed vocabulary of read
endpoints, which excludes every order endpoint and the analyzer toggle.

Holdings and net positions are separate broker books; their overlap is not
inferred. Funds are margin/limit values, not cash or net liquidation. This
connector cannot enter portfolio aggregation.
"""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

#: OpenAlgo release and upstream commit whose REST contract this module maps.
OPENALGO_CONTRACT = "2.0.3.3@7ba5267f7d5d15c352606b3aea6b12ab20223428"
_OVERRIDE_KEYS = ("host_url", "api_key")

#: The only endpoints this transport will ever call. Every OpenAlgo order
#: endpoint (placeorder, cancelorder, modifyorder, closeposition, ...) and the
#: ``analyzer/toggle`` mode switch are absent by construction.
READ_ENDPOINTS = frozenset(
    {
        "ping",
        "analyzer",
        "funds",
        "positionbook",
        "holdings",
        "orderbook",
        "tradebook",
        "quotes",
        "history",
    }
)

#: ``utils.constants.VALID_EXCHANGES`` at the pinned commit.
VALID_EXCHANGES = frozenset(
    {
        "NSE",
        "NFO",
        "CDS",
        "BSE",
        "BFO",
        "BCD",
        "MCX",
        "NCDEX",
        "NCO",
        "NSE_INDEX",
        "BSE_INDEX",
        "MCX_INDEX",
        "GLOBAL_INDEX",
        "CRYPTO",
    }
)
#: Exchanges whose prices and P&L are Indian rupees. GLOBAL_INDEX and CRYPTO are
#: left unlabelled because OpenAlgo reports no currency for them.
_INR_EXCHANGES = frozenset(VALID_EXCHANGES - {"GLOBAL_INDEX", "CRYPTO"})

#: Generic ``period`` vocabulary -> the intervals ``docs/api/market-data/history.md`` documents.
_INTERVALS = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "D",
    "1D": "D",
    "D": "D",
}
_INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}
_SESSION_MINUTES = 375  # NSE cash session, 09:15-15:30 IST
_MAX_BARS = 5000
_IST = timezone(timedelta(hours=5, minutes=30))
_OPEN_ORDER_STATUSES = frozenset(
    {"open", "pending", "trigger pending", "trigger_pending"}
)


class OpenAlgoAPIError(RuntimeError):
    """A bounded, credential-free failure message from a read operation."""


@dataclass(frozen=True)
class OpenAlgoConfig:
    """Server address and API key supplied by the connection's OS credential vault."""

    host_url: str = ""
    api_key: str = field(default="", repr=False)
    environment: str = "live"
    timeout: float = 15.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> OpenAlgoConfig:
        """Build the only supported environment; never simulate an account.

        Raises:
            ValueError: For a non-live environment, a non-string credential or an
                unsafe host URL.
        """
        values = dict(data or {})
        if values.get("environment", "live") != "live":
            raise ValueError("OpenAlgo supports only live read-only connections")
        for key in _OVERRIDE_KEYS:
            if not isinstance(values.get(key, ""), str):
                raise ValueError(f"{key} must be a string")
        host_url = values.get("host_url", "").strip().rstrip("/")
        if host_url:
            _validate_host(host_url)
        return cls(host_url=host_url, api_key=values.get("api_key", "").strip())


def _validate_host(host: str) -> None:
    """Accept https anywhere and plain http only on loopback.

    The API key travels in the request body and authorizes orders on the
    OpenAlgo server, so it is never sent in clear text over a network.
    """
    parts = urlsplit(host)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(
            "host_url must be an http(s) URL such as http://127.0.0.1:5000"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("host_url must not contain credentials, a query or a fragment")
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        raise ValueError(
            "plain http is allowed only for a loopback OpenAlgo host; use https"
        )


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> OpenAlgoConfig:
    """Resolve profile settings and approved overrides, without a secret file."""
    values = dict(profile_config or {})
    values.update(
        {
            key: value
            for key, value in dict(overrides or {}).items()
            if key in _OVERRIDE_KEYS and value is not None
        }
    )
    return OpenAlgoConfig.from_mapping(values)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _post(
    config: OpenAlgoConfig, endpoint: str, params: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """POST one read endpoint and return the validated success envelope."""
    if not config.host_url or not config.api_key:
        raise OpenAlgoAPIError(
            "Configure the OpenAlgo host URL and API key in connection settings."
        )
    if endpoint not in READ_ENDPOINTS:
        raise OpenAlgoAPIError("Unsupported OpenAlgo read endpoint")
    try:
        with httpx.Client(timeout=config.timeout, follow_redirects=False) as client:
            response = client.post(
                f"{config.host_url}/api/v1/{endpoint}",
                json={"apikey": config.api_key, **dict(params or {})},
                headers={"Accept": "application/json"},
            )
            status = response.status_code
            payload = response.json() if status == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        # Exception strings may echo the request body, which carries the API key.
        raise OpenAlgoAPIError(
            "OpenAlgo read failed: invalid response or network error. Check the host and retry."
        ) from exc
    if status == 403:
        raise OpenAlgoAPIError(
            "OpenAlgo rejected the API key. Check the key saved for this connection."
        )
    if status == 429:
        raise OpenAlgoAPIError(
            "OpenAlgo or its broker is rate limiting reads; retry shortly."
        )
    if status != 200:
        raise OpenAlgoAPIError(
            f"OpenAlgo read failed (HTTP {status}); check the server and broker session."
        )
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise OpenAlgoAPIError(
            "OpenAlgo rejected the read. Check the server and broker session before retrying."
        )
    if "mode" in payload and payload["mode"] != "analyze":
        raise OpenAlgoAPIError(
            "OpenAlgo returned an unmapped mode marker; the book's provenance is unknown."
        )
    return payload


def _mode(payload: Mapping[str, Any]) -> str:
    """Return ``analyze`` for a sandbox response and ``live`` for a broker response."""
    return "analyze" if payload.get("mode") == "analyze" else "live"


def _same_mode(*payloads: Mapping[str, Any]) -> str:
    modes = {_mode(payload) for payload in payloads}
    if len(modes) != 1:
        raise OpenAlgoAPIError(
            "OpenAlgo analyzer mode changed between reads; refusing to mix sandbox and live books. Retry."
        )
    return modes.pop()


def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise OpenAlgoAPIError(
            f"OpenAlgo returned an unmapped {what} shape; no empty book is inferred."
        )
    return value


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    """Parse an OpenAlgo number or numeric string; anything else is unknown, not zero."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _currency(exchange: Any) -> str | None:
    return (
        "INR"
        if isinstance(exchange, str) and exchange.upper() in _INR_EXCHANGES
        else None
    )


def _map(
    row: Mapping[str, Any], fields: Mapping[str, tuple[str, Any]]
) -> dict[str, Any]:
    """Rename mapped fields, convert their units, and keep unmapped keys under ``extra``."""
    mapped = {
        target: convert(row.get(source)) for source, (target, convert) in fields.items()
    }
    extra = {key: value for key, value in row.items() if key not in fields}
    if extra:
        mapped["extra"] = extra
    return mapped


_FUNDS_FIELDS = {
    "availablecash": ("available_cash", _num),
    "collateral": ("collateral", _num),
    "m2mrealized": ("realized_mtm", _num),
    "m2munrealized": ("unrealized_mtm", _num),
    "utiliseddebits": ("utilised_debits", _num),
}
_POSITION_FIELDS = {
    "symbol": ("symbol", _text),
    "exchange": ("exchange", _text),
    "product": ("product", _text),
    "quantity": ("quantity", _num),
    "average_price": ("average_price", _num),
    "ltp": ("ltp", _num),
    "pnl": ("pnl", _num),
    "average_price_basis": ("average_price_basis", _text),
}
_HOLDING_FIELDS = {
    "symbol": ("symbol", _text),
    "exchange": ("exchange", _text),
    "product": ("product", _text),
    "quantity": ("quantity", _num),
    "average_price": ("average_price", _num),
    "ltp": ("ltp", _num),
    "pnl": ("pnl", _num),
    "pnlpercent": ("pnl_percent", _num),
}
_HOLDING_STAT_FIELDS = {
    "totalholdingvalue": ("total_holding_value", _num),
    "totalinvvalue": ("total_investment_value", _num),
    "totalprofitandloss": ("total_pnl", _num),
    "totalpnlpercentage": ("total_pnl_percent", _num),
}
_ORDER_FIELDS = {
    "orderid": ("order_id", _text),
    "symbol": ("symbol", _text),
    "exchange": ("exchange", _text),
    "action": (
        "side",
        lambda value: value.strip().lower() if isinstance(value, str) else None,
    ),
    "quantity": ("quantity", _num),
    "price": ("price", _num),
    "trigger_price": ("trigger_price", _num),
    "pricetype": ("order_type", _text),
    "product": ("product", _text),
    "order_status": ("status", _text),
    "timestamp": ("timestamp", _text),
}
_TRADE_FIELDS = {
    "orderid": ("order_id", _text),
    "tradeid": ("trade_id", _text),
    "symbol": ("symbol", _text),
    "exchange": ("exchange", _text),
    "action": (
        "side",
        lambda value: value.strip().lower() if isinstance(value, str) else None,
    ),
    "quantity": ("quantity", _num),
    "average_price": ("average_price", _num),
    "trade_value": ("trade_value", _num),
    "product": ("product", _text),
    "timestamp": ("timestamp", _text),
}
_QUOTE_FIELDS = {
    "ltp": ("ltp", _num),
    "open": ("open", _num),
    "high": ("high", _num),
    "low": ("low", _num),
    "prev_close": ("prev_close", _num),
    "bid": ("bid", _num),
    "ask": ("ask", _num),
    "volume": ("volume", _num),
    "oi": ("oi", _num),
}


def _row_with_currency(
    row: Mapping[str, Any], fields: Mapping[str, tuple[str, Any]]
) -> dict[str, Any]:
    mapped = _map(row, fields)
    mapped["currency"] = _currency(mapped.get("exchange"))
    return mapped


def _book(mode: str, **values: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "openalgo_mode": mode,
        "provenance": "analyzer_sandbox" if mode == "analyze" else "live_broker",
        "openalgo_contract": OPENALGO_CONTRACT,
        "portfolio_eligible": False,
        **values,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_account_snapshot(config: OpenAlgoConfig | None = None) -> dict[str, Any]:
    """Return funds/margin limits with no invented cash or net-equity summary."""
    payload = _post(config or build_config(), "funds")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise OpenAlgoAPIError(
            "OpenAlgo returned an unmapped funds shape; no empty account is inferred."
        )
    return _book(
        _mode(payload),
        funds=_map(data, _FUNDS_FIELDS),
        currency=None,
        currency_note="OpenAlgo reports no currency; Indian broker adapters report INR.",
        valuation_basis="margin_limits_not_net_liquidation",
        note="Available cash, collateral and utilised debits are margin limits, not cash or net assets.",
    )


def get_positions(config: OpenAlgoConfig | None = None) -> dict[str, Any]:
    """Read holdings and net positions as separate books, without netting them."""
    cfg = config or build_config()
    position_payload = _post(cfg, "positionbook")
    holdings_payload = _post(cfg, "holdings")
    mode = _same_mode(position_payload, holdings_payload)
    net = _rows(position_payload.get("data"), "positionbook")
    holdings_data = holdings_payload.get("data")
    if not isinstance(holdings_data, dict):
        raise OpenAlgoAPIError(
            "OpenAlgo returned an unmapped holdings shape; no empty book is inferred."
        )
    holdings = _rows(holdings_data.get("holdings"), "holdings")
    statistics = holdings_data.get("statistics")
    return _book(
        mode,
        holdings=[_row_with_currency(row, _HOLDING_FIELDS) for row in holdings],
        holdings_statistics=(
            _map(statistics, _HOLDING_STAT_FIELDS)
            if isinstance(statistics, dict)
            else None
        ),
        net_positions=[_row_with_currency(row, _POSITION_FIELDS) for row in net],
        valuation_basis="broker_books_unaggregated",
        note="Holdings and net positions are separate books; delivery positions can appear in both. Do not sum them.",
    )


def get_open_orders(
    config: OpenAlgoConfig | None = None, *, include_executions: bool = False
) -> dict[str, Any]:
    """Read today's order book, optionally with the trade book as executions."""
    cfg = config or build_config()
    order_payload = _post(cfg, "orderbook")
    data = order_payload.get("data")
    if not isinstance(data, dict):
        raise OpenAlgoAPIError(
            "OpenAlgo returned an unmapped orderbook shape; no empty book is inferred."
        )
    orders = [
        _row_with_currency(row, _ORDER_FIELDS)
        for row in _rows(data.get("orders"), "orderbook")
    ]
    payloads = [order_payload]
    executions = None
    if include_executions:
        trade_payload = _post(cfg, "tradebook")
        payloads.append(trade_payload)
        executions = [
            _row_with_currency(row, _TRADE_FIELDS)
            for row in _rows(trade_payload.get("data"), "tradebook")
        ]
    result = _book(
        _same_mode(*payloads),
        open_orders=[
            order
            for order in orders
            if (order.get("status") or "").lower() in _OPEN_ORDER_STATUSES
        ],
        orders=orders,
    )
    if executions is not None:
        result["executions"] = executions
    return result


def _instrument(symbol: str, exchange: str | None) -> tuple[str, str]:
    """Split ``NSE:RELIANCE`` (or a bare symbol on ``exchange``/NSE) into OpenAlgo fields."""
    text = str(symbol or "").strip().upper()
    if ":" in text and exchange is None:
        exchange, text = text.split(":", 1)
    venue = str(exchange or "NSE").strip().upper()
    if venue not in VALID_EXCHANGES:
        raise OpenAlgoAPIError(
            f"Unsupported OpenAlgo exchange {venue!r}; use one of {sorted(VALID_EXCHANGES)}."
        )
    if not text or len(text) > 64 or any(char.isspace() for char in text):
        raise OpenAlgoAPIError(
            "OpenAlgo symbol must be a non-empty OpenAlgo-format symbol such as NSE:RELIANCE."
        )
    return text, venue


def get_quote(
    symbol: str,
    *,
    config: OpenAlgoConfig | None = None,
    exchange: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Read one broker quote snapshot for ``EXCHANGE:SYMBOL`` (bare symbols use NSE)."""
    try:
        clean, venue = _instrument(symbol, exchange)
        payload = _post(
            config or build_config(), "quotes", {"symbol": clean, "exchange": venue}
        )
    except OpenAlgoAPIError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "symbol": str(symbol or "").strip().upper(),
        }
    data = payload.get("data")
    quote = _map(data, _QUOTE_FIELDS) if isinstance(data, dict) else {}
    if not quote.get("ltp"):
        # Some adapters use zero placeholders; a missing or zero LTP is not a price.
        return {
            "status": "error",
            "error": f"OpenAlgo returned no last price for {venue}:{clean}",
            "symbol": clean,
        }
    return {
        "status": "ok",
        "symbol": clean,
        "exchange": venue,
        "currency": _currency(venue),
        "source": "broker_market_data",
        "openalgo_contract": OPENALGO_CONTRACT,
        "quote": quote,
    }


def _window(interval: str, limit: int) -> tuple[str, str]:
    """Return an IST calendar ``start_date``/``end_date`` wide enough for ``limit`` bars."""
    if interval == "D":
        days = math.ceil(limit * 7 / 5) + 10
    else:
        per_session = max(_SESSION_MINUTES // _INTERVAL_MINUTES[interval], 1)
        days = math.ceil(math.ceil(limit / per_session) * 7 / 5) + 4
    end = datetime.now(_IST).date()
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def get_historical_bars(
    symbol: str,
    *,
    config: OpenAlgoConfig | None = None,
    exchange: str | None = None,
    period: str = "1d",
    limit: int = 90,
) -> dict[str, Any]:
    """Read OHLCV bars; ``time`` is the epoch seconds OpenAlgo returns.

    Supported ``period`` tokens are the intervals OpenAlgo documents for every
    broker: 1m, 3m, 5m, 10m, 15m, 30m, 1h and 1d. Others fail closed.
    """
    interval = _INTERVALS.get(str(period).strip())
    shown = str(symbol or "").strip().upper()
    if interval is None:
        return {
            "status": "error",
            "error": f"unsupported period: {period!r}; supported: {sorted(_INTERVALS)}",
            "symbol": shown,
        }
    bars_wanted = min(max(int(limit), 1), _MAX_BARS)
    try:
        clean, venue = _instrument(symbol, exchange)
        start, end = _window(interval, bars_wanted)
        payload = _post(
            config or build_config(),
            "history",
            {
                "symbol": clean,
                "exchange": venue,
                "interval": interval,
                "start_date": start,
                "end_date": end,
            },
        )
        rows = _rows(payload.get("data"), "history")
    except OpenAlgoAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": shown}
    bars = []
    for row in rows:
        stamp = row.get("timestamp")
        close = _num(row.get("close"))
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, (int, float))
            or close is None
        ):
            return {
                "status": "error",
                "error": f"OpenAlgo returned a bar without epoch time or close for {venue}:{clean}",
                "symbol": clean,
            }
        bars.append(
            {
                "time": int(stamp),
                "open": _num(row.get("open")),
                "high": _num(row.get("high")),
                "low": _num(row.get("low")),
                "close": close,
                "volume": _num(row.get("volume")),
                "oi": _num(row.get("oi")),
            }
        )
    bars.sort(key=lambda bar: bar["time"])
    return {
        "status": "ok",
        "symbol": clean,
        "exchange": venue,
        "period": period,
        "interval": interval,
        "currency": _currency(venue),
        "time_unit": "epoch_seconds",
        "source": "broker_market_data",
        "openalgo_contract": OPENALGO_CONTRACT,
        "bars": bars[-bars_wanted:],
    }


def check_status(config: OpenAlgoConfig | None = None) -> dict[str, Any]:
    """Verify key, analyzer state and the position read without exposing books or credentials."""
    try:
        cfg = config or build_config()
        ping = _post(cfg, "ping")
        analyzer = _post(cfg, "analyzer")
        positions = _post(cfg, "positionbook")
        _rows(positions.get("data"), "positionbook")
    except (OpenAlgoAPIError, ValueError) as exc:
        return {"status": "error", "error": str(exc), "portfolio_eligible": False}
    ping_data = ping.get("data") if isinstance(ping.get("data"), dict) else {}
    analyzer_data = (
        analyzer.get("data") if isinstance(analyzer.get("data"), dict) else {}
    )
    analyze_mode = analyzer_data.get("analyze_mode")
    return {
        "status": "ok",
        "read_verified": True,
        "portfolio_eligible": False,
        "openalgo_broker": _text(ping_data.get("broker")),
        "analyze_mode": analyze_mode if isinstance(analyze_mode, bool) else None,
        "openalgo_mode": _mode(positions),
        "openalgo_contract": OPENALGO_CONTRACT,
    }


# ---------------------------------------------------------------------------
# Orders: refused for every configuration
# ---------------------------------------------------------------------------

_ORDER_REFUSED = (
    "OpenAlgo order placement and cancellation are disabled: analyzer mode is a mutable "
    "server-wide setting, so no request-time check can guarantee a write stays in the sandbox."
)


def place_order(
    *args: Any, config: OpenAlgoConfig | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Refuse every order before any network operation."""
    raise OpenAlgoAPIError(_ORDER_REFUSED)


def cancel_order(
    *args: Any, config: OpenAlgoConfig | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Refuse cancellation before any network operation."""
    raise OpenAlgoAPIError(_ORDER_REFUSED)
