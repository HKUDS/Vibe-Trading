"""Read-only Toss Securities (토스증권) connector via the public REST API.

Wraps the Toss Invest Open API's account, holdings, order-history, price, and
candle endpoints. No third-party SDK is required — ``requests`` only.

Paper-vs-live identity guard: none is verifiable. Toss Securities' Open API
(https://developers.tossinvest.com) requires a live brokerage account to
apply for API access and documents no sandbox environment, so — following the
Trading 212 precedent — the configured ``profile`` is operator-declared and
recorded in every payload as
``paper_guard="read_only_no_runtime_discriminator"``. Order placement and
cancellation are disabled for every profile until Toss offers a structural
paper/demo safety boundary this connector can verify.

Caveat: this connector was authored from the public Open API reference
(https://developers.tossinvest.com/docs) without a live Toss account to test
against — exact field names for less-common responses may need adjustment.
Endpoint paths and the OAuth flow (client-credentials grant) are documented;
verify response field names against the live API before relying on this in
production.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "toss.json"
DEFAULT_BASE_URL = "https://openapi.tossinvest.com"
PAPER_GUARD = "read_only_no_runtime_discriminator"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

#: Safety margin subtracted from the token's reported TTL before it is
#: treated as expired.
_TOKEN_REFRESH_MARGIN_SECONDS = 120


class TossConfigError(RuntimeError):
    """Raised when the Toss connector configuration is missing or invalid."""


class TossAPIError(RuntimeError):
    """Raised when Toss returns an auth, HTTP, network, or JSON error."""


@dataclass(frozen=True)
class TossConfig:
    """Toss Securities connector connection settings.

    Args:
        client_id: Toss Invest Open API client ID.
        client_secret: Toss Invest Open API client secret.
        account_seq: The ``accountSeq`` identifying which brokerage account to
            read (from ``GET /api/v1/accounts``); required for account-scoped
            calls via the ``X-Tossinvest-Account`` header.
        profile: ``paper``, ``live-readonly`` or ``live``. Operator-declared;
            Toss responses do not prove the account environment.
        base_url: Public API base URL.
        timeout: Network timeout in seconds.
        readonly: Always true for built-in profiles; order methods refuse all
            requests regardless of this flag.
    """

    client_id: str = ""
    client_secret: str = ""
    account_seq: str = ""
    profile: str = "live-readonly"
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "TossConfig":
        """Build a config from a JSON-like mapping, normalizing profile/URL."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "live-readonly").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise TossConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise TossConfigError("base_url must start with http:// or https://")
        return cls(
            client_id=str(payload.get("client_id") or "").strip(),
            client_secret=str(payload.get("client_secret") or "").strip(),
            account_seq=str(payload.get("account_seq") or "").strip(),
            profile=profile,
            base_url=base_url,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        account_seq: str | None = None,
        profile: str | None = None,
        base_url: str | None = None,
    ) -> "TossConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if client_id is not None:
            payload["client_id"] = client_id
        if client_secret is not None:
            payload["client_secret"] = client_secret
        if account_seq is not None:
            payload["account_seq"] = account_seq
        if profile is not None:
            payload["profile"] = profile
        if base_url is not None:
            payload["base_url"] = base_url
        return TossConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for the operator-declared profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "live")


_OVERRIDE_KEYS = ("client_id", "client_secret", "account_seq", "profile", "base_url")


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> TossConfig:
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = TossConfig.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level Toss config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> TossConfig:
    """Load Toss settings from ``~/.vibe-trading/toss.json``."""
    path = config_path()
    if not path.exists():
        return TossConfig()
    try:
        return TossConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise TossConfigError(f"invalid Toss config at {path}: {exc}") from exc


def save_config(config: TossConfig) -> Path:
    """Persist Toss settings with owner-only permissions."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def check_status(config: TossConfig | None = None) -> dict[str, Any]:
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
        report["error"] = f"Toss connector not configured: missing {', '.join(missing)}."
        return report

    try:
        get_account_snapshot(cfg)
    except (TossConfigError, TossAPIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {"profile": cfg.profile, "account_seq": cfg.account_seq}
    return report


def get_account_snapshot(config: TossConfig | None = None) -> dict[str, Any]:
    """Fetch holdings summary totals for the configured account."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v1/assets", authed=True, account_scoped=True)
    summary = _mapping_or_raw(_first(payload, ("summary", "accountSummary")))
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "account": summary,
    }


def get_positions(config: TossConfig | None = None) -> dict[str, Any]:
    """Fetch current KR/US equity holdings."""
    cfg = config or load_config()
    payload = _get(cfg, "/api/v1/assets", authed=True, account_scoped=True)
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "positions": [_position_to_dict(item) for item in _extract_items(payload)],
    }


def get_open_orders(
    config: TossConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Fetch open Toss orders, optionally with recently closed ones."""
    cfg = config or load_config()
    open_payload = _get(cfg, "/api/v1/order-history", authed=True, account_scoped=True, params={"status": "OPEN"})
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "open_orders": [_order_to_dict(item) for item in _extract_items(open_payload)],
    }
    if include_executions:
        closed_payload = _get(
            cfg, "/api/v1/order-history", authed=True, account_scoped=True, params={"status": "CLOSED"}
        )
        result["executions"] = [_order_to_dict(item) for item in _extract_items(closed_payload)]
    return result


def get_quote(symbol: str, *, config: TossConfig | None = None, **_: Any) -> dict[str, Any]:
    """Fetch the current price for a symbol (KR 6-digit code or US ticker)."""
    cfg = config or load_config()
    clean = str(symbol or "").strip().upper()
    try:
        payload = _get(cfg, "/api/v1/prices", authed=True, account_scoped=False, params={"symbols": clean})
    except TossAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}

    row = _first_item(payload)
    return {
        "status": "ok",
        "symbol": clean,
        "quote": {
            "last": _first(row, ("lastPrice", "price")),
            "currency": _first(row, ("currency",)),
            "timestamp": _first(row, ("timestamp",)),
        },
    }


def get_historical_bars(
    symbol: str,
    *,
    config: TossConfig | None = None,
    period: str = "1d",
    limit: int = 200,
) -> dict[str, Any]:
    """Fetch OHLCV candles for a symbol.

    ``period`` tokens: ``1m`` → 1-minute candles, ``1d``/``1D`` → daily
    candles (per the documented ``/api/v1/candles`` granularities). Other
    periods fail closed instead of silently substituting a different bar size.
    """
    cfg = config or load_config()
    clean = str(symbol or "").strip().upper()
    token = period.strip()
    interval = {"1m": "1m", "1d": "1d", "1D": "1d"}.get(token)
    if interval is None:
        return {
            "status": "error",
            "error": f"unsupported period: {period!r}; supported: ['1m', '1d']",
            "symbol": clean,
        }

    capped_limit = min(int(limit), 200)  # documented cap: 200 candles per call
    try:
        payload = _get(
            cfg,
            "/api/v1/candles",
            authed=True,
            account_scoped=False,
            params={"symbol": clean, "interval": interval, "limit": capped_limit},
        )
    except TossAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}

    bars = [_bar_to_dict(item) for item in _extract_items(payload)]
    return {"status": "ok", "symbol": clean, "period": period, "bars": bars}


_ORDER_DISABLED_ERROR = (
    "Toss Securities connector is read-only: order placement and cancellation "
    "are disabled until a structural paper/demo safety boundary is available."
)

_LIVE_ORDER_ERROR = (
    "Toss Securities order placement is not supported for live/read-only "
    "profiles (no runtime paper/live discriminator is available)."
)


def place_order(
    config: TossConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Refuse Toss order placement before any REST client is touched."""
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
    config: TossConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Refuse Toss order cancellation before any REST client is touched."""
    cfg = config or load_config()
    # ---- HARD GUARD: no verified live safety boundary (must run first) ----
    if cfg.environment != "paper":
        return _order_refused(cfg, _LIVE_ORDER_ERROR, order_id=order_id, symbol=symbol)
    return _order_refused(cfg, _ORDER_DISABLED_ERROR, order_id=order_id, symbol=symbol)


# ---------------------------------------------------------------------------
# SDK plumbing
# ---------------------------------------------------------------------------


def _token_cache_path(cfg: TossConfig) -> Path:
    return get_runtime_root() / "toss-token.json"


def _access_token(cfg: TossConfig) -> str:
    """Return a cached or freshly issued OAuth2 client-credentials token."""
    path = _token_cache_path(cfg)
    now = time.time()
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("client_id") == cfg.client_id and float(cached.get("expires_at", 0)) > now:
                return str(cached["access_token"])
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            pass

    try:
        response = requests.post(
            f"{cfg.base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
            },
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise TossAPIError(f"Toss token request failed: {exc}") from exc
    if response.status_code >= 400:
        raise TossAPIError(f"Toss token issuance returned HTTP {response.status_code}: {_error_message(response)}")

    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise TossAPIError(f"Toss token issuance returned no access_token: {body}")
    expires_in = float(body.get("expires_in") or 0)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "client_id": cfg.client_id,
            "access_token": token,
            "expires_at": now + max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0),
        }),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _get(
    cfg: TossConfig,
    path: str,
    *,
    authed: bool,
    account_scoped: bool,
    params: Mapping[str, Any] | None = None,
) -> Any:
    missing = _missing_fields(cfg, account_scoped=account_scoped)
    if missing:
        raise TossConfigError(f"Toss connector not configured: missing {', '.join(missing)}.")

    headers = {"Accept": "application/json"}
    if authed:
        headers["Authorization"] = f"Bearer {_access_token(cfg)}"
    if account_scoped:
        headers["X-Tossinvest-Account"] = cfg.account_seq

    try:
        response = requests.get(
            f"{cfg.base_url}{path}",
            headers=headers,
            params=dict(params or {}),
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise TossAPIError(f"Toss request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise TossAPIError("Toss API authentication failed: check client_id/client_secret/account_seq.")
    if response.status_code >= 400:
        raise TossAPIError(f"Toss API returned HTTP {response.status_code}: {_error_message(response)}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise TossAPIError("Toss API returned invalid JSON.") from exc


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason or "request failed"
    if isinstance(payload, Mapping):
        for key in ("message", "error", "error_description", "detail"):
            value = payload.get(key)
            if value:
                return str(value)
    return str(payload)


def _missing_fields(cfg: TossConfig, *, account_scoped: bool = True) -> list[str]:
    missing = []
    if not cfg.client_id:
        missing.append("client_id")
    if not cfg.client_secret:
        missing.append("client_secret")
    if account_scoped and not cfg.account_seq:
        missing.append("account_seq")
    return missing


def _public_config(cfg: TossConfig) -> dict[str, Any]:
    data = asdict(cfg)
    if data.get("client_id"):
        data["client_id"] = data["client_id"][:4] + "***"
    if data.get("client_secret"):
        data["client_secret"] = "***redacted***"
    return data


def _order_refused(config: TossConfig, message: str, **extra: Any) -> dict[str, Any]:
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
        for key in ("items", "data", "holdings", "orders", "candles", "prices", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return _as_iter(payload)


def _first_item(payload: Any) -> Any:
    items = _extract_items(payload)
    return items[0] if items else {}


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
        "symbol": _first(item, ("symbol", "productCode")),
        "name": _first(item, ("name", "productName")),
        "quantity": _first(item, ("quantity", "qty")),
        "average_price": _first(item, ("averagePrice", "avgPrice")),
        "current_price": _first(item, ("currentPrice", "price")),
        "pnl": _first(item, ("profitLoss", "pnl")),
        "currency": _first(item, ("currency",)),
        "market": _first(item, ("market", "exchange")),
    }


def _order_to_dict(item: Any) -> dict[str, Any]:
    return {
        "order_id": str(_first(item, ("orderId", "id"), "")),
        "symbol": _first(item, ("symbol", "productCode")),
        "side": str(_first(item, ("side",), "")),
        "order_type": str(_first(item, ("orderType", "type"), "")),
        "status": str(_first(item, ("status",), "")),
        "quantity": _first(item, ("quantity", "qty")),
        "filled_quantity": _first(item, ("filledQuantity", "filledQty")),
        "price": _first(item, ("price", "limitPrice")),
        "currency": _first(item, ("currency",)),
        "created_at": _first(item, ("createdAt", "orderedAt")),
    }


def _bar_to_dict(item: Any) -> dict[str, Any]:
    return {
        "time": _first(item, ("timestamp", "time")),
        "open": _first(item, ("openPrice", "open")),
        "high": _first(item, ("highPrice", "high")),
        "low": _first(item, ("lowPrice", "low")),
        "close": _first(item, ("closePrice", "close")),
        "volume": _first(item, ("volume",)),
    }
