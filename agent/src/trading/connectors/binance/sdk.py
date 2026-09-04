"""Binance ccxt connector with host-separated spot profiles.

The live read-only profile may opt into ``market_type="usdm"`` for strict
Shadow Account evidence. USD-M permits only signed account and position reads
against ``fapi.binance.com``; all order and market-data surfaces are rejected.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import getproxies

from src.config.paths import get_runtime_root
from src.trading.connectors.binance.shaping import (
    as_iter as _as_iter,
    nonzero_balances as _nonzero_balances,
    normalize_symbol,
    obj_get as _obj_get,
    ohlcv_to_dict as _ohlcv_to_dict,
    order_to_dict as _order_to_dict,
    to_float as _to_float,
    trade_to_dict as _trade_to_dict,
)
from src.trading.connectors.binance.usdm import (
    DEFAULT_OBSERVATION_ABSOLUTE_TOLERANCE,
    UsdMObservationError,
    assert_exchange_endpoints,
    read_account_observation,
)

CONFIG_FILENAME = "binance.json"

#: Profiles this connector understands and their default account environment.
PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

DEFAULT_TESTNET_HOST = "https://testnet.binance.vision"
LIVE_HOST = "https://api.binance.com"
USDM_LIVE_HOST = "https://fapi.binance.com"

class BinanceDependencyError(RuntimeError):
    """Raised when the optional ``ccxt`` package is not installed."""


class BinanceConfigError(RuntimeError):
    """Raised when the connector configuration is missing or invalid."""


@dataclass(frozen=True)
class BinanceConfig:
    """Binance connector connection settings.
    """

    api_key: str = ""
    api_secret: str = ""
    profile: str = "paper"
    market_type: str = "spot"
    observation_absolute_tolerance: float = DEFAULT_OBSERVATION_ABSOLUTE_TOLERANCE
    testnet_host: str = DEFAULT_TESTNET_HOST
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "BinanceConfig":
        """Build a config from a JSON-like mapping, normalizing the profile."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise BinanceConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        market_type = str(payload.get("market_type") or "spot").strip().lower()
        if market_type not in {"spot", "usdm"}:
            raise BinanceConfigError("market_type must be 'spot' or 'usdm'")
        if market_type == "usdm" and profile != "live-readonly":
            raise BinanceConfigError(
                "market_type 'usdm' is available only through the live-readonly profile"
            )
        raw_tolerance = payload.get("observation_absolute_tolerance")
        try:
            tolerance = float(
                raw_tolerance
                if raw_tolerance is not None
                else DEFAULT_OBSERVATION_ABSOLUTE_TOLERANCE
            )
        except (TypeError, ValueError) as exc:
            raise BinanceConfigError(
                "observation_absolute_tolerance must be non-negative and finite"
            ) from exc
        if not math.isfinite(tolerance) or tolerance < 0:
            raise BinanceConfigError(
                "observation_absolute_tolerance must be non-negative and finite"
            )
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            api_secret=str(payload.get("api_secret") or "").strip(),
            profile=profile,
            market_type=market_type,
            observation_absolute_tolerance=tolerance,
            testnet_host=str(payload.get("testnet_host") or DEFAULT_TESTNET_HOST).strip(),
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        profile: str | None = None,
        market_type: str | None = None,
        observation_absolute_tolerance: float | None = None,
        testnet_host: str | None = None,
    ) -> "BinanceConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if api_key is not None:
            payload["api_key"] = api_key
        if api_secret is not None:
            payload["api_secret"] = api_secret
        if profile is not None:
            payload["profile"] = profile
        if market_type is not None:
            payload["market_type"] = market_type
        if observation_absolute_tolerance is not None:
            payload["observation_absolute_tolerance"] = observation_absolute_tolerance
        if testnet_host is not None:
            payload["testnet_host"] = testnet_host
        return BinanceConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for this profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_testnet(self) -> bool:
        """Return whether this profile targets the testnet host/key."""
        return self.environment == "paper"

    @property
    def host(self) -> str:
        """Return the REST host this profile connects to."""
        if self.market_type == "usdm":
            return USDM_LIVE_HOST
        return self.testnet_host if self.is_testnet else LIVE_HOST


_OVERRIDE_KEYS = (
    "api_key", "api_secret", "profile", "market_type",
    "observation_absolute_tolerance", "testnet_host",
)


def build_config(profile_config: Mapping[str, Any] | None = None, overrides: Mapping[str, Any] | None = None) -> "BinanceConfig":
    """Resolve the effective config: saved file ← profile defaults ← CLI overrides.

    Credentials (``api_key`` / ``api_secret``) come from the saved
    ``~/.vibe-trading/binance.json``; the selected connector profile supplies the
    ``profile`` intent; CLI/tool overrides win last.

    """
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = BinanceConfig.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level Binance config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> BinanceConfig:
    """Load Binance settings from ``~/.vibe-trading/binance.json``."""
    path = config_path()
    if not path.exists():
        return BinanceConfig()
    try:
        return BinanceConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BinanceConfigError(f"invalid Binance config at {path}: {exc}") from exc


def save_config(config: BinanceConfig) -> Path:
    """Persist Binance settings with owner-only permissions."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def ccxt_available() -> bool:
    """Return whether the optional ``ccxt`` library can be imported."""
    try:
        _require_ccxt()
        return True
    except BinanceDependencyError:
        return False


def check_status(config: BinanceConfig | None = None) -> dict[str, Any]:
    """Check SDK readiness, config completeness, and host separation.

    Returns a JSON-serializable health report. Does not place or mutate any
    broker state. The host-allowlist guard asserts that the client's resolved
    host is the testnet host for a paper profile, or ``api.binance.com`` for a
    live profile, so a key/host mismatch fails closed before any read.
    """
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "ccxt", "installed": ccxt_available()},
        "paper_guard": "host_separated",
        "host": cfg.host,
    }

    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"Binance connector not configured: missing {', '.join(missing)}."
        return report

    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install ccxt`."
        return report

    try:
        _assert_host(cfg)
    except BinanceConfigError as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    try:
        snapshot = get_account_snapshot(cfg)
    except Exception as exc:  # noqa: BLE001 - health endpoint reports cleanly
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    account_summary = {
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
    }
    count_field = "positions" if cfg.market_type == "usdm" else "balances"
    account_summary[count_field] = len(snapshot.get(count_field, []))
    report["account"] = account_summary
    return report


def get_account_snapshot(config: BinanceConfig | None = None) -> dict[str, Any]:
    """Fetch spot balances or a strict USD-M Shadow Account observation.

    Returns the non-zero balances (each with ``free`` / ``used`` / ``total``)
    from ccxt's unified ``fetch_balance``.
    """
    cfg = config or load_config()
    _assert_host(cfg)
    ex = _exchange(cfg)
    if cfg.market_type == "usdm":
        return _get_usdm_observation(cfg, ex)
    balance = ex.fetch_balance()
    rows = _nonzero_balances(balance)
    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "host": cfg.host,
        "paper_guard": "host_separated",
        "balances": rows,
    }


def get_positions(config: BinanceConfig | None = None) -> dict[str, Any]:
    """Fetch spot holdings or strict USD-M position evidence.

    Binance spot has no positions; holdings are the non-zero balances. On live
    accounts Binance may expose Simple Earn Flexible collateral in the spot
    payload as synthetic ``LD<ASSET>`` balances. When the read-only Simple Earn
    endpoint is available, replace those wrappers with their underlying asset
    and authoritative ``totalAmount`` so portfolio valuation neither misses nor
    double-counts flexible holdings.
    """
    cfg = config or load_config()
    _assert_host(cfg)
    ex = _exchange(cfg)
    if cfg.market_type == "usdm":
        return _get_usdm_observation(cfg, ex)
    balance = ex.fetch_balance()
    spot_balances = _nonzero_balances(balance)
    earn_rows: list[dict[str, Any]] = []
    earn_wrappers: set[str] = set()
    earn_note: str | None = None
    if not cfg.is_testnet:
        try:
            payload = ex.sapi_get_simple_earn_flexible_position({"size": 100})
            for item in payload.get("rows", []) if isinstance(payload, Mapping) else []:
                asset = str(_obj_get(item, "asset", "")).strip().upper()
                quantity = _to_float(_obj_get(item, "totalAmount"))
                if not asset or not quantity:
                    continue
                earn_wrappers.add(f"LD{asset}")
                earn_rows.append(
                    {
                        "symbol": asset,
                        "quantity": quantity,
                        "free": 0.0,
                        "used": quantity,
                        "source": "simple_earn_flexible",
                    }
                )
        except Exception as exc:  # noqa: BLE001 - spot holdings still remain usable
            earn_note = f"Simple Earn Flexible holdings unavailable: {type(exc).__name__}"

    rows = [
        {
            "symbol": _obj_get(row, "asset"),
            "quantity": _obj_get(row, "total"),
            "free": _obj_get(row, "free"),
            "used": _obj_get(row, "used"),
            "source": "spot",
        }
        for row in spot_balances
        if str(_obj_get(row, "asset", "")).upper() not in earn_wrappers
    ] + earn_rows
    result = {
        "status": "ok",
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
        "positions": rows,
    }
    if earn_note:
        result["note"] = earn_note
    return result


def get_open_orders(config: BinanceConfig | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    """Fetch open orders and, optionally, recent personal trades.

    ``fetch_open_orders`` is called without a symbol to retrieve all open
    orders; some Binance setups require a symbol, so the call is wrapped and a
    note is returned on failure rather than failing the whole call. When
    ``include_executions`` is set, ``fetch_my_trades`` typically REQUIRES a
    symbol, so it is also wrapped and degrades to an empty list with a note.
    """
    cfg = config or load_config()
    _reject_unsupported_usdm_surface(cfg)
    _assert_host(cfg)
    ex = _exchange(cfg)
    symbol_required = _symbol_required_errors()
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
    }
    # Only the "this call needs a symbol" family degrades to a note; auth /
    # network / rate-limit errors must propagate so the caller sees a real
    # failure instead of a misleading status:ok with an empty list.
    try:
        open_orders = ex.fetch_open_orders()
        result["open_orders"] = [_order_to_dict(item) for item in _as_iter(open_orders)]
    except symbol_required as exc:
        result["open_orders"] = []
        result["open_orders_note"] = f"fetch_open_orders without a symbol failed: {exc}"
    if include_executions:
        try:
            trades = ex.fetch_my_trades()
            result["executions"] = [_trade_to_dict(item) for item in _as_iter(trades)]
        except symbol_required as exc:
            result["executions"] = []
            result["executions_note"] = f"fetch_my_trades without a symbol failed: {exc}"
    return result


def get_quote(symbol: str, *, config: BinanceConfig | None = None, **_: Any) -> dict[str, Any]:
    """Fetch a latest ticker snapshot for ``symbol`` (ccxt unified format)."""
    cfg = config or load_config()
    _reject_unsupported_usdm_surface(cfg)
    _assert_host(cfg)
    ex = _exchange(cfg)
    clean = normalize_symbol(symbol)
    ticker = ex.fetch_ticker(clean)
    return {
        "status": "ok",
        "symbol": clean,
        "quote": {
            "bid": _obj_get(ticker, "bid"),
            "ask": _obj_get(ticker, "ask"),
            "last": _obj_get(ticker, "last"),
            "high": _obj_get(ticker, "high"),
            "low": _obj_get(ticker, "low"),
            "volume": _obj_get(ticker, "baseVolume"),
            "time": str(_obj_get(ticker, "timestamp", "")),
        },
    }


def search_instruments(
    query: str,
    *,
    config: BinanceConfig | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Resolve an exact spot pair against the selected Binance market catalog.

    Binance's exchange-info catalog has symbols and assets, but no stable
    human-readable asset names. The connector therefore resolves only explicit
    pair spellings (``ETH-USDT``, ``ETH/USDT`` or ``ETHUSDT``) and never guesses
    from prose such as ``Ethereum``.
    """
    cfg = config or load_config()
    _reject_unsupported_usdm_surface(cfg)
    _assert_host(cfg)

    requested = normalize_symbol(query)
    if "/" not in requested:
        return {"status": "ok", "query": query, "instruments": []}

    try:
        bounded_limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError, OverflowError):
        bounded_limit = 10

    markets = _exchange(cfg).load_markets()
    if not isinstance(markets, Mapping):
        raise BinanceConfigError("Binance load_markets returned a non-mapping payload")

    instruments: list[dict[str, Any]] = []
    for key, raw_market in markets.items():
        if not isinstance(raw_market, Mapping):
            continue
        native_symbol = normalize_symbol(str(raw_market.get("symbol") or key))
        if native_symbol != requested:
            continue
        if raw_market.get("spot") is False or raw_market.get("active") is False:
            continue
        base, quote = native_symbol.split("/", 1)
        instruments.append(
            {
                "symbol": f"{base}-{quote}",
                "native_symbol": native_symbol,
                "exchange_symbol": str(raw_market.get("id") or "").strip() or None,
                "base": base,
                "quote": quote,
                "market": "crypto",
                "type": "cryptocurrency",
                "exchange": "BINANCE",
                "active": raw_market.get("active"),
            }
        )
        if len(instruments) >= bounded_limit:
            break

    return {"status": "ok", "query": query, "instruments": instruments}


#: Project/canonical period token → ccxt unified timeframe (lowercase).
_TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "1H": "1h", "4h": "4h", "4H": "4h",
    "1d": "1d", "1D": "1d", "1w": "1w", "1W": "1w", "1M": "1M",
}


def get_historical_bars(
    symbol: str,
    *,
    config: BinanceConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    """Fetch historical OHLCV bars for ``symbol`` (ccxt unified format)."""
    cfg = config or load_config()
    _reject_unsupported_usdm_surface(cfg)
    _assert_host(cfg)
    ex = _exchange(cfg)
    clean = normalize_symbol(symbol)
    timeframe = _TIMEFRAME_MAP.get(period.strip(), "1d")
    bars = ex.fetch_ohlcv(clean, timeframe=timeframe, limit=int(limit))
    return {
        "status": "ok",
        "symbol": clean,
        "period": period,
        "bars": [_ohlcv_to_dict(item) for item in _as_iter(bars)],
    }


# ---------------------------------------------------------------------------
# Order placement (write path; guarded by host separation + profile readonly)
# ---------------------------------------------------------------------------

#: ccxt ``timeInForce`` values Binance spot accepts for limit orders. Binance
#: has no DAY policy; the unified ``"day"`` intent maps to GTC, which is the
#: Binance default and the closest equivalent.
_TIME_IN_FORCE_MAP = {
    "day": "GTC",
    "gtc": "GTC",
    "ioc": "IOC",
    "fok": "FOK",
}


def place_order(
    config: BinanceConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place a spot order on Binance via ccxt's unified ``create_order``.

    The configured profile's host (testnet vs live) is the authoritative
    paper/live discriminator and is asserted before anything is submitted, so a
    testnet key can never reach the live host. The connector simply executes the
    intent the caller has already authorized; mandate/limit enforcement lives in
    a higher layer.

    Either ``quantity`` (base-asset amount) or ``notional`` (quote-asset spend)
    must be given, never both. ``notional`` is only supported for market orders:
    ccxt's binance adapter forwards ``params={"quoteOrderQty": notional}`` so
    Binance sizes the order in the quote asset (e.g. spend 50 USDT of BTC).
    Limit orders require ``quantity`` and ``limit_price``.

    Args:
        config: Connector config; falls back to the saved config when ``None``.
        symbol: Trading pair in any accepted form (normalized to ``BASE/QUOTE``).
        side: ``"buy"`` or ``"sell"``.
        quantity: Base-asset amount. Mutually exclusive with ``notional``.
        notional: Quote-asset spend (market orders only). Mutually exclusive
            with ``quantity``.
        order_type: ``"market"`` or ``"limit"``.
        limit_price: Required when ``order_type`` is ``"limit"``.
        time_in_force: Limit-order policy; ``"day"`` maps to Binance GTC.

    Returns:
        On success: ``{"status": "ok", "order_id": str, "symbol", "side",
        "profile", "order_type", "status", "filled", "amount", "price"}``. On
        any validation or execution failure: ``{"status": "error", "error":
        str}`` (fail-closed; nothing is submitted on a validation error).
    """
    cfg = config or load_config()

    if cfg.market_type == "usdm":
        return {
            "status": "error",
            "error": "Binance USD-M Shadow Account is read-only",
        }

    side_clean = str(side or "").strip().lower()
    if side_clean not in ("buy", "sell"):
        return {"status": "error", "error": "side must be 'buy' or 'sell'."}

    type_clean = str(order_type or "").strip().lower()
    if type_clean not in ("market", "limit"):
        return {"status": "error", "error": "order_type must be 'market' or 'limit'."}

    qty_given = quantity is not None
    notional_given = notional is not None
    if qty_given == notional_given:
        return {"status": "error", "error": "provide exactly one of 'quantity' or 'notional'."}

    qty_value = _to_float(quantity) if qty_given else None
    notional_value = _to_float(notional) if notional_given else None
    if qty_given and (qty_value is None or qty_value <= 0):
        return {"status": "error", "error": "quantity must be a positive number."}
    if notional_given and (notional_value is None or notional_value <= 0):
        return {"status": "error", "error": "notional must be a positive number."}

    if type_clean == "limit":
        if notional_given:
            return {"status": "error", "error": "limit orders require 'quantity', not 'notional'."}
        price_value = _to_float(limit_price)
        if price_value is None or price_value <= 0:
            return {"status": "error", "error": "limit orders require a positive 'limit_price'."}
    else:
        price_value = None

    # The connector merely executes against whatever environment the profile
    # selects; readonly/mandate gating is enforced upstream (service + profile
    # capabilities), not inside the connector. The host separation asserted next
    # is the one structural guard that cannot be bypassed here.
    try:
        _assert_host(cfg)
    except BinanceConfigError as exc:
        return {"status": "error", "error": str(exc)}

    clean_symbol = normalize_symbol(symbol)
    if not clean_symbol or "/" not in clean_symbol:
        return {"status": "error", "error": f"could not resolve a valid trading pair from symbol '{symbol}'."}

    params: dict[str, Any] = {}
    if type_clean == "limit":
        tif = _TIME_IN_FORCE_MAP.get(str(time_in_force or "").strip().lower())
        if tif is None:
            return {"status": "error", "error": "time_in_force must be one of 'day', 'gtc', 'ioc', 'fok'."}
        params["timeInForce"] = tif
        amount: float | None = qty_value
        price: float | None = price_value
    elif notional_given:
        # ccxt's binance adapter reads ``quoteOrderQty`` from params and sizes the
        # order in the quote asset; ``amount`` carries the same notional so callers
        # that inspect the unified amount see a sensible value.
        params["quoteOrderQty"] = notional_value
        amount = notional_value
        price = None
    else:
        amount = qty_value
        price = None

    try:
        ex = _exchange(cfg)
        order = ex.create_order(clean_symbol, type_clean, side_clean, amount, price, params)
    except Exception as exc:  # noqa: BLE001 - surface any ccxt/auth/network error as fail-closed
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "order_id": str(_obj_get(order, "id", "")),
        "symbol": _obj_get(order, "symbol", clean_symbol),
        "side": str(_obj_get(order, "side", side_clean)),
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
        "order_type": str(_obj_get(order, "type", type_clean)),
        "order_status": str(_obj_get(order, "status", "")),
        "filled": _obj_get(order, "filled"),
        "amount": _obj_get(order, "amount"),
        "price": _obj_get(order, "price"),
    }


def cancel_order(
    config: BinanceConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel an open order by id. Binance REQUIRES the order's symbol.

    Args:
        config: Connector config; falls back to the saved config when ``None``.
        order_id: The exchange order id to cancel.
        symbol: The order's trading pair. Binance cannot cancel without it.

    Returns:
        On success: ``{"status": "ok", "order_id", "symbol", "side", "profile",
        "order_status"}``. On any validation or execution failure:
        ``{"status": "error", "error": str}`` (fail-closed).
    """
    cfg = config or load_config()

    if cfg.market_type == "usdm":
        return {
            "status": "error",
            "error": "Binance USD-M Shadow Account is read-only",
        }

    order_id_clean = str(order_id or "").strip()
    if not order_id_clean:
        return {"status": "error", "error": "order_id is required to cancel an order."}
    if symbol is None or not str(symbol).strip():
        return {"status": "error", "error": "Binance cancel requires symbol."}

    try:
        _assert_host(cfg)
    except BinanceConfigError as exc:
        return {"status": "error", "error": str(exc)}

    clean_symbol = normalize_symbol(symbol)
    if not clean_symbol or "/" not in clean_symbol:
        return {"status": "error", "error": f"could not resolve a valid trading pair from symbol '{symbol}'."}

    try:
        ex = _exchange(cfg)
        order = ex.cancel_order(order_id_clean, clean_symbol)
    except Exception as exc:  # noqa: BLE001 - surface any ccxt/auth/network error as fail-closed
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "order_id": str(_obj_get(order, "id", order_id_clean)),
        "symbol": _obj_get(order, "symbol", clean_symbol),
        "side": str(_obj_get(order, "side", "")),
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
        "order_status": str(_obj_get(order, "status", "")),
    }


# ---------------------------------------------------------------------------
# SDK plumbing
# ---------------------------------------------------------------------------


def _require_ccxt() -> ModuleType:
    try:
        import ccxt  # type: ignore
    except ModuleNotFoundError as exc:
        raise BinanceDependencyError("ccxt is not installed; run `pip install ccxt`.") from exc
    return ccxt


def _symbol_required_errors() -> tuple[type[BaseException], ...]:
    """ccxt exception classes that mean "this call needs a symbol" (degrade-only).

    Auth/network/rate-limit errors are deliberately excluded so they propagate
    rather than being masked as a status:ok note.
    """
    ccxt = _require_ccxt()
    names = ("ArgumentsRequired", "BadSymbol", "NotSupported")
    classes = tuple(getattr(ccxt, n) for n in names if hasattr(ccxt, n))
    return classes or (ValueError,)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _reject_unsupported_usdm_surface(cfg: BinanceConfig) -> None:
    if cfg.market_type == "usdm":
        raise BinanceConfigError(
            "Binance USD-M Shadow Account exposes account and position reads only"
        )


def _get_usdm_observation(cfg: BinanceConfig, exchange: Any) -> dict[str, Any]:
    try:
        return read_account_observation(
            exchange,
            source_profile="binance-live-sdk-readonly",
            host=cfg.host,
            now=_utc_now,
            absolute_tolerance=cfg.observation_absolute_tolerance,
        )
    except UsdMObservationError as exc:
        raise BinanceConfigError(str(exc)) from None


def _exchange(cfg: BinanceConfig):
    """Build a ccxt Binance client bound to the configured market/environment."""
    ccxt = _require_ccxt()
    client_config: dict[str, Any] = {
        "apiKey": cfg.api_key,
        "secret": cfg.api_secret,
        "enableRateLimit": True,
        "timeout": int(cfg.timeout * 1000),
        # Signed Binance requests have a narrow timestamp window. Let ccxt
        # measure the exchange clock before the first private request so a
        # sleeping laptop or an imperfect system clock does not force users to
        # reconnect or recreate an otherwise valid read-only API key.
        "options": {
            "adjustForTimeDifference": True,
            "recvWindow": 10_000,
        },
    }
    # ``requests``/ccxt does not consistently inherit the macOS System Proxy.
    # urllib resolves both conventional proxy environment variables and the
    # active macOS network proxy, so local desktop connectors follow the same
    # route as the user's browser without persisting proxy details or secrets.
    system_proxies = getproxies()
    proxies = {
        scheme: str(system_proxies[scheme]).strip()
        for scheme in ("http", "https")
        if str(system_proxies.get(scheme) or "").strip()
    }
    if proxies:
        client_config["proxies"] = proxies
    exchange_class = ccxt.binanceusdm if cfg.market_type == "usdm" else ccxt.binance
    ex = exchange_class(client_config)
    ex.set_sandbox_mode(cfg.is_testnet)
    if cfg.market_type == "usdm":
        try:
            assert_exchange_endpoints(ex)
        except UsdMObservationError as exc:
            raise BinanceConfigError(str(exc)) from None
    return ex


def _assert_host(cfg: BinanceConfig) -> None:
    """Fail closed when the resolved host does not match the declared environment.

    The host is the authoritative discriminator: testnet keys cannot reach the
    live host. A live profile must resolve to ``api.binance.com``; a paper
    profile must resolve to the configured testnet host.
    """
    host = (urlparse(cfg.host).hostname or cfg.host or "").lower()
    if cfg.is_testnet:
        expected = (urlparse(cfg.testnet_host).hostname or cfg.testnet_host or "").lower()
        if host != expected:
            raise BinanceConfigError(
                f"Configured profile is paper, but the resolved host '{host}' is not the testnet host '{expected}'."
            )
        return
    expected_url = USDM_LIVE_HOST if cfg.market_type == "usdm" else LIVE_HOST
    expected = urlparse(expected_url).hostname or expected_url
    if host != expected:
        raise BinanceConfigError(
            f"Configured profile is live, but the resolved host '{host}' is not the live host '{expected}'."
        )


def _missing_fields(cfg: BinanceConfig) -> list[str]:
    missing = []
    if not cfg.api_key:
        missing.append("api_key")
    if not cfg.api_secret:
        missing.append("api_secret")
    return missing


def _public_config(cfg: BinanceConfig) -> dict[str, Any]:
    """Config snapshot with secrets redacted."""
    data = asdict(cfg)
    if data.get("api_secret"):
        data["api_secret"] = "***redacted***"
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:4] + "***"
    data["host"] = cfg.host
    return data
