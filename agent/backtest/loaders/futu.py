"""Futu OpenAPI-backed loader for HK and China A-share OHLCV data."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import (
    NoAvailableSourceError,
    loader_cache_get,
    loader_cache_put,
    validate_date_range,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

_INTERVAL_MAP: dict[str, str] = {
    "1m": "K_1M",
    "5m": "K_5M",
    "15m": "K_15M",
    "30m": "K_30M",
    "1D": "K_DAY",
    "1H": "K_60M",
    "4H": "K_240M",
    "1W": "K_WEEK",
    "1M": "K_MON",
}


def _to_futu_symbol(code: str) -> str:
    """Convert project symbol to Futu OpenAPI format.

    Examples:
        700.HK    -> HK.00700
        5.HK      -> HK.00005
        000001.SZ -> SZ.000001
        600519.SH -> SH.600519
    """
    upper = code.strip().upper()
    if upper.endswith(".HK"):
        return f"HK.{upper[:-3].zfill(5)}"
    if upper.endswith(".SZ"):
        return f"SZ.{upper[:-3].zfill(6)}"
    if upper.endswith(".SH"):
        return f"SH.{upper[:-3].zfill(6)}"
    return upper


def _to_futu_ktype(interval: str):
    """Map project interval string to a futu KLType enum value.

    Lazy-imports futu so the module can be imported without futu installed.
    Unsupported intervals fail explicitly so requested bar fidelity is never
    changed silently.
    """
    from futu import KLType  # noqa: PLC0415

    token = interval.strip()
    attr = _INTERVAL_MAP.get(token)
    if attr is None:
        raise NoAvailableSourceError(
            f"unsupported Futu interval: {interval!r}; "
            f"supported intervals: {sorted(_INTERVAL_MAP)}"
        )
    try:
        return getattr(KLType, attr)
    except AttributeError as exc:
        raise NoAvailableSourceError(
            f"installed Futu SDK does not expose KLType.{attr}"
        ) from exc


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a Futu kline DataFrame to the standard OHLCV schema.

    Args:
        df: Raw DataFrame returned by ``request_history_kline()``.

    Returns:
        DataFrame with columns [open, high, low, close, volume] indexed
        by ``trade_date`` (timezone-naive DatetimeIndex), sorted ascending.
    """
    if df.empty:
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    result = df.copy()
    result.index = pd.to_datetime(result["time_key"])
    result.index.name = "trade_date"
    result = result[_OHLCV_COLUMNS].copy()
    result = result.apply(pd.to_numeric, errors="coerce")
    result["volume"] = result["volume"].fillna(0.0)
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.sort_index()
    return result[~result.index.duplicated(keep="last")]


@register
class FutuLoader:
    """Fetch HK and China A-share bars from Futu OpenAPI.

    Requires FutuOpenD running locally (https://www.futunn.com/download/openAPI)
    and the environment variables ``FUTU_HOST`` / ``FUTU_PORT`` to be set.
    """

    name = "futu"
    markets = {"hk_equity", "a_share"}
    requires_auth = True

    def __init__(self) -> None:
        from src.config.accessor import get_env_config

        cfg = get_env_config().data
        self._host = cfg.futu_host
        self._port = cfg.futu_port

    def is_available(self) -> bool:
        """Return True if FutuOpenD is reachable."""
        from src.config.accessor import get_env_config

        cfg = get_env_config().data
        if not cfg.futu_host or not cfg.futu_port:
            return False
        try:
            import futu  # noqa: PLC0415
            ctx = futu.OpenQuoteContext(host=self._host, port=self._port)
            ctx.close()
            return True
        except Exception:
            return False

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV history from Futu OpenAPI.

        Args:
            codes: Project symbols such as ``700.HK`` or ``000001.SZ``.
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            interval: Backtest interval supported by :data:`_INTERVAL_MAP`.
            fields: Ignored; included for interface compatibility.

        Returns:
            Mapping of input symbol to normalised OHLCV dataframe.

        Raises:
            NoAvailableSourceError: If FutuOpenD connection fails.
        """
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)
        if interval.strip() not in _INTERVAL_MAP:
            raise NoAvailableSourceError(
                f"unsupported Futu interval: {interval!r}; "
                f"supported intervals: {sorted(_INTERVAL_MAP)}"
            )

        results: Dict[str, pd.DataFrame] = {}

        # Serve cached symbols first; only open a FutuOpenD connection when at
        # least one symbol is uncached, so a fully-cached request needs no
        # running gateway.
        pending: List[str] = []
        for code in codes:
            cached = loader_cache_get(
                source=self.name,
                symbol=code,
                timeframe=interval,
                start_date=start_date,
                end_date=end_date,
                fields=None,
            )
            if cached is not None and not cached.empty:
                results[code] = cached.copy()
            else:
                pending.append(code)

        if not pending:
            return results

        try:
            import futu  # noqa: PLC0415

            ktype = _to_futu_ktype(interval)
            ctx = futu.OpenQuoteContext(host=self._host, port=self._port)
        except Exception as exc:
            raise NoAvailableSourceError(
                f"Cannot connect to FutuOpenD at {self._host}:{self._port}: {exc}"
            ) from exc

        try:
            for code in pending:
                futu_code = _to_futu_symbol(code)
                page_key = None
                pages: List[pd.DataFrame] = []
                failed = False
                while True:
                    ret, data, next_page_key = ctx.request_history_kline(
                        futu_code,
                        start=start_date,
                        end=end_date,
                        ktype=ktype,
                        max_count=10_000,
                        page_req_key=page_key,
                    )
                    if ret != futu.RET_OK:
                        logger.warning(
                            "Futu returned error for %s: %s", futu_code, data
                        )
                        failed = True
                        break
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        pages.append(data)
                    if not next_page_key:
                        break
                    page_key = next_page_key

                if failed or not pages:
                    continue
                normalized = _normalize_frame(pd.concat(pages, ignore_index=True))
                if normalized.empty:
                    continue
                loader_cache_put(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    frame=normalized,
                )
                results[code] = normalized
        finally:
            ctx.close()

        return results
