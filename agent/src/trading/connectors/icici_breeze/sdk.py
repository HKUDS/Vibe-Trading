"""Read-only ICICI Direct Breeze connector.

Credentials are retrieved from Windows Credential Manager through ``keyring``
using service ``VibeTrading-ICICI`` and keys:
``api_key``, ``api_secret``, and ``api_session``.

No order-placement or cancellation functions are exposed in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any, Mapping

KEYRING_SERVICE = "VibeTrading-ICICI"
PROFILE_ENVIRONMENTS = {"live-readonly": "live"}
PAPER_GUARD = "read_only_live_breeze"


class ICICIBreezeDependencyError(RuntimeError):
    """Raised when an optional connector dependency is unavailable."""


class ICICIBreezeConfigError(RuntimeError):
    """Raised when the local connector configuration is invalid."""


class ICICIBreezeAPIError(RuntimeError):
    """Raised when Breeze returns an unsuccessful response."""


@dataclass(frozen=True)
class ICICIBreezeConfig:
    """ICICI Breeze connector settings."""

    profile: str = "live-readonly"
    keyring_service: str = KEYRING_SERVICE
    timeout: float = 30.0
    readonly: bool = True

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, Any] | None = None
    ) -> "ICICIBreezeConfig":
        payload = dict(data or {})
        profile = str(
            payload.get("profile") or "live-readonly"
        ).strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise ICICIBreezeConfigError(
                "profile must be 'live-readonly'"
            )
        return cls(
            profile=profile,
            keyring_service=str(
                payload.get("keyring_service") or KEYRING_SERVICE
            ).strip(),
            timeout=float(payload.get("timeout") or 30.0),
            readonly=True,
        )

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS[self.profile]


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ICICIBreezeConfig:
    """Build effective connector config from safe, non-secret values."""

    payload: dict[str, Any] = {}
    payload.update(dict(profile_config or {}))
    for key, value in dict(overrides or {}).items():
        if key in {"profile", "keyring_service", "timeout"} and value not in (
            None,
            "",
        ):
            payload[key] = value
    return ICICIBreezeConfig.from_mapping(payload)


def check_status(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Check credentials and Breeze account access without trading."""

    cfg = config or ICICIBreezeConfig()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {
            "package": "breeze-connect",
            "installed": _breeze_available(),
        },
        "credential_store": {
            "package": "keyring",
            "installed": _keyring_available(),
        },
        "paper_guard": PAPER_GUARD,
        "readonly": True,
    }

    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = (
            "Breeze SDK missing: run "
            "`python -m pip install breeze-connect`."
        )
        return report

    if not report["credential_store"]["installed"]:
        report["status"] = "error"
        report["error"] = (
            "Keyring missing: run "
            "`python -m pip install keyring`."
        )
        return report

    missing = _missing_credentials(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = (
            "ICICI Breeze credentials missing from Windows Credential "
            f"Manager: {', '.join(missing)}."
        )
        return report

    try:
        snapshot = get_account_snapshot(cfg)
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {
        "profile": cfg.profile,
        "currency": "INR",
        "demat_holdings": snapshot.get("demat_holdings_count", 0),
    }
    return report


def get_account_snapshot(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Read funds and a count of Demat holdings."""

    cfg = config or ICICIBreezeConfig()
    client = _client(cfg)
    funds = _success(client.get_funds(), "get_funds", default={})
    holdings = _success(
        client.get_demat_holdings(),
        "get_demat_holdings",
        default=[],
    )

    if not isinstance(funds, Mapping):
        funds = {}
    holding_rows = _as_list(holdings)

    account = {
        "currency": "INR",
        "total_bank_balance": funds.get("total_bank_balance"),
        "allocated_equity": funds.get("allocated_equity"),
        "allocated_fno": funds.get("allocated_fno"),
        "allocated_commodity": funds.get("allocated_commodity"),
        "allocated_currency": funds.get("allocated_currency"),
        "block_by_trade_balance": funds.get("block_by_trade_balance"),
        "unallocated_balance": funds.get("unallocated_balance"),
        "demat_holdings_count": len(holding_rows),
    }

    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "readonly": True,
        "account": account,
        "demat_holdings_count": len(holding_rows),
    }


def get_positions(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Read Demat holdings and current trading positions."""

    cfg = config or ICICIBreezeConfig()
    client = _client(cfg)

    holdings = _success(
        client.get_demat_holdings(),
        "get_demat_holdings",
        default=[],
    )
    open_positions = _success(
        client.get_portfolio_positions(),
        "get_portfolio_positions",
        default=[],
        allow_status_200_error=True,
    )

    rows: list[dict[str, Any]] = []

    for item in _as_list(holdings):
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "account": "ICICI Demat",
                "symbol": item.get("stock_code"),
                "type": "demat_holding",
                "quantity": _number(item.get("quantity")),
                "available_quantity": _number(
                    item.get("demat_avail_quantity")
                ),
                "blocked_quantity": _number(
                    item.get("blocked_quantity")
                ),
                "allocated_quantity": _number(
                    item.get("demat_allocated_quantity")
                ),
                "isin": item.get("stock_ISIN"),
                "currency": "INR",
            }
        )

    for item in _as_list(open_positions):
        if not isinstance(item, Mapping):
            continue
        quantity = _number(item.get("quantity"))
        if not quantity:
            continue
        rows.append(
            {
                "account": "ICICI Trading",
                "symbol": item.get("stock_code"),
                "type": item.get("product_type") or "open_position",
                "quantity": quantity,
                "average_cost": _number(item.get("average_price")),
                "current_price": _number(
                    item.get("ltp") or item.get("price")
                ),
                "pnl": _number(item.get("pnl")),
                "exchange": item.get("exchange_code"),
                "expiry_date": item.get("expiry_date"),
                "right": item.get("right"),
                "strike_price": _number(item.get("strike_price")),
                "currency": "INR",
            }
        )

    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "readonly": True,
        "positions": rows,
    }


def get_open_orders(
    config: ICICIBreezeConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Read today's NSE and NFO orders."""

    cfg = config or ICICIBreezeConfig()
    client = _client(cfg)

    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from_date = _iso_z(start)
    to_date = _iso_z(now)

    open_orders: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    notes: list[str] = []

    for exchange_code in ("NSE", "NFO"):
        try:
            payload = client.get_order_list(
                exchange_code=exchange_code,
                from_date=from_date,
                to_date=to_date,
            )
            items = _success(
                payload,
                f"get_order_list({exchange_code})",
                default=[],
                allow_status_200_error=True,
            )
        except Exception as exc:
            notes.append(f"{exchange_code}: {exc}")
            continue

        for item in _as_list(items):
            if not isinstance(item, Mapping):
                continue
            row = _order_to_dict(item)
            status = str(item.get("status") or "").strip().lower()
            if status in {
                "ordered",
                "open",
                "pending",
                "partially executed",
                "partially_executed",
                "requested",
            }:
                open_orders.append(row)
            elif include_executions and status in {
                "executed",
                "filled",
                "traded",
                "complete",
                "completed",
            }:
                executions.append(row)

    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "readonly": True,
        "open_orders": open_orders,
    }
    if include_executions:
        result["executions"] = executions
    if notes:
        result["notes"] = notes
    return result


def get_quote(
    symbol: str,
    *,
    config: ICICIBreezeConfig | None = None,
    exchange_code: str = "NSE",
    **_: Any,
) -> dict[str, Any]:
    """Read an NSE cash quote using an NSE symbol or Breeze stock code."""

    cfg = config or ICICIBreezeConfig()
    client = _client(cfg)
    stock_code = _resolve_stock_code(
        client, symbol, exchange_code=exchange_code
    )

    payload = client.get_quotes(
        stock_code=stock_code,
        exchange_code=exchange_code,
        expiry_date="",
        product_type="cash",
        right="",
        strike_price="",
    )
    items = _success(payload, "get_quotes", default=[])
    first = _as_list(items)
    quote = first[0] if first else {}
    if not isinstance(quote, Mapping):
        quote = {}

    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "readonly": True,
        "symbol": str(symbol or "").strip().upper(),
        "stock_code": stock_code,
        "quote": {
            "bid": _number(quote.get("best_bid_price")),
            "ask": _number(quote.get("best_offer_price")),
            "last": _number(quote.get("ltp")),
            "open": _number(quote.get("open")),
            "high": _number(quote.get("high")),
            "low": _number(quote.get("low")),
            "close": _number(quote.get("previous_close")),
            "volume": _number(quote.get("total_quantity_traded")),
            "time": quote.get("ltt"),
        },
    }


def get_historical_bars(
    symbol: str,
    *,
    config: ICICIBreezeConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    exchange_code: str = "NSE",
    **_: Any,
) -> dict[str, Any]:
    """Read NSE cash OHLCV history through Breeze Historical Data V2."""

    cfg = config or ICICIBreezeConfig()
    client = _client(cfg)
    stock_code = _resolve_stock_code(
        client, symbol, exchange_code=exchange_code
    )

    period_map = {
        "1m": ("1minute", 1),
        "5m": ("5minute", 5),
        "30m": ("30minute", 30),
        "1d": ("1day", 1440),
    }
    token = str(period or "1d").strip().lower()
    if token not in period_map:
        return {
            "status": "error",
            "profile": cfg.profile,
            "paper_guard": PAPER_GUARD,
            "readonly": True,
            "symbol": str(symbol or "").strip().upper(),
            "error": (
                "ICICI Breeze history currently supports periods "
                "1m, 5m, 30m, and 1d."
            ),
        }

    interval, minutes = period_map[token]
    count = max(1, min(int(limit), 1000))
    now = datetime.now(timezone.utc)

    if token == "1d":
        start = now - timedelta(days=max(count * 2, 30))
    else:
        start = now - timedelta(
            minutes=max(count * minutes * 3, 24 * 60)
        )

    payload = client.get_historical_data_v2(
        interval=interval,
        from_date=_iso_z(start),
        to_date=_iso_z(now),
        stock_code=stock_code,
        exchange_code=exchange_code,
        product_type="cash",
    )
    items = _success(payload, "get_historical_data_v2", default=[])
    bars = [_bar_to_dict(item) for item in _as_list(items)]
    bars = bars[-count:]

    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "readonly": True,
        "symbol": str(symbol or "").strip().upper(),
        "stock_code": stock_code,
        "period": token,
        "bars": bars,
    }


def _client(config: ICICIBreezeConfig):
    BreezeConnect = _require_breeze().BreezeConnect
    credentials = _credentials(config)
    client = BreezeConnect(api_key=credentials["api_key"])
    client.generate_session(
        api_secret=credentials["api_secret"],
        session_token=credentials["api_session"],
    )
    return client


def _credentials(config: ICICIBreezeConfig) -> dict[str, str]:
    keyring = _require_keyring()
    values = {
        key: str(
            keyring.get_password(config.keyring_service, key) or ""
        ).strip()
        for key in ("api_key", "api_secret", "api_session")
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ICICIBreezeConfigError(
            "ICICI Breeze credentials missing from Windows Credential "
            f"Manager: {', '.join(missing)}."
        )
    return values


def _missing_credentials(config: ICICIBreezeConfig) -> list[str]:
    try:
        keyring = _require_keyring()
    except ICICIBreezeDependencyError:
        return ["api_key", "api_secret", "api_session"]
    return [
        key
        for key in ("api_key", "api_secret", "api_session")
        if not str(
            keyring.get_password(config.keyring_service, key) or ""
        ).strip()
    ]


def _breeze_available() -> bool:
    try:
        _require_breeze()
        return True
    except ICICIBreezeDependencyError:
        return False


def _keyring_available() -> bool:
    try:
        _require_keyring()
        return True
    except ICICIBreezeDependencyError:
        return False


def _require_breeze() -> ModuleType:
    try:
        import breeze_connect
    except ModuleNotFoundError as exc:
        raise ICICIBreezeDependencyError(
            "breeze-connect is not installed."
        ) from exc
    return breeze_connect


def _require_keyring() -> ModuleType:
    try:
        import keyring
    except ModuleNotFoundError as exc:
        raise ICICIBreezeDependencyError(
            "keyring is not installed."
        ) from exc
    return keyring


def _success(
    payload: Any,
    operation: str,
    *,
    default: Any,
    allow_status_200_error: bool = False,
) -> Any:
    if not isinstance(payload, Mapping):
        raise ICICIBreezeAPIError(
            f"{operation} returned an invalid response."
        )

    status = payload.get("Status")
    error = payload.get("Error")

    if status != 200:
        raise ICICIBreezeAPIError(
            f"{operation} failed: status={status}, error={error}"
        )

    if error and not allow_status_200_error:
        raise ICICIBreezeAPIError(
            f"{operation} returned error: {error}"
        )

    success = payload.get("Success")
    return default if success in (None, "") else success


def _resolve_stock_code(
    client: Any,
    symbol: str,
    *,
    exchange_code: str,
) -> str:
    clean = str(symbol or "").strip().upper()
    for suffix in (".NS", ".NSE"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
    if clean.startswith("NSE:"):
        clean = clean[4:]
    if not clean:
        raise ICICIBreezeConfigError("symbol is required.")

    try:
        names = client.get_names(
            exchange_code=exchange_code,
            stock_code=clean,
        )
        if isinstance(names, Mapping):
            resolved = str(names.get("isec_stock_code") or "").strip()
            if resolved:
                return resolved
    except Exception:
        pass

    return clean


def _order_to_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    quantity = _number(item.get("quantity"))
    pending = _number(item.get("pending_quantity"))
    return {
        "order_id": str(item.get("order_id") or ""),
        "symbol": item.get("stock_code"),
        "side": str(item.get("action") or ""),
        "order_type": str(item.get("order_type") or ""),
        "status": str(item.get("status") or ""),
        "quantity": quantity,
        "filled_quantity": max(0.0, quantity - pending),
        "pending_quantity": pending,
        "price": _number(item.get("price")),
        "average_price": _number(item.get("average_price")),
        "exchange": item.get("exchange_code"),
        "product_type": item.get("product_type"),
        "time": item.get("order_datetime"),
    }


def _bar_to_dict(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    return {
        "time": str(item.get("datetime") or ""),
        "open": _number(item.get("open")),
        "high": _number(item.get("high")),
        "low": _number(item.get("low")),
        "close": _number(item.get("close")),
        "volume": _number(item.get("volume")),
    }


def _public_config(config: ICICIBreezeConfig) -> dict[str, Any]:
    return asdict(config)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_z(value: datetime) -> str:
    """Format a Breeze timestamp as YYYY-MM-DDTHH:MM:SS.000Z."""
    return value.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
