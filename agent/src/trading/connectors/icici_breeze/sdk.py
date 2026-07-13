"""ICICI Direct Breeze connector with local paper trading.

Credentials are retrieved from Windows Credential Manager through ``keyring``
using service ``VibeTrading-ICICI`` and keys:
``api_key``, ``api_secret``, and ``api_session``.

Safety boundary
---------------
* ``live-readonly`` exposes reads only.
* ``paper`` uses live Breeze quotations, but orders and cancellations are
  simulated in a local JSON ledger.
* This module never calls Breeze ``place_order``, ``modify_order``,
  ``cancel_order``, or any other broker-write method.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from src.config.paths import get_runtime_root

KEYRING_SERVICE = "VibeTrading-ICICI"
PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
}
PAPER_GUARD = "simulated_locally"
PAPER_LEDGER_FILENAME = "icici_breeze_paper.json"
_LEDGER_LOCK = threading.RLock()


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
    paper_starting_cash: float = 100000.0

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
                "profile must be 'paper' or 'live-readonly'"
            )
        starting_cash = float(
            payload.get("paper_starting_cash") or 100000.0
        )
        if not math.isfinite(starting_cash) or starting_cash <= 0:
            raise ICICIBreezeConfigError(
                "paper_starting_cash must be positive"
            )
        return cls(
            profile=profile,
            keyring_service=str(
                payload.get("keyring_service") or KEYRING_SERVICE
            ).strip(),
            timeout=float(payload.get("timeout") or 30.0),
            readonly=profile != "paper",
            paper_starting_cash=starting_cash,
        )

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS[self.profile]

    @property
    def is_paper(self) -> bool:
        return self.environment == "paper"


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ICICIBreezeConfig:
    """Build effective connector config from safe, non-secret values."""

    payload: dict[str, Any] = {}
    payload.update(dict(profile_config or {}))
    for key, value in dict(overrides or {}).items():
        if key in {
            "profile",
            "keyring_service",
            "timeout",
            "paper_starting_cash",
        } and value not in (None, ""):
            payload[key] = value
    return ICICIBreezeConfig.from_mapping(payload)


def check_status(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Check credentials and Breeze connectivity without trading."""

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
        "paper_guard": PAPER_GUARD if cfg.is_paper else "read_only",
        "readonly": cfg.readonly,
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
        # Creating a session is a read-only connectivity/authentication probe.
        _client(cfg)
        snapshot = get_account_snapshot(cfg)
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "currency": "INR",
    }
    if cfg.is_paper:
        account = snapshot.get("account") or {}
        report["account"].update(
            {
                "cash": account.get("cash"),
                "equity": account.get("equity"),
                "positions": account.get("positions_count"),
            }
        )
    else:
        report["account"]["demat_holdings"] = snapshot.get(
            "demat_holdings_count", 0
        )
    return report


def get_account_snapshot(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Read a paper account or live ICICI funds summary."""

    cfg = config or ICICIBreezeConfig()
    if cfg.is_paper:
        _process_open_paper_orders(cfg)
        ledger = _load_ledger(cfg)
        marked = _mark_paper_positions(cfg, ledger)
        account = {
            "account": "ICICI Paper",
            "currency": "INR",
            "starting_cash": ledger["starting_cash"],
            "cash": ledger["cash"],
            "market_value": marked["market_value"],
            "unrealized_pnl": marked["unrealized_pnl"],
            "realized_pnl": ledger.get("realized_pnl", 0.0),
            "equity": ledger["cash"] + marked["market_value"],
            "positions_count": len(marked["positions"]),
            "orders_count": len(ledger["orders"]),
            "charges_model": "not_included_v1",
        }
        return {
            "status": "ok",
            "profile": cfg.profile,
            "is_paper": True,
            "paper_guard": PAPER_GUARD,
            "readonly": False,
            "account": account,
            "accounts": ["ICICI Paper"],
        }

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
        "account": "ICICI Direct",
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
        "paper_guard": "read_only",
        "readonly": True,
        "account": account,
        "accounts": ["ICICI Direct"],
        "demat_holdings_count": len(holding_rows),
    }


def get_positions(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Read paper positions or live Demat holdings/open positions."""

    cfg = config or ICICIBreezeConfig()
    if cfg.is_paper:
        _process_open_paper_orders(cfg)
        ledger = _load_ledger(cfg)
        marked = _mark_paper_positions(cfg, ledger)
        return {
            "status": "ok",
            "profile": cfg.profile,
            "is_paper": True,
            "paper_guard": PAPER_GUARD,
            "readonly": False,
            "positions": marked["positions"],
        }

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
                "quantity": _first_number(
                    item,
                    "quantity",
                    "demat_total_quantity",
                    "demat_avail_quantity",
                    "total_quantity",
                ),
                "average_cost": _first_number(
                    item,
                    "average_price",
                    "average_cost",
                    "buy_price",
                ),
                "available_quantity": _first_number(
                    item,
                    "demat_avail_quantity",
                    "available_quantity",
                ),
                "blocked_quantity": _first_number(
                    item,
                    "blocked_quantity",
                ),
                "allocated_quantity": _first_number(
                    item,
                    "demat_allocated_quantity",
                ),
                "isin": item.get("stock_ISIN"),
                "currency": "INR",
            }
        )

    for item in _as_list(open_positions):
        if not isinstance(item, Mapping):
            continue
        quantity = _first_number(item, "quantity", "net_quantity")
        if not quantity:
            continue
        rows.append(
            {
                "account": "ICICI Trading",
                "symbol": item.get("stock_code"),
                "type": item.get("product_type") or "open_position",
                "quantity": quantity,
                "average_cost": _first_number(
                    item,
                    "average_price",
                    "average_cost",
                ),
                "current_price": _first_number(
                    item,
                    "ltp",
                    "price",
                ),
                "pnl": _first_number(item, "pnl"),
                "exchange": item.get("exchange_code"),
                "expiry_date": item.get("expiry_date"),
                "right": item.get("right"),
                "strike_price": _first_number(
                    item,
                    "strike_price",
                ),
                "currency": "INR",
            }
        )

    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": "read_only",
        "readonly": True,
        "positions": rows,
    }


def get_open_orders(
    config: ICICIBreezeConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Read paper orders or today's live NSE/NFO orders."""

    cfg = config or ICICIBreezeConfig()
    if cfg.is_paper:
        _process_open_paper_orders(cfg)
        ledger = _load_ledger(cfg)
        open_orders = [
            _paper_order_public(order)
            for order in ledger["orders"]
            if order.get("status") == "open"
        ]
        executions = [
            _paper_order_public(order)
            for order in ledger["orders"]
            if order.get("status") == "filled"
        ]
        result: dict[str, Any] = {
            "status": "ok",
            "profile": cfg.profile,
            "is_paper": True,
            "paper_guard": PAPER_GUARD,
            "readonly": False,
            "open_orders": open_orders,
        }
        if include_executions:
            result["executions"] = executions
        return result

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

    result = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": "read_only",
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
    return _quote_with_client(
        client,
        symbol=symbol,
        stock_code=stock_code,
        exchange_code=exchange_code,
        profile=cfg.profile,
        is_paper=cfg.is_paper,
    )


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
            "paper_guard": PAPER_GUARD if cfg.is_paper else "read_only",
            "readonly": cfg.readonly,
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
        "paper_guard": PAPER_GUARD if cfg.is_paper else "read_only",
        "readonly": cfg.readonly,
        "symbol": str(symbol or "").strip().upper(),
        "stock_code": stock_code,
        "period": token,
        "bars": bars,
    }


def place_order(
    config: ICICIBreezeConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "limit",
    limit_price: float | None = None,
    time_in_force: str = "day",
    exchange_code: str = "NSE",
    **_: Any,
) -> dict[str, Any]:
    """Place a PAPER-ONLY NSE cash order in the local ledger.

    The hard paper guard runs before any order logic. This function never
    invokes a Breeze broker-write API.
    """

    cfg = config or ICICIBreezeConfig()

    # HARD GUARD: live-readonly can never reach a paper or broker write path.
    if not cfg.is_paper:
        return {
            "status": "error",
            "error": (
                "ICICI Breeze order placement is available only in the "
                "local paper profile. Live broker writes are not installed."
            ),
        }

    clean_symbol = str(symbol or "").strip().upper()
    if not clean_symbol:
        return {"status": "error", "error": "symbol is required"}

    side_token = str(side or "").strip().lower()
    if side_token not in {"buy", "sell"}:
        return {
            "status": "error",
            "error": "side must be 'buy' or 'sell'",
        }

    order_token = str(order_type or "limit").strip().lower()
    if order_token not in {"market", "limit"}:
        return {
            "status": "error",
            "error": "order_type must be 'market' or 'limit'",
        }

    tif = str(time_in_force or "day").strip().lower()
    if tif not in {"day", "gtc"}:
        return {
            "status": "error",
            "error": "time_in_force must be 'day' or 'gtc'",
        }

    if order_token == "limit":
        if limit_price is None:
            return {
                "status": "error",
                "error": "limit order requires limit_price",
            }
        limit_value = _positive_number(limit_price, "limit_price")
    else:
        limit_value = None

    quote_result = get_quote(
        clean_symbol,
        config=cfg,
        exchange_code=exchange_code,
    )
    if quote_result.get("status") != "ok":
        return quote_result

    quote = quote_result.get("quote") or {}
    market_price = _execution_reference(quote, side_token)
    if market_price <= 0:
        return {
            "status": "error",
            "error": "a positive live quote is required for paper execution",
            "symbol": clean_symbol,
        }

    if quantity is None:
        if notional is None:
            return {
                "status": "error",
                "error": "quantity or notional is required",
            }
        budget = _positive_number(notional, "notional")
        qty = int(math.floor(budget / market_price))
        if qty < 1:
            return {
                "status": "error",
                "error": (
                    "notional is below the price of one whole NSE share"
                ),
                "symbol": clean_symbol,
                "reference_price": market_price,
            }
    else:
        quantity_value = _positive_number(quantity, "quantity")
        if not quantity_value.is_integer():
            return {
                "status": "error",
                "error": "NSE cash paper quantity must be a whole share",
            }
        qty = int(quantity_value)

    now = _now_iso()
    order_id = f"ICICI-PAPER-{uuid.uuid4().hex[:12].upper()}"
    marketable = (
        order_token == "market"
        or (
            side_token == "buy"
            and market_price <= float(limit_value)
        )
        or (
            side_token == "sell"
            and market_price >= float(limit_value)
        )
    )

    fill_price = (
        market_price
        if order_token == "market"
        else (
            min(market_price, float(limit_value))
            if side_token == "buy"
            else max(market_price, float(limit_value))
        )
    )

    order = {
        "order_id": order_id,
        "symbol": clean_symbol,
        "stock_code": quote_result.get("stock_code"),
        "exchange": exchange_code,
        "product_type": "cash",
        "side": side_token,
        "order_type": order_token,
        "quantity": qty,
        "limit_price": limit_value,
        "time_in_force": tif,
        "status": "open",
        "filled_quantity": 0,
        "average_price": 0.0,
        "created_at": now,
        "updated_at": now,
        "paper": True,
        "charges": 0.0,
        "charges_model": "not_included_v1",
    }

    with _LEDGER_LOCK:
        ledger = _load_ledger(cfg)
        if marketable:
            error = _apply_paper_fill(
                ledger,
                order,
                fill_price=fill_price,
            )
            if error:
                return {
                    "status": "error",
                    "error": error,
                    "symbol": clean_symbol,
                    "side": side_token,
                    "quantity": qty,
                    "reference_price": market_price,
                }
        ledger["orders"].append(order)
        _save_ledger(ledger)

    public_order = _paper_order_public(order)
    return {
        **public_order,
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": True,
        "paper_guard": PAPER_GUARD,
        "broker_write_called": False,
    }


def cancel_order(
    config: ICICIBreezeConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel an open PAPER order in the local ledger only."""

    cfg = config or ICICIBreezeConfig()

    # HARD GUARD: no live cancellation method exists.
    if not cfg.is_paper:
        return {
            "status": "error",
            "error": (
                "ICICI Breeze cancellation is available only in the "
                "local paper profile. Live broker writes are not installed."
            ),
        }

    clean_id = str(order_id or "").strip()
    if not clean_id:
        return {"status": "error", "error": "order_id is required"}

    with _LEDGER_LOCK:
        ledger = _load_ledger(cfg)
        for order in ledger["orders"]:
            if order.get("order_id") != clean_id:
                continue
            if order.get("status") != "open":
                return {
                    "status": "error",
                    "error": (
                        f"paper order is already {order.get('status')}"
                    ),
                    "order_id": clean_id,
                }
            order["status"] = "cancelled"
            order["updated_at"] = _now_iso()
            _save_ledger(ledger)
            return {
                "status": "ok",
                "profile": cfg.profile,
                "is_paper": True,
                "paper_guard": PAPER_GUARD,
                "broker_write_called": False,
                "order_id": clean_id,
                "symbol": order.get("symbol") or symbol,
                "cancelled": True,
            }

    return {
        "status": "error",
        "error": "paper order was not found",
        "order_id": clean_id,
    }


def reset_paper_account(
    config: ICICIBreezeConfig | None = None,
) -> dict[str, Any]:
    """Reset only the local paper ledger to its configured starting cash."""

    cfg = config or ICICIBreezeConfig.from_mapping({"profile": "paper"})
    if not cfg.is_paper:
        return {"status": "error", "error": "paper profile required"}
    with _LEDGER_LOCK:
        ledger = _new_ledger(cfg)
        _save_ledger(ledger)
    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": True,
        "cash": ledger["cash"],
        "paper_guard": PAPER_GUARD,
    }


def _process_open_paper_orders(config: ICICIBreezeConfig) -> None:
    if not config.is_paper:
        return

    with _LEDGER_LOCK:
        ledger = _load_ledger(config)
        open_orders = [
            order
            for order in ledger["orders"]
            if order.get("status") == "open"
        ]
        if not open_orders:
            return

        changed = False
        for order in open_orders:
            try:
                quote_result = get_quote(
                    str(order.get("symbol") or ""),
                    config=config,
                    exchange_code=str(
                        order.get("exchange") or "NSE"
                    ),
                )
                quote = quote_result.get("quote") or {}
                market_price = _execution_reference(
                    quote,
                    str(order.get("side") or ""),
                )
                limit_price = float(order.get("limit_price") or 0.0)
                should_fill = (
                    order.get("order_type") == "market"
                    or (
                        order.get("side") == "buy"
                        and market_price > 0
                        and market_price <= limit_price
                    )
                    or (
                        order.get("side") == "sell"
                        and market_price > 0
                        and market_price >= limit_price
                    )
                )
                if not should_fill:
                    continue

                fill_price = (
                    min(market_price, limit_price)
                    if order.get("side") == "buy"
                    else max(market_price, limit_price)
                )
                error = _apply_paper_fill(
                    ledger,
                    order,
                    fill_price=fill_price,
                )
                if error:
                    order["status"] = "rejected"
                    order["reject_reason"] = error
                    order["updated_at"] = _now_iso()
                changed = True
            except Exception as exc:
                order["last_refresh_error"] = str(exc)
                order["updated_at"] = _now_iso()
                changed = True

        if changed:
            _save_ledger(ledger)


def _apply_paper_fill(
    ledger: dict[str, Any],
    order: dict[str, Any],
    *,
    fill_price: float,
) -> str | None:
    qty = int(order["quantity"])
    symbol = str(order["symbol"])
    side = str(order["side"])
    value = round(qty * float(fill_price), 8)
    positions = ledger.setdefault("positions", {})
    position = dict(
        positions.get(symbol)
        or {
            "quantity": 0,
            "average_cost": 0.0,
            "realized_pnl": 0.0,
        }
    )
    current_qty = int(position.get("quantity") or 0)
    current_avg = float(position.get("average_cost") or 0.0)

    if side == "buy":
        if float(ledger["cash"]) + 1e-9 < value:
            return (
                f"insufficient paper cash: need INR {value:.2f}, "
                f"available INR {float(ledger['cash']):.2f}"
            )
        new_qty = current_qty + qty
        new_avg = (
            ((current_qty * current_avg) + value) / new_qty
            if new_qty
            else 0.0
        )
        ledger["cash"] = round(float(ledger["cash"]) - value, 8)
        position["quantity"] = new_qty
        position["average_cost"] = round(new_avg, 8)
        positions[symbol] = position
    else:
        if current_qty < qty:
            return (
                f"insufficient paper holdings: have {current_qty}, "
                f"attempted to sell {qty}"
            )
        realized = (float(fill_price) - current_avg) * qty
        remaining = current_qty - qty
        ledger["cash"] = round(float(ledger["cash"]) + value, 8)
        ledger["realized_pnl"] = round(
            float(ledger.get("realized_pnl") or 0.0) + realized,
            8,
        )
        if remaining:
            position["quantity"] = remaining
            position["realized_pnl"] = round(
                float(position.get("realized_pnl") or 0.0) + realized,
                8,
            )
            positions[symbol] = position
        else:
            positions.pop(symbol, None)

    order["status"] = "filled"
    order["filled_quantity"] = qty
    order["average_price"] = round(float(fill_price), 8)
    order["filled_at"] = _now_iso()
    order["updated_at"] = order["filled_at"]
    return None


def _mark_paper_positions(
    config: ICICIBreezeConfig,
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    market_value = 0.0
    unrealized_pnl = 0.0

    for symbol, raw in dict(ledger.get("positions") or {}).items():
        item = dict(raw or {})
        qty = int(item.get("quantity") or 0)
        if qty <= 0:
            continue
        avg = float(item.get("average_cost") or 0.0)
        current = avg
        quote_error = None
        try:
            quote_result = get_quote(symbol, config=config)
            quote = quote_result.get("quote") or {}
            current = _first_positive(
                quote.get("last"),
                quote.get("close"),
                avg,
            )
        except Exception as exc:
            quote_error = str(exc)

        value = qty * current
        pnl = qty * (current - avg)
        market_value += value
        unrealized_pnl += pnl

        row = {
            "account": "ICICI Paper",
            "symbol": symbol,
            "type": "paper_cash_equity",
            "quantity": qty,
            "average_cost": round(avg, 8),
            "current_price": round(current, 8),
            "market_value": round(value, 8),
            "unrealized_pnl": round(pnl, 8),
            "currency": "INR",
        }
        if quote_error:
            row["quote_error"] = quote_error
        rows.append(row)

    return {
        "positions": rows,
        "market_value": round(market_value, 8),
        "unrealized_pnl": round(unrealized_pnl, 8),
    }


def _quote_with_client(
    client: Any,
    *,
    symbol: str,
    stock_code: str,
    exchange_code: str,
    profile: str,
    is_paper: bool,
) -> dict[str, Any]:
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
        "profile": profile,
        "is_paper": is_paper,
        "paper_guard": PAPER_GUARD if is_paper else "read_only",
        "readonly": not is_paper,
        "symbol": str(symbol or "").strip().upper(),
        "stock_code": stock_code,
        "quote": {
            "bid": _first_number(
                quote,
                "best_bid_price",
                "best_bid",
                "bid",
            ),
            "ask": _first_number(
                quote,
                "best_offer_price",
                "best_ask_price",
                "ask",
            ),
            "last": _first_number(quote, "ltp", "last"),
            "open": _first_number(quote, "open"),
            "high": _first_number(quote, "high"),
            "low": _first_number(quote, "low"),
            "close": _first_number(
                quote,
                "previous_close",
                "close",
            ),
            "volume": _first_number(
                quote,
                "total_quantity_traded",
                "volume",
            ),
            "time": quote.get("ltt"),
        },
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
    quantity = _first_number(item, "quantity")
    pending = _first_number(item, "pending_quantity")
    return {
        "order_id": str(item.get("order_id") or ""),
        "symbol": item.get("stock_code"),
        "side": str(item.get("action") or ""),
        "order_type": str(item.get("order_type") or ""),
        "status": str(item.get("status") or ""),
        "quantity": quantity,
        "filled_quantity": max(0.0, quantity - pending),
        "pending_quantity": pending,
        "price": _first_number(item, "price"),
        "average_price": _first_number(item, "average_price"),
        "exchange": item.get("exchange_code"),
        "product_type": item.get("product_type"),
        "time": item.get("order_datetime"),
    }


def _paper_order_public(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(item.get("order_id") or ""),
        "symbol": item.get("symbol"),
        "side": item.get("side"),
        "order_type": item.get("order_type"),
        "status": item.get("status"),
        "order_status": item.get("status"),
        "quantity": item.get("quantity"),
        "filled_quantity": item.get("filled_quantity"),
        "pending_quantity": (
            int(item.get("quantity") or 0)
            - int(item.get("filled_quantity") or 0)
        ),
        "limit_price": item.get("limit_price"),
        "price": item.get("limit_price"),
        "average_price": item.get("average_price"),
        "exchange": item.get("exchange"),
        "product_type": item.get("product_type"),
        "time": item.get("created_at"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "paper": True,
        "broker_write_called": False,
        "charges": item.get("charges", 0.0),
        "charges_model": item.get(
            "charges_model",
            "not_included_v1",
        ),
    }


def _bar_to_dict(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    timestamp = str(item.get("datetime") or "")
    return {
        "date": timestamp,
        "time": timestamp,
        "open": _first_number(item, "open"),
        "high": _first_number(item, "high"),
        "low": _first_number(item, "low"),
        "close": _first_number(item, "close"),
        "volume": _first_number(item, "volume"),
    }


def _ledger_path() -> Path:
    return get_runtime_root() / PAPER_LEDGER_FILENAME


def _new_ledger(config: ICICIBreezeConfig) -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "broker": "icici_breeze",
        "environment": "paper",
        "starting_cash": round(config.paper_starting_cash, 8),
        "cash": round(config.paper_starting_cash, 8),
        "realized_pnl": 0.0,
        "positions": {},
        "orders": [],
        "created_at": now,
        "updated_at": now,
        "charges_model": "not_included_v1",
    }


def _load_ledger(config: ICICIBreezeConfig) -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        ledger = _new_ledger(config)
        _save_ledger(ledger)
        return ledger
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ICICIBreezeConfigError(
            f"invalid ICICI paper ledger at {path}: {exc}"
        ) from exc
    if not isinstance(ledger, dict):
        raise ICICIBreezeConfigError(
            f"invalid ICICI paper ledger at {path}: root must be an object"
        )
    ledger.setdefault("positions", {})
    ledger.setdefault("orders", [])
    ledger.setdefault("realized_pnl", 0.0)
    ledger.setdefault("starting_cash", config.paper_starting_cash)
    ledger.setdefault("cash", config.paper_starting_cash)
    return ledger


def _save_ledger(ledger: Mapping[str, Any]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(ledger)
    payload["updated_at"] = _now_iso()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


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


def _first_number(
    mapping: Mapping[str, Any],
    *keys: str,
) -> float:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            number = _number(value)
            if number or str(value).strip() in {"0", "0.0"}:
                return number
    return 0.0


def _first_positive(*values: Any) -> float:
    for value in values:
        number = _number(value)
        if number > 0:
            return number
    return 0.0


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _positive_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ICICIBreezeConfigError(
            f"{name} must be a number"
        ) from exc
    if not math.isfinite(number) or number <= 0:
        raise ICICIBreezeConfigError(
            f"{name} must be positive"
        )
    return number


def _execution_reference(
    quote: Mapping[str, Any],
    side: str,
) -> float:
    if side == "buy":
        return _first_positive(
            quote.get("ask"),
            quote.get("last"),
            quote.get("close"),
        )
    return _first_positive(
        quote.get("bid"),
        quote.get("last"),
        quote.get("close"),
    )


def _iso_z(value: datetime) -> str:
    """Format a Breeze timestamp as YYYY-MM-DDTHH:MM:SS.000Z."""
    return value.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
