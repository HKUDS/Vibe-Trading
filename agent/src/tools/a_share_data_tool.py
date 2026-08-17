"""Read-only A-share data surface backed by the a-stock-data adapters."""

from __future__ import annotations

import json
import math
from typing import Any

from src.agent.tools import BaseTool
from src.a_share_data import (
    canonical_a_share_code,
    cninfo_announcements,
    eastmoney_global_news,
    eastmoney_reports,
    eastmoney_stock_info,
    eastmoney_stock_news,
    cls_telegraph,
    sina_financial_report,
    ths_eps_forecast,
    tencent_bars,
    tencent_quote,
)


_MAX_LIMIT = 50


def _limit(value: Any, default: int = 20) -> int:
    try:
        return max(1, min(int(value), _MAX_LIMIT))
    except (TypeError, ValueError, OverflowError):
        return default


def _json_safe(value: Any) -> Any:
    """Convert provider values, including pandas NaN, to strict JSON values."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _success(operation: str, data: Any, source: str = "a-stock-data") -> str:
    return json.dumps(
        {
            "ok": True,
            "market": "a_share",
            "source": source,
            "operation": operation,
            "data": _json_safe(data),
        },
        ensure_ascii=False,
        allow_nan=False,
    )


def _error(operation: str, message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "market": "a_share",
            "source": "a-stock-data",
            "operation": operation,
            "error": message,
        },
        ensure_ascii=False,
    )


class AShareDataTool(BaseTool):
    """Fetch A-share quotes, bars, reports, news, fundamentals, and notices."""

    name = "get_a_share_data"
    description = (
        "Read-only mainland A-share data using the a-stock-data provider adapters. "
        "Operations: quote (Tencent snapshot and valuation), bars (Tencent qfq daily "
        "OHLCV), reports (Eastmoney broker reports plus THS consensus), news (Eastmoney "
        "stock news or CLS/Eastmoney global flash news), fundamentals (Eastmoney profile "
        "or Sina statements), and announcements (CNINFO). This tool is additive; use "
        "get_market_data, get_research_reports, get_stock_news, or get_financial_statements "
        "for their existing compatible behavior."
    )
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["quote", "bars", "reports", "news", "fundamentals", "announcements"],
            },
            "code": {
                "type": "string",
                "description": "A-share code such as 600519.SH, SH600519, or 600519.",
            },
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional batch of codes for quote; code is also accepted for one quote.",
            },
            "start_date": {"type": "string", "description": "Bars start date, YYYY-MM-DD."},
            "end_date": {"type": "string", "description": "Bars end date, YYYY-MM-DD."},
            "statement": {
                "type": "string",
                "enum": ["profile", "income", "balance", "cashflow", "all"],
                "default": "profile",
            },
            "scope": {"type": "string", "enum": ["stock", "global"], "default": "stock"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["operation"],
    }

    def execute(self, **kwargs: Any) -> str:
        operation = str(kwargs.get("operation") or "").strip().lower()
        if operation not in {"quote", "bars", "reports", "news", "fundamentals", "announcements"}:
            return _error(operation, "operation must be quote, bars, reports, news, fundamentals, or announcements")

        try:
            if operation == "quote":
                raw_codes = kwargs.get("codes") or ([kwargs.get("code")] if kwargs.get("code") else [])
                if not isinstance(raw_codes, list) or not raw_codes:
                    return _error(operation, "code or codes is required")
                codes = [canonical_a_share_code(str(item)) for item in raw_codes]
                return _success(operation, {"quotes": tencent_quote(codes)})

            if operation == "news" and str(kwargs.get("scope") or "stock").strip().lower() == "global":
                limit = _limit(kwargs.get("limit"))
                feeds: dict[str, Any] = {}
                errors: dict[str, str] = {}
                for name, fetch in (("cls", cls_telegraph), ("eastmoney", eastmoney_global_news)):
                    try:
                        feeds[name] = fetch(limit=limit)
                    except Exception as exc:
                        errors[name] = str(exc)
                if errors:
                    feeds["errors"] = errors
                return _success(operation, {"scope": "global", "feeds": feeds}, "a-stock-data:cls+eastmoney")

            code = kwargs.get("code")
            if not isinstance(code, str) or not code.strip():
                return _error(operation, "code is required")
            canonical = canonical_a_share_code(code, stock_only=True)
            limit = _limit(kwargs.get("limit"))

            if operation == "bars":
                start_date = kwargs.get("start_date")
                end_date = kwargs.get("end_date")
                if not isinstance(start_date, str) or not isinstance(end_date, str):
                    return _error(operation, "start_date and end_date are required")
                return _success(operation, {
                    "code": canonical,
                    "adjustment": "qfq",
                    "bars": tencent_bars(canonical, start_date, end_date),
                })

            if operation == "reports":
                report_error = None
                try:
                    reports = eastmoney_reports(canonical, limit=limit)
                except Exception as exc:  # keep THS consensus usable when Eastmoney is unavailable
                    reports = []
                    report_error = str(exc)
                try:
                    consensus = ths_eps_forecast(canonical)
                except Exception as exc:  # consensus is deliberately best-effort
                    consensus = []
                    consensus_error = str(exc)
                else:
                    consensus_error = None
                data: dict[str, Any] = {"code": canonical, "reports": reports, "consensus_eps": consensus}
                if report_error:
                    data["reports_error"] = report_error
                if consensus_error:
                    data["consensus_error"] = consensus_error
                if report_error and consensus_error:
                    return _error(operation, f"research feeds unavailable: {report_error}; {consensus_error}")
                return _success(operation, data, "a-stock-data:eastmoney+ths")

            if operation == "news":
                scope = str(kwargs.get("scope") or "stock").strip().lower()
                if scope == "stock":
                    return _success(operation, {"code": canonical, "items": eastmoney_stock_news(canonical, limit=limit)})
                return _error(operation, "scope must be stock or global")

            if operation == "fundamentals":
                statement = str(kwargs.get("statement") or "profile").strip().lower()
                if statement == "profile":
                    try:
                        profile = eastmoney_stock_info(canonical)
                        source = "a-stock-data:eastmoney"
                    except Exception as exc:
                        quote = tencent_quote([canonical]).get(canonical)
                        if not quote:
                            raise RuntimeError(f"profile feeds unavailable: {exc}") from exc
                        profile = {"code": canonical, "quote_fallback": quote, "profile_error": str(exc)}
                        source = "a-stock-data:tencent-fallback"
                    return _success(operation, {"code": canonical, "profile": profile}, source)
                if statement in {"income", "balance", "cashflow"}:
                    return _success(operation, {
                        "code": canonical,
                        "statement": statement,
                        "rows": sina_financial_report(canonical, statement=statement, limit=limit),
                    })
                if statement == "all":
                    result: dict[str, Any] = {"code": canonical, "profile": eastmoney_stock_info(canonical)}
                    for name in ("income", "balance", "cashflow"):
                        try:
                            result[name] = sina_financial_report(canonical, statement=name, limit=limit)
                        except Exception as exc:
                            result[name] = {"error": str(exc)}
                    return _success(operation, result)
                return _error(operation, "statement must be profile, income, balance, cashflow, or all")

            return _success(operation, {"code": canonical, "items": cninfo_announcements(canonical, limit=limit)})
        except Exception as exc:  # provider failures stay inside a valid tool envelope
            return _error(operation, str(exc))
