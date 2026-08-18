"""Personal portfolio ledger and read-only broker reconciliation routes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.security import require_auth
from src.session.models import Principal
from src.trading.service import get_positions

from src.portfolio.calculator import calculate_snapshot
from src.portfolio.store import PortfolioStore


class PortfolioCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_currency: str = Field(default="CNY", min_length=3, max_length=3)


class PortfolioUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class TransactionRequest(BaseModel):
    type: str
    asset_type: str | None = None
    symbol: str | None = None
    market: str | None = None
    quantity: str | float | int | None = None
    price: str | float | int | None = None
    amount: str | float | int | None = None
    fee: str | float | int | None = None
    tax: str | float | int | None = None
    currency: str = Field(min_length=3, max_length=3)
    trade_at: str | None = None
    external_ref: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class PriceOverrideRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=20)
    currency: str = Field(min_length=3, max_length=3)
    price: str | float | int


def _scope(principal: Principal) -> str:
    return principal.subject


def _store() -> PortfolioStore:
    return PortfolioStore()


def _portfolio_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "base_currency": item.base_currency,
        "archived": item.archived,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _quote_key(market: str, symbol: str) -> str:
    return f"{market.lower()}:{symbol.upper()}"


_COMMODITY_INSTRUMENTS = [
    {"symbol": "XAUUSD", "name": "黄金现货", "short_name": "黄金", "market": "commodity", "asset_type": "commodity", "quote_symbol": "GC=F", "aliases": ("黄金", "gold", "xau", "xauusd", "gc=f", "黄金现货")},
    {"symbol": "GC=F", "name": "COMEX黄金期货", "short_name": "黄金期货", "market": "commodity", "asset_type": "future", "quote_symbol": "GC=F", "aliases": ("黄金期货", "comex", "gc=f", "gold futures")},
    {"symbol": "AU.SHF", "name": "上期所黄金期货", "short_name": "沪金", "market": "commodity", "asset_type": "future", "aliases": ("沪金", "上期所黄金", "au", "au.shf", "黄金期货")},
    {"symbol": "BANK_GOLD", "name": "银行积存金（自定义）", "short_name": "积存金", "market": "other", "asset_type": "bank_gold", "aliases": ("积存金", "银行积存金", "bank gold", "account gold")},
    {"symbol": "ICBC_GOLD", "name": "工商银行积存金", "short_name": "工行积存金", "market": "other", "asset_type": "bank_gold", "aliases": ("工行积存金", "工商银行积存金", "icbc gold")},
    {"symbol": "CMB_GOLD", "name": "招商银行积存金", "short_name": "招行积存金", "market": "other", "asset_type": "bank_gold", "aliases": ("招行积存金", "招商银行积存金", "cmb gold")},
    {"symbol": "CCB_GOLD", "name": "建设银行积存金", "short_name": "建行积存金", "market": "other", "asset_type": "bank_gold", "aliases": ("建行积存金", "建设银行积存金", "ccb gold")},
]


def _portfolio_instrument_search(query: str) -> list[dict[str, Any]]:
    """Search ledger instruments across stocks, ETFs, and manually tracked assets."""
    normalized = query.strip().lower()
    if not normalized:
        return []

    commodity_matches = []
    for item in _COMMODITY_INSTRUMENTS:
        haystack = (item["symbol"], item["name"], item["short_name"], *item["aliases"])
        if any(normalized in value.lower() for value in haystack):
            commodity_matches.append({key: value for key, value in item.items() if key != "aliases"})

    results: list[dict[str, Any]] = commodity_matches
    from src.api.market_routes import _search_market_symbols

    for market in ("a_share", "us"):
        try:
            candidates = _search_market_symbols(query.strip(), market)
        except Exception:
            candidates = []
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "").upper()
            if not symbol:
                continue
            results.append({
                "symbol": symbol,
                "name": str(candidate.get("name") or symbol),
                "short_name": str(candidate.get("short_name") or candidate.get("name") or symbol),
                "market": market,
                "asset_type": "etf" if "ETF" in str(candidate.get("name") or "").upper() else "equity",
            })

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        key = (str(item["market"]), str(item["symbol"]).upper())
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:15]


def _fetch_quotes(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Use the existing market sources without making quotes mandatory."""
    from src.a_share_data import tencent_quote
    from src.api.market_routes import _fetch_us_snapshots

    a_symbols = [item["symbol"] for item in holdings if item["market"] == "a_share"]
    us_symbols = [item["symbol"] for item in holdings if item["market"] == "us"]
    commodity_items = [item for item in holdings if item["market"] == "commodity"]
    instrument_names = {item["symbol"]: item["name"] for item in _COMMODITY_INSTRUMENTS}
    result: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc).isoformat()
    try:
        a_quotes = tencent_quote(a_symbols) if a_symbols else {}
    except Exception:
        a_quotes = {}
    for symbol in a_symbols:
        raw = a_quotes.get(symbol) or {}
        result[_quote_key("a_share", symbol)] = {
            "name": raw.get("name") or symbol,
            "price": raw.get("price"),
            "change_pct": raw.get("change_pct"),
            "status": "ok" if raw.get("price") is not None else "unavailable",
            "source": "tencent",
            "updated_at": now,
        }
    try:
        us_quotes = _fetch_us_snapshots(us_symbols) if us_symbols else {}
    except Exception:
        us_quotes = {}
    for symbol in us_symbols:
        price, change_pct, source = us_quotes.get(symbol, (None, None, "yfinance"))
        result[_quote_key("us", symbol)] = {
            "name": symbol.removesuffix(".US"),
            "price": price,
            "change_pct": change_pct,
            "status": "ok" if price is not None else "unavailable",
            "source": source,
            "updated_at": now,
        }
    commodity_quote_symbols = list(dict.fromkeys(str(item.get("quote_symbol") or item["symbol"]) for item in commodity_items))
    try:
        commodity_quotes = _fetch_us_snapshots(commodity_quote_symbols) if commodity_quote_symbols else {}
    except Exception:
        commodity_quotes = {}
    for item in commodity_items:
        symbol = item["symbol"]
        quote_symbol = str(item.get("quote_symbol") or symbol)
        price, change_pct, source = commodity_quotes.get(quote_symbol, (None, None, "yfinance"))
        result[_quote_key("commodity", symbol)] = {
            "name": item.get("name") or instrument_names.get(symbol) or symbol,
            "price": price,
            "change_pct": change_pct,
            "status": "ok" if price is not None else "unavailable",
            "source": source,
            "updated_at": now,
        }
    return result


def _position_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("positions") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or row.get("instrument") or "").strip().upper()
        quantity = row.get("quantity", row.get("qty", row.get("shares", row.get("size"))))
        if not symbol or quantity is None:
            continue
        try:
            quantity_d = Decimal(str(quantity))
        except Exception:
            continue
        if quantity_d == 0:
            continue
        market = str(row.get("market") or row.get("asset_class") or "").lower()
        if market not in {"a_share", "us"}:
            market = "us" if ".US" in symbol or symbol.isalpha() else "a_share"
        normalized.append({
            "symbol": symbol,
            "market": market,
            "quantity": format(quantity_d, "f"),
            "avg_cost": row.get("avg_cost", row.get("average_price", row.get("entry_price"))),
            "market_value": row.get("market_value", row.get("marketValue")),
            "status": "observed",
        })
    return normalized


def register_portfolio_routes(app: FastAPI) -> None:
    @app.get("/portfolio/portfolios", dependencies=[Depends(require_auth)])
    def list_portfolios(principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        return {"items": [_portfolio_dict(item) for item in _store().list_portfolios(_scope(principal))]}

    @app.post("/portfolio/portfolios", dependencies=[Depends(require_auth)])
    def create_portfolio(payload: PortfolioCreateRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return _portfolio_dict(_store().create_portfolio(_scope(principal), payload.name, payload.base_currency))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/portfolio/portfolios/{portfolio_id}", dependencies=[Depends(require_auth)])
    def update_portfolio(portfolio_id: str, payload: PortfolioUpdateRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return _portfolio_dict(_store().update_portfolio(_scope(principal), portfolio_id, name=payload.name, archived=payload.archived))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/portfolio/instruments/search", dependencies=[Depends(require_auth)])
    def search_portfolio_instruments(query: str = Query(..., min_length=1, max_length=80), principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        del principal
        return {"items": _portfolio_instrument_search(query)}

    @app.get("/portfolio/{portfolio_id}/transactions", dependencies=[Depends(require_auth)])
    def list_transactions(portfolio_id: str, symbol: str | None = None, type: str | None = None, start_date: str | None = None, end_date: str | None = None, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            items = _store().list_transactions(_scope(principal), portfolio_id, symbol=symbol, type=type, start_date=start_date, end_date=end_date)
            return {"items": [item.to_dict() for item in items]}
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404 if isinstance(exc, KeyError) else 400, detail=str(exc)) from exc

    @app.post("/portfolio/{portfolio_id}/transactions", dependencies=[Depends(require_auth)])
    def add_transaction(portfolio_id: str, payload: TransactionRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            item = _store().add_transaction(_scope(principal), portfolio_id, payload.model_dump())
            return item.to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/portfolio/{portfolio_id}/prices", dependencies=[Depends(require_auth)])
    def save_portfolio_price(portfolio_id: str, payload: PriceOverrideRequest, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return _store().save_price_override(
                _scope(principal), portfolio_id, symbol=payload.symbol, market=payload.market,
                currency=payload.currency, price=payload.price,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/portfolio/{portfolio_id}/transactions/{transaction_id}/reverse", dependencies=[Depends(require_auth)])
    def reverse_transaction(portfolio_id: str, transaction_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return _store().reverse_transaction(_scope(principal), portfolio_id, transaction_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/portfolio/{portfolio_id}/snapshot", dependencies=[Depends(require_auth)])
    def portfolio_snapshot(portfolio_id: str, principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        store = _store()
        try:
            transactions = store.all_transactions(_scope(principal), portfolio_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        symbols = {(tx.market, tx.symbol, tx.currency, tx.asset_type) for tx in transactions if tx.symbol and tx.market and tx.type in {"buy", "adjustment"}}
        seed = [{"market": market, "symbol": symbol, "asset_type": asset_type, "quote_symbol": "GC=F" if market == "commodity" and symbol in {"XAUUSD", "XAU", "GOLD"} else symbol} for market, symbol, _currency, asset_type in symbols]
        quotes = _fetch_quotes(seed)
        override_maps = []
        if portfolio_id != "all":
            override_maps.append(store.list_price_overrides(_scope(principal), portfolio_id))
        else:
            override_maps.extend(
                store.list_price_overrides(_scope(principal), item.id)
                for item in store.list_portfolios(_scope(principal))
            )
        for overrides in override_maps:
            for key, override in overrides.items():
                market, symbol, _currency = key.split(":", 2)
                quote = dict(quotes.get(f"{market}:{symbol}:{override['currency'].upper()}") or quotes.get(f"{market}:{symbol}") or {})
                quote.update({"price": override["price"], "status": "manual", "source": "manual", "updated_at": override["updated_at"]})
                quotes[f"{market}:{symbol}:{override['currency'].upper()}"] = quote
        snapshot = calculate_snapshot(transactions, quotes)
        snapshot["portfolio_id"] = portfolio_id
        snapshot["portfolio"] = None if portfolio_id == "all" else _portfolio_dict(store.get_portfolio(_scope(principal), portfolio_id))
        return snapshot

    @app.get("/portfolio/{portfolio_id}/reconciliation", dependencies=[Depends(require_auth)])
    def portfolio_reconciliation(portfolio_id: str, broker_profile_id: str | None = Query(None), principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        try:
            return _store().latest_reconciliation(_scope(principal), portfolio_id, broker_profile_id) or {"items": []}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/portfolio/{portfolio_id}/reconciliation/refresh", dependencies=[Depends(require_auth)])
    def refresh_reconciliation(portfolio_id: str, broker_profile_id: str = Query(..., min_length=1, max_length=100), principal: Principal = Depends(require_auth)) -> dict[str, Any]:
        store = _store()
        try:
            store.get_portfolio(_scope(principal), portfolio_id)
            payload = get_positions(profile_id=broker_profile_id)
            rows = _position_rows(payload)
            return store.save_reconciliation(_scope(principal), portfolio_id, broker_profile_id, rows)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"broker positions unavailable: {exc}") from exc
