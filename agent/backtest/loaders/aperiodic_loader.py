"""Aperiodic loader: perpetual-futures bars for Binance, OKX and Hyperliquid.

Aperiodic (https://aperiodic.io) serves point-in-time perpetual-futures data
through its ``aperiodic`` Python SDK: OHLCV bars and the funding rate each
venue published, for Binance USD-M futures, OKX swaps and Hyperliquid perps.
That includes Hyperliquid HIP-3 markets (tokenized stocks, indices and
commodities listed by a builder dex such as ``xyz``) and contracts that have
since been delisted. Published bars are not revised afterwards.

The source is opt-in. It joins no fallback chain, and an explicit request never
degrades to another loader (``registry._NO_NETWORK_FALLBACK_SOURCES``): the
same pair on another venue is a different instrument.

Symbols name the venue, because the same pair trades on several of them::

    BINANCE.BTC-USDT-PERP           binance-futures    perpetual-BTC-USDT:USDT
    OKX.ETH-USDT-PERP               okx-perps          perpetual-ETH-USDT:USDT
    HYPERLIQUID.BTC-USDC-PERP       hyperliquid-perps  perpetual-BTC-USDC:USDC
    HYPERLIQUID.XYZ.TSLA-USDC-PERP  hyperliquid-perps  perpetual-XYZ:TSLA-USDC:USDC

Dots, not colons, separate the parts: the symbol ends up in run artifact file
names (``ohlcv_<code>.csv``), which may not contain a colon on Windows.
``BASE-USDT-PERP`` without a venue stays with the ccxt/Binance loader. Only
linear contracts quoted and settled in a USD stablecoin are accepted, the
contract the crypto market's USD accounting assumes.

Access: ``APERIODIC_API_KEY`` is sent with every request, and the plan behind
it decides what is served. Without a key the request goes to Aperiodic's
public preview, which serves a single sample and refuses everything else. A
refusal (HTTP 400/401/403) is raised with the API's own message rather than
read as "no data".

Frames are indexed by bar open in tz-naive UTC, like the ccxt perpetual path,
and carry ``open``/``high``/``low``/``close``/``volume`` (base-asset units)
plus ``funding_rate``. The crypto engine settles funding at 00:00, 08:00 and
16:00 UTC from that column (``engines._market_hooks.calc_crypto_funding_fee``),
so it is filled in the same convention as the ccxt frame: on the first bar of
each settlement hour it holds the last rate the venue published before that
hour (for the first slot of the range, the first rate published in it), and
0.0 on every other bar. A venue's rate is quoted per its own funding period,
so it is restated per 8 hours: Hyperliquid funds hourly and its rate is
multiplied by 8. Binance and OKX are taken to fund every 8 hours, which holds
for most but not all of their contracts. A published rate is the venue's
prediction until settlement, not the settled-rate history. A settlement slot
with no published rate fails the symbol, as a missing settlement does on the
ccxt path, rather than settling at the engine's configured fixed rate.
Mark-price candles and maintenance brackets are not served, so
``perpetual_strict`` runs remain on the ccxt/Binance path.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from backtest.engines._market_hooks import FUNDING_HOURS, VENUE_PERP_PATTERN
from backtest.loaders.base import (
    NoAvailableSourceError,
    acquisition_error_kind,
    loader_cache_get,
    loader_cache_put,
    validate_date_range,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_AUTH_ENV = "APERIODIC_API_KEY"
_KEY_PLACEHOLDERS = {"", "your_aperiodic_api_key", "changeme", "xxx"}
_INSTALL_HINT = "pip install 'vibe-trading-ai[aperiodic]'"
_SIGNUP_URL = "https://aperiodic.io"

_EXCHANGES = {
    "BINANCE": "binance-futures",
    "OKX": "okx-perps",
    "HYPERLIQUID": "hyperliquid-perps",
}

# Hours between funding settlements that each venue's published rate refers to.
_VENUE_FUNDING_HOURS = {
    "binance-futures": 8,
    "okx-perps": 8,
    "hyperliquid-perps": 1,
}
_ENGINE_FUNDING_HOURS = 8

# Project interval -> Aperiodic interval. Weekly and monthly bars are built
# from daily ones upstream (``base.RESAMPLED_INTERVALS``).
_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "1h": "1h",
    "4H": "4h",
    "4h": "4h",
    "1D": "1d",
    "1d": "1d",
}
_BAR_SPAN = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
# Timestamps as the exchange reported them, as the other venue loaders use.
_TIMESTAMP_SOURCE = "exchange"
# Concurrent SDK calls per fetch: two datasets per symbol. The data gateway
# gives one loader call a few seconds (VIBE_GATEWAY_SOURCE_TIMEOUT), which a
# year of bars for two symbols fetched one request at a time already exceeds.
_MAX_PARALLEL_REQUESTS = 8
_URL_RE = re.compile(r"https?://\S+")


class AperiodicRequestError(RuntimeError):
    """Raised when Aperiodic served none of the requested symbols."""


@dataclass(frozen=True)
class Instrument:
    """One Aperiodic market: the SDK's exchange name and Atlas symbol id."""

    exchange: str
    atlas_symbol: str


def parse_symbol(code: str) -> Instrument:
    """Map a project symbol to the Aperiodic market it names.

    Args:
        code: ``VENUE.[DEX.]BASE-QUOTE-PERP``, e.g. ``OKX.BTC-USDT-PERP`` or
            ``HYPERLIQUID.XYZ.TSLA-USDC-PERP``; case-insensitive.

    Returns:
        The SDK exchange name and Atlas symbol id.

    Raises:
        ValueError: The code is not a venue-qualified linear USD perpetual, or
            names a builder dex on a venue other than Hyperliquid.
    """
    match = VENUE_PERP_PATTERN.fullmatch(code.strip().upper())
    if match is None:
        raise ValueError(
            f"{code!r} is not an Aperiodic perpetual symbol; use "
            "VENUE.BASE-QUOTE-PERP with VENUE one of BINANCE, OKX, HYPERLIQUID, "
            "e.g. OKX.BTC-USDT-PERP or HYPERLIQUID.XYZ.TSLA-USDC-PERP"
        )
    venue, dex, base, quote = match.group("venue", "dex", "base", "quote")
    if dex and venue != "HYPERLIQUID":
        raise ValueError(f"{code!r}: a builder dex prefix exists only on HYPERLIQUID")
    market = f"{dex}:{base}" if dex else base
    return Instrument(_EXCHANGES[venue], f"perpetual-{market}-{quote}:{quote}")


def _resolve_key() -> str:
    """Return the configured API key, or ``""`` when unset or a placeholder."""
    from src.config.accessor import get_env_config

    key = get_env_config().data.aperiodic_api_key.strip()
    return "" if key.lower() in _KEY_PLACEHOLDERS else key


def _require_sdk() -> Any:
    """Import and return the ``aperiodic`` SDK.

    Raises:
        NoAvailableSourceError: The SDK, or pyarrow to read its Parquet files,
            is not installed.
    """
    try:
        import aperiodic  # noqa: PLC0415
    except ImportError as exc:
        raise NoAvailableSourceError(
            f"The 'aperiodic' SDK is not installed. Run: {_INSTALL_HINT}"
        ) from exc
    if importlib.util.find_spec("pyarrow") is None:
        raise NoAvailableSourceError(
            f"The 'aperiodic' SDK needs pyarrow to read its data. Run: {_INSTALL_HINT}"
        )
    return aperiodic


def _naive_utc(values: Any) -> pd.DatetimeIndex:
    """Bar times as a tz-naive UTC ``datetime64[ns]`` index."""
    index = pd.DatetimeIndex(pd.to_datetime(values))
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    return index.astype("datetime64[ns]")


def _require_columns(frame: pd.DataFrame, columns: List[str], what: str) -> None:
    missing = [column for column in ["time", *columns] if column not in frame.columns]
    if missing:
        raise ValueError(f"Aperiodic {what} response lacks column(s) {missing}")


def _bars_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Normalize an OHLCV response into the loader frame, without funding."""
    _require_columns(ohlcv, _OHLCV_COLUMNS, "OHLCV")
    frame = (
        ohlcv[_OHLCV_COLUMNS].apply(pd.to_numeric, errors="coerce").astype("float64")
    )
    frame.index = _naive_utc(ohlcv["time"])
    frame.index.name = "trade_date"
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame.dropna(subset=["open", "high", "low", "close"])


def _slot_funding(
    index: pd.DatetimeIndex,
    funding: pd.DataFrame,
    bar: str,
    exchange: str,
    label: str,
) -> pd.Series:
    """Funding per 8-hour settlement slot, on the bar the engine settles it on.

    Args:
        index: Bar-open times of the served frame.
        funding: The SDK's ``funding`` metric: ``time`` (bar open) and
            ``funding_rate`` (the last rate published in that bar).
        bar: Aperiodic interval of both responses.
        exchange: SDK exchange name, which sets the venue's funding period.
        label: Symbol named in errors.

    Returns:
        The rate restated per 8 hours on the first bar of each 00/08/16 UTC
        hour, 0.0 elsewhere.

    Raises:
        ValueError: A settlement slot has no published rate within one bar of
            it, which would otherwise settle at the engine's fixed rate.
    """
    rates = pd.Series(0.0, index=index, name="funding_rate")
    hours = index.floor("h")
    slot_bars = index[index.hour.isin(sorted(FUNDING_HOURS)) & ~hours.duplicated()]
    if slot_bars.empty:
        return rates

    no_rate = (
        f"Aperiodic published no funding rate for {label} between {index[0]} "
        f"and {index[-1]}, the span of its bars"
    )
    if funding is None or funding.empty:
        raise ValueError(no_rate)
    _require_columns(funding, ["funding_rate"], "funding")
    step = _BAR_SPAN[bar]
    published = pd.Series(
        pd.to_numeric(funding["funding_rate"], errors="coerce").to_numpy(
            dtype="float64"
        ),
        # The last rate of a bar is known by the bar's end.
        index=_naive_utc(funding["time"]) + step,
    ).dropna()
    published = published[~published.index.duplicated(keep="last")].sort_index()
    if published.empty:
        raise ValueError(no_rate)

    slots = slot_bars.floor("h")
    observed = pd.DataFrame({"observed": published.index, "rate": published.to_numpy()})
    found = pd.merge_asof(
        pd.DataFrame({"slot": slots}),
        observed,
        left_on="slot",
        right_on="observed",
        direction="backward",
        tolerance=step,
    )["rate"]
    first_at = published.index[0]
    opens_range = (slots < first_at) & (first_at <= slots + step)
    found = found.where(~(found.isna() & opens_range), published.iloc[0])
    missing = slots[found.isna().to_numpy()]
    if not missing.empty and (missing < first_at).all():
        raise ValueError(
            f"Aperiodic has no funding rate for {label} before {first_at - step}, "
            f"but its bars start at {index[0]}; start the range at or after {first_at - step}"
        )
    if not missing.empty:
        raise ValueError(
            f"Aperiodic funding rate is missing for {label} at {len(missing)} "
            f"settlement slot(s), first: {', '.join(str(slot) for slot in missing[:5])}"
        )
    scale = _ENGINE_FUNDING_HOURS / _VENUE_FUNDING_HOURS[exchange]
    rates.loc[slot_bars] = found.to_numpy() * scale
    return rates


def _redact_urls(text: str) -> str:
    """Drop URLs (presigned download links carry signatures) from a message."""
    return _URL_RE.sub("<url>", text)


def _describe_failure(exc: Exception, *, preview: bool) -> str:
    """Explain a failed request, keeping the API's own wording."""
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or not hasattr(exc, "message"):
        return _redact_urls(f"{type(exc).__name__}: {exc}")
    text = f"HTTP {status}: {exc.message}"
    details = getattr(exc, "details", None)
    if details:
        text += f" ({'; '.join(str(item) for item in details)})"
    text = _redact_urls(text)
    if preview:
        text += (
            f". {_AUTH_ENV} is not set, so the request went to Aperiodic's public "
            f"preview, which serves only its sample data. Set {_AUTH_ENV} "
            f"(free account at {_SIGNUP_URL}) to use your plan"
        )
    elif status == 401:
        text += f". {_AUTH_ENV} was rejected"
    elif status == 403:
        text += f". The plan behind {_AUTH_ENV} does not cover this request"
    elif status == 429:
        text += ". Rate or daily request limit reached"
    return text


def _request(
    instrument: Instrument, bar: str, start: dt.date, end: dt.date, key: str
) -> Dict[str, Any]:
    """SDK keyword arguments for one market; without a key, the preview."""
    request: Dict[str, Any] = {
        "timestamp": _TIMESTAMP_SOURCE,
        "interval": bar,
        "exchange": instrument.exchange,
        "symbol": instrument.atlas_symbol,
        "start_date": start,
        "end_date": end,
        "output": "pandas",
        "show_progress": False,
    }
    if key:
        request["api_key"] = key
    else:
        request["preview"] = True
    return request


def _build_frame(
    ohlcv: Optional[pd.DataFrame],
    funding: Callable[[], pd.DataFrame],
    bar: str,
    exchange: str,
    label: str,
) -> Optional[pd.DataFrame]:
    """Join one market's bars with its settlement-slot funding.

    Returns:
        The loader frame, or ``None`` when the range holds no bars.
    """
    if ohlcv is None or ohlcv.empty:
        return None
    frame = _bars_frame(ohlcv)
    if frame.empty:
        return None
    frame["funding_rate"] = _slot_funding(frame.index, funding(), bar, exchange, label)
    return frame


@register
class DataLoader:
    """Perpetual-futures bars and funding from Aperiodic (opt-in, SDK-backed)."""

    name = "aperiodic"
    markets = {"crypto"}
    # A key is needed for anything beyond the public preview sample.
    requires_auth = True

    def __init__(self) -> None:
        """Initialize the loader (no SDK import or network at construction)."""
        self.fetch_errors: Dict[str, str] = {}

    def is_available(self) -> bool:
        """Return whether the SDK is installed; the API decides what a key covers."""
        try:
            _require_sdk()
        except NoAvailableSourceError:
            return False
        return True

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch bars and funding for each venue-qualified perpetual symbol.

        The bars and funding of every symbol are requested concurrently, so a
        batch fits the data gateway's per-source time budget. One refused or
        empty symbol does not discard the others; its reason is logged and
        kept in ``fetch_errors``.

        Args:
            codes: Symbols such as ``OKX.BTC-USDT-PERP``.
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.
            interval: ``1m``/``5m``/``15m``/``30m``/``1H``/``4H``/``1D``.
            fields: Ignored.

        Returns:
            Mapping of each served symbol to its frame.

        Raises:
            ValueError: ``start_date`` is after ``end_date`` or unparseable.
            NoAvailableSourceError: The interval is unsupported or the SDK is
                not installed.
            AperiodicRequestError: No symbol was served; the message carries
                each symbol's reason, including the API's refusal text.
        """
        del fields
        validate_date_range(start_date, end_date)
        bar = _INTERVAL_MAP.get(str(interval).strip())
        if bar is None:
            raise NoAvailableSourceError(
                f"unsupported Aperiodic interval {interval!r}; "
                "supported: 1m, 5m, 15m, 30m, 1H, 4H, 1D"
            )
        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        key = _resolve_key()
        cache_args = {
            "source": self.name,
            "timeframe": interval,
            "start_date": start_date,
            "end_date": end_date,
            "fields": None,
        }

        self.fetch_errors = {}
        failures: Dict[str, str] = {}
        served: Dict[str, pd.DataFrame] = {}
        pending: Dict[str, Instrument] = {}
        for code in codes:
            try:
                instrument = parse_symbol(code)
            except ValueError as exc:
                self._record_failure(code, "fetch_failed", str(exc), failures)
                continue
            cached = loader_cache_get(symbol=code, **cache_args)
            if cached is not None:
                served[code] = cached
            else:
                pending[code] = instrument

        jobs: Dict[str, Tuple[Future, Future]] = {}
        if pending:
            sdk = _require_sdk()
            workers = min(_MAX_PARALLEL_REQUESTS, 2 * len(pending))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for code, instrument in pending.items():
                    request = _request(instrument, bar, start, end, key)
                    jobs[code] = (
                        pool.submit(sdk.get_ohlcv, **request),
                        pool.submit(
                            sdk.get_derivative_metrics, metric="funding", **request
                        ),
                    )
        for code, (bars_job, funding_job) in jobs.items():
            exchange = pending[code].exchange
            try:
                frame = _build_frame(
                    bars_job.result(), funding_job.result, bar, exchange, code
                )
            except Exception as exc:  # noqa: BLE001 - reported per symbol
                reason = _describe_failure(exc, preview=not key)
                self._record_failure(
                    code, acquisition_error_kind(exc), reason, failures
                )
                continue
            if frame is None:
                reason = (
                    f"no bars between {start_date} and {end_date} (the market is "
                    "not listed, or the range is outside its history)"
                )
                self._record_failure(code, "no_data", reason, failures)
                continue
            loader_cache_put(symbol=code, frame=frame, **cache_args)
            served[code] = frame

        if failures and not served:
            raise AperiodicRequestError(
                "Aperiodic served none of the requested symbols: "
                + "; ".join(f"{code}: {reason}" for code, reason in failures.items())
            )
        return {code: served[code] for code in codes if code in served}

    def _record_failure(
        self, code: str, kind: str, reason: str, failures: Dict[str, str]
    ) -> None:
        """Keep a symbol's failure for ``fetch_errors``, the final error and the log."""
        self.fetch_errors[code] = kind
        failures[code] = reason
        logger.warning("aperiodic failed for %s: %s", code, reason)
