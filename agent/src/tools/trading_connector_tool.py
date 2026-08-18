"""Connector-first trading tools.

Tools take an optional ``connection`` profile id. If omitted, they use the
selected profile from ``~/.vibe-trading/trading-connections.json``.
"""

from __future__ import annotations

import json
import math
from typing import Any

from src.agent.tools import BaseTool
from src.trading.profiles import (
    list_profiles,
    load_selected_profile_id,
    profile_by_id,
    save_selected_profile_id,
)
from src.trading.service import (
    cancel_close_order,
    cancel_order,
    check_connection,
    close_position,
    edit_position_stops,
    etoro_copy_close,
    etoro_copy_poll,
    etoro_copy_precheck,
    etoro_copy_start,
    get_account,
    get_acc_cash_flow,
    get_capital_distribution,
    get_capital_flow,
    get_earnings_calendar,
    get_financials,
    get_history,
    get_history_deals,
    get_open_orders,
    get_positions,
    get_quote,
    get_rehab,
    place_order,
    search_instruments,
)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _connection(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class InvalidTradingArgument(ValueError):
    """A numeric trading argument was supplied but is malformed or non-finite."""


def _brief(value: Any) -> str:
    """Render a rejected argument for an error message without ever raising.

    ``repr()`` is not total: an int with more than 4300 digits raises
    ``ValueError`` under Python's int→str limit. An order tool must not fail to
    describe why it refused, so fall back to the type name.

    Args:
        value: The rejected argument value.

    Returns:
        A short, printable description of the value.
    """
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 — building an error message must never fail
        return f"<unprintable {type(value).__name__}>"
    return text if len(text) <= 80 else f"{text[:77]}..."


def _finite_float(value: Any, field: str) -> float:
    """Convert a supplied numeric argument to a finite float.

    Args:
        value: Raw argument value (already known to be present).
        field: Argument name, used in the error message.

    Returns:
        The value as a finite float.

    Raises:
        InvalidTradingArgument: If the value is not numeric, or is NaN/Infinity.
            Trading tools are action-bearing, so a malformed size/price/port is
            rejected outright rather than coerced to a default.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise InvalidTradingArgument(f"{field} must be a finite number, got {_brief(value)}") from None
    if not math.isfinite(number):
        raise InvalidTradingArgument(f"{field} must be a finite number, got {_brief(value)}")
    return number


def _int_or_none(value: Any, field: str = "value") -> int | None:
    """Coerce an optional whole-number argument, rejecting malformed input.

    Args:
        value: Raw argument value; ``None`` and ``""`` mean "not supplied".
        field: Argument name, used in the error message.

    Returns:
        The integer value, or ``None`` when the argument was not supplied.

    Raises:
        InvalidTradingArgument: If the value is present but not a finite whole
            number.
    """
    if value is None or value == "":
        return None
    number = _finite_float(value, field)
    if number != int(number):
        raise InvalidTradingArgument(f"{field} must be a whole number, got {_brief(value)}")
    return int(number)


def _num_or_none(value: Any, field: str = "value") -> float | None:
    """Coerce an optional numeric argument, rejecting malformed input.

    Args:
        value: Raw argument value; ``None`` and ``""`` mean "not supplied".
        field: Argument name, used in the error message.

    Returns:
        The float value, or ``None`` when the argument was not supplied.

    Raises:
        InvalidTradingArgument: If the value is present but not a finite number.
    """
    if value is None or value == "":
        return None
    return _finite_float(value, field)


TRADING_COMMON_PARAMETERS = {
    "connection": {
        "type": "string",
        "description": "Trading connector profile id, e.g. ibkr-paper-local or robinhood-live-mcp. Defaults to the selected profile.",
    },
    "host": {
        "type": "string",
        "description": "Optional local TWS/Gateway host override for local profiles.",
    },
    "port": {
        "type": "integer",
        "description": "Optional local TWS/Gateway port override for local profiles.",
    },
    "client_id": {
        "type": "integer",
        "description": "Optional local TWS/Gateway client id override for local profiles.",
    },
    "account": {
        "type": "string",
        "description": "Optional account code filter when supported by the connector.",
    },
}

ETORO_CREDENTIAL_PARAMETERS = {
    "api_key": {
        "type": "string",
        "description": "Optional eToro Public API key override.",
    },
    "user_key": {
        "type": "string",
        "description": "Optional eToro user key override.",
    },
}


ETORO_TOOL_PARAMETERS = {**TRADING_COMMON_PARAMETERS, **ETORO_CREDENTIAL_PARAMETERS}


def _overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build the local-connector override dict, rejecting malformed numerics.

    Args:
        kwargs: Raw tool arguments.

    Returns:
        Override mapping with ``None`` for every unsupplied field.

    Raises:
        InvalidTradingArgument: If ``port`` or ``client_id`` is supplied but
            malformed. Silently dropping them would connect to a different
            terminal than the caller asked for.
    """
    return {
        "host": _connection(kwargs.get("host")),
        "port": _int_or_none(kwargs.get("port"), "port"),
        "client_id": _int_or_none(kwargs.get("client_id"), "client_id"),
        "account": _connection(kwargs.get("account")),
    }


def _etoro_overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build override dict for eToro tools, including optional credential overrides."""
    return {
        **_overrides(kwargs),
        "api_key": _connection(kwargs.get("api_key")),
        "user_key": _connection(kwargs.get("user_key")),
    }


class TradingConnectionsTool(BaseTool):
    """List available trading connector profiles."""

    name = "trading_connections"
    description = (
        "List selectable trading connector profiles. Connectors come first; paper/live is a profile attribute."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    repeatable = True
    is_readonly = True

    def execute(self, **_: Any) -> str:
        """List connector profiles and mark the selected one."""
        try:
            selected = load_selected_profile_id()
            return _json_result(
                {
                    "status": "ok",
                    "selected_profile": selected,
                    "profiles": [profile.to_dict(selected=profile.id == selected) for profile in list_profiles()],
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingSelectConnectionTool(BaseTool):
    """Select the default trading connector profile."""

    name = "trading_select_connection"
    description = "Select the default trading connector profile for subsequent trading_* tool calls."
    parameters = {
        "type": "object",
        "properties": {
            "connection": {
                "type": "string",
                "description": "Profile id to select, e.g. ibkr-paper-local.",
            }
        },
        "required": ["connection"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Persist the selected profile id."""
        try:
            profile = profile_by_id(str(kwargs["connection"]).strip())
            path = save_selected_profile_id(profile.id)
            return _json_result({"status": "ok", "selected_profile": profile.id, "path": str(path)})
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingCheckTool(BaseTool):
    """Check a trading connector profile."""

    name = "trading_check"
    description = "Check whether a trading connector profile is configured and reachable. This never places orders."
    parameters = {
        "type": "object",
        "properties": TRADING_COMMON_PARAMETERS,
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Check connector readiness."""
        try:
            return _json_result(check_connection(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingAccountTool(BaseTool):
    """Read account summary from a trading connector profile."""

    name = "trading_account"
    description = "Read account summary from the selected trading connector profile. Read-only."
    parameters = TradingCheckTool.parameters
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read account summary."""
        try:
            return _json_result(get_account(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingPositionsTool(BaseTool):
    """Read positions from a trading connector profile."""

    name = "trading_positions"
    description = "Read positions from the selected trading connector profile. Read-only."
    parameters = TradingCheckTool.parameters
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read positions."""
        try:
            return _json_result(get_positions(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingOrdersTool(BaseTool):
    """Read open orders from a trading connector profile."""

    name = "trading_orders"
    description = "Read open orders from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "include_executions": {"type": "boolean", "default": False},
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read open orders."""
        try:
            return _json_result(
                get_open_orders(
                    _connection(kwargs.get("connection")),
                    include_executions=bool(kwargs.get("include_executions", False)),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingQuoteTool(BaseTool):
    """Read a quote from a trading connector profile."""

    name = "trading_quote"
    description = "Read a quote snapshot from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "symbol": {"type": "string", "description": "Symbol, e.g. AAPL"},
            "exchange": {"type": "string", "default": "SMART"},
            "currency": {"type": "string", "default": "USD"},
            "sec_type": {"type": "string", "default": "STK"},
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read quote snapshot."""
        try:
            return _json_result(
                get_quote(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    exchange=str(kwargs.get("exchange") or "SMART"),
                    currency=str(kwargs.get("currency") or "USD"),
                    sec_type=str(kwargs.get("sec_type") or "STK"),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingHistoryTool(BaseTool):
    """Read historical bars from a trading connector profile."""

    name = "trading_history"
    description = "Read historical bars from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "duration": {"type": "string", "default": "30 D", "description": "IBKR (local_tws) duration string."},
            "bar_size": {"type": "string", "default": "1 day", "description": "IBKR (local_tws) bar size."},
            "what_to_show": {"type": "string", "default": "TRADES"},
            "use_rth": {"type": "boolean", "default": True},
            "period": {
                "type": "string",
                "default": "1d",
                "description": "Bar interval for SDK connectors (broker_sdk): 1m/5m/15m/30m/1h/4h/1d/1w/1M.",
            },
            "limit": {"type": "integer", "default": 90, "description": "Number of bars for SDK connectors."},
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read historical bars."""
        try:
            return _json_result(
                get_history(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    exchange=str(kwargs.get("exchange") or "SMART"),
                    currency=str(kwargs.get("currency") or "USD"),
                    sec_type=str(kwargs.get("sec_type") or "STK"),
                    duration=str(kwargs.get("duration") or "30 D"),
                    bar_size=str(kwargs.get("bar_size") or "1 day"),
                    what_to_show=str(kwargs.get("what_to_show") or "TRADES"),
                    use_rth=bool(kwargs.get("use_rth", True)),
                    period=str(kwargs.get("period") or "1d"),
                    limit=int(kwargs.get("limit") or 90),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingRehabTool(BaseTool):
    """Read dividend / split adjustment factors for a symbol.

    Use the returned adjustment factors to compute forward-adjusted close prices
    so backtests don't show dividend-driven gaps. Read-only.
    """

    name = "trading_rehab"
    description = "Read dividend / split / rights-issue adjustment factors for a symbol from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read rehab adjustment factors."""
        try:
            return _json_result(
                get_rehab(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingCapitalFlowTool(BaseTool):
    """Read historical main-flow (super/big/mid/small) time series for a symbol.

    Tracks institutional vs retail capital inflow / outflow across
    intraday / daily / weekly / monthly buckets. Read-only.
    """

    name = "trading_capital_flow"
    description = "Read historical capital flow time series (institutional / retail inflow-outflow) for a symbol. period_type: INTRADAY/DAY/WEEK/MONTH. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "period_type": {
                "type": "string",
                "default": "INTRADAY",
                "description": "Aggregation window: INTRADAY / DAY / WEEK / MONTH.",
            },
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read capital flow time series."""
        try:
            return _json_result(
                get_capital_flow(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    period_type=str(kwargs.get("period_type") or "INTRADAY"),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingCapitalDistributionTool(BaseTool):
    """Read the LATEST capital in-flow vs out-flow snapshot for a symbol.

    Today's running tally of super/big/mid/small buys vs sells. Use it to spot
    when institutions are accumulating or distributing right now. Read-only.
    """

    name = "trading_capital_distribution"
    description = "Read today's capital in-flow vs out-flow snapshot (super/big/mid/small buckets) for a symbol. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read today's capital distribution snapshot."""
        try:
            return _json_result(
                get_capital_distribution(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingHistoryDealsTool(BaseTool):
    """Read historical FILL records (executed deals) for shadow-account analysis.

    Unlike history_order_list_query (returns intent), this returns only orders
    that ACTUALLY filled — with fill price, qty, counter broker, fee, settlement
    date. Required for true cost-basis reconstruction. Read-only.
    """

    name = "trading_history_deals"
    description = "Read historical FILL records (executed deals) for shadow-account cost-basis reconstruction. start/end YYYY-MM-DD; max window 360 days. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "start": {"type": "string", "description": "Start date YYYY-MM-DD."},
            "end": {"type": "string", "description": "End date YYYY-MM-DD."},
            "code": {
                "type": "string",
                "default": "",
                "description": "Optional Futu instrument code (e.g. HK.00700). Empty = all symbols.",
            },
        },
        "required": ["start", "end"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read historical fill records."""
        try:
            return _json_result(
                get_history_deals(
                    str(kwargs["start"]),
                    str(kwargs["end"]),
                    _connection(kwargs.get("connection")),
                    code=str(kwargs.get("code") or ""),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingAccCashFlowTool(BaseTool):
    """Read account cash-flow movements for a clearing date.

    Tracks deposit / withdrawal / FX conversion / buy-sell settlement /
    margin interest / dividends received / fees. Read-only.
    """

    name = "trading_acc_cash_flow"
    description = "Read account cash-flow movements for a clearing date (YYYY-MM-DD): deposit, withdrawal, FX, settlement, fees. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "clearing_date": {
                "type": "string",
                "description": "Clearing date YYYY-MM-DD.",
            },
        },
        "required": ["clearing_date"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read account cash-flow for one clearing date."""
        try:
            return _json_result(
                get_acc_cash_flow(
                    str(kwargs["clearing_date"]),
                    _connection(kwargs.get("connection")),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingFinancialsTool(BaseTool):
    """Read financial statements (income / balance / cash flow) for a symbol.

    Returns structure_list (field definitions) + report_list (period values).
    Read-only.
    """

    name = "trading_financials"
    description = "Read financial statements (INCOME / BALANCE / CASH_FLOW) for a symbol. Returns structure_list + report_list across N periods. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "statement_type": {
                "type": "string",
                "default": "INCOME",
                "description": "Statement type: INCOME / BALANCE / CASH_FLOW.",
            },
            "num": {"type": "integer", "default": 20, "description": "Maximum periods."},
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read financial statements."""
        try:
            return _json_result(
                get_financials(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    statement_type=str(kwargs.get("statement_type") or "INCOME"),
                    num=int(kwargs.get("num") or 20),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingEarningsCalendarTool(BaseTool):
    """Read upcoming earnings-release dates with EPS / revenue consensus.

    Used to plan earnings-season trades (vol crush, surprise, IV rank).
    Read-only.
    """

    name = "trading_earnings_calendar"
    description = "Read upcoming earnings calendar (code, name, EPS/revenue forecast, IV, IV rank) for US / HK. begin/end YYYY-MM-DD. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "market": {"type": "string", "default": "US", "description": "US or HK."},
            "begin_date": {"type": "string", "default": "", "description": "Begin YYYY-MM-DD."},
            "end_date": {"type": "string", "default": "", "description": "End YYYY-MM-DD."},
        },
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read earnings calendar."""
        try:
            return _json_result(
                get_earnings_calendar(
                    _connection(kwargs.get("connection")),
                    market=str(kwargs.get("market") or "US"),
                    begin_date=str(kwargs.get("begin_date") or ""),
                    end_date=str(kwargs.get("end_date") or ""),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingPlaceOrderTool(BaseTool):
    """Place an order through a trading connector profile.

    Paper profiles place against the broker's sandbox account. Live profiles
    route through the bounded-autonomy mandate gate (mandate + kill switch +
    fail-closed pre-trade checks + audit) before any order reaches the broker.
    Not read-only; not repeatable (an order must never be silently re-issued).
    """

    name = "trading_place_order"
    description = (
        "Place an order through the selected trading connector profile. Paper "
        "profiles trade a sandbox account; live profiles are gated by the user's "
        "mandate and kill switch. side is 'buy' or 'sell'; give exactly one of "
        "quantity (units) or notional (account-currency amount)."
    )
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "symbol": {"type": "string", "description": "Symbol, e.g. AAPL, BTC-USDT, 700.HK, HK.00700."},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {
                "type": "number",
                "description": "Order size in units/shares/contracts. Exactly one of quantity/notional.",
            },
            "notional": {
                "type": "number",
                "description": "Order size as an account-currency amount. Exactly one of quantity/notional.",
            },
            "order_type": {"type": "string", "enum": ["market", "limit"], "default": "market"},
            "limit_price": {"type": "number", "description": "Required for limit orders."},
            "time_in_force": {"type": "string", "enum": ["day", "gtc"], "default": "day"},
        },
        "required": ["symbol", "side"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Place an order via the connector profile.

        Every numeric argument is converted first and a malformed or non-finite
        value aborts with an error envelope BEFORE the service is called: an
        order tool must fail closed rather than drop a bad size field and place
        a different, plausible-looking order.
        """
        try:
            # LLMs frequently populate BOTH sizing fields, leaving the unused
            # one at 0; a zero size is never valid, so treat it as absent to
            # preserve the "exactly one of quantity/notional" contract.
            quantity = _num_or_none(kwargs.get("quantity"), "quantity") or None
            notional = _num_or_none(kwargs.get("notional"), "notional") or None
            limit_price = _num_or_none(kwargs.get("limit_price"), "limit_price")
            overrides = _overrides(kwargs)
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})

        try:
            return _json_result(
                place_order(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    side=str(kwargs.get("side") or ""),
                    quantity=quantity,
                    notional=notional,
                    order_type=str(kwargs.get("order_type") or "market"),
                    limit_price=limit_price,
                    time_in_force=str(kwargs.get("time_in_force") or "day"),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingCancelOrderTool(BaseTool):
    """Cancel an order through a trading connector profile (risk-reducing)."""

    name = "trading_cancel_order"
    description = "Cancel an open order on the selected trading connector profile by order id."
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "order_id": {"type": "string", "description": "Broker order id to cancel."},
            "symbol": {"type": "string", "description": "Symbol (required by some brokers, e.g. OKX/Binance)."},
        },
        "required": ["order_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Cancel an order via the connector profile.

        Malformed connector overrides are rejected before the service call, so a
        cancel never silently targets a different terminal than requested.
        """
        try:
            overrides = _overrides(kwargs)
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})

        try:
            return _json_result(
                cancel_order(
                    str(kwargs["order_id"]),
                    _connection(kwargs.get("connection")),
                    symbol=_connection(kwargs.get("symbol")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroSearchInstrumentsTool(BaseTool):
    """Resolve eToro tickers via ``internalSymbolFull`` or fuzzy discovery."""

    name = "etoro_search_instruments"
    description = (
        "Search eToro instruments by ticker (BTC, AAPL), free text, or asset class "
        "(crypto, stocks, forex). Tickers use exact internalSymbolFull lookup; "
        "asset-class labels browse via instrumentTypeIds on /market-data/instruments."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "query": {
                "type": "string",
                "description": "Ticker, search text (e.g. Apple), or asset class (e.g. crypto).",
            },
            "limit": {"type": "integer", "description": "Max results (default 10, max 50)."},
            "mode": {
                "type": "string",
                "enum": ["auto", "symbol", "discover", "type"],
                "description": "auto: ticker exact lookup then fuzzy; symbol: exact only; discover: fuzzy only; type: browse by instrument_type_id.",
            },
            "instrument_type_id": {
                "type": "integer",
                "description": "eToro instrumentTypeID (1=Forex … 10=Crypto). Browse mode when set.",
            },
            "include_rates": {
                "type": "boolean",
                "description": "When browsing by type, attach bid/ask/last from /market-data/instruments/rates.",
            },
        },
        "required": ["query"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            limit = _int_or_none(kwargs.get("limit"), "limit") or 10
            mode = str(kwargs.get("mode") or "auto")
            instrument_type_id = _int_or_none(kwargs.get("instrument_type_id"), "instrument_type_id")
            include_rates = bool(kwargs.get("include_rates", False))
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                search_instruments(
                    str(kwargs["query"]),
                    _connection(kwargs.get("connection")),
                    limit=limit,
                    mode=mode,
                    instrument_type_id=instrument_type_id,
                    include_rates=include_rates,
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroClosePositionTool(BaseTool):
    """Close or partially close an eToro position."""

    name = "etoro_close_position"
    description = "Close or partially close an open eToro position by position id."
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "position_id": {"type": "string", "description": "eToro position id."},
            "instrument_id": {
                "type": "integer",
                "description": "Optional instrument id; always resolved and verified against the open position.",
            },
            "units_to_close": {"type": "number", "description": "Units to close; omit to close entire position."},
            "request_id": {"type": "string", "description": "Optional idempotency request id (UUID)."},
        },
        "required": ["position_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            units = _num_or_none(kwargs.get("units_to_close"), "units_to_close")
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                close_position(
                    kwargs["position_id"],
                    _connection(kwargs.get("connection")),
                    instrument_id=_int_or_none(kwargs.get("instrument_id"), "instrument_id"),
                    units_to_close=units,
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroCancelCloseOrderTool(BaseTool):
    name = "etoro_cancel_close_order"
    description = (
        "Cancel a pending eToro market close order by order id (paper only; "
        "live is fail-closed because this reinstates exposure)."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "order_id": {"type": "string", "description": "Pending close order id."},
            "request_id": {"type": "string", "description": "Optional idempotency request id (UUID)."},
        },
        "required": ["order_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                cancel_close_order(
                    str(kwargs["order_id"]),
                    _connection(kwargs.get("connection")),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroEditPositionStopsTool(BaseTool):
    name = "etoro_edit_position_stops"
    description = (
        "Modify or clear stop-loss/take-profit on an open eToro position "
        "(paper only; live edits are fail-closed until incremental funding can be quantified)."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "position_id": {"type": "string", "description": "eToro position id."},
            "stop_loss": {"type": "number", "description": "New stop-loss rate."},
            "take_profit": {"type": "number", "description": "New take-profit rate."},
            "trailing_stop_loss": {
                "type": "boolean",
                "description": "true selects trailing; false selects fixed stop-loss type.",
            },
            "clear_stop_loss": {"type": "boolean", "description": "Remove the stop-loss."},
            "clear_take_profit": {"type": "boolean", "description": "Remove the take-profit."},
            "request_id": {"type": "string", "description": "Optional idempotency request id (UUID)."},
        },
        "required": ["position_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            stop_loss = _num_or_none(kwargs.get("stop_loss"), "stop_loss")
            take_profit = _num_or_none(kwargs.get("take_profit"), "take_profit")
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        trailing = kwargs.get("trailing_stop_loss")
        try:
            return _json_result(
                edit_position_stops(
                    kwargs["position_id"],
                    _connection(kwargs.get("connection")),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    trailing_stop_loss=bool(trailing) if trailing is not None else None,
                    clear_stop_loss=bool(kwargs.get("clear_stop_loss", False)),
                    clear_take_profit=bool(kwargs.get("clear_take_profit", False)),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroCopyPrecheckTool(BaseTool):
    name = "etoro_copy_precheck"
    description = (
        "Dry-run whether the account can copy an investor with an account-currency amount. "
        "Live accounts only — not supported on demo (paper) profiles."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "parent_cid": {"type": "integer", "description": "Investor parent CID."},
            "amount": {"type": "number", "description": "Positive amount in the account currency."},
            "request_id": {"type": "string", "description": "Optional request id (UUID)."},
        },
        "required": ["parent_cid", "amount"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            amount = _finite_float(kwargs["amount"], "amount")
            parent_cid = _int_or_none(kwargs["parent_cid"], "parent_cid")
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                etoro_copy_precheck(
                    parent_cid,
                    amount,
                    _connection(kwargs.get("connection")),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroCopyStartTool(BaseTool):
    name = "etoro_copy_start"
    description = (
        "Start copying an investor or adjust an existing copy allocation. "
        "Live accounts only — not supported on demo (paper) profiles."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "parent_cid": {"type": "integer", "description": "Investor parent CID."},
            "amount": {
                "type": "number",
                "description": "Account-currency amount to add (negative to reduce). Live increases require a verified USD account.",
            },
            "reference_id": {
                "type": "string",
                "description": "Required caller reference: 1-35 URL-safe characters, used for polling.",
            },
            "request_id": {"type": "string", "description": "Optional request id (UUID)."},
        },
        "required": ["parent_cid", "amount", "reference_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            amount = _finite_float(kwargs["amount"], "amount")
            parent_cid = _int_or_none(kwargs["parent_cid"], "parent_cid")
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                etoro_copy_start(
                    parent_cid,
                    amount,
                    _connection(kwargs.get("connection")),
                    reference_id=str(kwargs["reference_id"]),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroCopyPollTool(BaseTool):
    name = "etoro_copy_poll"
    description = (
        "Poll the outcome of an asynchronous eToro copy operation. "
        "Live accounts only — not supported on demo (paper) profiles."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "reference_id": {"type": "string", "description": "Copy operation reference id."},
            "request_id": {"type": "string", "description": "Optional request id (UUID)."},
        },
        "required": ["reference_id"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                etoro_copy_poll(
                    str(kwargs["reference_id"]),
                    _connection(kwargs.get("connection")),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class EtoroCopyCloseTool(BaseTool):
    name = "etoro_copy_close"
    description = (
        "Close or detach an eToro copy relationship by mirror id. "
        "Live accounts only — not supported on demo (paper) profiles."
    )
    parameters = {
        "type": "object",
        "properties": {
            **ETORO_TOOL_PARAMETERS,
            "mirror_id": {"type": "integer", "description": "Copy mirror id."},
            "unregister_type": {
                "type": "string",
                "enum": ["Close", "Detach"],
                "description": "Close liquidates copy; Detach moves positions to main portfolio.",
            },
            "request_id": {"type": "string", "description": "Optional request id (UUID)."},
        },
        "required": ["mirror_id"],
    }
    repeatable = False
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            overrides = _etoro_overrides(kwargs)
            mirror_id = _int_or_none(kwargs["mirror_id"], "mirror_id")
        except InvalidTradingArgument as exc:
            return _json_result({"status": "error", "error": str(exc)})
        try:
            return _json_result(
                etoro_copy_close(
                    mirror_id,
                    _connection(kwargs.get("connection")),
                    unregister_type=str(kwargs.get("unregister_type") or "Close"),
                    request_id=_connection(kwargs.get("request_id")),
                    **overrides,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})
