"""Risk X-Ray for the canonical Asistente Casa portfolio.

Local integration (ported from the cc54832 Vibe checkout to a5b79422):
Asistente Casa remains the source of truth for holdings and persisted market
history. Vibe performs the deterministic risk computation.

This tool is self-contained by design: it resolves its own symbols/weights
from Asistente Casa and never accepts a ``symbols`` argument from the model,
so it never trips the generic instrument-identity gate
(``agent/src/agent/grounding/identity.py`` only gates calls whose arguments
carry a key in ``code/codes/symbol/symbols/ticker/tickers/underlying/
underlyings``) and never touches the generic market-data fallback chain
(``search_symbol``, ``fetch_market_data``/``get_market_data``, yfinance,
tushare/tencent, ...).

Local customization (2026-09-15, see
``docs/investments/VIBE_TRADING_CUSTOMIZATIONS.md`` in the Asistente Casa
repo): the 120-day default lookback is a Risk X-Ray convenience default, not
a datastore boundary. There is no hard maximum lookback here anymore --
availability is whatever Asistente Casa has actually persisted. Coverage
questions ("since when do you have data") must go through
``AsistenteCasaMarketHistoryCoverageTool`` / ``/market-history/coverage``
below, never be inferred from a short history request's ``from`` date.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from backtest.risk_xray import compute_risk_xray
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = 120
_SUPPORTED_ASSET_TYPES = {"ACCIONES", "CEDEARS"}
_SUPPORTED_HORIZONS = {"1y", "ytd", "since_inception"}
_TIMEOUT_SECONDS = 30.0
_NUMERIC_FORMAT = "json_number"


class ConnectorError(RuntimeError):
    """Raised when Asistente Casa cannot return a trustworthy payload."""


def _env_credentials() -> tuple[str, str]:
    base_url = str(os.environ.get("ASISTENTE_CASA_BASE_URL") or "").strip().rstrip("/")
    api_key = str(os.environ.get("ASISTENTE_CASA_API_KEY") or "").strip()
    if not base_url or not api_key:
        raise ValueError("Asistente Casa environment is not configured")
    return base_url, api_key


def _get(base_url: str, api_key: str, path: str, params: Mapping[str, str]) -> dict[str, Any]:
    query = urlencode(params)
    request = Request(
        f"{base_url}{path}?{query}",
        headers={"Accept": "application/json", "X-Vibe-API-Key": api_key},
        method="GET",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise ConnectorError(f"Asistente Casa returned HTTP {exc.code} for {path}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectorError(f"Asistente Casa is unavailable ({path}): {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"Asistente Casa returned invalid JSON for {path}") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ConnectorError(f"Asistente Casa returned an unsuccessful payload for {path}")
    if payload.get("numeric_format") != _NUMERIC_FORMAT:
        raise ConnectorError(f"unexpected numeric_format for {path}; refusing localized numeric parsing")
    return payload


def _fetch_coverage(
    base_url: str, api_key: str, *, symbols: list[str], asset_type: str
) -> dict[str, Any]:
    """Read persisted-only coverage metadata (no OHLC rows) for a basket.

    This is the only sanctioned source for "since when do you have data"
    answers -- it must never be approximated from a short history request's
    ``from`` date.
    """
    payload = _get(
        base_url,
        api_key,
        "/inversiones/vibe/market-history/coverage",
        {"symbols": ",".join(symbols), "asset_type": asset_type},
    )
    if payload.get("policy") != "persisted_only":
        raise ValueError("Asistente Casa coverage policy is not persisted_only")
    return payload


class AsistenteCasaPortfolioRiskXrayTool(BaseTool):
    """Analyze the user's canonical Asistente Casa investment portfolio."""

    name = "asistente_casa_portfolio_risk_xray"

    description = (
        "PREFERRED tool for VaR, Expected Shortfall, volatility, drawdown, "
        "concentration, diversification, or correlation of the user's CURRENT "
        "Asistente Casa portfolio (the real, canonical Argentine brokerage "
        "account) — for ACCIONES and CEDEARS. Use this INSTEAD of the generic "
        "portfolio_risk_xray whenever the request is about 'mi cartera real', "
        "'mis datos reales', or the account already loaded through the "
        "asistente-casa connector: this tool resolves holdings, weights and "
        "canonical persisted price history itself — the model does NOT supply "
        "symbols or weights, and must NOT call search_symbol/fetch_market_data/"
        "get_market_data first. Currently validated for ACCIONES (Argentine "
        "equities) and CEDEARS, analyzed as separate scopes. "
        "IMPORTANT ROUTING RULES: this result is deterministic for the same "
        "portfolio snapshot and date range. Call this tool at most ONCE per "
        "scope for a given analysis unless the user explicitly requests a "
        "different date range or refreshed data. Do NOT call it repeatedly to "
        "verify metrics it already returned. Do NOT use ACCIONES or CEDEARS "
        "metrics as if either scope represented the complete portfolio. Do NOT "
        "combine or extrapolate these results to BONOS or FCI."
    )

    parameters = {
        "type": "object",
        "properties": {
            "asset_type": {
                "type": "string",
                "enum": ["ACCIONES", "CEDEARS"],
                "description": "Portfolio asset type. Validated scopes: ACCIONES and CEDEARS.",
            },
            "start_date": {
                "type": "string",
                "description": (
                    "Optional YYYY-MM-DD start date. Defaults to 120 calendar days "
                    "before end_date. Mutually exclusive with horizon. This default "
                    "is a Risk X-Ray convenience window, not the start of persisted "
                    "history -- use asistente_casa_market_history_coverage for "
                    "'since when do you have data' questions."
                ),
            },
            "end_date": {
                "type": "string",
                "description": "Optional YYYY-MM-DD end date. Defaults to today.",
            },
            "horizon": {
                "type": "string",
                "enum": ["1Y", "YTD", "since_inception"],
                "description": (
                    "Optional shorthand instead of start_date. '1Y' = trailing 365 "
                    "calendar days. 'YTD' = January 1 of end_date's year. "
                    "'since_inception' = this basket's earliest common persisted "
                    "date (from the coverage endpoint), i.e. the earliest date for "
                    "which every symbol in scope has an aligned observation -- use "
                    "this for 'analyze since inception' portfolio-level requests. "
                    "Mutually exclusive with start_date."
                ),
            },
        },
        "required": [],
    }

    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        return bool(
            str(os.environ.get("ASISTENTE_CASA_BASE_URL") or "").strip()
            and str(os.environ.get("ASISTENTE_CASA_API_KEY") or "").strip()
        )

    def execute(self, **kwargs: Any) -> str:
        try:
            return self._run(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- tool must always return JSON
            logger.warning("asistente_casa_portfolio_risk_xray failed: %s", exc)
            return json.dumps(
                {"status": "error", "error": str(exc), "source": "asistente-casa"},
                ensure_ascii=False,
                allow_nan=False,
            )

    def _run(self, **kwargs: Any) -> str:
        asset_type = str(kwargs.get("asset_type") or "ACCIONES").strip().upper()
        if asset_type not in _SUPPORTED_ASSET_TYPES:
            raise ValueError(
                f"asset_type {asset_type!r} is not validated; currently supported: ACCIONES, CEDEARS"
            )

        start_raw = kwargs.get("start_date")
        end_raw = kwargs.get("end_date")
        horizon_raw = kwargs.get("horizon")
        horizon = str(horizon_raw).strip().lower().replace("-", "_") if horizon_raw else None
        if horizon and horizon not in _SUPPORTED_HORIZONS:
            raise ValueError(f"horizon {horizon_raw!r} is not supported; use 1Y, YTD, or since_inception")
        if horizon and start_raw:
            raise ValueError("start_date and horizon are mutually exclusive")

        base_url, api_key = _env_credentials()

        # ------------------------------------------------------------
        # Canonical portfolio, scoped to this asset_type
        # ------------------------------------------------------------
        portfolio_payload = _get(base_url, api_key, "/inversiones/vibe/portfolio", {"asset_type": asset_type})
        portfolio_block = portfolio_payload.get("portfolio", {})
        positions = portfolio_block.get("positions", [])
        if not positions:
            raise ValueError(f"Asistente Casa returned no positions for {asset_type}")

        symbols = [str(position["symbol"]).strip().upper() for position in positions]
        weights = {
            str(position["symbol"]).strip().upper(): float(position["weight_scope"])
            for position in positions
        }

        end = date.fromisoformat(str(end_raw)) if end_raw else date.today()
        start = self._resolve_start(
            start_raw=start_raw,
            horizon=horizon,
            end=end,
            symbols=symbols,
            asset_type=asset_type,
            base_url=base_url,
            api_key=api_key,
        )
        if start >= end:
            raise ValueError("start_date must be before end_date")
        start_date, end_date = start.isoformat(), end.isoformat()

        instrument_names: dict[str, str | None] = {}
        portfolio_positions: list[dict[str, Any]] = []
        for position in positions:
            symbol = str(position["symbol"]).strip().upper()
            raw_name = str(position.get("name") or "").strip()
            name = raw_name or None
            instrument_names[symbol] = name
            portfolio_positions.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "label": f"{symbol} - {name}" if name else symbol,
                    "weight_scope": float(position["weight_scope"]),
                }
            )

        weight_sum = sum(weights.values())
        if weight_sum <= 0:
            raise ValueError("portfolio weights sum to zero")

        # ------------------------------------------------------------
        # Canonical persisted market history, daily EOD only
        # ------------------------------------------------------------
        history_payload = _get(
            base_url,
            api_key,
            "/inversiones/vibe/market-history",
            {"symbols": ",".join(symbols), "asset_type": asset_type, "from": start_date, "to": end_date},
        )
        if history_payload.get("policy") != "persisted_only":
            raise ValueError("Asistente Casa market-history policy is not persisted_only")
        if str(history_payload.get("interval") or "").upper() != "1D":
            raise ValueError("Asistente Casa market-history interval is not 1D")
        if not history_payload.get("complete"):
            raise ValueError(
                "Asistente Casa historical coverage incomplete: "
                f"unresolved={history_payload.get('unresolved_symbols')}, "
                f"unsafe={history_payload.get('unsafe_symbols')}, "
                f"without_history={history_payload.get('symbols_without_history')}"
            )

        series: dict[str, pd.Series] = {}
        for symbol in symbols:
            observations = history_payload.get("series", {}).get(symbol, {}).get("observations", [])
            if not observations:
                raise ValueError(f"no historical observations for {symbol}")
            series[symbol] = pd.Series(
                {pd.Timestamp(row["date"]): float(row["close"]) for row in observations},
                name=symbol,
                dtype=float,
            )

        closes_raw = pd.DataFrame(series).sort_index()
        if closes_raw.empty:
            raise ValueError("historical close panel is empty")

        # strict_intersection_no_fill: one common observation date for every
        # symbol, never forward-filled or synthesized.
        missing_by_symbol = {
            symbol: int(count) for symbol, count in closes_raw.isna().sum().items() if count
        }
        closes = closes_raw.dropna(axis=0, how="any")
        if closes.empty:
            raise ValueError("historical close panel has no common dates across symbols")
        dropped_non_common_dates = len(closes_raw) - len(closes)

        # ------------------------------------------------------------
        # Vibe deterministic Risk X-Ray
        # ------------------------------------------------------------
        report = compute_risk_xray(closes, weights, periods_per_year=252)

        result = {
            "status": "ok",
            "source": "asistente-casa",
            "asset_type": asset_type,
            "portfolio_positions": portfolio_positions,
            "instrument_names": instrument_names,
            "data": report,
            "meta": {
                "portfolio_contract_version": portfolio_payload.get("contract_version"),
                "history_contract_version": history_payload.get("contract_version"),
                "position_quantity_source": portfolio_payload.get("position_quantity_source"),
                "position_snapshot_id": portfolio_payload.get("position_snapshot_id"),
                "position_snapshot_at": portfolio_payload.get("position_snapshot_at"),
                "history_policy": history_payload.get("policy"),
                "history_source_selection": history_payload.get("source_selection"),
                "horizon": horizon or "default_120d",
                "start_date": start_date,
                "end_date": end_date,
                "symbols": symbols,
                "position_count": len(symbols),
                "total_value_ars": portfolio_block.get("total_value_ars"),
                "scope_value_ars": portfolio_block.get("scope_value_ars"),
                "weight_sum": weight_sum,
                "history_complete": True,
                "raw_close_observations": len(closes_raw),
                "close_observations": len(closes),
                "common_date_count": len(closes),
                "dropped_non_common_dates": dropped_non_common_dates,
                "missing_dates_by_symbol": missing_by_symbol,
                "alignment_policy": "strict_intersection_no_fill",
            },
        }
        return json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)

    @staticmethod
    def _resolve_start(
        *,
        start_raw: Any,
        horizon: str | None,
        end: date,
        symbols: list[str],
        asset_type: str,
        base_url: str,
        api_key: str,
    ) -> date:
        """Resolve the effective start date for the requested window.

        No calendar-day maximum is enforced here: actual availability is
        whatever Asistente Casa has persisted, and the strict basket
        intersection downstream already fails closed instead of padding or
        inventing observations when coverage falls short of what was asked.
        """
        if start_raw:
            return date.fromisoformat(str(start_raw))
        if horizon == "1y":
            return end - timedelta(days=365)
        if horizon == "ytd":
            return date(end.year, 1, 1)
        if horizon == "since_inception":
            coverage = _fetch_coverage(base_url, api_key, symbols=symbols, asset_type=asset_type)
            earliest_common = coverage.get("earliest_common_date")
            if not earliest_common:
                raise ValueError(
                    "Asistente Casa coverage has no earliest_common_date for this basket"
                )
            return date.fromisoformat(str(earliest_common))
        return end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)


class AsistenteCasaMarketHistoryCoverageTool(BaseTool):
    """Report persisted historical coverage for the Asistente Casa portfolio.

    This tool answers "since when do you have data" / "until when do you have
    quotes" questions using ``/inversiones/vibe/market-history/coverage``
    directly -- it never downloads OHLC rows and never infers datastore
    inception from a Risk X-Ray short-window request. Like the risk tool
    above, it resolves its own symbols from the current Asistente Casa
    portfolio and never accepts a ``symbols`` argument from the model, so it
    does not trip the generic instrument-identity gate.
    """

    name = "asistente_casa_market_history_coverage"

    description = (
        "Report persisted historical DATA COVERAGE (not risk metrics) for the "
        "user's CURRENT Asistente Casa portfolio: since when data exists, "
        "until when it is up to date, and how many observations are stored. "
        "Use this INSTEAD of asistente_casa_portfolio_risk_xray whenever the "
        "user asks 'since when', 'how far back', 'until when', 'how much "
        "history do you have' -- for one asset_type scope (ACCIONES or "
        "CEDEARS) or, if asset_type is omitted, for both. Do NOT answer "
        "coverage questions from a Risk X-Ray result's start_date: that is "
        "only a short default request window, not the start of the "
        "datastore. The response distinguishes, per scope, the OLDEST "
        "INDIVIDUAL persisted date across the basket (earliest_any_date, and "
        "per-symbol first_date in series) from the COMMON basket date every "
        "symbol shares (earliest_common_date) -- report both when the user "
        "asks about a group ('mis acciones', 'mis CEDEARs') and only the "
        "per-symbol first_date when the user asks about one instrument."
    )

    parameters = {
        "type": "object",
        "properties": {
            "asset_type": {
                "type": "string",
                "enum": ["ACCIONES", "CEDEARS"],
                "description": (
                    "Optional portfolio scope. Omit to report coverage for both "
                    "ACCIONES and CEDEARS."
                ),
            },
        },
        "required": [],
    }

    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        return bool(
            str(os.environ.get("ASISTENTE_CASA_BASE_URL") or "").strip()
            and str(os.environ.get("ASISTENTE_CASA_API_KEY") or "").strip()
        )

    def execute(self, **kwargs: Any) -> str:
        try:
            return self._run(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- tool must always return JSON
            logger.warning("asistente_casa_market_history_coverage failed: %s", exc)
            return json.dumps(
                {"status": "error", "error": str(exc), "source": "asistente-casa"},
                ensure_ascii=False,
                allow_nan=False,
            )

    def _run(self, **kwargs: Any) -> str:
        asset_type_raw = kwargs.get("asset_type")
        if asset_type_raw:
            asset_type = str(asset_type_raw).strip().upper()
            if asset_type not in _SUPPORTED_ASSET_TYPES:
                raise ValueError(
                    f"asset_type {asset_type!r} is not validated; currently supported: "
                    "ACCIONES, CEDEARS"
                )
            scopes = [asset_type]
        else:
            scopes = sorted(_SUPPORTED_ASSET_TYPES)

        base_url, api_key = _env_credentials()

        scope_results: dict[str, Any] = {}
        for scope in scopes:
            portfolio_payload = _get(base_url, api_key, "/inversiones/vibe/portfolio", {"asset_type": scope})
            positions = portfolio_payload.get("portfolio", {}).get("positions", [])
            if not positions:
                continue
            symbols = [str(position["symbol"]).strip().upper() for position in positions]
            coverage_payload = _fetch_coverage(base_url, api_key, symbols=symbols, asset_type=scope)
            scope_results[scope] = {
                "symbols": symbols,
                "earliest_any_date": coverage_payload.get("earliest_any_date"),
                "earliest_common_date": coverage_payload.get("earliest_common_date"),
                "latest_common_date": coverage_payload.get("latest_common_date"),
                "complete": coverage_payload.get("complete"),
                "unresolved_symbols": coverage_payload.get("unresolved_symbols"),
                "symbols_without_history": coverage_payload.get("symbols_without_history"),
                "series": coverage_payload.get("series"),
            }

        if not scope_results:
            raise ValueError(f"Asistente Casa returned no positions for {scopes}")

        all_first_dates = [
            str(item["first_date"])
            for scope in scope_results.values()
            for item in scope["series"].values()
            if item.get("first_date")
        ]
        all_last_dates = [
            str(item["last_date"])
            for scope in scope_results.values()
            for item in scope["series"].values()
            if item.get("last_date")
        ]

        result = {
            "status": "ok",
            "source": "asistente-casa",
            "policy": "persisted_only",
            "scopes": scope_results,
            "overall": {
                "earliest_any_date": min(all_first_dates) if all_first_dates else None,
                "latest_any_date": max(all_last_dates) if all_last_dates else None,
            },
        }
        return json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
