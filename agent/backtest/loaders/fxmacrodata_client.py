"""Thin FXMacroData REST client shared by loaders and tools.

The client intentionally reads credentials from the runtime environment only.
No API key is stored in source code, logs, cache keys, or query strings. When
``FXMD_API_KEY`` is present it is sent as ``X-API-Key``; otherwise public
FXMacroData endpoints can still be queried.
"""

from __future__ import annotations

from typing import Any

from backtest.loaders._http import throttled_get_json
from src.config.accessor import get_env_config

_HOST_KEY = "fxmacrodata"
_TIMEOUT_S = 20.0


def _data_config():
    return get_env_config().data


def has_api_key() -> bool:
    """Return whether a non-empty FXMacroData API key is configured."""
    return bool(_data_config().fxmd_api_key.strip())


def base_url() -> str:
    """Return the configured FXMacroData API base URL without a trailing slash."""
    return _data_config().fxmacrodata_api_base_url.strip().rstrip("/")


def _headers() -> dict[str, str] | None:
    api_key = _data_config().fxmd_api_key.strip()
    if not api_key:
        return None
    return {"X-API-Key": api_key}


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Fetch one FXMacroData JSON endpoint.

    Args:
        path: API path relative to ``/api/v1``. A leading slash is optional.
        params: Optional query parameters. ``None`` values are dropped.

    Returns:
        Decoded JSON payload.
    """
    clean_path = path if path.startswith("/") else f"/{path}"
    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value is not None and value != ""
    }
    return throttled_get_json(
        f"{base_url()}{clean_path}",
        host_key=_HOST_KEY,
        min_interval=_data_config().vibe_trading_fxmacrodata_min_interval,
        params=clean_params or None,
        headers=_headers(),
        timeout=_TIMEOUT_S,
    )


def forex(
    base: str,
    quote: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    indicators: str | None = None,
) -> Any:
    """Fetch official-reference FX spot rates for a currency pair."""
    return _get(
        f"/forex/{base.lower()}/{quote.lower()}",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "indicators": indicators,
        },
    )


def data_catalogue(currency: str, *, include_coverage: bool = True) -> Any:
    """Fetch indicator metadata and optional coverage for a currency."""
    return _get(
        f"/data_catalogue/{currency.lower()}",
        {"include_coverage": str(include_coverage).lower()},
    )


def calendar(
    currency: str,
    *,
    indicator: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    timezone: str | None = None,
) -> Any:
    """Fetch upcoming or recent economic release-calendar rows."""
    return _get(
        f"/calendar/{currency.lower()}",
        {
            "indicator": indicator,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone,
        },
    )


def indicator(
    currency: str,
    indicator_slug: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    series_mode: str | None = None,
    seasonality: str | None = None,
    frequency: str | None = None,
    revisions: str | None = None,
    basis: str | None = None,
    official_only: bool | None = None,
) -> Any:
    """Fetch one standardized macroeconomic indicator series."""
    return _get(
        f"/announcements/{currency.lower()}/{indicator_slug}",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "series_mode": series_mode,
            "seasonality": seasonality,
            "frequency": frequency,
            "revisions": revisions,
            "basis": basis,
            "official_only": official_only,
        },
    )


def predictions(
    currency: str,
    indicator_slug: str | None = None,
    *,
    prediction_type: str | None = None,
    prediction_source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch FXMacroData forecast or consensus rows."""
    path = f"/predictions/{currency.lower()}"
    if indicator_slug:
        path = f"{path}/{indicator_slug}"
    return _get(
        path,
        {
            "prediction_type": prediction_type,
            "prediction_source": prediction_source,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    )


def cot(
    currency: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch CFTC Commitment of Traders positioning rows."""
    return _get(
        f"/cot/{currency.lower()}",
        {"start_date": start_date, "end_date": end_date, "limit": limit},
    )


def commodities(
    indicator_slug: str | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch latest commodity values or one commodity time series."""
    if indicator_slug:
        return _get(
            f"/commodities/{indicator_slug}",
            {"start_date": start_date, "end_date": end_date, "limit": limit},
        )
    return _get("/commodities/latest")


def market_sessions(*, at: str | None = None) -> Any:
    """Fetch FX market-session timetable state."""
    return _get("/market_sessions", {"at": at})


def risk_sentiment(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch the global risk-on / risk-off indicator."""
    return _get(
        "/risk_sentiment",
        {"start_date": start_date, "end_date": end_date, "limit": limit},
    )


def rate_differentials(
    base: str,
    quote: str,
    *,
    measure: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch pair rate differentials."""
    return _get(
        f"/rate_differentials/{base.lower()}/{quote.lower()}",
        {
            "measure": measure,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    )


def forward_differentials(
    base: str,
    quote: str,
    *,
    curve_family: str | None = None,
    start_tenor_years: float | None = None,
    end_tenor_years: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> Any:
    """Fetch pair forward-rate differentials."""
    return _get(
        f"/forward_differentials/{base.lower()}/{quote.lower()}",
        {
            "curve_family": curve_family,
            "start_tenor_years": start_tenor_years,
            "end_tenor_years": end_tenor_years,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    )


def curves(
    currency: str,
    *,
    kind: str = "curves",
    curve_family: str | None = None,
    metric: str | None = None,
    method: str | None = None,
    date: str | None = None,
) -> Any:
    """Fetch curve nodes, curve proxies, or forward curve segments."""
    if kind not in {"curves", "curve_proxies", "forward_curves"}:
        raise ValueError("kind must be curves, curve_proxies, or forward_curves")
    return _get(
        f"/{kind}/{currency.lower()}",
        {
            "curve_family": curve_family,
            "metric": metric,
            "method": method,
            "date": date,
        },
    )


def central_bank_news(
    currency: str,
    *,
    press_releases_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> Any:
    """Fetch central-bank news or press releases."""
    family = "press-releases" if press_releases_only else "news"
    return _get(
        f"/{family}/{currency.lower()}",
        {"limit": limit, "offset": offset},
    )
