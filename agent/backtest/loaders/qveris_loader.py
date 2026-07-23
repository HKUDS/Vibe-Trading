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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

from backtest.loaders.base import (
    cached_loader_fetch,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

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
_FIELD_ALIASES = {
    "open": ("open", "o", "1. open"),
    "high": ("high", "h", "2. high"),
    "low": ("low", "l", "3. low"),
    "close": ("close", "c", "adj_close", "adjusted_close", "4. close"),
    "volume": ("volume", "vol", "v", "5. volume", "6. volume"),
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
    markets = {"us_equity", "hk_equity", "a_share", "crypto", "forex", "fund", "macro"}
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
        """
        del fields
        validate_date_range(start_date, end_date)
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
            if (
                not math.isfinite(quoted_cost)
                or quoted_cost < 0.0
                or budget_state["spent"] + quoted_cost
                > self._config.budget_credits_per_session
            ):
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


def _expected_cost(value: Any) -> float:
    if value is None:
        return float("inf")
    text = str(value)
    number = ""
    for char in text:
        if char.isdigit() or char == ".":
            number += char
        elif number:
            break
    try:
        return float(number)
    except ValueError:
        return float("inf")


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
            parameters[name] = _provider_symbol(code)
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


def _provider_symbol(code: str) -> str:
    """Normalize common project US suffixes while preserving other markets."""
    upper = code.strip().upper()
    if upper.endswith(".US"):
        return upper[: -len(".US")]
    return upper


def _is_symbol_param(name: str) -> bool:
    return any(token in name for token in ("symbol", "ticker", "instrument", "code"))


def _is_start_param(name: str) -> bool:
    return any(token in name for token in ("start", "from", "begin")) and "end" not in name


def _is_end_param(name: str) -> bool:
    return any(token in name for token in ("end", "to", "until"))


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


def _result_to_frame(result: Any, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    rows = [_normalize_record(record) for record in _iter_ohlcv_records(result)]
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


def _record_has_ohlc(record: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in record}
    return all(any(alias in lowered for alias in aliases) for aliases in (
        _FIELD_ALIASES["open"],
        _FIELD_ALIASES["high"],
        _FIELD_ALIASES["low"],
        _FIELD_ALIASES["close"],
    ))


def _normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    lowered = {str(key).lower(): value for key, value in record.items()}
    date = _first_value(lowered, _DATE_KEYS)
    if date is None:
        return None
    row = {"trade_date": date}
    for field, aliases in _FIELD_ALIASES.items():
        row[field] = _first_value(lowered, aliases)
    if any(row[field] is None for field in ("open", "high", "low", "close")):
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
