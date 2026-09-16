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
_MAX_LOOKBACK_DAYS = 730
_SUPPORTED_ASSET_TYPES = {"ACCIONES", "CEDEARS"}
_TIMEOUT_SECONDS = 30.0
_NUMERIC_FORMAT = "json_number"


class ConnectorError(RuntimeError):
    """Raised when Asistente Casa cannot return a trustworthy payload."""


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
                "description": "Optional YYYY-MM-DD start date. Defaults to 120 calendar days before end_date.",
            },
            "end_date": {
                "type": "string",
                "description": "Optional YYYY-MM-DD end date. Defaults to today.",
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

        start_date, end_date = self._parse_dates(kwargs.get("start_date"), kwargs.get("end_date"))

        base_url = str(os.environ.get("ASISTENTE_CASA_BASE_URL") or "").strip().rstrip("/")
        api_key = str(os.environ.get("ASISTENTE_CASA_API_KEY") or "").strip()
        if not base_url or not api_key:
            raise ValueError("Asistente Casa environment is not configured")

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
    def _parse_dates(start_raw: Any, end_raw: Any) -> tuple[str, str]:
        end = date.fromisoformat(str(end_raw)) if end_raw else date.today()
        start = (
            date.fromisoformat(str(start_raw))
            if start_raw
            else end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        )
        if start >= end:
            raise ValueError("start_date must be before end_date")
        lookback = (end - start).days
        if lookback > _MAX_LOOKBACK_DAYS:
            raise ValueError(f"maximum lookback is {_MAX_LOOKBACK_DAYS} calendar days")
        return start.isoformat(), end.isoformat()
