"""Read-only Trading 212 connector via the public REST API.

Wraps Trading 212's account cash/info, portfolio, open-order, order-history,
and metadata endpoints. Market quotes and OHLCV bars are not exposed by the
public API, so the generic quote/history entry points return a clear unsupported
payload instead of fabricating market data from account state.

Paper-vs-live identity guard: none is verifiable from the response body. The
configured ``profile`` is operator-declared from the API key and recorded in
every payload as ``paper_guard="read_only_no_runtime_discriminator"``. Order
placement and cancellation are disabled for every profile until Trading 212
offers a structural paper/demo safety boundary this connector can verify.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

import requests

from src.config.paths import get_runtime_root
from src.trading.endpoint_policy import is_broker_url

CONFIG_FILENAME = "trading212.json"
DEFAULT_BASE_URL = "https://live.trading212.com"
PAPER_GUARD = "read_only_no_runtime_discriminator"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}


class Trading212ConfigError(RuntimeError):
    """Raised when the Trading 212 connector configuration is missing/invalid."""


class Trading212APIError(RuntimeError):
    """Raised when Trading 212 returns an auth, HTTP, network, or JSON error."""


@dataclass(frozen=True)
class Trading212Config:
    """Trading 212 connector connection settings.

    Args:
        api_key: Trading 212 API key.
        api_secret: Optional Trading 212 API secret. When present, requests use
            HTTP Basic auth as described by the current Trading 212 API docs.
            When omitted, the connector falls back to the legacy
            ``Authorization`` API-key header.
        profile: ``paper``, ``live-readonly`` or ``live``. This is
            operator-declared; Trading 212 responses do not prove the account
            environment.
        base_url: Public API base URL.
        timeout: Network timeout in seconds.
        readonly: Always true for built-in profiles; order methods refuse all
            requests regardless of this flag.
    """

    api_key: str = ""
    api_secret: str = ""
    profile: str = "live-readonly"
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "Trading212Config":
        """Build a config from a JSON-like mapping, normalizing profile/URL."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "live-readonly").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise Trading212ConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        if not is_broker_url(base_url, ("trading212.com",)):
            raise Trading212ConfigError(f"base_url must be an https URL on trading212.com, got {base_url!r}")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            api_secret=str(payload.get("api_secret") or "").strip(),
            profile=profile,
            base_url=base_url,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        profile: str | None = None,
        base_url: str | None = None,
    ) -> "Trading212Config":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if api_key is not None:
            payload["api_key"] = api_key
        if api_secret is not None:
            payload["api_secret"] = api_secret
        if profile is not None:
            payload["profile"] = profile
        if base_url is not None:
            payload["base_url"] = base_url
        return Trading212Config.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for the operator-declared profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "live")


_OVERRIDE_KEYS = ("api_key", "api_secret", "base_url")


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Trading212Config:
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = Trading212Config.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level Trading 212 config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> Trading212Config:
    """Load Trading 212 settings from ``~/.vibe-trading/trading212.json``."""
    path = config_path()
    if not path.exists():
        return Trading212Config()
    try:
        return Trading212Config.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise Trading212ConfigError(f"invalid Trading 212 config at {path}: {exc}") from exc


def save_config(config: Trading212Config) -> Path:
    """Persist Trading 212 settings with owner-only permissions."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def check_status(config: Trading212Config | None = None) -> dict[str, Any]:
    """Check REST readiness and config completeness without mutating broker state."""
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "requests", "installed": True},
        "paper_guard": PAPER_GUARD,
        "base_url": cfg.base_url,
    }

    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"Trading 212 connector not configured: missing {', '.join(missing)}."
        return report

    try:
        snapshot = get_account_snapshot(cfg)
    except (Trading212ConfigError, Trading212APIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report
    except Exception as exc:  # noqa: BLE001 - health endpoint reports cleanly
        report["status"] = "error"
        report["error"] = f"Trading 212 connector check failed: {exc}"
        return report

    report["account"] = {
        "profile": cfg.profile,
        "cash_currency": _first(snapshot.get("cash"), ("currencyCode", "currency")),
        "account_type": _first(snapshot.get("metadata"), ("type", "accountType")),
    }
    return report


def get_account_snapshot(config: Trading212Config | None = None) -> dict[str, Any]:
    """Fetch account cash and account metadata for the configured API key."""
    cfg = config or load_config()
    cash = get_account_cash(cfg)["cash"]
    metadata = get_account_metadata(cfg)["metadata"]
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "cash": cash,
        "metadata": metadata,
    }


def get_account_cash(config: Trading212Config | None = None) -> dict[str, Any]:
    """Fetch account cash balances."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/account/cash")
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "cash": _mapping_or_raw(payload),
    }


def get_account_metadata(config: Trading212Config | None = None) -> dict[str, Any]:
    """Fetch account metadata/info."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/account/info")
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "metadata": _mapping_or_raw(payload),
    }


def get_positions(config: Trading212Config | None = None) -> dict[str, Any]:
    """Fetch current portfolio positions."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/portfolio")
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "positions": [_position_to_dict(item) for item in _extract_items(payload)],
    }


def get_open_orders(config: Trading212Config | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    """Fetch currently open Trading 212 equity orders."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/orders")
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "open_orders": [_order_to_dict(item) for item in _extract_items(payload)],
    }
    if include_executions:
        history = get_order_history(cfg)
        result["executions"] = history["orders"]
    return result


def get_order_history(
    config: Trading212Config | None = None,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Fetch historical orders for the configured account."""
    cfg = config or load_config()
    params: dict[str, Any] = {"limit": int(limit)}
    if cursor:
        params["cursor"] = cursor
    payload = _get(cfg, "/api/v0/equity/history/orders", params=params)
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "orders": [_order_to_dict(item) for item in _extract_items(payload)],
        "next_page_path": _first(payload, ("nextPagePath", "next_page_path")),
    }


def get_instrument_metadata(
    config: Trading212Config | None = None,
    *,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Fetch Trading 212 instrument metadata, optionally filtered by ticker."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/metadata/instruments")
    rows = [_instrument_to_dict(item) for item in _extract_items(payload)]
    if ticker:
        clean = ticker.strip().upper()
        rows = [row for row in rows if str(row.get("ticker") or "").upper() == clean]
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "instruments": rows,
    }


def get_exchanges(config: Trading212Config | None = None) -> dict[str, Any]:
    """Fetch Trading 212 exchange metadata."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v0/equity/metadata/exchanges")
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "exchanges": [_mapping_or_raw(item) for item in _extract_items(payload)],
    }


def get_quote(symbol: str, *, config: Trading212Config | None = None, **_: Any) -> dict[str, Any]:
    """Return a clear unsupported payload; Trading 212 exposes no quote endpoint."""
    cfg = config or load_config()
    return _unsupported_market_data(cfg, "quotes.read", symbol=symbol)


def get_historical_bars(
    symbol: str,
    *,
    config: Trading212Config | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    """Return a clear unsupported payload; Trading 212 exposes no OHLCV endpoint."""
    cfg = config or load_config()
    result = _unsupported_market_data(cfg, "history.read", symbol=symbol)
    result["period"] = period
    result["limit"] = int(limit)
    return result


_ORDER_DISABLED_ERROR = (
    "Trading 212 connector is read-only: order placement and cancellation are "
    "disabled until a structural paper/demo safety boundary is available."
)

_LIVE_ORDER_ERROR = (
    "Trading 212 order placement is not supported for live/read-only profiles "
    "(no runtime paper/live discriminator is available)."
)


def place_order(
    config: Trading212Config | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Refuse Trading 212 order placement before any REST client is touched."""
    cfg = config or load_config()
    # ---- HARD GUARD: no verified live safety boundary (must run first) ----
    if cfg.environment != "paper":
        return _order_refused(cfg, _LIVE_ORDER_ERROR, symbol=symbol, side=side)
    return _order_refused(
        cfg,
        _ORDER_DISABLED_ERROR,
        symbol=symbol,
        side=side,
        quantity=quantity,
        notional=notional,
        order_type=order_type,
        limit_price=limit_price,
        time_in_force=time_in_force,
    )


def cancel_order(
    config: Trading212Config | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Refuse Trading 212 order cancellation before any REST client is touched."""
    cfg = config or load_config()
    # ---- HARD GUARD: no verified live safety boundary (must run first) ----
    if cfg.environment != "paper":
        return _order_refused(cfg, _LIVE_ORDER_ERROR, order_id=order_id, symbol=symbol)
    return _order_refused(cfg, _ORDER_DISABLED_ERROR, order_id=order_id, symbol=symbol)


def _get(config: Trading212Config, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
    """Perform a read-only GET request against the Trading 212 REST API."""
    return _request(config, "GET", path, params=params)


def _request(
    config: Trading212Config,
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
) -> Any:
    """Run an HTTP request and normalize Trading 212 failure modes."""
    missing = _missing_fields(config)
    if missing:
        raise Trading212ConfigError(f"Trading 212 connector not configured: missing {', '.join(missing)}.")

    url = urljoin(f"{config.base_url.rstrip('/')}/", path.lstrip("/"))
    headers = {"Accept": "application/json"}
    auth = None
    if config.api_secret:
        auth = (config.api_key, config.api_secret)
    else:
        headers["Authorization"] = config.api_key
    try:
        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            auth=auth,
            params=dict(params or {}),
            timeout=config.timeout,
        )
    except requests.RequestException as exc:
        raise Trading212APIError(f"Trading 212 request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise Trading212APIError("Trading 212 API authentication failed: check api_key/api_secret.")
    if response.status_code >= 400:
        raise Trading212APIError(f"Trading 212 API returned HTTP {response.status_code}: {_error_message(response)}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise Trading212APIError("Trading 212 API returned invalid JSON.") from exc


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason or "request failed"
    if isinstance(payload, Mapping):
        for key in ("message", "error", "detail", "title"):
            value = payload.get(key)
            if value:
                return str(value)
    return str(payload)


def _missing_fields(config: Trading212Config) -> list[str]:
    missing = []
    if not config.api_key:
        missing.append("api_key")
    return missing


def _public_config(config: Trading212Config) -> dict[str, Any]:
    """Config snapshot with the API key redacted."""
    data = asdict(config)
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:4] + "***"
    if data.get("api_secret"):
        data["api_secret"] = "***redacted***"
    return data


def _unsupported_market_data(config: Trading212Config, capability: str, *, symbol: str) -> dict[str, Any]:
    return {
        "status": "error",
        "profile": config.profile,
        "paper_guard": PAPER_GUARD,
        "symbol": str(symbol or "").strip().upper(),
        "error": f"Trading 212 public API does not expose {capability} market data.",
    }


def _order_refused(config: Trading212Config, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "error": message,
        "profile": config.profile,
        "paper_guard": PAPER_GUARD,
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def _as_iter(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("items", "data", "orders", "instruments", "exchanges", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return _as_iter(payload)


def _mapping_or_raw(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    return {"raw": value}


def _obj_get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        value = _obj_get(obj, name, None)
        if value is not None:
            return value
    return default


def _position_to_dict(item: Any) -> dict[str, Any]:
    return {
        "symbol": _first(item, ("ticker", "symbol")),
        "ticker": _first(item, ("ticker",)),
        "quantity": _first(item, ("quantity",)),
        "average_price": _first(item, ("averagePrice", "average_price")),
        "current_price": _first(item, ("currentPrice", "current_price")),
        "pnl": _first(item, ("ppl", "pnl")),
        "fx_pnl": _first(item, ("fxPpl", "fx_pnl")),
        "currency": _first(item, ("currencyCode", "currency")),
        "initial_fill_date": _first(item, ("initialFillDate", "initial_fill_date")),
        "max_buy": _first(item, ("maxBuy", "max_buy")),
        "max_sell": _first(item, ("maxSell", "max_sell")),
        "cash_invested": _first(item, ("cashInvested", "cash_invested")),
    }


def _order_to_dict(item: Any) -> dict[str, Any]:
    return {
        "order_id": str(_first(item, ("id", "orderId", "order_id"), "")),
        "symbol": _first(item, ("ticker", "symbol")),
        "ticker": _first(item, ("ticker",)),
        "side": str(_first(item, ("side",), "")),
        "order_type": str(_first(item, ("type", "orderType", "order_type"), "")),
        "status": str(_first(item, ("status",), "")),
        "quantity": _first(item, ("quantity",)),
        "filled_quantity": _first(item, ("filledQuantity", "filled_quantity")),
        "limit_price": _first(item, ("limitPrice", "limit_price")),
        "stop_price": _first(item, ("stopPrice", "stop_price")),
        "price": _first(item, ("price",)),
        "value": _first(item, ("value",)),
        "currency": _first(item, ("currencyCode", "currency")),
        "time_validity": _first(item, ("timeValidity", "time_validity")),
        "created_at": _first(item, ("creationTime", "createdAt", "dateCreated", "created_at")),
        "executed_at": _first(item, ("dateExecuted", "executedAt", "executed_at")),
    }


def _instrument_to_dict(item: Any) -> dict[str, Any]:
    return {
        "ticker": _first(item, ("ticker",)),
        "name": _first(item, ("name",)),
        "short_name": _first(item, ("shortName", "short_name")),
        "isin": _first(item, ("isin",)),
        "type": _first(item, ("type",)),
        "currency": _first(item, ("currencyCode", "currency")),
        "exchange": _first(item, ("exchange", "exchangeCode", "exchange_code")),
        "working_schedule_id": _first(item, ("workingScheduleId", "working_schedule_id")),
        "max_open_quantity": _first(item, ("maxOpenQuantity", "max_open_quantity")),
        "min_trade_quantity": _first(item, ("minTradeQuantity", "min_trade_quantity")),
        "added_on": _first(item, ("addedOn", "added_on")),
    }
