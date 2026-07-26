"""Real-time bridge to a running VeighNa (vn.py) ``MainEngine`` over its RPC service.

Architecture: vn.py's built-in ``vnpy_rpcservice`` app exposes a ``MainEngine``
over ZeroMQ — a REQ/REP socket for remote calls (``send_order``, ``cancel_order``,
``subscribe``, ``query_history``, the ``get_*``/``get_all_*`` readers) and a
PUB/SUB socket that republishes every engine event (ticks, trades, orders,
positions, accounts, logs) in real time. This module is a thin client for that
service: it never touches a broker SDK directly, it talks to whatever gateway(s)
the operator has already connected inside their own vn.py Trader instance (CTP,
XTP, Tora, IB, ...).

Setup on the vn.py side (one-time, in the running Trader):
    1. Add and connect the desired gateway (CTP / XTP / Futu / IB / ...).
    2. Open the "RPC Service" app, start it (default ports 2014 req / 4102 pub).

Setup on the Vibe-Trading side: point this connector's ``req_address`` /
``sub_address`` at that vn.py instance and set ``gateway_name`` to whatever
gateway key was used on step 1 (e.g. ``"CTP"``, ``"XTP"``, ``"FUTU"``).

Paper-vs-live caveat (read before wiring a live profile): unlike Futu's OpenD,
which tags every account row with an SDK-verifiable ``trd_env``, a vn.py RPC
endpoint has no runtime-discoverable paper/live discriminator — that boundary
is entirely a property of *which broker account the operator logged the remote
vn.py instance into*. This connector cannot verify it, so ``place_order`` /
``cancel_order`` fail closed unless the caller sets
``assume_environment_verified=True`` in the config, which is a manual
acknowledgement that the operator has confirmed the remote instance's gateway
session by hand.
"""

from __future__ import annotations

import json
import queue
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "vnpy.json"

#: Default vn.py RpcService endpoints (see vnpy_rpcservice.rpc_service.engine).
DEFAULT_REQ_ADDRESS = "tcp://127.0.0.1:2014"
DEFAULT_SUB_ADDRESS = "tcp://127.0.0.1:4102"

PROFILE_ENVIRONMENTS = {"paper": "paper", "live": "live"}


class VnpyDependencyError(RuntimeError):
    """Raised when the optional ``vnpy`` package is not installed."""


class VnpyConfigError(RuntimeError):
    """Raised when the connector configuration is missing or invalid."""


@dataclass(frozen=True)
class VnpyConfig:
    """VeighNa RPC bridge connection settings.

    Args:
        req_address: ZeroMQ REQ endpoint of the remote vn.py RpcService.
        sub_address: ZeroMQ SUB endpoint of the remote vn.py RpcService.
        profile: ``paper`` or ``live`` — a label only; see module docstring.
        gateway_name: The gateway key connected inside the remote vn.py
            instance (e.g. ``CTP``, ``XTP``, ``FUTU``, ``IB``).
        timeout: RPC round-trip timeout in seconds.
        quote_wait: Seconds to listen on the SUB feed for a fresh tick after
            subscribing, for :func:`get_quote`.
        assume_environment_verified: Manual fail-closed gate for order
            placement/cancellation — see module docstring.
    """

    req_address: str = DEFAULT_REQ_ADDRESS
    sub_address: str = DEFAULT_SUB_ADDRESS
    profile: str = "paper"
    gateway_name: str = ""
    timeout: float = 10.0
    quote_wait: float = 3.0
    assume_environment_verified: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "VnpyConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise VnpyConfigError("profile must be 'paper' or 'live'")
        return cls(
            req_address=str(payload.get("req_address") or DEFAULT_REQ_ADDRESS).strip(),
            sub_address=str(payload.get("sub_address") or DEFAULT_SUB_ADDRESS).strip(),
            profile=profile,
            gateway_name=str(payload.get("gateway_name") or "").strip(),
            timeout=float(payload.get("timeout") or 10.0),
            quote_wait=float(payload.get("quote_wait") or 3.0),
            assume_environment_verified=bool(payload.get("assume_environment_verified", False)),
        )

    def with_overrides(self, **overrides: Any) -> "VnpyConfig":
        payload = asdict(self)
        for key, value in overrides.items():
            if value is not None:
                payload[key] = value
        return VnpyConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")


_OVERRIDE_KEYS = (
    "req_address", "sub_address", "profile", "gateway_name",
    "timeout", "quote_wait", "assume_environment_verified",
)


def build_config(profile_config: Mapping[str, Any] | None = None, overrides: Mapping[str, Any] | None = None) -> VnpyConfig:
    """Resolve the effective config: saved file <- profile defaults <- overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = VnpyConfig.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> VnpyConfig:
    path = config_path()
    if not path.exists():
        return VnpyConfig()
    try:
        return VnpyConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VnpyConfigError(f"invalid vnpy config at {path}: {exc}") from exc


def save_config(config: VnpyConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def vnpy_available() -> bool:
    try:
        _require_vnpy()
        return True
    except VnpyDependencyError:
        return False


def _require_vnpy():
    try:
        from vnpy.rpc import RpcClient  # noqa: F401
        from vnpy.trader import object as vnpy_object  # noqa: F401
        from vnpy.trader import constant  # noqa: F401
    except ModuleNotFoundError as exc:
        raise VnpyDependencyError(
            "vnpy is not installed; run `pip install vnpy` (this bridge only needs "
            "vnpy.rpc + vnpy.trader.object, but the vnpy package itself pulls in its "
            "PySide6 GUI dependency chain)."
        ) from exc


def _tcp_host_port(address: str) -> tuple[str, int]:
    """Parse host:port out of a ``tcp://host:port`` zmq endpoint string."""
    rest = address.split("://", 1)[-1]
    host, _, port = rest.partition(":")
    return (host or "127.0.0.1", int(port or 0))


def tcp_port_open(address: str, timeout: float = 0.5) -> bool:
    host, port = _tcp_host_port(address)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _QueueClient:
    """A short-lived vn.py ``RpcClient`` that queues published events."""

    def __init__(self, cfg: VnpyConfig) -> None:
        from vnpy.rpc import RpcClient

        self._events: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        class _Client(RpcClient):
            def callback(_self, topic: str, data: Any) -> None:  # noqa: N805
                self._events.put((topic, data))

        self._client = _Client()
        self._client.subscribe_topic("")
        self._client.start(cfg.req_address, cfg.sub_address)
        self.cfg = cfg

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", int(self.cfg.timeout * 1000))
        return getattr(self._client, name)(*args, **kwargs)

    def drain_events(self, seconds: float) -> list[tuple[str, Any]]:
        import time

        events: list[tuple[str, Any]] = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                events.append(self._events.get(timeout=remaining))
            except queue.Empty:
                break
        return events

    def close(self) -> None:
        self._client.stop()
        self._client.join()


def check_status(config: VnpyConfig | None = None) -> dict[str, Any]:
    """Check SDK readiness and RPC reachability. Never mutates remote state."""
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": asdict(cfg),
        "sdk": {"package": "vnpy", "installed": vnpy_available()},
    }

    reachable = tcp_port_open(cfg.req_address)
    report["gateway"] = {"req_address": cfg.req_address, "sub_address": cfg.sub_address, "open": reachable}
    if not reachable:
        report["status"] = "error"
        report["error"] = (
            f"No vn.py RpcService is listening at {cfg.req_address}. "
            "Open the RPC Service app in the vn.py Trader and click Start."
        )
        return report

    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install vnpy`."
        return report

    client = _QueueClient(cfg)
    try:
        contracts = client.call("get_all_contracts")
        accounts = client.call("get_all_accounts")
    except Exception as exc:  # noqa: BLE001 - health endpoint reports cleanly
        report["status"] = "error"
        report["error"] = str(exc)
        return report
    finally:
        client.close()

    report["contract_count"] = len(contracts or [])
    report["account_count"] = len(accounts or [])
    report["gateway_name"] = cfg.gateway_name
    return report


def get_account_snapshot(config: VnpyConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    client = _QueueClient(cfg)
    try:
        accounts = client.call("get_all_accounts")
        return {"status": "ok", "profile": cfg.profile, "accounts": [_account_to_dict(a) for a in accounts]}
    finally:
        client.close()


def get_positions(config: VnpyConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    client = _QueueClient(cfg)
    try:
        positions = client.call("get_all_positions")
        return {"status": "ok", "profile": cfg.profile, "positions": [_position_to_dict(p) for p in positions]}
    finally:
        client.close()


def get_open_orders(config: VnpyConfig | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    client = _QueueClient(cfg)
    try:
        orders = client.call("get_all_active_orders")
        result: dict[str, Any] = {
            "status": "ok",
            "profile": cfg.profile,
            "open_orders": [_order_to_dict(o) for o in orders],
        }
        if include_executions:
            trades = client.call("get_all_trades")
            result["executions"] = [_trade_to_dict(t) for t in trades]
        return result
    finally:
        client.close()


def get_quote(symbol: str, *, config: VnpyConfig | None = None, **_: Any) -> dict[str, Any]:
    """Subscribe on the remote gateway and listen for one fresh tick.

    Unlike a request/response quote API, vn.py pushes ticks over its PUB feed —
    there is no synchronous "give me the current price" RPC call. ``RpcEngine``
    republishes every engine ``Event`` under an empty topic, so this subscribes
    then drains the event queue for ``cfg.quote_wait`` seconds unwrapping each
    ``Event`` looking for ``eTick.<vt_symbol>``.
    """
    cfg = config or load_config()
    code, exchange = _split_symbol(symbol)
    from vnpy.trader.event import EVENT_TICK
    from vnpy.trader.object import SubscribeRequest

    client = _QueueClient(cfg)
    try:
        req = SubscribeRequest(symbol=code, exchange=exchange)
        client.call("subscribe", req, cfg.gateway_name)
        vt_symbol = req.vt_symbol
        target_type = f"{EVENT_TICK}{vt_symbol}"
        for _topic, event in client.drain_events(cfg.quote_wait):
            if getattr(event, "type", None) == target_type:
                return {"status": "ok", "symbol": vt_symbol, "quote": _tick_to_dict(event.data)}
        return {
            "status": "error",
            "symbol": vt_symbol,
            "error": f"No tick received within {cfg.quote_wait}s of subscribing.",
        }
    finally:
        client.close()


def get_historical_bars(
    symbol: str,
    *,
    config: VnpyConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    cfg = config or load_config()
    code, exchange = _split_symbol(symbol)
    from datetime import datetime, timedelta

    from vnpy.trader.object import HistoryRequest

    interval = _interval_for(period)
    lookback_days = {"1m": 5, "5m": 20, "15m": 40, "30m": 60, "1h": 90, "1d": max(limit * 2, 120)}
    end = datetime.now()
    start = end - timedelta(days=lookback_days.get(period.strip(), 120))

    req = HistoryRequest(symbol=code, exchange=exchange, start=start, end=end, interval=interval)
    client = _QueueClient(cfg)
    try:
        bars = client.call("query_history", req, cfg.gateway_name)
        bars = list(bars or [])[-int(limit):]
        return {"status": "ok", "symbol": req.vt_symbol, "period": period, "bars": [_bar_to_dict(b) for b in bars]}
    finally:
        client.close()


def _interval_for(period: str) -> Any:
    from vnpy.trader.constant import Interval

    interval_map = {
        "1m": Interval.MINUTE, "5m": Interval.MINUTE, "15m": Interval.MINUTE, "30m": Interval.MINUTE,
        "1h": Interval.HOUR, "1d": Interval.DAILY, "1D": Interval.DAILY, "1w": Interval.WEEKLY,
    }
    return interval_map.get(period.strip(), Interval.DAILY)


# ---------------------------------------------------------------------------
# Order placement (fails closed unless the remote environment is manually
# acknowledged — see module docstring for why this connector cannot verify
# paper vs. live the way Futu's OpenD trd_env guard can).
# ---------------------------------------------------------------------------

_SIDE_TO_DIRECTION = {"buy": "LONG", "sell": "SHORT"}


def place_order(
    config: VnpyConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | int | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    cfg = config or load_config()

    if not cfg.assume_environment_verified:
        return _order_error(
            cfg,
            "Refusing to place an order: this vn.py RPC bridge cannot verify whether "
            f"{cfg.req_address} is a paper or live account by itself. Confirm by hand "
            "which broker session the remote vn.py Trader is logged into, then set "
            "assume_environment_verified=true in the connector config to proceed.",
        )
    if not cfg.gateway_name:
        return _order_error(cfg, "gateway_name is required (the gateway key connected in the remote vn.py Trader)")

    side_key = str(side or "").strip().lower()
    if side_key not in _SIDE_TO_DIRECTION:
        return _order_error(cfg, "side must be 'buy' or 'sell'")
    if notional is not None:
        return _order_error(cfg, "vn.py orders are volume-based; notional-based orders are not supported")
    if quantity is None:
        return _order_error(cfg, "quantity is required")
    try:
        volume = float(quantity)
    except (TypeError, ValueError):
        return _order_error(cfg, "quantity must be a number")
    if volume <= 0:
        return _order_error(cfg, "quantity must be positive")

    order_kind = str(order_type or "").strip().lower()
    if order_kind not in ("market", "limit"):
        return _order_error(cfg, "order_type must be 'market' or 'limit'")
    price = 0.0
    if order_kind == "limit":
        if limit_price is None:
            return _order_error(cfg, "limit_price is required for a limit order")
        try:
            price = float(limit_price)
        except (TypeError, ValueError):
            return _order_error(cfg, "limit_price must be a number")

    try:
        _require_vnpy()
    except VnpyDependencyError as exc:
        return _order_error(cfg, str(exc))

    from vnpy.trader.constant import Direction, OrderType
    from vnpy.trader.object import OrderRequest

    code, exchange = _split_symbol(symbol)
    req = OrderRequest(
        symbol=code,
        exchange=exchange,
        direction=Direction[_SIDE_TO_DIRECTION[side_key]],
        type=OrderType.MARKET if order_kind == "market" else OrderType.LIMIT,
        volume=volume,
        price=price,
    )

    client = _QueueClient(cfg)
    try:
        vt_orderid = client.call("send_order", req, cfg.gateway_name)
        if not vt_orderid:
            return _order_error(cfg, "vn.py send_order returned no order id (rejected before submission)")
        return {
            "status": "ok",
            "order_id": vt_orderid,
            "symbol": req.vt_symbol,
            "side": side_key,
            "profile": cfg.profile,
            "gateway_name": cfg.gateway_name,
            "order_type": order_kind,
            "quantity": volume,
            "limit_price": price if order_kind == "limit" else None,
            "time_in_force": str(time_in_force or "day"),
        }
    except Exception as exc:  # noqa: BLE001 - order path must fail closed
        return _order_error(cfg, str(exc))
    finally:
        client.close()


def cancel_order(
    config: VnpyConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()

    if not cfg.assume_environment_verified:
        return _order_error(cfg, "Refusing to cancel: assume_environment_verified is not set (see place_order).")

    oid = str(order_id or "").strip()
    if not oid:
        return _order_error(cfg, "order_id is required")
    if not symbol:
        return _order_error(cfg, "symbol is required (vn.py cancels need symbol + exchange)")

    try:
        _require_vnpy()
    except VnpyDependencyError as exc:
        return _order_error(cfg, str(exc))

    from vnpy.trader.object import CancelRequest

    code, exchange = _split_symbol(symbol)
    req = CancelRequest(orderid=oid.split(".")[-1], symbol=code, exchange=exchange)

    client = _QueueClient(cfg)
    try:
        client.call("cancel_order", req, cfg.gateway_name)
        return {"status": "ok", "order_id": oid, "symbol": req.vt_symbol, "profile": cfg.profile}
    except Exception as exc:  # noqa: BLE001 - cancel path must fail closed
        return _order_error(cfg, str(exc))
    finally:
        client.close()


def _order_error(cfg: VnpyConfig, message: str) -> dict[str, Any]:
    return {"status": "error", "error": message, "profile": cfg.profile}


# ---------------------------------------------------------------------------
# vt_symbol <-> (code, Exchange) + object -> dict mapping
# ---------------------------------------------------------------------------


def _split_symbol(symbol: str):
    """Split a Vibe-Trading ``CODE.EXCHANGE`` symbol into (code, Exchange)."""
    from vnpy.trader.constant import Exchange

    text = str(symbol or "").strip().upper()
    code, _, exch_name = text.rpartition(".")
    if not code:
        raise VnpyConfigError(f"symbol must be 'CODE.EXCHANGE' (e.g. 'IF2406.CFFEX'), got {symbol!r}")
    try:
        exchange = Exchange[exch_name]
    except KeyError as exc:
        raise VnpyConfigError(f"unknown vn.py exchange {exch_name!r} in symbol {symbol!r}") from exc
    return code, exchange


def _account_to_dict(a: Any) -> dict[str, Any]:
    return {
        "accountid": getattr(a, "accountid", None),
        "balance": getattr(a, "balance", None),
        "frozen": getattr(a, "frozen", None),
        "available": getattr(a, "available", None),
        "gateway_name": getattr(a, "gateway_name", None),
    }


def _position_to_dict(p: Any) -> dict[str, Any]:
    return {
        "symbol": getattr(p, "symbol", None),
        "exchange": str(getattr(p, "exchange", "")),
        "direction": str(getattr(p, "direction", "")),
        "volume": getattr(p, "volume", None),
        "frozen": getattr(p, "frozen", None),
        "price": getattr(p, "price", None),
        "pnl": getattr(p, "pnl", None),
        "gateway_name": getattr(p, "gateway_name", None),
    }


def _order_to_dict(o: Any) -> dict[str, Any]:
    return {
        "orderid": getattr(o, "orderid", None),
        "vt_orderid": getattr(o, "vt_orderid", None),
        "symbol": getattr(o, "symbol", None),
        "exchange": str(getattr(o, "exchange", "")),
        "direction": str(getattr(o, "direction", "")),
        "offset": str(getattr(o, "offset", "")),
        "type": str(getattr(o, "type", "")),
        "status": str(getattr(o, "status", "")),
        "price": getattr(o, "price", None),
        "volume": getattr(o, "volume", None),
        "traded": getattr(o, "traded", None),
        "datetime": str(getattr(o, "datetime", "")),
    }


def _trade_to_dict(t: Any) -> dict[str, Any]:
    return {
        "tradeid": getattr(t, "tradeid", None),
        "orderid": getattr(t, "orderid", None),
        "symbol": getattr(t, "symbol", None),
        "exchange": str(getattr(t, "exchange", "")),
        "direction": str(getattr(t, "direction", "")),
        "price": getattr(t, "price", None),
        "volume": getattr(t, "volume", None),
        "datetime": str(getattr(t, "datetime", "")),
    }


def _tick_to_dict(tick: Any) -> dict[str, Any]:
    return {
        "symbol": getattr(tick, "symbol", None),
        "exchange": str(getattr(tick, "exchange", "")),
        "last": getattr(tick, "last_price", None),
        "volume": getattr(tick, "volume", None),
        "bid": getattr(tick, "bid_price_1", None),
        "ask": getattr(tick, "ask_price_1", None),
        "open": getattr(tick, "open_price", None),
        "high": getattr(tick, "high_price", None),
        "low": getattr(tick, "low_price", None),
        "datetime": str(getattr(tick, "datetime", "")),
    }


def _bar_to_dict(bar: Any) -> dict[str, Any]:
    return {
        "datetime": str(getattr(bar, "datetime", "")),
        "open": getattr(bar, "open_price", None),
        "high": getattr(bar, "high_price", None),
        "low": getattr(bar, "low_price", None),
        "close": getattr(bar, "close_price", None),
        "volume": getattr(bar, "volume", None),
    }
