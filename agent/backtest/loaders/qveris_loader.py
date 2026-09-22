"""QVeris loader: explicit, key-gated OHLCV fetches through QVeris tools.

This loader is intentionally self-contained for the QVeris integration parcel:
it reads the shared ``~/.vibe-trading/qveris.json`` config schema, applies the
``QVERIS_API_KEY`` / ``QVERIS_BASE_URL`` environment overrides, and embeds the
small HTTP client it needs for ``POST /search``, ``POST /tools/execute``, and
truncated-result downloads.

QVeris is a paid-capability router, so it must only run when the user explicitly
requests ``source="qveris"``. The registry keeps it out of every auto fallback
chain.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

from backtest.engines._market_hooks import _detect_market
from backtest.loaders.base import (
    NoAvailableSourceError,
    cached_loader_fetch,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import market_has_corporate_actions, register

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".vibe-trading" / "qveris.json"
_DEFAULT_BASE_URL = "https://qveris.ai/api/v1"
_API_KEY_ENV = "QVERIS_API_KEY"
_BASE_URL_ENV = "QVERIS_BASE_URL"
_MIN_INTERVAL_ENV = "VIBE_TRADING_QVERIS_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.5
_HTTP_TIMEOUT_S = 30.0
_MAX_RETRIES = 3
_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
_DATE_KEYS = (
    "trade_date",
    "date",
    "datetime",
    "timestamp",
    "time",
    "period",
)
#: A quote bounds the bill only when it is a flat price per call: "24.2
#: credits", "1 credits/call", or a bare number. ``cn_financial_pro.
#: history_quotation.v1`` quoted "1 credits/result" and billed 9.66 credits for
#: one stock-year, 244 rows x 30 fields at 0.00132 credits a value (#1494), so
#: a quote priced per any other unit, or in a shape not listed here, reserves
#: nothing that caps the charge and prices as unknown.
_FLAT_QUOTE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:credits?)?\s*(?:(?:/|per)\s*(call|request))?")

#: The four fields that must all be present for a record to become a bar.
_PRICE_QUARTET = ("open", "high", "low", "close")

#: Aliases for an unadjusted bar.
_FIELD_ALIASES = {
    "open": ("open", "o", "1. open"),
    "high": ("high", "h", "2. high"),
    "low": ("low", "l", "3. low"),
    "close": ("close", "c", "4. close"),
    "volume": ("volume", "vol", "v", "5. volume", "6. volume"),
}

#: Volume names that make no adjustment claim, shared by both tables. The
#: family split exists to stop unadjusted and adjusted *price levels* sharing a
#: bar; volume is not a price level, so an adjusted bar must still report a
#: volume the payload calls ``volume`` (``6. volume`` is Alpha Vantage's label
#: for the adjusted series' volume) instead of silently reporting NaN. The
#: unadjusted tuple is referenced rather than copied so the two cannot drift and
#: the unadjusted path stays byte-identical.
_PLAIN_VOLUME_ALIASES = _FIELD_ALIASES["volume"]

#: Aliases for an adjusted bar, resolved as a complete alternate set rather
#: than field by field. ``adj_close`` used to sit in the unadjusted ``close``
#: aliases while it had no ``adj_open``/``adj_high``/``adj_low`` siblings,
#: which cut both ways (#1494): a record carrying only adjusted fields failed
#: the OHLC check on every row, so a billed call produced no bars, while a
#: record carrying unadjusted open/high/low with only ``adj_close`` was
#: accepted as one bar mixing unadjusted and adjusted price levels.
_ADJUSTED_FIELD_ALIASES = {
    "open": ("adj_open", "adjusted_open"),
    "high": ("adj_high", "adjusted_high"),
    "low": ("adj_low", "adjusted_low"),
    "close": ("adj_close", "adjusted_close"),
    "volume": ("adj_volume", "adjusted_volume") + _PLAIN_VOLUME_ALIASES,
}


@dataclass(frozen=True)
class QVerisConfig:
    """Resolved QVeris loader configuration."""

    enabled: bool
    base_url: str
    api_key: str
    mode: str
    budget_credits_per_session: float


def _load_config() -> QVerisConfig:
    """Read QVeris config with environment overrides.

    Returns:
        Resolved config. Missing or malformed config files fall back to the
        disabled default; env vars only override matching fields and do not
        implicitly enable the integration.
    """
    raw: dict[str, Any] = {
        "enabled": False,
        "base_url": _DEFAULT_BASE_URL,
        "api_key": "",
        "mode": "free",
        "budget_credits_per_session": 50.0,
    }
    try:
        if _CONFIG_PATH.is_file():
            loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw.update(loaded)
    except Exception as exc:  # noqa: BLE001 - config read failures mean unavailable
        logger.warning("qveris config ignored: %s", exc)

    from src.config.accessor import get_env_config

    api_key = (get_env_config().data.qveris_api_key or str(raw.get("api_key") or "")).strip()
    base_url = (get_env_config().data.qveris_base_url or str(raw.get("base_url") or _DEFAULT_BASE_URL)).strip()
    try:
        budget = float(raw.get("budget_credits_per_session", 50.0))
    except (TypeError, ValueError):
        budget = 50.0
    if not math.isfinite(budget):
        budget = 50.0
    return QVerisConfig(
        enabled=bool(raw.get("enabled")),
        base_url=(base_url or _DEFAULT_BASE_URL).rstrip("/"),
        api_key=api_key,
        mode=_normalize_mode(str(raw.get("mode") or "free")),
        budget_credits_per_session=max(budget, 0.0),
    )


def _normalize_mode(mode: str) -> str:
    """Normalize QVeris paid-route mode."""
    return {"preview": "free", "allow_paid": "paid", "free": "free", "paid": "paid"}.get(mode.strip(), "free")


def _min_interval() -> float:
    """Resolve the minimum interval between QVeris requests."""
    raw = os.getenv(_MIN_INTERVAL_ENV)  # noqa: env-gate — loader-specific rate limit
    if raw is None or not raw.strip():
        return _DEFAULT_MIN_INTERVAL_S
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r, using default %s",
            _MIN_INTERVAL_ENV,
            raw,
            _DEFAULT_MIN_INTERVAL_S,
        )
        return _DEFAULT_MIN_INTERVAL_S
    if value < 0:
        logger.warning(
            "negative %s=%r, using default %s",
            _MIN_INTERVAL_ENV,
            raw,
            _DEFAULT_MIN_INTERVAL_S,
        )
        return _DEFAULT_MIN_INTERVAL_S
    return value


class QVerisClient:
    """Minimal QVeris HTTP client for search, execute, and full-result GET."""

    def __init__(self, config: QVerisConfig) -> None:
        """Initialize a session-bound client.

        Args:
            config: Resolved QVeris config containing base URL and API key.
        """
        self._config = config
        self._session = requests.Session()
        self._last_request_at = 0.0

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        """Call ``POST /search``.

        Args:
            query: Natural-language capability query.
            limit: Maximum result count.

        Returns:
            Decoded response body.
        """
        return self._post_json("/search", {"query": query, "limit": limit})

    def execute(
        self,
        tool_id: str,
        parameters: dict[str, Any],
        *,
        search_id: str | None = None,
    ) -> dict[str, Any]:
        """Call ``POST /tools/execute`` and hydrate truncated results.

        Args:
            tool_id: QVeris tool identifier returned by search.
            parameters: Provider parameters.
            search_id: Optional search correlation id.

        Returns:
            Decoded execute response, with ``result`` replaced by downloaded
            full JSON when QVeris returned ``full_content_file_url``.
        """
        body: dict[str, Any] = {
            "parameters": parameters,
            "max_response_size": 20480,
        }
        if search_id:
            body["search_id"] = search_id
        payload = self._post_json(f"/tools/execute?tool_id={tool_id}", body)
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            full_url = payload["result"].get("full_content_file_url")
            if isinstance(full_url, str) and full_url:
                payload = dict(payload)
                payload["result"] = self._get_json(full_url)
        return payload

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._config.base_url}{path}"
        response = self._request("post", url, json=body, auth=True)
        decoded = response.json()
        return decoded if isinstance(decoded, dict) else {}

    def _get_json(self, url: str) -> Any:
        response = self._request("get", url, auth=False)
        try:
            return response.json()
        except ValueError:
            return json.loads(response.text)

    def _request(self, method: str, url: str, *, auth: bool, **kwargs: Any) -> requests.Response:
        headers = {"User-Agent": "Vibe-Trading/1.0"}
        if auth:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        for attempt in range(_MAX_RETRIES + 1):
            self._wait()
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=_HTTP_TIMEOUT_S,
                **kwargs,
            )
            if response.status_code != 429:
                response.raise_for_status()
                return response
            if attempt == _MAX_RETRIES:
                response.raise_for_status()
            time.sleep(_retry_after_seconds(response))
        raise AssertionError("unreachable: retry loop must return or raise")

    def _wait(self) -> None:
        interval = _min_interval()
        if interval <= 0:
            return
        now = time.monotonic()
        sleep_for = self._last_request_at + interval - now
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last_request_at = time.monotonic()


def _retry_after_seconds(response: requests.Response) -> float:
    """Parse a Retry-After header, falling back to the default interval."""
    raw = response.headers.get("Retry-After", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = _min_interval()
    return max(value, 0.0)


@register
class DataLoader:
    """QVeris OHLCV loader, available only when explicitly configured."""

    name = "qveris"
    markets = {"crypto", "forex", "macro"}
    requires_auth = True

    def __init__(self) -> None:
        """Initialize without network access."""
        self._config = _load_config()

    def is_available(self) -> bool:
        """Return whether paid QVeris routing is enabled and keyed."""
        return self._config.enabled and bool(self._config.api_key) and self._config.mode == "paid"

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch daily OHLCV history through selected QVeris capabilities.

        Args:
            codes: Symbols to fetch.
            start_date: Inclusive ``YYYY-MM-DD`` start date.
            end_date: Inclusive ``YYYY-MM-DD`` end date.
            interval: Bar interval. QVeris selection is optimized for daily
                bars; non-daily values are passed through when a tool accepts an
                interval-like parameter.
            fields: Ignored; QVeris loader returns the standard OHLCV columns.

        Returns:
            Mapping of input symbol to normalized OHLCV DataFrames.

        Raises:
            ValueError: If ``start_date`` > ``end_date``.
            NoAvailableSourceError: If a symbol belongs to a market with
                corporate actions, whose price adjustment this loader cannot
                establish (#1494). Nothing is fetched or billed.
        """
        del fields
        validate_date_range(start_date, end_date)
        # A market with splits and dividends would be served by whichever
        # capability ranks first in search, and the ranking ignores adjustment:
        # for 600519.SH the top pick was FMP's non_split_adjusted EOD, and
        # mkt_bars_adjusted routed to a tool whose adj_close equalled the raw
        # closes (#1494). No capability is pinned to a measured adjustment, so
        # such a bar has no caliber anyone can state, and "unknown" stays out of
        # every run-level caliber check. Refused before anything is billed.
        refused = {code: _detect_market(code) for code in codes}
        refused = {code: market for code, market in refused.items() if market_has_corporate_actions(market)}
        if refused:
            raise NoAvailableSourceError(
                "source='qveris' does not serve markets with splits and dividends: it "
                "picks a capability by search rank, which ignores price adjustment, so "
                "these bars would reach the run at an adjustment nobody can state "
                "(#1494). Refused: "
                + ", ".join(f"{code} ({market})" for code, market in refused.items())
                + ". Use a source with a measured price caliber for these symbols."
            )
        if not self.is_available():
            logger.warning("qveris fetch skipped: disabled or %s not set", _API_KEY_ENV)
            return {}

        client = QVerisClient(self._config)
        budget_state = {"spent": 0.0}
        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(
                        client,
                        code,
                        start_date,
                        end_date,
                        interval,
                        budget_state,
                    ),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 - one symbol must not abort the batch
                logger.warning("qveris failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self,
        client: QVerisClient,
        code: str,
        start_date: str,
        end_date: str,
        interval: str,
        budget_state: dict[str, float],
    ) -> Optional[pd.DataFrame]:
        search_payload = client.search(_search_query(code, interval))
        candidates = _select_capabilities(search_payload.get("results"), interval)
        search_id = _str_or_none(search_payload.get("search_id"))
        for capability in candidates:
            tool_id = str(capability.get("tool_id") or "").strip()
            if not tool_id:
                continue
            quoted_cost = _expected_cost(capability.get("expected_cost"))
            if not math.isfinite(quoted_cost):
                logger.warning(
                    "QVeris capability %s skipped for %s: quote %r is not a flat "
                    "price per call, so no reservation bounds its bill",
                    tool_id,
                    code,
                    capability.get("expected_cost"),
                )
                continue
            if budget_state["spent"] + quoted_cost > self._config.budget_credits_per_session:
                logger.warning(
                    "QVeris paid capability skipped for %s: credit budget exceeded",
                    code,
                )
                continue
            parameters = _build_parameters(capability, code, start_date, end_date, interval)
            # Reserve the quoted cost before the request. If transport fails
            # after the provider accepted it, later symbols still fail closed.
            budget_state["spent"] += quoted_cost
            execute_payload = client.execute(tool_id, parameters, search_id=search_id)
            try:
                actual_cost = float(execute_payload.get("cost"))
            except (TypeError, ValueError):
                actual_cost = quoted_cost
            if math.isfinite(actual_cost) and actual_cost > quoted_cost:
                budget_state["spent"] += actual_cost - quoted_cost
            if execute_payload.get("success") is False:
                logger.warning("QVeris execute failed for %s via %s", code, tool_id)
                continue
            frame = _result_to_frame(execute_payload.get("result"), start_date, end_date)
            if frame is not None:
                return frame
            logger.warning("QVeris result for %s via %s had no parseable bars", code, tool_id)
        return None


_MAX_CANDIDATES = 3


def _search_query(symbol: str, interval: str) -> str:
    """Build a capability-search query for one symbol."""
    return f"daily OHLCV historical market data for {symbol.strip().upper()} interval {interval}"


def _select_capabilities(results: Any, interval: str) -> list[dict[str, Any]]:
    """Rank OHLCV-like capabilities, excluding wrong-granularity series."""
    if not isinstance(results, list):
        return []
    wanted, unwanted = _granularity_tokens(interval)
    candidates = []
    for item in results:
        if not isinstance(item, dict) or not _looks_ohlcv(item):
            continue
        text = _capability_text(item)
        if any(token in text for token in unwanted):
            continue
        priority = 0 if any(token in text for token in wanted) else 1
        candidates.append((priority, item))
    ranked = sorted(candidates, key=lambda pair: (pair[0],) + _capability_rank(pair[1]))
    return [item for _, item in ranked[:_MAX_CANDIDATES]]


def _capability_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "").lower() for key in ("tool_id", "name", "description")
    )


def _granularity_tokens(interval: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (wanted, unwanted) capability-text tokens for a bar interval.

    ``1m``/``5m``/``15m``/``30m`` are case-sensitive minute tokens; ``1M`` is
    month. Lowercasing first would collapse ``1m`` into an empty match and let
    daily capabilities outrank minute ones.
    """
    token = interval.strip()
    norm = token.lower()
    intraday = ("intraday", "minute", "1min", "5min", "15min", "30min", "60min", "hourly")
    if norm in ("", "1d", "d", "day", "daily"):
        return ("daily", "eod", "end-of-day", "end of day"), ("monthly", "weekly") + intraday
    # Case-sensitive: ``1M`` (month) must not be treated as ``1m`` (minute).
    if token == "1M" or "month" in norm:
        return ("monthly",), ("weekly",) + intraday
    if token in {"1m", "5m", "15m", "30m"} or "min" in norm or norm in ("1h", "4h") or "hour" in norm:
        return intraday, ("monthly", "weekly")
    if "w" in norm or "week" in norm:
        return ("weekly",), ("monthly",) + intraday
    if "mo" in norm:
        return ("monthly",), ("weekly",) + intraday
    return (), ()


def _looks_ohlcv(item: dict[str, Any]) -> bool:
    text_parts = [
        item.get("name"),
        item.get("description"),
        item.get("provider_name"),
        json.dumps(item.get("params") or "", default=str),
        json.dumps(item.get("examples") or "", default=str),
    ]
    text = " ".join(str(part or "").lower() for part in text_parts)
    has_price = any(token in text for token in ("ohlcv", "open", "high", "low", "close", "candle", "historical price"))
    has_symbol = any(token in text for token in ("symbol", "ticker", "instrument", "code"))
    return has_price and has_symbol


def _capability_rank(item: dict[str, Any]) -> tuple[float, float, str]:
    success_rate = _success_rate(item.get("stats"))
    cost = _expected_cost(item.get("expected_cost"))
    return (-success_rate, cost, str(item.get("tool_id") or item.get("name") or ""))


def _success_rate(stats: Any) -> float:
    if not isinstance(stats, dict):
        return 0.0
    value = stats.get("success_rate", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed / 100.0 if parsed > 1.0 else parsed


def quoted_call_cost(value: Any) -> float | None:
    """Return the credits one call can cost under ``value``, or None.

    Args:
        value: A capability's ``expected_cost`` quote.

    Returns:
        The flat per-call price, or None when the quote does not bound the
        bill: absent, negative, priced per result/row/value, or in any shape
        ``_FLAT_QUOTE`` does not describe.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    match = _FLAT_QUOTE.fullmatch(str(value).strip().lower())
    return float(match.group(1)) if match else None


def _expected_cost(value: Any) -> float:
    cost = quoted_call_cost(value)
    return float("inf") if cost is None else cost


def _build_parameters(
    capability: dict[str, Any],
    code: str,
    start_date: str,
    end_date: str,
    interval: str,
) -> dict[str, Any]:
    """Build an execute parameter object from examples plus known date keys."""
    parameters = _sample_parameters(capability)
    for param in capability.get("params") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if _is_symbol_param(lower):
            parameters[name] = code.strip().upper()
        elif _is_start_param(lower):
            parameters[name] = start_date
        elif _is_end_param(lower):
            parameters[name] = end_date
        elif _is_interval_param(lower):
            parameters[name] = _interval_value(param, interval)
    return parameters


def _sample_parameters(capability: dict[str, Any]) -> dict[str, Any]:
    examples = capability.get("examples")
    if not isinstance(examples, dict):
        return {}
    sample = examples.get("sample_parameters")
    return dict(sample) if isinstance(sample, dict) else {}


def _is_symbol_param(name: str) -> bool:
    return any(token in name for token in ("symbol", "ticker", "instrument", "code"))


def _is_start_param(name: str) -> bool:
    return any(token in name for token in ("start", "from", "begin")) and "end" not in name


def _is_end_param(name: str) -> bool:
    normalized = name.replace("-", "_")
    return normalized in {
        "end",
        "end_date",
        "enddate",
        "to",
        "to_date",
        "until",
        "until_date",
    }


def _is_interval_param(name: str) -> bool:
    return any(token in name for token in ("interval", "timeframe", "resolution", "frequency"))


def _interval_value(param: dict[str, Any], interval: str) -> str:
    enum = param.get("enum")
    if isinstance(enum, list):
        lowered = {str(value).lower(): value for value in enum}
        for candidate in (interval, interval.lower(), "1d", "d", "daily"):
            if candidate.lower() in lowered:
                return str(lowered[candidate.lower()])
    return "daily" if interval.upper() == "1D" else interval


def _response_field_set(records: list[dict[str, Any]]) -> dict[str, tuple[str, ...]] | None:
    """Return the one alias table every usable record in a response supports.

    Choosing per record let one payload carry an unadjusted row and an
    adjusted-only row, and the series then mixed the two price levels (#1527).
    Records with no complete quartet are skipped as before; if the rest do not
    share a family the response yields no bars rather than a mixed series.
    """
    complete = [
        [table for table in (_FIELD_ALIASES, _ADJUSTED_FIELD_ALIASES) if _resolve_field_set_in(keys, table)]
        for keys in ({str(key).lower() for key in record} for record in records)
    ]
    complete = [tables for tables in complete if tables]
    for table in (_FIELD_ALIASES, _ADJUSTED_FIELD_ALIASES):
        if complete and all(table in tables for tables in complete):
            return table
    if complete:
        logger.warning("QVeris response mixes unadjusted and adjusted records; no bars built from it")
    return None


def _resolve_field_set_in(keys: set[str], table: dict[str, tuple[str, ...]]) -> bool:
    return all(any(alias in keys for alias in table[field]) for field in _PRICE_QUARTET)


def _result_to_frame(result: Any, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    records = list(_iter_ohlcv_records(result))
    table = _response_field_set(records)
    if table is None:
        return None
    rows = [_normalize_record(record, table) for record in records]
    cleaned = [row for row in rows if row is not None]
    if not cleaned:
        return None

    df = pd.DataFrame(cleaned)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype(
        "datetime64[ns]"
    )
    for field in _OHLCV_COLUMNS:
        if field not in df.columns:
            df[field] = None
        df[field] = pd.to_numeric(df[field], errors="coerce").astype(float)
    df = df.dropna(subset=["trade_date", "open", "high", "low", "close"])
    if df.empty:
        return None

    df = df.set_index("trade_date").sort_index()
    df = df[_OHLCV_COLUMNS]
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    df = df.loc[(df.index >= start) & (df.index <= end)]
    df = validate_ohlc(df)
    return None if df.empty else df


def _iter_ohlcv_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield dict-like OHLCV records from common QVeris/provider shapes."""
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_ohlcv_records(item)
        return
    if not isinstance(payload, dict):
        return

    if _record_has_ohlc(payload):
        yield payload

    date_keyed = _date_keyed_records(payload)
    if date_keyed is not None:
        yield from date_keyed
        return

    yielded = False
    for key in (
        "data",
        "results",
        "result",
        "historical",
        "prices",
        "items",
        "rows",
        "candles",
        "values",
        "time_series",
        "Time Series (Daily)",
    ):
        if key in payload:
            for record in _iter_ohlcv_records(payload[key]):
                yielded = True
                yield record
    if yielded:
        return
    # Provider-specific series containers ("Weekly Adjusted Time Series",
    # "Time Series (5min)", ...) — any nested dict of date-keyed records.
    for value in payload.values():
        if isinstance(value, dict):
            date_keyed = _date_keyed_records(value)
            if date_keyed:
                yield from date_keyed


def _date_keyed_records(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows: list[dict[str, Any]] = []
    for key, value in payload.items():
        if not isinstance(value, dict) or not _looks_like_date(key):
            return None
        row = dict(value)
        row.setdefault("trade_date", key)
        rows.append(row)
    return rows if rows else None


def _looks_like_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        pd.Timestamp(value)
    except Exception:
        return False
    return True


def _resolve_field_set(keys: Iterable[str]) -> dict[str, tuple[str, ...]] | None:
    """Return the alias table that supplies one complete price quartet.

    The unadjusted table wins when a record carries both sets, which is the
    preference the previous single-table lookup had. ``None`` means neither
    table is complete, so a bar is never assembled from a mix of unadjusted and
    adjusted fields.
    """
    for table in (_FIELD_ALIASES, _ADJUSTED_FIELD_ALIASES):
        if _resolve_field_set_in(set(keys), table):
            return table
    return None


def _record_has_ohlc(record: dict[str, Any]) -> bool:
    return _resolve_field_set({str(key).lower() for key in record}) is not None


def _normalize_record(record: dict[str, Any], table: dict[str, tuple[str, ...]]) -> dict[str, Any] | None:
    """Build one bar from ``record`` using the response's alias ``table``.

    An unadjusted bar never takes ``adj_volume``: split-adjusted volume is not
    on the scale of unadjusted prices, so a missing unadjusted volume stays NaN.
    """
    lowered = {str(key).lower(): value for key, value in record.items()}
    date = _first_value(lowered, _DATE_KEYS)
    if date is None:
        return None
    row = {"trade_date": date}
    for field in _OHLCV_COLUMNS:
        row[field] = _first_value(lowered, table[field])
    if any(row[field] is None for field in _PRICE_QUARTET):
        return None
    return row


def _first_value(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
