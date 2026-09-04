"""Zerodha Kite Connect connector SDK (read path + paper-capped orders).

Mirrors the Shoonya/Dhan connector surface so the ``india_broker`` loader can
treat Zerodha uniformly:

  get_historical_bars(symbol, *, exchange="NSE", period="1d", limit=90)
      -> {"status": "ok", "symbol": ..., "bars": [{time, open, high, low, close, volume}]}
  get_account_snapshot() / get_positions() / get_open_orders() / get_quote(symbol)
      -> Shoonya-shaped read envelopes (the ``service.py`` broker_sdk surface)

Kite specifics handled here:
  * interval map: project tokens (1m/5m/15m/30m/1h/1d) -> Kite intervals
    (minute/5minute/15minute/30minute/60minute/day). ``4h`` is rejected, not
    aliased: Kite has no 4h interval, and returning daily candles under a 4h
    period would silently mislabel data (fail closed, like Dhan).
  * Kite caps each historical request at a per-interval number of days
    (1m: 60, 5m: 100, 15m/30m: 200, 60m: 400, day: 2000); we paginate the
    [start, end] range into cap-sized windows and normalize the resulting
    index to UTC-naive (matching the loader).
  * Symbols: project ``RELIANCE.NS`` -> Kite ``exchange=NSE``,
    ``tradingsymbol=RELIANCE``. Token-based fetch is also supported if the
    instrument token is supplied, but the symbol form mirrors Shoonya/Dhan.

Paper guard: like Shoonya, Kite exposes no sandbox, so live order placement is
structurally refused (paper profile only).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "zerodha.json"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

KITE_HIST_BASE = "https://api.kite.trade"

#: India Standard Time (Kite timestamps are IST).
_IST = timezone(timedelta(hours=5, minutes=30))

_PAPER_ONLY_ERROR = (
    "Zerodha connector is paper-only: Kite exposes no runtime paper/live "
    "discriminator (a live token reaches the real account), so live order "
    "placement is not supported. Use a zerodha-paper-* profile."
)


class ZerodhaDependencyError(RuntimeError):
    """Raised when ``kiteconnect`` is not installed."""


class ZerodhaConfigError(RuntimeError):
    """Raised when config is missing or invalid."""


class ZerodhaExchange:
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"  # NSE F&O
    BFO = "BFO"  # BSE F&O
    CDS = "CDS"  # Currency
    MCX = "MCX"  # Commodity


@dataclass(frozen=True)
class ZerodhaConfig:
    """Zerodha connector connection settings."""

    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    profile: str = "paper"
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "ZerodhaConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise ZerodhaConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            api_secret=str(payload.get("api_secret") or "").strip(),
            access_token=str(payload.get("access_token") or "").strip(),
            profile=profile,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(self, **kw: Any) -> "ZerodhaConfig":
        payload = asdict(self)
        for key in ("api_key", "api_secret", "access_token", "profile"):
            if kw.get(key) is not None:
                payload[key] = kw[key]
        return ZerodhaConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_paper(self) -> bool:
        return self.environment == "paper"


_OVERRIDE_KEYS = ("api_key", "api_secret", "access_token", "profile")

#: Project interval token -> Kite interval. ``4h`` is deliberately absent:
#: Kite has no 4h interval and aliasing it to daily would return mislabeled
#: daily candles (fail closed instead).
_INTERVAL_MAP = {
    "1m": "minute",
    "5m": "5minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1H": "60minute",
    "1d": "day",
    "1D": "day",
}

#: Kite caps each historical request at this many calendar days per interval
#: (documented API limits; a wider span raises "interval exceeds max limit").
_KITE_MAX_SPAN_DAYS: dict[str, int] = {
    "minute": 60,
    "5minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
    "day": 2000,
}


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> ZerodhaConfig:
    path = config_path()
    if not path.exists():
        return ZerodhaConfig()
    try:
        return ZerodhaConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ZerodhaConfigError(f"invalid Zerodha config at {path}: {exc}") from exc


def save_config(config: ZerodhaConfig) -> Path:
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


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> "ZerodhaConfig":
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = ZerodhaConfig.from_mapping(base)
    clean = {
        k: v for k, v in dict(overrides or {}).items()
        if k in _OVERRIDE_KEYS and v not in (None, "")
    }
    return cfg.with_overrides(**clean) if clean else cfg


def _require_kite():
    try:
        from kiteconnect import KiteConnect  # type: ignore
    except ImportError as exc:  # optional dependency
        raise ZerodhaDependencyError(
            "Optional dependency missing: install with `pip install \"vibe-trading-ai[zerodha]\"`"
        ) from exc
    return KiteConnect


def zerodha_available() -> bool:
    """True only when ``kiteconnect`` is importable AND credentials exist.

    The ``india_broker`` loader treats the first available connector as *the*
    broker (``_resolve_broker`` never falls through to the next one after a
    runtime error), so an import-only check would let an unconfigured install
    shadow a configured Shoonya/Dhan account. Mirrors the loader's documented
    contract: available only when the SDK is importable AND a broker is
    configured.
    """
    try:
        _require_kite()
    except ZerodhaDependencyError:
        return False
    cfg = load_config()
    return bool(cfg.api_key and cfg.access_token)


def _public_config(cfg: ZerodhaConfig) -> dict[str, Any]:
    return {
        "api_key_set": bool(cfg.api_key),
        "access_token_set": bool(cfg.access_token),
        "profile": cfg.profile,
    }


def _login(cfg: ZerodhaConfig):
    """Return an authenticated KiteConnect client (access_token set)."""
    KiteConnect = _require_kite()
    if not cfg.api_key:
        raise ZerodhaConfigError("api_key is required")
    kite = KiteConnect(api_key=cfg.api_key)
    if cfg.access_token:
        kite.set_access_token(cfg.access_token)
    elif cfg.api_secret:
        # Without a request token we cannot mint a fresh access token headlessly;
        # the user must supply either access_token or run the login helper.
        raise ZerodhaConfigError(
            "access_token is required (Kite login needs an interactive "
            "request-token exchange; supply access_token directly)"
        )
    return kite


def check_status(config: ZerodhaConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "kiteconnect", "installed": zerodha_available()},
        "paper_guard": "simulated_locally",
        "host": KITE_HIST_BASE,
        "brokerage": "Zerodha equity delivery ₹0; intraday 0.03% / ₹20 flat",
    }
    missing = []
    if not cfg.api_key:
        missing.append("api_key")
    if not cfg.access_token:
        missing.append("access_token")
    if missing:
        report["status"] = "error"
        report["error"] = f"Zerodha connector not configured: missing {', '.join(missing)}."
        return report
    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install \"vibe-trading-ai[zerodha]\"`"
        return report
    return report


def _bar_epoch(ts: Any, *, day_bar: bool) -> int | None:
    """Epoch (UTC-naive seconds) for a Kite candle timestamp.

    Kite timestamps are IST. Intraday candles are real instants, so the UTC
    epoch is exact. Day candles are dated at midnight IST; shifting that
    instant to UTC (18:30 the *previous* day) would relabel every daily bar
    one calendar day early and make the loader's date-range clip drop the
    first day of each window — so day bars keep their IST calendar date at
    midnight UTC instead.
    """
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:  # kiteconnect is tz-aware; defensive fallback
        ts = ts.replace(tzinfo=_IST)
    if day_bar:
        return int(datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc).timestamp())
    return int(ts.astimezone(timezone.utc).timestamp())


def get_historical_bars(
    symbol: str,
    *,
    config: ZerodhaConfig | None = None,
    exchange: str = "NSE",
    period: str = "1d",
    limit: int = 90,
) -> dict[str, Any]:
    """Fetch historical OHLCV bars from Kite, paginated past the per-interval cap."""
    cfg = config or load_config()
    clean = symbol.strip().upper()

    interval = _INTERVAL_MAP.get(str(period).strip())
    if interval is None:
        return {
            "status": "error",
            "error": f"unsupported period: {period!r}; supported: {sorted(_INTERVAL_MAP)}",
            "symbol": clean,
        }

    try:
        kite = _login(cfg)
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}

    # Size the window to `limit` bars with 2x trading-day headroom, like the
    # day path. Dense intervals (1m/5m/15m/30m) stay within their per-request
    # cap: 60 days of 1m candles is already ~22k rows, and Kite's own
    # retention for these is bounded anyway. 60minute/day paginate past their
    # caps, so a 1h request is no longer truncated to 5 days.
    end = datetime.now(timezone.utc)
    cap = _KITE_MAX_SPAN_DAYS[interval]
    window = min(limit * 2, 4000)
    if interval in ("minute", "5minute", "15minute", "30minute"):
        window = min(window, cap)
    start = end - timedelta(days=window)

    # Resolve the instrument token once (the exchange dump is cached).
    try:
        token = _symbol_to_token(kite, clean, exchange)
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}

    bars: list[dict[str, Any]] = []
    # Paginate in per-interval chunks (Kite hard cap per request).
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=cap), end)
        try:
            rows = kite.historical_data(
                instrument_token=token,
                from_date=chunk_start,
                to_date=chunk_end,
                interval=interval,
            )
        except Exception as exc:  # noqa: BLE001 — one bad symbol never aborts
            return {"status": "error", "error": str(exc), "symbol": clean}
        for r in rows:
            ts_epoch = _bar_epoch(r.get("date"), day_bar=(interval == "day"))
            if ts_epoch is None:
                continue
            bars.append({
                "time": ts_epoch,
                "open": float(r.get("open", 0)),
                "high": float(r.get("high", 0)),
                "low": float(r.get("low", 0)),
                "close": float(r.get("close", 0)),
                "volume": int(r.get("volume", 0)),
            })
        # Kite's from/to dates are inclusive; advance a full day so the
        # boundary candle is not fetched twice by the next chunk.
        chunk_start = chunk_end + timedelta(days=1)

    if not bars:
        return {"status": "ok", "symbol": clean, "exchange": exchange, "period": period, "bars": []}
    return {
        "status": "ok",
        "symbol": clean,
        "exchange": exchange,
        "period": period,
        "bars": bars[-limit:],
    }


#: Kite's full instrument list per exchange, cached per process. The dump is
#: large (tens of MB) and static within a session; re-downloading it on every
#: bar fetch would dominate the read path.
_INSTRUMENT_CACHE: dict[str, tuple[dict[str, Any], ...]] = {}


def _symbol_to_token(kite, symbol: str, exchange: str) -> int:
    """Resolve a tradingsymbol+exchange to an instrument token.

    The instrument list is fetched once per exchange and cached for the
    process. A cache miss surfaces the real API error instead of masquerading
    as "token not found".
    """
    instruments = _INSTRUMENT_CACHE.get(exchange)
    if instruments is None:
        try:
            instruments = tuple(kite.instruments(exchange=exchange) or ())
        except Exception as exc:
            raise ZerodhaConfigError(
                f"failed to fetch {exchange} instrument list: {exc}"
            ) from exc
        _INSTRUMENT_CACHE[exchange] = instruments
    for inst in instruments:
        if inst.get("tradingsymbol", "").upper() == symbol.upper():
            return int(inst["instrument_token"])
    raise ZerodhaConfigError(f"instrument token not found for {symbol} ({exchange})")


def get_quote(
    symbol: str,
    *,
    config: ZerodhaConfig | None = None,
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = config or load_config()
    clean = symbol.strip().upper()
    try:
        kite = _login(cfg)
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}
    try:
        q = kite.quote([f"{exchange}:{clean}"])
        last = q.get(f"{exchange}:{clean}", {})
    except Exception as exc:
        return {"status": "error", "error": str(exc), "symbol": clean}
    return {
        "status": "ok",
        "symbol": clean,
        "exchange": exchange,
        "quote": {
            "ltp": float(last.get("last_price", 0)),
            "open": float(last.get("ohlc", {}).get("open", 0)),
            "high": float(last.get("ohlc", {}).get("high", 0)),
            "low": float(last.get("ohlc", {}).get("low", 0)),
            "close": float(last.get("ohlc", {}).get("close", 0)),
            "volume": int(last.get("volume", 0)),
        },
    }


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce a Kite API field to float, tolerating None/empty strings."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def get_account_snapshot(config: ZerodhaConfig | None = None) -> dict[str, Any]:
    """Read fund/margin summary from Kite (equity segment)."""
    cfg = config or load_config()
    try:
        kite = _login(cfg)
        margins = kite.margins()
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — one bad read never aborts
        return {"status": "error", "error": str(exc)}
    equity = margins.get("equity", {}) if isinstance(margins, dict) else {}
    available = equity.get("available", {}) or {}
    utilised = equity.get("utilised", {}) or {}
    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "host": KITE_HIST_BASE,
        "brokerage": "Zerodha equity delivery ₹0; intraday 0.03% / ₹20 flat",
        "account": {
            "currency": "INR",
            "cash": _num(available.get("cash")),
            "margin_available": _num(equity.get("net")),
            "margin_used": _num(utilised.get("margins")),
            "collateral": _num(available.get("collateral")),
            "payin": _num(available.get("intraday_payin")),
        },
    }


def get_positions(config: ZerodhaConfig | None = None) -> dict[str, Any]:
    """Read open (net) positions from Kite."""
    cfg = config or load_config()
    try:
        kite = _login(cfg)
        positions = kite.positions()
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — one bad read never aborts
        return {"status": "error", "error": str(exc)}
    raw = positions.get("net", []) if isinstance(positions, dict) else positions
    rows = []
    for item in _as_list(raw):
        rows.append({
            "symbol": item.get("tradingsymbol", ""),
            "exchange": item.get("exchange", ""),
            "product_type": item.get("product", ""),
            "quantity": int(_num(item.get("quantity", 0))),
            "average_cost": _num(item.get("average_price", 0)),
            "ltp": _num(item.get("last_price", 0)),
            "unrealized_pnl": _num(item.get("unrealised", 0)),
            "realized_pnl": _num(item.get("realised", 0)),
            "overnight_quantity": int(_num(item.get("overnight_quantity", 0))),
            "multiplier": _num(item.get("multiplier", 1)),
        })
    return {"status": "ok", "profile": cfg.profile, "is_paper": cfg.is_paper, "positions": rows}


def get_open_orders(
    config: ZerodhaConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Read the Kite order book; open orders, optionally executions."""
    cfg = config or load_config()
    try:
        kite = _login(cfg)
        orders = kite.orders()
    except ZerodhaConfigError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — one bad read never aborts
        return {"status": "error", "error": str(exc)}
    open_orders: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    for item in _as_list(orders):
        status = str(item.get("status", "")).upper()
        order = {
            "order_id": item.get("order_id", ""),
            "symbol": item.get("tradingsymbol", ""),
            "exchange": item.get("exchange", ""),
            "side": "buy" if str(item.get("transaction_type", "")).upper() == "BUY" else "sell",
            "order_type": str(item.get("order_type", "")).lower(),
            "quantity": int(_num(item.get("quantity", 0))),
            "filled_qty": int(_num(item.get("filled_quantity", 0))),
            "price": _num(item.get("price", 0)),
            "status": item.get("status", ""),
            "product_type": item.get("product", ""),
        }
        if status in ("OPEN", "PENDING", "TRIGGER_PENDING"):
            open_orders.append(order)
        elif include_executions and status in ("COMPLETE", "FILLED"):
            executions.append(order)
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "open_orders": open_orders,
    }
    if include_executions:
        result["executions"] = executions
    return result


def place_order(
    config: ZerodhaConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
    exchange: str = "NSE",
    product_type: str = "C",
) -> dict[str, Any]:
    """Place a PAPER-ONLY order on Zerodha (simulated locally).

    Kite exposes no sandbox, so this connector is structurally capped at paper:
    the very first check refuses any non-paper config. There is no live order
    path, by design.
    """
    cfg = config or load_config()
    if not cfg.is_paper:
        return {"status": "error", "error": _PAPER_ONLY_ERROR}

    # ``notional`` and ``time_in_force`` are part of the uniform service.py
    # surface but meaningless for a locally simulated paper fill.
    del notional, time_in_force

    clean_symbol = str(symbol or "").strip().upper()
    if not clean_symbol:
        return {"status": "error", "error": "symbol is required"}

    side_token = str(side or "").strip().upper()
    side_map = {"BUY": "B", "SELL": "S", "B": "B", "S": "S"}
    if side_token not in side_map:
        return {"status": "error", "error": "side must be 'buy' or 'sell'"}
    buy_or_sell = side_map[side_token]

    if quantity is None or float(quantity) <= 0:
        return {"status": "error", "error": "quantity must be positive"}
    qty = int(float(quantity))

    return {
        "status": "ok",
        "order_id": f"PAPER-{clean_symbol}-{buy_or_sell}-{qty}",
        "symbol": clean_symbol,
        "side": side_token.lower(),
        "profile": cfg.profile,
        "is_paper": True,
        "paper_guard": "simulated_locally",
        "order_type": order_type.lower(),
        "quantity": qty,
        "limit_price": float(limit_price) if limit_price is not None else None,
        "order_status": "simulated_fill",
        "exchange": exchange,
        "product_type": product_type,
    }


def cancel_order(
    config: ZerodhaConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel a PAPER-ONLY order (simulated locally).

    Kite exposes no sandbox, so like ``place_order`` this is structurally
    capped at paper: the very first check refuses any non-paper config, and a
    cancel is a local simulation, never a live API call.
    """
    cfg = config or load_config()
    if not cfg.is_paper:
        return {"status": "error", "error": _PAPER_ONLY_ERROR}

    clean_id = str(order_id or "").strip()
    if not clean_id:
        return {"status": "error", "error": "order_id is required"}

    return {
        "status": "ok",
        "order_id": clean_id,
        "symbol": symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None,
        "profile": cfg.profile,
        "is_paper": True,
        "cancelled": True,
    }
