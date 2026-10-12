"""Read-only tool: official Brazilian market data from the local store.

Serves what ``python -m src.br_data sync`` downloaded from B3 (COTAHIST),
CVM (funds, companies, financial statements), Banco Central (SGS) and
Tesouro Transparente. Everything is local SQLite, so calls are fast and
never rate-limited. BCB series that were not synced are fetched live.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT

_DEFAULT_LIMIT = 250
_MAX_LIMIT = 5000

# Friendly names for common SGS series.
_BCB_ALIASES = {
    "selic": 11, "selic_meta": 432, "cdi": 12, "cdi_anual": 4389,
    "ipca": 433, "ipca_12m": 13522, "igpm": 189, "inpc": 188,
    "dolar": 1, "usd": 1, "ptax": 1, "euro": 21619, "pib": 4380, "desemprego": 24369,
}
_STATEMENTS = ("BPA", "BPP", "DRE", "DRA", "DFC_MD", "DFC_MI", "DVA", "DMPL")


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text[:-3] if text.endswith(".SA") else text


def _limit(value: Any) -> int:
    try:
        return max(1, min(int(value), _MAX_LIMIT))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _dates(kwargs: dict) -> tuple[str, str]:
    end = str(kwargs.get("end_date") or datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat())[:10]
    start = str(kwargs.get("start_date") or (date.fromisoformat(end) - timedelta(days=365)).isoformat())[:10]
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("start_date must not be after end_date")
    return start, end


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _envelope(action: str, rows: list[dict], extra: dict | None = None) -> str:
    """Return the newest rows that fit the result budget."""
    count = len(rows)
    while True:
        data = {"action": action, "count": count, "available": len(rows),
                "truncated": count < len(rows), "rows": rows[-count:] if count else []}
        if extra:
            data.update(extra)
        text = json.dumps({"ok": True, "market": "BR", "source": "br_data", "data": data},
                          ensure_ascii=False, default=str)
        if len(text) <= TOOL_RESULT_LIMIT:
            return text
        if count <= 1:
            return _error("Result metadata exceeds the tool limit; narrow the query.")
        count = max(1, min(count - 1, int(count * TOOL_RESULT_LIMIT / len(text))))


class BrMarketDataTool(BaseTool):
    """Brazilian official data: B3 quotes, CVM funds/companies, BCB, Tesouro."""

    name = "get_br_market_data"
    description = (
        "Official, free Brazilian market data from the local store synced from "
        "B3, CVM, Banco Central and Tesouro Direto. Actions: "
        "'quotes' (daily B3 bars for any listed instrument — shares, FIIs, ETFs, "
        "BDRs, options — e.g. tickers=['PETR4','HGLG11']; prices are as traded, "
        "not adjusted); 'search' (find tickers, funds or companies by name); "
        "'fund' (daily quota, net assets, flows and holders of any CVM fund by "
        "CNPJ); 'financials' (DFP annual / ITR quarterly statements of a listed "
        "company by ticker or CNPJ: DRE, BPA, BPP, DFC_MI ...); 'macro' (BCB "
        "SGS series: selic, cdi, ipca, igpm, ptax or a numeric code); "
        "'tesouro' (Tesouro Direto prices and yields); 'status' (what is synced). "
        'Example: {"action": "fund", "cnpj": "00.017.024/0001-53", '
        '"start_date": "2025-01-01"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["quotes", "search", "fund", "financials", "macro", "tesouro", "status"],
            },
            "tickers": {
                "type": "array", "items": {"type": "string"},
                "description": "B3 tickers for 'quotes' (PETR4 or PETR4.SA), or one ticker for 'financials'.",
            },
            "query": {"type": "string", "description": "Name fragment for 'search' or bond name for 'tesouro'."},
            "cnpj": {"type": "string", "description": "Fund CNPJ ('fund') or company CNPJ ('financials')."},
            "statement": {"type": "string", "enum": list(_STATEMENTS), "description": "Statement for 'financials' (default DRE)."},
            "doc": {"type": "string", "enum": ["DFP", "ITR"], "description": "DFP annual (default) or ITR quarterly."},
            "series": {"type": "string", "description": "BCB alias (selic, cdi, ipca, igpm, ptax, dolar, euro) or SGS code."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD (default: one year before end_date)."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD (default: today)."},
            "limit": {"type": "integer", "description": f"Max rows (1-{_MAX_LIMIT}, default {_DEFAULT_LIMIT}); newest kept."},
        },
        "required": ["action"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip().lower()
        handlers: dict[str, Callable[[sqlite3.Connection, dict], str]] = {
            "quotes": self._quotes, "search": self._search, "fund": self._fund,
            "financials": self._financials, "macro": self._macro,
            "tesouro": self._tesouro, "status": self._status,
        }
        handler = handlers.get(action)
        if handler is None:
            return _error(f"unknown action {action!r}; use one of {sorted(handlers)}")
        from src.br_data.store import connect

        try:
            with connect() as conn:
                return handler(conn, kwargs)
        except FileNotFoundError as exc:
            if action == "macro":
                return self._macro(None, kwargs)
            return _error(str(exc))
        except (ValueError, TypeError) as exc:
            return _error(f"invalid request: {exc}")
        except sqlite3.Error as exc:
            return _error(f"store query failed: {exc}")

    # -- actions -----------------------------------------------------------

    def _quotes(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        tickers = [_ticker(t) for t in (kwargs.get("tickers") or []) if _ticker(t)]
        if not tickers:
            return _error("'tickers' is required for action 'quotes'")
        start, end = _dates(kwargs)
        marks = ",".join("?" for _ in tickers)
        rows = conn.execute(
            "SELECT trade_date, ticker, market_type, spec, open, high, low, close, avg, "
            "volume, turnover, trades, strike, expiry FROM b3_quotes "
            f"WHERE ticker IN ({marks}) AND trade_date BETWEEN ? AND ? ORDER BY trade_date DESC, ticker DESC LIMIT ?",
            (*tickers, start, end, _limit(kwargs.get("limit"))),
        ).fetchall()
        out = [dict(r) for r in reversed(rows)]
        return _envelope("quotes", out, {"adjustment": "raw (as traded)", "currency": "BRL"})

    def _search(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        query = str(kwargs.get("query") or "").strip()
        if len(query) < 2:
            return _error("'query' (2+ characters) is required for action 'search'")
        like = f"%{query.upper()}%"
        limit = min(_limit(kwargs.get("limit")), 50)
        tickers = conn.execute(
            "SELECT ticker, short_name, spec, MAX(trade_date) AS last_trade FROM b3_quotes "
            "WHERE market_type = 10 AND (ticker LIKE ? OR UPPER(short_name) LIKE ?) "
            "AND trade_date >= (SELECT date(MAX(trade_date), '-90 day') FROM b3_quotes) "
            "GROUP BY ticker ORDER BY ticker LIMIT ?",
            (like, like, limit),
        ).fetchall()
        funds = conn.execute(
            "SELECT cnpj, name, fund_type, fund_class, status FROM cvm_funds "
            "WHERE UPPER(name) LIKE ? OR cnpj LIKE ? ORDER BY (status LIKE 'EM FUNCIONAMENTO%') DESC, name LIMIT ?",
            (like, f"%{_digits(query) or '#'}%", limit),
        ).fetchall()
        companies = conn.execute(
            "SELECT c.cnpj, c.name, c.trade_name, c.sector, c.status, "
            "GROUP_CONCAT(t.ticker) AS tickers FROM cvm_companies c "
            "LEFT JOIN cvm_company_tickers t ON t.cnpj = c.cnpj "
            "WHERE UPPER(c.name) LIKE ? OR UPPER(c.trade_name) LIKE ? OR t.ticker LIKE ? "
            "GROUP BY c.cnpj LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return _envelope("search", [], {
            "tickers": [dict(r) for r in tickers],
            "funds": [dict(r) for r in funds],
            "companies": [dict(r) for r in companies],
        })

    def _fund(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        cnpj = _digits(kwargs.get("cnpj"))
        if len(cnpj) != 14:
            return _error("'cnpj' (14 digits) is required for action 'fund'; use action 'search' to find it")
        start, end = _dates(kwargs)
        info = conn.execute("SELECT * FROM cvm_funds WHERE cnpj = ?", (cnpj,)).fetchone()
        rows = conn.execute(
            "SELECT trade_date, subclass, quota, net_assets, total_value, inflows, outflows, holders "
            "FROM cvm_fund_daily WHERE cnpj = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date DESC, subclass DESC LIMIT ?",
            (cnpj, start, end, _limit(kwargs.get("limit"))),
        ).fetchall()
        out = [dict(r) for r in reversed(rows)]
        extra: dict[str, Any] = {"fund": dict(info) if info else None, "currency": "BRL"}
        if len({r["subclass"] for r in out}) == 1 and len(out) >= 2 and out[0]["quota"] and out[-1]["quota"]:
            extra["quota_return"] = round(out[-1]["quota"] / out[0]["quota"] - 1, 6)
        return _envelope("fund", out, extra)

    def _financials(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        cnpj = _digits(kwargs.get("cnpj"))
        tickers = kwargs.get("tickers") or []
        if not cnpj and tickers:
            ticker = _ticker(tickers[0])
            row = conn.execute("SELECT cnpj FROM cvm_company_tickers WHERE ticker = ?", (ticker,)).fetchone()
            if row is None:
                return _error(f"no CVM company mapped to ticker {ticker}; try action 'search'")
            cnpj = row["cnpj"]
        if len(cnpj) != 14:
            return _error("'cnpj' or one entry in 'tickers' is required for action 'financials'")
        statement = str(kwargs.get("statement") or "DRE").upper()
        doc = str(kwargs.get("doc") or "DFP").upper()
        rows = conn.execute(
            "SELECT statement, period_end, period_start, account, description, value, version FROM cvm_statements "
            "WHERE cnpj = ? AND doc = ? AND statement IN (?, ?) ORDER BY period_end, account",
            (cnpj, doc, statement, f"{statement}_ind"),
        ).fetchall()
        periods = sorted({r["period_end"] for r in rows})
        keep = set(periods[-min(_limit(kwargs.get("limit")), 8 if doc == "DFP" else 12):])
        out = [dict(r) for r in rows if r["period_end"] in keep]
        company = conn.execute("SELECT * FROM cvm_companies WHERE cnpj = ?", (cnpj,)).fetchone()
        return _envelope("financials", out, {
            "company": dict(company) if company else {"cnpj": cnpj},
            "doc": doc, "statement": statement, "currency": "BRL", "periods": sorted(keep),
            "point_in_time": False, "basis": "latest stored restatement; scope is labelled per row",
        })

    def _macro(self, conn: sqlite3.Connection | None, kwargs: dict) -> str:
        raw = str(kwargs.get("series") or "").strip().lower()
        code = _BCB_ALIASES.get(raw) or (int(raw) if raw.isdigit() else None)
        if code is None:
            return _error(f"'series' must be a BCB SGS code or one of {sorted(_BCB_ALIASES)}")
        start, end = _dates(kwargs)
        rows: list[dict] = []
        if conn is not None:
            rows = [dict(r) for r in conn.execute(
                "SELECT obs_date AS date, value FROM bcb_series WHERE code = ? "
                "AND obs_date BETWEEN ? AND ? ORDER BY obs_date", (code, start, end),
            ).fetchall()]
        if not rows:
            from src.br_data.bcb import fetch_series

            try:
                rows = [{"date": d, "value": v} for d, v in
                        fetch_series(code, date.fromisoformat(start), date.fromisoformat(end))]
            except Exception as exc:  # noqa: BLE001 - surface as envelope
                return _error(f"BCB SGS request failed: {exc}")
        from src.br_data.bcb import SERIES

        return _envelope("macro", rows[-_limit(kwargs.get("limit")):],
                         {"series": code, "name": SERIES.get(code)})

    def _tesouro(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        start, end = _dates(kwargs)
        query = f"%{str(kwargs.get('query') or '').upper()}%"
        rows = conn.execute(
            "SELECT base_date, bond, maturity, buy_rate, sell_rate, buy_price, sell_price "
            "FROM tesouro_prices WHERE UPPER(bond) LIKE ? AND base_date BETWEEN ? AND ? "
            "ORDER BY base_date DESC, bond DESC, maturity DESC LIMIT ?", (query, start, end, _limit(kwargs.get("limit"))),
        ).fetchall()
        return _envelope("tesouro", [dict(r) for r in reversed(rows)], {"currency": "BRL"})

    def _status(self, conn: sqlite3.Connection, kwargs: dict) -> str:
        out = []
        for table, col in (("b3_quotes", "trade_date"), ("cvm_fund_daily", "trade_date"),
                           ("cvm_statements", "period_end"), ("bcb_series", "obs_date"),
                           ("tesouro_prices", "base_date")):
            row = conn.execute(f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {table}").fetchone()
            out.append({"table": table, "rows": row[0], "from": row[1], "to": row[2]})
        return _envelope("status", out)
