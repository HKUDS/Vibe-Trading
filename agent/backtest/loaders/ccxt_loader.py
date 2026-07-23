"""CCXT loader: unified crypto exchange data (100+ exchanges).

Uses the CCXT library to fetch OHLCV candles from any supported exchange.
Defaults to Binance; configurable via CCXT_EXCHANGE env var.
No API key required for public market data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import (
    cached_loader_fetch,
    check_budget,
    positive_env_float,
    positive_env_int,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1w", "1M": "1M",
}

_TIMEFRAME_DELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
    "1w": pd.Timedelta(weeks=1),
    "1M": pd.Timedelta(days=31),
}

# P12-b: ccxt had no request timeout and an unbounded paginated fetch with
# no retry budget, so a transient disconnect hung get_market_data for 10+
# minutes. Cap each HTTP call, bound transient retries, and enforce a hard
# wall-clock budget so the fetch fails fast instead of hanging. Retry
# scheduling is delegated to :mod:`backtest.loaders.base`.
_CCXT_TIMEOUT_MS = positive_env_int("CCXT_TIMEOUT_MS", 15_000)
_CCXT_FETCH_BUDGET_S = positive_env_float("CCXT_FETCH_BUDGET_S", 60.0)
_FUNDING_HOURS = {0, 8, 16}


def _parse_ccxt_symbol(code: str) -> tuple[str, str]:
    """Return the canonical CCXT symbol and instrument type for ``code``."""
    normalized = code.strip().upper()
    if normalized.endswith("-PERP"):
        match = re.fullmatch(r"([A-Z0-9]+)-USDT-PERP", normalized)
        if match is None:
            raise ValueError(
                "USD-M perpetual symbol must use BASE-USDT-PERP, e.g. BTC-USDT-PERP"
            )
        return f"{match.group(1)}/USDT:USDT", "swap"
    return normalized.replace("-", "/"), "spot"


def _first_proxy_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()  # noqa: env-gate — system proxy vars
        if value:
            return value
    return ""


def _ccxt_proxy_config() -> dict[str, str]:
    """Build CCXT proxy settings from conventional proxy environment variables."""
    all_proxy = _first_proxy_env("ALL_PROXY", "all_proxy")
    http_proxy = _first_proxy_env("HTTP_PROXY", "http_proxy") or all_proxy
    https_proxy = _first_proxy_env("HTTPS_PROXY", "https_proxy") or all_proxy or http_proxy

    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


_BRACKET_SCHEMA_VERSION = 1


def _validate_bracket_artifact(artifact: dict, *, expected_symbol: str) -> tuple[list[dict], str]:
    """Validate a caller-supplied maintenance-bracket artifact.

    ``binanceusdm.fetch_leverage_tiers()`` routes to Binance's signed
    ``GET /fapi/v1/leverageBracket`` USER_DATA endpoint — it requires an API
    key even though the response carries no account-specific data. This
    loader no longer calls it: maintenance brackets are supplied out of band
    as a versioned artifact and validated here, never fetched live. Fails
    closed (raises ``ValueError``) on any schema, symbol, provenance,
    ordering, or content-hash problem.
    """
    if not isinstance(artifact, dict):
        raise ValueError("bracket artifact must be a dict")

    schema_version = artifact.get("schema_version")
    if schema_version != _BRACKET_SCHEMA_VERSION:
        raise ValueError(
            f"bracket artifact schema_version must be {_BRACKET_SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )

    symbol = artifact.get("symbol")
    if symbol != expected_symbol:
        raise ValueError(
            f"bracket artifact symbol mismatch: expected {expected_symbol!r}, got {symbol!r}"
        )

    provenance_timestamp = artifact.get("provenance_timestamp")
    if not provenance_timestamp:
        raise ValueError("bracket artifact is missing provenance_timestamp")
    try:
        pd.Timestamp(provenance_timestamp)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"bracket artifact provenance_timestamp is not a valid timestamp: "
            f"{provenance_timestamp!r}"
        ) from exc

    brackets = artifact.get("brackets")
    if not brackets:
        raise ValueError("bracket artifact has no brackets")

    normalized: list[dict] = []
    for tier in brackets:
        try:
            record = {
                "bracket_tier": int(tier["bracket_tier"]),
                "notional_cap": float(tier["notional_cap"]),
                "maintenance_rate": float(tier["maintenance_rate"]),
                "cumulative_maintenance_amount": float(tier["cumulative_maintenance_amount"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"bracket artifact tier for {expected_symbol} is missing a required field: {exc}"
            ) from exc
        # Optional: reserved for future risk-model calibration, not part of
        # Binance's own bracket schema. Validated only if present.
        coefficient = tier.get("notional_coefficient")
        if coefficient is not None:
            try:
                record["notional_coefficient"] = float(coefficient)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"bracket artifact notional_coefficient must be numeric: {coefficient!r}"
                ) from exc
        normalized.append(record)

    normalized.sort(key=lambda row: row["bracket_tier"])
    caps = [row["notional_cap"] for row in normalized]
    if caps != sorted(caps) or len(caps) != len(set(caps)):
        raise ValueError(
            f"bracket artifact notional caps for {expected_symbol} are not strictly increasing"
        )

    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    computed_hash = hashlib.sha256(blob).hexdigest()[:16]
    content_hash = artifact.get("content_hash")
    if content_hash != computed_hash:
        raise ValueError(
            f"bracket artifact content_hash mismatch for {expected_symbol}: "
            f"expected {computed_hash}, artifact declares {content_hash!r}"
        )

    return normalized, computed_hash


@register
class DataLoader:
    """CCXT-backed crypto OHLCV loader (100+ exchanges)."""

    name = "ccxt"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available if ccxt is installed."""
        try:
            import ccxt  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        pass

    def _get_exchange(self, instrument_type: str = "spot"):
        """Create an exchange instance for spot or Binance USD-M swaps."""
        import ccxt
        from src.config.accessor import get_env_config

        exchange_id = get_env_config().data.ccxt_exchange.lower()
        if instrument_type == "swap":
            if exchange_id not in {"binance", "binanceusdm"}:
                raise ValueError(
                    "BASE-USDT-PERP currently requires CCXT_EXCHANGE=binance"
                )
            exchange_id = "binanceusdm"
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            logger.warning("Unknown CCXT exchange %s, falling back to binance", exchange_id)
            exchange_cls = ccxt.binance

        config = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
        proxies = _ccxt_proxy_config()
        if proxies:
            config["proxies"] = proxies
        return exchange_cls(config)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
        bracket_artifacts: Optional[Dict[str, dict]] = None,
        require_brackets: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch crypto OHLCV via CCXT.

        Args:
            codes: Symbols like ``["BTC-USDT", "ETH-USDT"]``.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            interval: Bar size.
            fields: Ignored.
            bracket_artifacts: Optional ``{code: artifact}`` map of caller-supplied,
                versioned maintenance-bracket artifacts (see
                ``_validate_bracket_artifact``) for ``-PERP`` codes. Normal
                execution/mark/funding data never needs this — it stays
                zero-credential regardless. This loader does not fetch brackets
                live: ``binanceusdm.fetch_leverage_tiers()`` requires a Binance
                API key, which this historical/backtest path never carries.
            require_brackets: When True, a ``-PERP`` code without a matching,
                valid artifact in ``bracket_artifacts`` fails closed instead of
                silently returning data without bracket columns. Intended for
                strict margin-risk consumers.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        timeframe = _INTERVAL_MAP.get(interval, "1d")
        since_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp() * 1000)

        # Build the exchange lazily so a full cache hit never imports ccxt or
        # opens an exchange object.
        exchange_holder: Dict[str, object] = {}

        def get_exchange(instrument_type: str):
            if instrument_type not in exchange_holder:
                exchange_holder[instrument_type] = self._get_exchange(instrument_type)
            return exchange_holder[instrument_type]

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            instrument_type = "spot"
            try:
                ccxt_symbol, instrument_type = _parse_ccxt_symbol(code)
                exchange = get_exchange(instrument_type)
                artifact = (bracket_artifacts or {}).get(code)

                def fetch_frame():
                    if instrument_type == "swap":
                        return self._fetch_perpetual(
                            exchange, ccxt_symbol, timeframe, since_ms, end_ms,
                            bracket_artifact=artifact, require_brackets=require_brackets,
                        )
                    return self._fetch_one(
                        exchange, ccxt_symbol, timeframe, since_ms, end_ms
                    )

                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=fetch_frame,
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                if instrument_type == "swap" or code.strip().upper().endswith("-PERP"):
                    raise
                logger.warning("CCXT failed for %s: %s", code, exc)
        return result

    @classmethod
    def _fetch_perpetual(
        cls, exchange, symbol: str, timeframe: str, since_ms: int, end_ms: int,
        *, bracket_artifact: dict | None = None, require_brackets: bool = False,
    ) -> pd.DataFrame:
        """Fetch aligned trade-price and mark-price candles for one USD-M swap.

        Maintenance brackets are never fetched live (see
        ``_validate_bracket_artifact``): they're attached only when the caller
        supplies a validated artifact. A strict caller (``require_brackets``)
        fails closed before any network call when no artifact is supplied.
        """
        if require_brackets and bracket_artifact is None:
            raise ValueError(
                f"strict margin-risk fetch for {symbol} requires a maintenance-bracket "
                "artifact, but none was supplied. This loader does not perform a live "
                "authenticated bracket fetch (binanceusdm.fetch_leverage_tiers requires "
                "a Binance API key this backtest path does not carry) — pass a validated "
                "artifact via DataLoader.fetch(bracket_artifacts={code: artifact})."
            )

        trade = cls._fetch_one(exchange, symbol, timeframe, since_ms, end_ms)
        mark = cls._fetch_one(
            exchange,
            symbol,
            timeframe,
            since_ms,
            end_ms,
            params={"price": "mark"},
        )
        if trade is None or mark is None or not trade.index.equals(mark.index):
            raise ValueError(f"mark-price timestamps are incomplete or unsynchronized for {symbol}")

        result = trade.copy()
        result["execution_open"] = trade["open"]
        for column in ("open", "high", "low", "close"):
            result[f"mark_{column}"] = mark[column]

        funding = cls._fetch_funding_history(exchange, symbol, since_ms, end_ms)
        if funding.index.has_duplicates:
            raise ValueError(f"duplicate funding settlement for {symbol}")
        required = result.index[result.index.hour.isin(_FUNDING_HOURS)]
        missing = required.difference(funding.index)
        if not missing.empty:
            raise ValueError(
                f"funding settlement data is missing for {symbol}: "
                f"{', '.join(str(ts) for ts in missing)}"
            )

        result["funding_rate"] = 0.0
        result["funding_settlement_time"] = pd.NaT
        aligned = funding.index.intersection(result.index)
        if not aligned.empty:
            result.loc[aligned, "funding_rate"] = funding.loc[aligned, "funding_rate"]
            result.loc[aligned, "funding_settlement_time"] = aligned

        if bracket_artifact is not None:
            brackets, version = _validate_bracket_artifact(
                bracket_artifact, expected_symbol=symbol
            )
            result["maintenance_brackets"] = json.dumps(brackets)
            result["maintenance_bracket_version"] = version
        return result

    @staticmethod
    def _fetch_funding_history(
        exchange, symbol: str, since_ms: int, end_ms: int,
    ) -> pd.DataFrame:
        """Fetch bounded historical funding settlements for one USD-M swap."""
        import ccxt

        rows: list[dict] = []
        cursor = since_ms
        limit = 1000
        deadline = time.monotonic() + _CCXT_FETCH_BUDGET_S
        label = f"ccxt funding fetch for {symbol}"

        for _ in range(200):
            check_budget(deadline, label, budget_s=_CCXT_FETCH_BUDGET_S)
            page = retry_with_budget(
                lambda: exchange.fetch_funding_rate_history(
                    symbol, since=cursor, limit=limit
                ),
                transient=ccxt.NetworkError,
                deadline=deadline,
                label=label,
            )
            if not page:
                break
            rows.extend(page)
            last_ts = int(page[-1]["timestamp"])
            if last_ts >= end_ms or len(page) < limit:
                break
            cursor = last_ts + 1

        if not rows:
            return pd.DataFrame(
                {"funding_rate": pd.Series(dtype=float)},
                index=pd.DatetimeIndex([], name="trade_date"),
            )

        frame = pd.DataFrame({
            "trade_date": pd.to_datetime(
                [row["timestamp"] for row in rows], unit="ms"
            ),
            "funding_rate": pd.to_numeric(
                [row["fundingRate"] for row in rows], errors="raise"
            ),
        }).set_index("trade_date").sort_index()
        start_dt = pd.Timestamp(since_ms, unit="ms")
        end_dt = pd.Timestamp(end_ms, unit="ms")
        return frame[(frame.index >= start_dt) & (frame.index < end_dt)]

    @staticmethod
    def _fetch_one(
        exchange,
        symbol: str,
        timeframe: str,
        since_ms: int,
        end_ms: int,
        *,
        params: dict[str, str] | None = None,
    ) -> Optional[pd.DataFrame]:
        """Paginated OHLCV fetch for one symbol."""
        import ccxt

        all_rows: list = []
        cursor = since_ms
        limit = 1000
        deadline = time.monotonic() + _CCXT_FETCH_BUDGET_S
        label = f"ccxt fetch for {symbol}"
        hit_page_cap = True

        for _ in range(200):
            check_budget(deadline, label, budget_s=_CCXT_FETCH_BUDGET_S)
            # ``ccxt.NetworkError`` covers RequestTimeout / DDoSProtection /
            # ExchangeNotAvailable — the transient family. Anything else
            # (e.g. ``ExchangeError`` for a bad symbol) is not retried.
            def fetch_page():
                kwargs = {"since": cursor, "limit": limit}
                if params is not None:
                    kwargs["params"] = params
                return exchange.fetch_ohlcv(symbol, timeframe, **kwargs)

            ohlcv = retry_with_budget(
                fetch_page,
                transient=ccxt.NetworkError,
                deadline=deadline,
                label=label,
            )
            if not ohlcv:
                hit_page_cap = False
                break
            all_rows.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            if last_ts >= end_ms or len(ohlcv) < limit:
                hit_page_cap = False
                break
            cursor = last_ts + 1

        if not all_rows:
            return None

        df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["trade_date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("trade_date").sort_index()

        start_dt = pd.Timestamp(since_ms, unit="ms")
        end_dt = pd.Timestamp(end_ms, unit="ms")
        df = df[(df.index >= start_dt) & (df.index < end_dt)]

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        if df.empty:
            return None

        tolerance = _TIMEFRAME_DELTA.get(timeframe)
        if tolerance is None:
            raise ValueError(f"unsupported CCXT timeframe: {timeframe}")
        if hit_page_cap and df.index[-1] < end_dt - tolerance:
            raise ValueError(
                f"incomplete CCXT history for {symbol}: requested "
                f"[{start_dt}, {end_dt}), received [{df.index[0]}, {df.index[-1]}]"
            )
        return df
