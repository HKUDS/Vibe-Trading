"""FXMacroData loader for FX/macro time series.

FXMacroData provides official-source macroeconomic indicators, central-bank
reference FX rates, commodities, COT, rates, curves, and event calendars. The
backtest loader layer can only consume historical numeric bars, so this loader
maps selected numeric FXMacroData series into Vibe's canonical OHLCV frame:

``open = high = low = close = value`` and ``volume = 0``.

Richer non-bar datasets are exposed through ``src.tools.fxmacrodata_tools``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders import fxmacrodata_client as client
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
_COMPACT_FX_RE = re.compile(r"^(?P<base>[A-Z]{3})(?P<quote>[A-Z]{3})(?:\.FX)?$", re.I)
_SLASH_FX_RE = re.compile(r"^(?P<base>[A-Z]{3})/(?P<quote>[A-Z]{3})$", re.I)
_FX_PREFIX_RE = re.compile(r"^fx:(?P<pair>[A-Z]{3}/[A-Z]{3})$", re.I)
_FXMD_PREFIX_RE = re.compile(r"^fxmd:(?P<body>.+)$", re.I)

_DATE_KEYS = (
    "trade_date",
    "date",
    "observation_date",
    "observation_datetime_iso",
    "announcement_datetime_local",
    "announcement_datetime",
    "report_date",
)
_VALUE_KEYS = (
    "val",
    "value",
    "close",
    "price",
    "rate",
    "spot",
    "spread_percentage_points",
    "spread_percent",
    "spread",
    "net",
    "commercial_net",
    "non_commercial_net",
    "score",
)


@dataclass(frozen=True)
class ParsedSymbol:
    """Parsed FXMacroData loader symbol."""

    kind: str
    symbol: str
    base: str | None = None
    quote: str | None = None
    currency: str | None = None
    indicator: str | None = None
    measure: str | None = None


def parse_symbol(code: str) -> ParsedSymbol:
    """Parse a Vibe symbol into one FXMacroData request type.

    Supported examples:
    ``EUR/USD``, ``EURUSD``, ``EURUSD.FX``, ``fx:EUR/USD``,
    ``fxmd:forex:EUR/USD``, ``fxmd:commodity:gold``,
    ``fxmd:indicator:USD:inflation``, ``fxmd:cot:JPY``,
    ``fxmd:risk_sentiment``, ``fxmd:rate_diff:EUR/USD:policy_rate``, and
    ``fxmd:forward_diff:EUR/USD``.
    """
    raw = code.strip()
    if not raw:
        raise ValueError("empty FXMacroData symbol")

    prefixed_fx = _FX_PREFIX_RE.match(raw)
    if prefixed_fx:
        return _parse_pair(prefixed_fx.group("pair"), raw)

    fxmd = _FXMD_PREFIX_RE.match(raw)
    if fxmd:
        return _parse_fxmd_body(fxmd.group("body"), raw)

    slash = _SLASH_FX_RE.match(raw)
    if slash:
        return _parse_pair(raw, raw)

    compact = _COMPACT_FX_RE.match(raw)
    if compact:
        base = compact.group("base").upper()
        quote = compact.group("quote").upper()
        return ParsedSymbol("forex", raw, base=base, quote=quote)

    raise ValueError(f"unsupported FXMacroData symbol format: {code}")


def _parse_pair(pair: str, original: str) -> ParsedSymbol:
    match = _SLASH_FX_RE.match(pair.strip())
    if not match:
        raise ValueError(f"invalid FX pair: {pair}")
    return ParsedSymbol(
        "forex",
        original,
        base=match.group("base").upper(),
        quote=match.group("quote").upper(),
    )


def _parse_fxmd_body(body: str, original: str) -> ParsedSymbol:
    parts = [part.strip() for part in body.split(":") if part.strip()]
    if not parts:
        raise ValueError("empty fxmd symbol")
    family = parts[0].lower()
    if family == "forex" and len(parts) == 2:
        return _parse_pair(parts[1], original)
    if family in {"commodity", "commodities"} and len(parts) == 2:
        return ParsedSymbol("commodity", original, indicator=parts[1].lower())
    if family in {"indicator", "macro", "announcement"} and len(parts) == 3:
        return ParsedSymbol(
            "indicator",
            original,
            currency=parts[1].upper(),
            indicator=parts[2].lower(),
        )
    if family == "cot" and len(parts) == 2:
        return ParsedSymbol("cot", original, currency=parts[1].upper())
    if family == "risk_sentiment" and len(parts) == 1:
        return ParsedSymbol("risk_sentiment", original)
    if family in {"rate_diff", "rate_differential"} and len(parts) in {2, 3}:
        parsed = _parse_pair(parts[1], original)
        return ParsedSymbol(
            "rate_diff",
            original,
            base=parsed.base,
            quote=parsed.quote,
            measure=parts[2].lower() if len(parts) == 3 else None,
        )
    if family in {"forward_diff", "forward_differential"} and len(parts) == 2:
        parsed = _parse_pair(parts[1], original)
        return ParsedSymbol(
            "forward_diff",
            original,
            base=parsed.base,
            quote=parsed.quote,
        )
    raise ValueError(f"unsupported fxmd symbol format: {original}")


@register
class DataLoader:
    """FXMacroData numeric time-series loader."""

    name = "fxmacrodata"
    markets = {"forex", "macro"}
    requires_auth = True

    def is_available(self) -> bool:
        """FXMacroData loader participates in fallback only when a key is set."""
        return client.has_api_key()

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch FXMacroData series as normalized OHLCV frames."""
        del fields
        validate_date_range(start_date, end_date)
        if interval.upper() not in {"1D", "D", "1DAY"}:
            logger.info("fxmacrodata currently returns daily/reference-date series")

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                parsed = parse_symbol(code)
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda parsed=parsed: self._fetch_one(
                        parsed, start_date, end_date
                    ),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 - one symbol should not abort the batch
                logger.warning("fxmacrodata failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self,
        parsed: ParsedSymbol,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        payload = _fetch_payload(parsed, start_date, end_date)
        rows = _extract_rows(payload)
        return _rows_to_ohlcv(rows)


def _fetch_payload(parsed: ParsedSymbol, start_date: str, end_date: str) -> Any:
    if parsed.kind == "forex":
        return client.forex(
            parsed.base or "",
            parsed.quote or "",
            start_date=start_date,
            end_date=end_date,
        )
    if parsed.kind == "commodity":
        return client.commodities(
            parsed.indicator,
            start_date=start_date,
            end_date=end_date,
        )
    if parsed.kind == "indicator":
        return client.indicator(
            parsed.currency or "",
            parsed.indicator or "",
            start_date=start_date,
            end_date=end_date,
        )
    if parsed.kind == "cot":
        return client.cot(parsed.currency or "", start_date=start_date, end_date=end_date)
    if parsed.kind == "risk_sentiment":
        return client.risk_sentiment(start_date=start_date, end_date=end_date)
    if parsed.kind == "rate_diff":
        return client.rate_differentials(
            parsed.base or "",
            parsed.quote or "",
            measure=parsed.measure,
            start_date=start_date,
            end_date=end_date,
        )
    if parsed.kind == "forward_diff":
        return client.forward_differentials(
            parsed.base or "",
            parsed.quote or "",
            start_date=start_date,
            end_date=end_date,
        )
    raise ValueError(f"unsupported FXMacroData kind: {parsed.kind}")


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        observations = payload.get("observations")
        if isinstance(observations, list):
            return [row for row in observations if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _rows_to_ohlcv(rows: list[dict[str, Any]]) -> Optional[pd.DataFrame]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        timestamp = _row_date(row)
        value = _row_value(row)
        if timestamp is None or value is None:
            continue
        normalized.append(
            {
                "trade_date": timestamp.normalize(),
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "volume": 0.0,
            }
        )
    if not normalized:
        return None

    df = pd.DataFrame(normalized)
    df = df.drop_duplicates(subset=["trade_date"], keep="last")
    df = df.set_index("trade_date").sort_index()
    df.index.name = "trade_date"
    return df[_OHLCV_COLUMNS].astype(float)


def _row_date(row: dict[str, Any]) -> pd.Timestamp | None:
    for key in _DATE_KEYS:
        if key not in row:
            continue
        value = row.get(key)
        try:
            if isinstance(value, (int, float)):
                ts = pd.to_datetime(value, unit="s", utc=True)
            else:
                ts = pd.to_datetime(value, utc=True)
        except Exception:
            continue
        if pd.isna(ts):
            continue
        return pd.Timestamp(ts).tz_convert(None)
    return None


def _row_value(row: dict[str, Any]) -> float | None:
    for key in _VALUE_KEYS:
        if key not in row:
            continue
        try:
            return float(row[key])
        except (TypeError, ValueError):
            continue
    return None
