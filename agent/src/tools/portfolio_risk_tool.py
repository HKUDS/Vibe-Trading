"""Agent tool: portfolio risk x-ray (Portfolio Studio slice).

Wraps ``backtest.risk_xray.compute_risk_xray`` with data fetching through the
standard loader fallback chain (``src.market_data.fetch_market_data``), so the
agent can ask "how risky is this basket" without caring which source serves
the prices. The computation itself is pure and unit-tested directly; this
file only does argument handling, panel shaping, and the JSON envelope.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import pandas as pd

from backtest.risk_xray import compute_risk_xray
from src.agent.tools import BaseTool
from src.market_data import fetch_market_data

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = 365
_MAX_SYMBOLS = 50

# Candidate record keys that may carry the bar's date/timestamp after
# ``DataFrame.reset_index().to_dict("records")`` — loaders name the index
# differently ("date", "datetime", "trade_date", ...).
_DATE_KEYS = ("date", "datetime", "trade_date", "time", "timestamp")


class PortfolioRiskXrayTool(BaseTool):
    """Compute concentration, volatility, drawdown, tail risk, and
    co-movement for a weighted basket of symbols."""

    name = "portfolio_risk_xray"
    description = (
        "Portfolio risk x-ray: given symbols (and optional weights), fetch "
        "recent daily closes through the data fallback chain and compute "
        "concentration (HHI/effective N), annualized volatility, max drawdown, "
        "historical VaR/expected shortfall, diversification ratio, and "
        "correlation/beta. Long-only; weights are renormalized when they do "
        "not sum to 1."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Symbols in the basket, e.g. [\"AAPL\", \"MSFT\", \"SPY\"]. Optional when portfolio_id is supplied.",
            },
            "weights": {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "description": "Optional symbol → weight map. Equal weights when omitted.",
            },
            "start_date": {
                "type": "string",
                "description": "YYYY-MM-DD. Defaults to one year before end_date.",
            },
            "end_date": {
                "type": "string",
                "description": "YYYY-MM-DD. Defaults to today (UTC).",
            },
            "source": {
                "type": "string",
                "description": "Data source preference; 'auto' (default) walks the fallback chain.",
            },
            "interval": {
                "type": "string",
                "description": "Bar interval passed to the loaders; defaults to '1D'.",
            },
            "portfolio_id": {
                "type": "string",
                "description": "Optional personal portfolio id. Holdings are used as the basket when symbols are omitted.",
            },
        },
        "required": [],
    }

    def __init__(self, data_fetcher: Callable[..., dict[str, Any]] | None = None) -> None:
        # Injectable for tests; production uses the real fallback chain.
        self._fetch = data_fetcher or fetch_market_data

    def execute(self, **kwargs: Any) -> str:
        try:
            return self._run(**kwargs)
        except Exception as exc:  # noqa: BLE001 — tool must always return JSON
            logger.warning("portfolio_risk_xray failed: %s", exc)
            return json.dumps(
                {"status": "error", "error": str(exc)}, ensure_ascii=False, allow_nan=False
            )

    # ------------------------------------------------------------------
    def _run(self, **kwargs: Any) -> str:
        symbols = kwargs.get("symbols")
        if symbols is None and kwargs.get("portfolio_id"):
            from src.portfolio.calculator import calculate_snapshot
            from src.portfolio.store import PortfolioStore

            scope = "shared-key-holder"
            transactions = PortfolioStore().all_transactions(scope, str(kwargs["portfolio_id"]))
            derived = calculate_snapshot(transactions)
            symbols = [item["symbol"] for item in derived["holdings"]]
            costs = {item["symbol"]: float(item["cost_basis"]) for item in derived["holdings"]}
            total_cost = sum(costs.values())
            kwargs["weights"] = {symbol: value / total_cost for symbol, value in costs.items()} if total_cost else None
        if not isinstance(symbols, list) or not symbols or not all(
            isinstance(s, str) and s.strip() for s in symbols
        ):
            raise ValueError("symbols must be a non-empty list of strings")
        symbols = [s.strip() for s in symbols]
        if len(symbols) > _MAX_SYMBOLS:
            raise ValueError(f"too many symbols ({len(symbols)}); cap is {_MAX_SYMBOLS}")

        weights = self._parse_weights(kwargs.get("weights"), symbols)
        start_date, end_date = self._parse_dates(kwargs.get("start_date"), kwargs.get("end_date"))
        source = str(kwargs.get("source") or "auto")
        interval = str(kwargs.get("interval") or "1D")

        raw = self._fetch(
            codes=symbols,
            start_date=start_date,
            end_date=end_date,
            source=source,
            interval=interval,
        )
        closes = self._closes_frame(raw, symbols)
        unresolved = raw.get("_unresolved") if isinstance(raw, Mapping) else None

        report = compute_risk_xray(closes, weights)
        envelope = {
            "status": "ok",
            "data": report,
            "meta": {
                "start_date": start_date,
                "end_date": end_date,
                "interval": interval,
                "source": source,
                "unresolved_symbols": list(unresolved or []),
            },
        }
        return json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_weights(raw: Any, symbols: list[str]) -> dict[str, float]:
        if raw is None:
            return {sym: 1.0 / len(symbols) for sym in symbols}
        if not isinstance(raw, Mapping):
            raise ValueError("weights must be an object mapping symbol → number")
        unknown = [sym for sym in raw if sym not in symbols]
        if unknown:
            raise ValueError(f"weights name symbols not in the basket: {sorted(unknown)}")
        missing = [sym for sym in symbols if sym not in raw]
        if missing:
            raise ValueError(f"weights missing basket symbols: {sorted(missing)}")
        return {sym: raw[sym] for sym in symbols}

    @staticmethod
    def _parse_dates(start_raw: Any, end_raw: Any) -> tuple[str, str]:
        end = (
            datetime.strptime(end_raw, "%Y-%m-%d").date()
            if isinstance(end_raw, str) and end_raw
            else datetime.now(timezone.utc).date()
        )
        start = (
            datetime.strptime(start_raw, "%Y-%m-%d").date()
            if isinstance(start_raw, str) and start_raw
            else end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        )
        if start >= end:
            raise ValueError(f"start_date {start} must be before end_date {end}")
        return start.isoformat(), end.isoformat()

    @staticmethod
    def _closes_frame(raw: Mapping[str, Any], symbols: list[str]) -> pd.DataFrame:
        """Shape the fetch envelope into a date-indexed close-price panel."""
        series: dict[str, pd.Series] = {}
        for sym in symbols:
            records = raw.get(sym)
            if not records:
                continue
            times: list[Any] = []
            prices: list[float] = []
            for record in records:
                if not isinstance(record, Mapping) or "close" not in record:
                    continue
                when = next((record[k] for k in _DATE_KEYS if k in record), None)
                try:
                    price = float(record["close"])
                except (TypeError, ValueError):
                    continue
                times.append(when)
                prices.append(price)
            if not prices:
                continue
            # Mixed typed/untyped timestamps can't be sorted together; when any
            # bar lacks a date, trust loader order (chronological) instead.
            if any(when is None for when in times):
                series[sym] = pd.Series(prices, name=sym)
            else:
                series[sym] = pd.Series(prices, index=times, name=sym).sort_index()
        if not series:
            raise ValueError("no close prices returned for any requested symbol")
        return pd.DataFrame(series)
