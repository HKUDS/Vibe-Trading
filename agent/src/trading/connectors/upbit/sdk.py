"""Read-only + locally-simulated-paper Upbit connector via the public REST API.

Wraps Upbit's JWT-authenticated Exchange API (accounts, orders) and the public
Quotation API (ticker, candles) for the five read operations plus paper order
simulation. No third-party SDK is required — requests + PyJWT only.

Paper-vs-live: Upbit has no sandbox environment and no runtime paper/live
discriminator (a single Access/Secret Key pair reads the same account
regardless of the declared profile). Following the Dhan/Longbridge precedent,
this connector is therefore structurally capped at paper: order placement is
simulated locally against a live ticker price and never reaches Upbit.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping
from urllib.parse import urlencode

import requests

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "upbit.json"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
}

UPBIT_API_URL = "https://api.upbit.com/v1"

#: Prefix of every order id the local paper simulator issues. ``cancel_order``
#: refuses any other id, because only these orders exist in the simulation —
#: reads (``get_open_orders``) hit the real account, so a real order's id
#: could otherwise reach here and be acknowledged as cancelled without ever
#: calling Upbit.
_PAPER_ORDER_PREFIX = "PAPER-"

#: Returned by order methods when a non-paper config reaches them. Upbit
#: exposes no runtime paper/live discriminator (same key pair reads the same
#: account), so — following the Dhan/Longbridge precedent — the connector is
#: structurally capped at paper and never opens a live order path.
_PAPER_ONLY_ERROR = (
    "Upbit connector is paper-only: it exposes no runtime paper/live "
    "discriminator, so live order placement is not supported. Use an "
    "upbit-paper-* profile."
)


class UpbitDependencyError(RuntimeError):
    """Raised when the optional ``PyJWT`` package is not installed."""


class UpbitConfigError(RuntimeError):
    """Raised when the connector configuration is missing or invalid."""


class UpbitAPIError(RuntimeError):
    """Raised when Upbit returns an auth, HTTP, network, or JSON error."""


@dataclass(frozen=True)
class UpbitConfig:
    """Upbit connector connection settings.

    Args:
        access_key: Upbit Open API access key.
        secret_key: Upbit Open API secret key.
        profile: ``paper`` or ``live-readonly``.
        timeout: Network timeout in seconds.
        readonly: Whether order placement is disabled.
    """

    access_key: str = ""
    secret_key: str = ""
    profile: str = "paper"
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "UpbitConfig":
        """Build a config from a JSON-like mapping."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise UpbitConfigError("profile must be 'paper' or 'live-readonly'")
        return cls(
            access_key=str(payload.get("access_key") or "").strip(),
            secret_key=str(payload.get("secret_key") or "").strip(),
            profile=profile,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
        profile: str | None = None,
    ) -> "UpbitConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if access_key is not None:
            payload["access_key"] = access_key
        if secret_key is not None:
            payload["secret_key"] = secret_key
        if profile is not None:
            payload["profile"] = profile
        return UpbitConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_paper(self) -> bool:
        return self.environment == "paper"


_OVERRIDE_KEYS = ("access_key", "secret_key", "profile")


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> "UpbitConfig":
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = UpbitConfig.from_mapping(base)
    clean = {
        k: v
        for k, v in dict(overrides or {}).items()
        if k in _OVERRIDE_KEYS and v not in (None, "")
    }
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> UpbitConfig:
    path = config_path()
    if not path.exists():
        return UpbitConfig()
    try:
        return UpbitConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise UpbitConfigError(f"invalid Upbit config at {path}: {exc}") from exc


def save_config(config: UpbitConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def upbit_jwt_available() -> bool:
    try:
        _require_jwt()
        return True
    except UpbitDependencyError:
        return False


# ---------------------------------------------------------------------------
# Five read operations + order placement
# ---------------------------------------------------------------------------


def check_status(config: UpbitConfig | None = None) -> dict[str, Any]:
    """Check SDK readiness and config completeness."""
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "PyJWT", "installed": upbit_jwt_available()},
        "paper_guard": "simulated_locally",
        "host": UPBIT_API_URL,
    }

    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"Upbit connector not configured: missing {', '.join(missing)}."
        return report

    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install \"vibe-trading-ai[upbit]\"`."
        return report

    try:
        get_account_snapshot(cfg)  # connectivity probe; result unused
    except (UpbitConfigError, UpbitAPIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {"profile": cfg.profile, "is_paper": cfg.is_paper}
    return report


def get_account_snapshot(config: UpbitConfig | None = None) -> dict[str, Any]:
    """Fetch the KRW cash balance (account summary) for the configured account."""
    cfg = config or load_config()
    accounts = _accounts(cfg)
    krw = next((row for row in accounts if str(row.get("currency")) == "KRW"), None)

    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "host": UPBIT_API_URL,
        "account": {
            "currency": "KRW",
            "balance": _as_float(krw.get("balance")) if krw else 0.0,
            "locked": _as_float(krw.get("locked")) if krw else 0.0,
        },
    }


def get_positions(config: UpbitConfig | None = None) -> dict[str, Any]:
    """Fetch current crypto holdings (every non-KRW balance)."""
    cfg = config or load_config()
    accounts = _accounts(cfg)

    rows = []
    for item in accounts:
        currency = str(item.get("currency") or "")
        if not currency or currency == "KRW":
            continue
        quantity = _as_float(item.get("balance")) + _as_float(item.get("locked"))
        if quantity <= 0:
            continue
        unit_currency = str(item.get("unit_currency") or "KRW")
        rows.append({
            "symbol": f"{unit_currency}-{currency}",
            "currency": currency,
            "quantity": quantity,
            "available": _as_float(item.get("balance")),
            "locked": _as_float(item.get("locked")),
            # avg_buy_price is a price per unit of `currency`, denominated in
            # `unit_currency` (e.g. a KRW price for a BTC position) -- not in
            # `currency` itself, which is what `average_cost` alone would imply.
            "average_cost": _as_float(item.get("avg_buy_price")),
            "average_cost_currency": unit_currency,
            "unit_currency": unit_currency,
        })

    return {"status": "ok", "profile": cfg.profile, "is_paper": cfg.is_paper, "positions": rows}


def get_open_orders(
    config: UpbitConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Fetch open (waiting) orders and optionally recently closed ones."""
    cfg = config or load_config()
    open_rows = _as_list(_request(cfg, "GET", "/orders/open"))
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "open_orders": [_order_to_dict(item) for item in open_rows],
    }
    if include_executions:
        closed_rows = _as_list(_request(cfg, "GET", "/orders/closed"))
        result["executions"] = [_order_to_dict(item) for item in closed_rows]
    return result


def get_quote(symbol: str, *, config: UpbitConfig | None = None, **_: Any) -> dict[str, Any]:
    """Fetch the current ticker for a market (e.g. ``KRW-BTC``)."""
    cfg = config or load_config()
    market = _normalize_market(symbol)

    try:
        rows = _request(cfg, "GET", "/ticker", params={"markets": market}, authed=False)
    except UpbitAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": symbol}

    row = _as_list(rows)[0] if _as_list(rows) else {}
    return {
        "status": "ok",
        "symbol": market,
        "quote": {
            "last": row.get("trade_price"),
            "open": row.get("opening_price"),
            "high": row.get("high_price"),
            "low": row.get("low_price"),
            "prev_close": row.get("prev_closing_price"),
            "change_rate": row.get("signed_change_rate"),
            "volume_24h": row.get("acc_trade_volume_24h"),
        },
    }


#: Minute candle units Upbit serves without remapping to a different bar size.
_MINUTE_UNITS = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "240m": 240}


def get_historical_bars(
    symbol: str,
    *,
    config: UpbitConfig | None = None,
    period: str = "1d",
    limit: int = 200,
) -> dict[str, Any]:
    """Fetch historical OHLCV candles.

    ``period`` tokens: ``1m``/``3m``/``5m``/``15m``/``30m``/``60m``/``240m`` →
    minute candles; ``1d``/``1D`` → day candles; ``1w`` → week candles;
    ``1M`` → month candles. Unsupported periods fail closed instead of
    silently substituting a different bar size.
    """
    cfg = config or load_config()
    market = _normalize_market(symbol)
    token = period.strip()
    capped_limit = min(int(limit), 200)  # Upbit caps a single call at 200 candles.

    if token in _MINUTE_UNITS:
        path = f"/candles/minutes/{_MINUTE_UNITS[token]}"
    elif token in ("1d", "1D"):
        path = "/candles/days"
    elif token == "1w":
        path = "/candles/weeks"
    elif token == "1M":
        path = "/candles/months"
    else:
        return {
            "status": "error",
            "error": (
                f"unsupported period: {period!r}; "
                f"supported: {sorted(_MINUTE_UNITS)} + ['1d', '1w', '1M']"
            ),
            "symbol": market,
        }

    try:
        rows = _request(
            cfg, "GET", path, params={"market": market, "count": capped_limit}, authed=False
        )
    except UpbitAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": market}

    bars = [_candle_to_dict(item) for item in reversed(_as_list(rows))]
    return {"status": "ok", "symbol": market, "period": period, "bars": bars}


def place_order(
    config: UpbitConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place a PAPER-ONLY order on Upbit (simulated locally against a live quote).

    Upbit exposes no runtime paper/live discriminator, so this connector is
    structurally capped at paper: the very first check refuses any config whose
    ``environment`` is not ``paper``. There is therefore no live order path
    here, by design.

    Every order looks up the current live price and refuses if none is
    available. A market order fills at that price. A limit order fills only
    if it is immediately marketable against it -- a buy at ``min(limit,
    last)``, a sell at ``max(limit, last)`` -- and is refused otherwise, since
    this simulator has no order book to rest a non-marketable order on.

    Args:
        symbol: Market code, e.g. ``KRW-BTC``.
        side: ``buy`` or ``sell``.
        quantity: Base-currency quantity (e.g. BTC amount). Mutually exclusive
            with ``notional``, which is the more natural unit for Upbit market
            buys (KRW amount to spend).
        order_type: ``market`` or ``limit``.
        limit_price: Required for limit orders.
    """
    cfg = config or load_config()

    # ---- HARD GUARD: structurally paper-only (must run before anything) ----
    if not cfg.is_paper:
        return {"status": "error", "error": _PAPER_ONLY_ERROR}

    market = _normalize_market(symbol)
    if not market:
        return {"status": "error", "error": "symbol is required"}

    side_token = str(side or "").strip().lower()
    if side_token not in ("buy", "sell"):
        return {"status": "error", "error": "side must be 'buy' or 'sell'"}

    type_token = str(order_type or "").strip().lower()
    if type_token not in ("market", "limit"):
        return {"status": "error", "error": "order_type must be 'market' or 'limit'"}

    has_qty = quantity is not None
    has_notional = notional is not None
    if has_qty == has_notional:
        return {"status": "error", "error": "provide exactly one of quantity or notional"}
    if has_qty and float(quantity) <= 0:  # type: ignore[arg-type]
        return {"status": "error", "error": "quantity must be positive"}
    if has_notional and float(notional) <= 0:  # type: ignore[arg-type]
        return {"status": "error", "error": "notional must be positive"}

    if type_token == "limit" and limit_price is None:
        return {"status": "error", "error": "limit order requires limit_price"}

    # Paper-only: simulate locally against a live quote (Upbit has no
    # sandbox). Every order looks up the current price and refuses when none
    # is available -- a simulated fill with no price is not a fill; any
    # position or P&L built on it would be invented.
    quote = get_quote(market, config=cfg)
    last = _as_float(quote.get("quote", {}).get("last")) if quote.get("status") == "ok" else None
    if not last:
        return {
            "status": "error",
            "error": f"could not resolve a live quote for {market!r}; Upbit may not recognize this market",
            "symbol": market,
        }

    if type_token == "limit":
        limit = float(limit_price)  # type: ignore[arg-type]
        if side_token == "buy":
            if limit < last:
                return {
                    "status": "error",
                    "error": (
                        f"limit price {limit} would not fill against the current price {last}; "
                        "this simulator only fills orders that are immediately marketable"
                    ),
                    "symbol": market,
                }
            fill_price = min(limit, last)
        else:
            if limit > last:
                return {
                    "status": "error",
                    "error": (
                        f"limit price {limit} would not fill against the current price {last}; "
                        "this simulator only fills orders that are immediately marketable"
                    ),
                    "symbol": market,
                }
            fill_price = max(limit, last)
    else:
        fill_price = last

    filled_qty = float(notional) / fill_price if has_notional else float(quantity)  # type: ignore[arg-type]

    return {
        "status": "ok",
        "order_id": f"{_PAPER_ORDER_PREFIX}{market}-{side_token}-{uuid.uuid4().hex[:8]}",
        "symbol": market,
        "side": side_token,
        "profile": cfg.profile,
        "is_paper": True,
        "paper_guard": "simulated_locally",
        "order_type": type_token,
        "quantity": filled_qty,
        "limit_price": float(limit_price) if type_token == "limit" else None,  # type: ignore[arg-type]
        "fill_price": fill_price,
        "order_status": "simulated_fill",
    }


def cancel_order(
    config: UpbitConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel a PAPER-ONLY order on Upbit (simulated locally).

    Like :func:`place_order`, the first check refuses any non-paper config —
    this connector never reaches a live order, so it never cancels one.
    """
    cfg = config or load_config()

    # ---- HARD GUARD: structurally paper-only (must run before anything) ----
    if not cfg.is_paper:
        return {"status": "error", "error": _PAPER_ONLY_ERROR}

    clean_id = str(order_id or "").strip()
    if not clean_id:
        return {"status": "error", "error": "order_id is required"}
    if not clean_id.startswith(_PAPER_ORDER_PREFIX):
        # get_open_orders reads the real account, so a real order's id can
        # arrive here; acknowledging it would report a cancel that never
        # happened while the real order keeps working.
        return {
            "status": "error",
            "error": (
                f"order {clean_id!r} was not issued by this paper simulator, so it "
                "cannot be cancelled here; cancel a real order on Upbit directly"
            ),
        }

    return {
        "status": "ok",
        "order_id": clean_id,
        "symbol": _normalize_market(symbol) if symbol else None,
        "profile": cfg.profile,
        "is_paper": True,
        "cancelled": True,
    }


# ---------------------------------------------------------------------------
# SDK plumbing
# ---------------------------------------------------------------------------


def _require_jwt() -> ModuleType:
    try:
        import jwt  # type: ignore
    except ModuleNotFoundError as exc:
        raise UpbitDependencyError(
            "PyJWT is not installed; run `pip install \"vibe-trading-ai[upbit]\"`."
        ) from exc
    return jwt


def _accounts(cfg: UpbitConfig) -> list[Any]:
    return _as_list(_request(cfg, "GET", "/accounts"))


def _auth_headers(cfg: UpbitConfig, params: Mapping[str, Any] | None) -> dict[str, str]:
    jwt = _require_jwt()
    if not cfg.access_key or not cfg.secret_key:
        raise UpbitConfigError(
            "Upbit connector not configured: set access_key and secret_key "
            "in ~/.vibe-trading/upbit.json or via environment."
        )
    payload: dict[str, Any] = {"access_key": cfg.access_key, "nonce": str(uuid.uuid4())}
    if params:
        query_string = urlencode(list(params.items()), doseq=True)
        payload["query_hash"] = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    token = jwt.encode(payload, cfg.secret_key, algorithm="HS256")
    if isinstance(token, bytes):  # PyJWT < 2.0 returned bytes
        token = token.decode("utf-8")
    return {"Authorization": f"Bearer {token}"}


def _request(
    cfg: UpbitConfig,
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    authed: bool = True,
) -> Any:
    """Run an HTTP request and normalize Upbit failure modes."""
    if authed:
        missing = _missing_fields(cfg)
        if missing:
            raise UpbitConfigError(f"Upbit connector not configured: missing {', '.join(missing)}.")
    headers = {"Accept": "application/json"}
    if authed:
        headers.update(_auth_headers(cfg, params))

    try:
        response = requests.request(
            method.upper(),
            f"{UPBIT_API_URL}{path}",
            headers=headers,
            params=dict(params or {}),
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise UpbitAPIError(f"Upbit request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise UpbitAPIError("Upbit API authentication failed: check access_key/secret_key.")
    if response.status_code >= 400:
        raise UpbitAPIError(f"Upbit API returned HTTP {response.status_code}: {_error_message(response)}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise UpbitAPIError("Upbit API returned invalid JSON.") from exc


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason or "request failed"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or error.get("name") or payload)
    return str(payload)


def _missing_fields(cfg: UpbitConfig) -> list[str]:
    missing = []
    if not cfg.access_key:
        missing.append("access_key")
    if not cfg.secret_key:
        missing.append("secret_key")
    return missing


def _public_config(cfg: UpbitConfig) -> dict[str, Any]:
    data = asdict(cfg)
    if data.get("access_key"):
        data["access_key"] = data["access_key"][:8] + "***"
    if data.get("secret_key"):
        data["secret_key"] = "***redacted***"
    return data


def _normalize_market(symbol: str | None) -> str:
    """Normalize a market code: uppercase, ``/`` → ``-`` (Upbit uses ``QUOTE-BASE``)."""
    return str(symbol or "").strip().upper().replace("/", "-")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _order_to_dict(item: Any) -> dict[str, Any]:
    return {
        "order_id": str(item.get("uuid", "")),
        "symbol": item.get("market", ""),
        "side": item.get("side", ""),
        "order_type": item.get("ord_type", ""),
        "price": _as_float(item.get("price")) if item.get("price") is not None else None,
        "quantity": _as_float(item.get("volume")) if item.get("volume") is not None else None,
        "remaining_quantity": (
            _as_float(item.get("remaining_volume")) if item.get("remaining_volume") is not None else None
        ),
        "executed_quantity": (
            _as_float(item.get("executed_volume")) if item.get("executed_volume") is not None else None
        ),
        "status": item.get("state", ""),
        "created_at": item.get("created_at", ""),
    }


def _candle_to_dict(item: Any) -> dict[str, Any]:
    return {
        "time": item.get("candle_date_time_utc"),
        "open": item.get("opening_price"),
        "high": item.get("high_price"),
        "low": item.get("low_price"),
        "close": item.get("trade_price"),
        "volume": item.get("candle_acc_trade_volume"),
    }
