"""Adapters for existing historical routes and free US option snapshots."""

from datetime import datetime, timezone
import json
import math
import re
import time
from typing import Any

from src.config.accessor import get_env_value

from .service import GatewayError

MAX_CONTRACTS = 120
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def finite(value: Any, *, positive: bool = False) -> float | None:
    """Accept only observed finite numeric fields, without substituting zero."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) and (not positive or value > 0) else None


def normalize(ticker: str, source: str, raw: dict, expiration: int | None, *, full: bool = False) -> dict:
    """Validate identity/expiry, select nearby strikes and preserve missing fields."""
    dates = raw.get("expirationDates")
    if not isinstance(dates, list) or not dates:
        raise GatewayError("Missing option expirations")
    dates = sorted({d for d in dates if isinstance(d, int) and not isinstance(d, bool) and d > 0})
    block = (raw.get("options") or [None])[0]
    if not isinstance(block, dict) or block.get("expirationDate") not in dates:
        raise GatewayError("Malformed or mismatched option expiration")
    selected = block["expirationDate"]
    if expiration is not None and selected != expiration:
        raise GatewayError("Requested expiration is not available")
    if selected + 86400 < time.time():
        raise GatewayError("Option chain has expired")
    quote = raw.get("quote") or {}
    if quote.get("symbol", ticker).upper() != ticker.upper():
        raise GatewayError("Underlying identity mismatch")
    spot = finite(quote.get("regularMarketPrice"), positive=True)
    if spot is None:
        raise GatewayError("Missing observed underlying price")
    result = {"ticker": ticker, "underlying_price": spot, "expiration": selected, "expirations": dates}
    fields = {
        "contractSymbol": "contract_symbol",
        "strike": "strike",
        "lastPrice": "last_price",
        "bid": "bid",
        "ask": "ask",
        "volume": "volume",
        "openInterest": "open_interest",
        "impliedVolatility": "implied_volatility",
        "inTheMoney": "in_the_money",
        "expiration": "expiration",
        "delta": "delta",
        "lastTradeDate": "last_trade_time",
    }
    for side in ("calls", "puts"):
        rows = []
        for row in block.get(side) or []:
            if not isinstance(row, dict) or row.get("expiration") != selected:
                continue
            strike = finite(row.get("strike"), positive=True)
            symbol = row.get("contractSymbol")
            # Standard 100-share contracts only; adjusted roots require deliverables.
            match = re.fullmatch(r"([A-Z.-]+)(\d{6})([CP])(\d{8})", symbol or "")
            if not match or match[1] != ticker or match[3] != ("C" if side == "calls" else "P"):
                continue
            try:
                contract_expiry = int(datetime.strptime(match[2], "%y%m%d").replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
            if contract_expiry != selected or strike is None or abs(int(match[4]) / 1000 - strike) > 0.0001:
                continue
            normalized = {target: row.get(key) for key, target in fields.items()}
            for field in (
                "strike",
                "last_price",
                "bid",
                "ask",
                "volume",
                "open_interest",
                "implied_volatility",
                "delta",
            ):
                normalized[field] = finite(normalized[field])
            delta = normalized["delta"]
            if delta is not None and not (-1 <= delta <= 1):
                normalized["delta"] = None
            bid, ask = normalized["bid"], normalized["ask"]
            normalized["usable_quote"] = bid is not None and ask is not None and 0 <= bid <= ask and ask > 0
            normalized["multiplier"] = 100
            normalized["in_the_money"] = strike < spot if side == "calls" else strike > spot
            rows.append(normalized)
        if not rows or not any(r["usable_quote"] for r in rows):
            raise GatewayError("No usable two-sided option quotes")
        rows.sort(key=lambda r: (abs(r["strike"] - spot), r["strike"]))
        result[side] = sorted((rows if full else rows[:MAX_CONTRACTS]), key=lambda r: r["strike"])
        result[side + "_count"] = len(result[side])
        result[side + "_total"] = len(rows)
    result["atm_strike"] = min((r["strike"] for r in result["calls"] + result["puts"]), key=lambda p: abs(p - spot))
    result["coverage"] = "all_standard_contracts_in_source_expiration" if full else "near_spot"
    result["complete_expiration"] = all(result[s + "_count"] == result[s + "_total"] for s in ("calls", "puts"))
    result["price_basis"] = "ask_for_buy_bid_for_sell"
    return {
        "ok": True,
        "market": "us",
        "source": source,
        "data": result,
        "gateway": {
            "delayed": True if source == "cboe" else None,
            "source_timestamp": raw.get("timestamp"),
            "underlying_quote_time": quote.get("regularMarketTime"),
            "quote_time_known": False,
            "executable": False,
            "quality": "delayed" if source == "cboe" else "delay_unknown",
        },
    }


def yahoo_options(ticker: str, expiration: int | None = None, full: bool = False) -> dict:
    """Reuse the existing throttled cookie/crumb-aware Yahoo client."""
    from backtest.loaders import yahoo_client

    raw = yahoo_client.get_options(ticker, expiration=expiration)
    return normalize(ticker, "yahoo", raw, expiration, full=full)


def cboe_options(ticker: str, expiration: int | None = None, full: bool = False) -> dict:
    """Fetch Cboe's public delayed snapshot, never relabel it as live quotes.

    The public response carries a timestamp without a timezone. It is retained
    verbatim, not converted into a fabricated UTC quote timestamp. Individual
    last-trade times are not bid/ask update times.
    """
    import requests

    # URL host is fixed; caller validation plus this check excludes path injection.
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", ticker):
        raise GatewayError("Invalid underlying")
    timeout = float(get_env_value("VIBE_GATEWAY_HTTP_TIMEOUT", "5"))
    if not 0.1 <= timeout <= 20:
        raise ValueError("VIBE_GATEWAY_HTTP_TIMEOUT must be between .1 and 20")
    with requests.get(
        f"https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json", timeout=timeout, stream=True
    ) as response:
        response.raise_for_status()
        data = bytearray()
        started = time.monotonic()
        for chunk in response.iter_content(65536):
            if time.monotonic() - started > timeout:
                raise TimeoutError("Option snapshot read deadline exceeded")
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES:
                raise GatewayError("Option snapshot is too large")
        payload = json.loads(data)
    body = payload.get("data", {})
    if payload.get("symbol") != ticker or body.get("symbol") != ticker:
        raise GatewayError("Cboe underlying identity mismatch")
    by_date: dict[int, dict[str, list]] = {}
    for row in body.get("options", []):
        match = re.fullmatch(r"([A-Z.-]+)(\d{6})([CP])(\d{8})", row.get("option", ""))
        if not match or match[1] != ticker:
            continue
        epoch = int(datetime.strptime(match[2], "%y%m%d").replace(tzinfo=timezone.utc).timestamp())
        if epoch + 86400 < time.time():
            continue
        bucket = by_date.setdefault(epoch, {"calls": [], "puts": []})
        bucket["calls" if match[3] == "C" else "puts"].append(
            {
                "contractSymbol": row["option"],
                "strike": int(match[4]) / 1000,
                "expiration": epoch,
                "bid": row.get("bid"),
                "ask": row.get("ask"),
                "lastPrice": row.get("last_trade_price"),
                "volume": row.get("volume"),
                "openInterest": row.get("open_interest"),
                "impliedVolatility": row.get("iv"),
                "delta": row.get("delta"),
                "lastTradeDate": row.get("last_trade_time"),
            }
        )
    dates = sorted(by_date)
    if not dates:
        raise GatewayError("Cboe returned no option expirations")
    selected = expiration if expiration is not None else dates[0]
    if selected not in by_date:
        raise GatewayError("Requested expiration is not available")
    return normalize(
        ticker,
        "cboe",
        {
            "expirationDates": dates,
            "options": [{"expirationDate": selected, **by_date[selected]}],
            "quote": {"symbol": ticker, "regularMarketPrice": body.get("current_price")},
            "timestamp": payload.get("timestamp"),
        },
        expiration,
        full=full,
    )
