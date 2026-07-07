"""Read-only FXMacroData research tools.

These tools expose the wider FXMacroData product surface to the agent while the
``fxmacrodata`` backtest loader stays focused on numeric historical series.
Credentials are read from ``FXMD_API_KEY`` at call time by the shared client and
sent as ``X-API-Key`` only; secrets are never returned in tool output.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from backtest.loaders import fxmacrodata_client as fxmd
from src.agent.tools import BaseTool

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _limit(value: Any, default: int = _DEFAULT_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, _MAX_LIMIT))


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _json_response(endpoint: str, fetch: Callable[[], Any]) -> str:
    try:
        payload = fetch()
    except Exception as exc:  # noqa: BLE001 - tool calls return error envelopes
        return json.dumps(
            {
                "ok": False,
                "source": "fxmacrodata",
                "endpoint": endpoint,
                "error": str(exc),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "source": "fxmacrodata",
            "endpoint": endpoint,
            "data": payload,
        },
        ensure_ascii=False,
    )


class FXMacroDataCatalogueTool(BaseTool):
    """Fetch available FXMacroData indicators and coverage for one currency."""

    name = "get_fxmacrodata_catalogue"
    description = (
        "Fetch FXMacroData's available macro indicator catalogue and coverage "
        "metadata for a currency. Use this before requesting a specific "
        "indicator when you need exact availability."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {
                "type": "string",
                "description": "3-letter currency code, e.g. USD, EUR, JPY.",
            },
            "include_coverage": {
                "type": "boolean",
                "description": "Include per-indicator coverage metadata.",
                "default": True,
            },
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        include_coverage = bool(kwargs.get("include_coverage", True))
        return _json_response(
            f"/data_catalogue/{currency.lower()}",
            lambda: fxmd.data_catalogue(currency, include_coverage=include_coverage),
        )


class FXMacroDataIndicatorTool(BaseTool):
    """Fetch one FXMacroData macroeconomic indicator series."""

    name = "get_fxmacrodata_indicator"
    description = (
        "Fetch a standardized FXMacroData macroeconomic indicator series such "
        "as inflation, unemployment, GDP, policy_rate, retail_sales, trade_balance, "
        "or gov_bond_10y for a currency."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency code."},
            "indicator": {"type": "string", "description": "Indicator slug."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
            "seasonality": {"type": "string", "description": "Optional sa or nsa."},
            "frequency": {"type": "string", "description": "Optional level/yoy/qoq/mom."},
            "revisions": {"type": "string", "description": "Optional latest/first/final/all."},
            "basis": {"type": "string", "description": "Optional real or nominal."},
        },
        "required": ["currency", "indicator"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        indicator = (_clean(kwargs.get("indicator")) or "").lower()
        if not currency or not indicator:
            return _error("currency and indicator are required")
        return _json_response(
            f"/announcements/{currency.lower()}/{indicator}",
            lambda: fxmd.indicator(
                currency,
                indicator,
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                limit=_limit(kwargs.get("limit")),
                seasonality=_clean(kwargs.get("seasonality")),
                frequency=_clean(kwargs.get("frequency")),
                revisions=_clean(kwargs.get("revisions")),
                basis=_clean(kwargs.get("basis")),
            ),
        )


class FXMacroDataCalendarTool(BaseTool):
    """Fetch FXMacroData release-calendar rows."""

    name = "get_fxmacrodata_release_calendar"
    description = (
        "Fetch FXMacroData economic release-calendar rows for a currency, "
        "optionally filtered by indicator and date window."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency code."},
            "indicator": {"type": "string", "description": "Optional indicator slug."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "timezone": {"type": "string", "description": "Optional display timezone."},
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        return _json_response(
            f"/calendar/{currency.lower()}",
            lambda: fxmd.calendar(
                currency,
                indicator=_clean(kwargs.get("indicator")),
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                timezone=_clean(kwargs.get("timezone")),
            ),
        )


class FXMacroDataPredictionsTool(BaseTool):
    """Fetch FXMacroData forecast, nowcast, and consensus rows."""

    name = "get_fxmacrodata_predictions"
    description = (
        "Fetch FXMacroData prediction rows for a currency or one indicator, "
        "including market consensus, surveys, central-bank forecasts, IMF WEO, "
        "nowcasts, and FXMacroData forecasts when available."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency code."},
            "indicator": {"type": "string", "description": "Optional indicator slug."},
            "prediction_type": {"type": "string", "description": "Optional forecast type."},
            "prediction_source": {"type": "string", "description": "Optional source id."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        indicator = _clean(kwargs.get("indicator"))
        return _json_response(
            f"/predictions/{currency.lower()}",
            lambda: fxmd.predictions(
                currency,
                indicator_slug=indicator.lower() if indicator else None,
                prediction_type=_clean(kwargs.get("prediction_type")),
                prediction_source=_clean(kwargs.get("prediction_source")),
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                limit=_limit(kwargs.get("limit")),
            ),
        )


class FXMacroDataCOTTool(BaseTool):
    """Fetch FXMacroData CFTC COT positioning rows."""

    name = "get_fxmacrodata_cot"
    description = "Fetch weekly CFTC Commitment of Traders positioning data from FXMacroData."
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency or XAU."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        return _json_response(
            f"/cot/{currency.lower()}",
            lambda: fxmd.cot(
                currency,
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                limit=_limit(kwargs.get("limit")),
            ),
        )


class FXMacroDataCommoditiesTool(BaseTool):
    """Fetch latest or historical FXMacroData commodity rows."""

    name = "get_fxmacrodata_commodities"
    description = (
        "Fetch FXMacroData commodity data. Omit indicator for latest values or "
        "use gold, silver, platinum, oil_wti, oil_brent, or natural_gas."
    )
    parameters = {
        "type": "object",
        "properties": {
            "indicator": {"type": "string", "description": "Optional commodity slug."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
        },
    }

    def execute(self, **kwargs: Any) -> str:
        indicator = _clean(kwargs.get("indicator"))
        endpoint = f"/commodities/{indicator}" if indicator else "/commodities/latest"
        return _json_response(
            endpoint,
            lambda: fxmd.commodities(
                indicator.lower() if indicator else None,
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                limit=_limit(kwargs.get("limit")),
            ),
        )


class FXMacroDataRatesTool(BaseTool):
    """Fetch rate and forward-rate differentials from FXMacroData."""

    name = "get_fxmacrodata_rate_differentials"
    description = (
        "Fetch FXMacroData historical rate differentials or forward-rate "
        "differentials for a currency pair."
    )
    parameters = {
        "type": "object",
        "properties": {
            "base": {"type": "string", "description": "Base currency."},
            "quote": {"type": "string", "description": "Quote currency."},
            "forward": {"type": "boolean", "description": "Use forward differentials.", "default": False},
            "measure": {"type": "string", "description": "auto, risk_free_rate, gov_bond_2y, gov_bond_10y, or policy_rate."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
        },
        "required": ["base", "quote"],
    }

    def execute(self, **kwargs: Any) -> str:
        base = (_clean(kwargs.get("base")) or "").upper()
        quote = (_clean(kwargs.get("quote")) or "").upper()
        if not base or not quote:
            return _error("base and quote are required")
        forward = bool(kwargs.get("forward", False))
        endpoint = (
            f"/forward_differentials/{base.lower()}/{quote.lower()}"
            if forward
            else f"/rate_differentials/{base.lower()}/{quote.lower()}"
        )
        return _json_response(
            endpoint,
            lambda: (
                fxmd.forward_differentials(
                    base,
                    quote,
                    start_date=_clean(kwargs.get("start_date")),
                    end_date=_clean(kwargs.get("end_date")),
                    limit=_limit(kwargs.get("limit")),
                )
                if forward
                else fxmd.rate_differentials(
                    base,
                    quote,
                    measure=_clean(kwargs.get("measure")),
                    start_date=_clean(kwargs.get("start_date")),
                    end_date=_clean(kwargs.get("end_date")),
                    limit=_limit(kwargs.get("limit")),
                )
            ),
        )


class FXMacroDataCurvesTool(BaseTool):
    """Fetch curve nodes, curve proxies, or forward curves."""

    name = "get_fxmacrodata_curves"
    description = (
        "Fetch FXMacroData official-source curve nodes, curve slope proxies, "
        "or derived forward curves for a currency."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency code."},
            "kind": {
                "type": "string",
                "description": "curves, curve_proxies, or forward_curves.",
                "default": "curves",
            },
            "curve_family": {"type": "string", "description": "Optional curve family."},
            "metric": {"type": "string", "description": "Optional curve metric."},
            "method": {"type": "string", "description": "Optional forward-curve method."},
            "date": {"type": "string", "description": "Optional YYYY-MM-DD date."},
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        kind = _clean(kwargs.get("kind")) or "curves"
        return _json_response(
            f"/{kind}/{currency.lower()}",
            lambda: fxmd.curves(
                currency,
                kind=kind,
                curve_family=_clean(kwargs.get("curve_family")),
                metric=_clean(kwargs.get("metric")),
                method=_clean(kwargs.get("method")),
                date=_clean(kwargs.get("date")),
            ),
        )


class FXMacroDataNewsTool(BaseTool):
    """Fetch central-bank news or press releases from FXMacroData."""

    name = "get_fxmacrodata_news"
    description = (
        "Fetch recent official central-bank news or press releases from FXMacroData."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {"type": "string", "description": "3-letter currency code."},
            "press_releases_only": {
                "type": "boolean",
                "description": "Use the press-releases endpoint instead of news.",
                "default": False,
            },
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
            "offset": {"type": "integer", "description": "Pagination offset.", "default": 0},
        },
        "required": ["currency"],
    }

    def execute(self, **kwargs: Any) -> str:
        currency = (_clean(kwargs.get("currency")) or "").upper()
        if not currency:
            return _error("currency is required")
        press = bool(kwargs.get("press_releases_only", False))
        endpoint = "/press-releases" if press else "/news"
        return _json_response(
            f"{endpoint}/{currency.lower()}",
            lambda: fxmd.central_bank_news(
                currency,
                press_releases_only=press,
                limit=_limit(kwargs.get("limit")),
                offset=int(kwargs.get("offset") or 0),
            ),
        )


class FXMacroDataMarketSessionsTool(BaseTool):
    """Fetch FX market-session state from FXMacroData."""

    name = "get_fxmacrodata_market_sessions"
    description = "Fetch Sydney, Tokyo, London, and New York FX session status."
    parameters = {
        "type": "object",
        "properties": {
            "at": {
                "type": "string",
                "description": "Optional ISO timestamp to evaluate; defaults to now.",
            }
        },
    }

    def execute(self, **kwargs: Any) -> str:
        return _json_response(
            "/market_sessions",
            lambda: fxmd.market_sessions(at=_clean(kwargs.get("at"))),
        )


class FXMacroDataRiskSentimentTool(BaseTool):
    """Fetch global risk-on/risk-off indicator rows."""

    name = "get_fxmacrodata_risk_sentiment"
    description = "Fetch FXMacroData's global risk-on / risk-off indicator."
    parameters = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD upper bound."},
            "limit": {"type": "integer", "description": "Rows to return.", "default": 20},
        },
    }

    def execute(self, **kwargs: Any) -> str:
        return _json_response(
            "/risk_sentiment",
            lambda: fxmd.risk_sentiment(
                start_date=_clean(kwargs.get("start_date")),
                end_date=_clean(kwargs.get("end_date")),
                limit=_limit(kwargs.get("limit")),
            ),
        )


def _error(message: str) -> str:
    return json.dumps(
        {"ok": False, "source": "fxmacrodata", "error": message},
        ensure_ascii=False,
    )
