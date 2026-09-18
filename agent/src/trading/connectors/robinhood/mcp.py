"""Robinhood remote MCP generic-operation mapping and reply shapes.

Every consumer that reads a Robinhood reply goes through this module: the
trading service's generic reads, the portfolio source, the live runner, the
pre-trade order gate and the mandate ceiling fetch. They used to read the reply
one level too shallow (``data.positions`` where Robinhood nests
``data.data.positions``), each in its own way (#1442).

What the shapes are built from, and nothing else:

* ``get_accounts``: observed field names and types posted on #1428
  (2026-09-14). Not a schema.
* ``get_portfolio``: observed on #1428 (2026-09-14). Not a schema.
* ``get_equity_positions``: the server's advertised ``outputSchema`` posted on
  #1428 (2026-09-16). ``data`` allows exactly ``positions`` and ``next``. An item
  carries ``symbol``, ``quantity`` and an optional ``average_buy_price``, and no
  price or currency.

Still unobserved: ``get_equity_quotes``, ``get_equity_orders``, the argument that
fetches a further page, and what an item's ``type`` means. So a reply with
more than one page is an error rather than a first page read as the whole
account, and ``type`` is carried through without being interpreted.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

_REMOTE_TOOL_NAMES = {
    "accounts": "get_accounts",
    "account": "get_portfolio",
    "positions": "get_equity_positions",
    "orders": "get_equity_orders",
    "quote": "get_equity_quotes",
}

_RUNNER_TOOL_NAMES = {
    "accounts": "get_accounts",
    "account": "get_portfolio",
    "positions": "get_equity_positions",
    "orders": "get_equity_orders",
    "quote": "get_equity_quotes",
    "submit_order": "place_equity_order",
    "cancel_order": "cancel_equity_order",
}

#: ``get_portfolio`` values held outside equities. ``get_equity_positions``
#: covers none of them, so a holdings view is only complete when all are zero.
NON_EQUITY_VALUE_FIELDS = (
    "options_value",
    "crypto_value",
    "futures_value",
    "event_contracts_value",
    "mutual_funds_value",
    "fixed_income_value",
)

#: Operations whose remote tool takes the selected account as ``account_number``.
ACCOUNT_SCOPED_OPERATIONS = frozenset({"account", "positions", "orders"})


class RobinhoodShapeError(ValueError):
    """A Robinhood reply that does not match the shape this mapping was built from."""


def remote_tool_name(operation: str) -> str | None:
    """Return the Robinhood remote tool name for a generic operation."""
    return _REMOTE_TOOL_NAMES.get(operation)


def runner_tool_name(operation: str) -> str | None:
    """Return the Robinhood remote tool name used by live runner plumbing."""
    return _RUNNER_TOOL_NAMES.get(operation)


def remote_arguments(operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize generic arguments for a Robinhood remote MCP operation."""
    if operation == "quote":
        symbol = arguments.get("symbol")
        symbols = arguments.get("symbols")
        return {"symbols": symbols or ([symbol] if symbol else [])}
    if operation in ACCOUNT_SCOPED_OPERATIONS:
        # Robinhood's get_portfolio / get_equity_positions / get_equity_orders
        # MCP tools require account_number. The generic trading service passes
        # the CLI/agent-supplied account code in under the "account" key; map
        # it to the field name Robinhood's schema actually expects.
        account_number = arguments.get("account_number") or arguments.get("account")
        if account_number:
            return {"account_number": account_number}
        return {}
    return {}


def broker_data(envelope: Any, tool: str) -> dict[str, Any]:
    """Return the broker's inner ``data`` object from an adapter envelope.

    Args:
        envelope: ``MCPServerAdapter.call_tool`` result.
        tool: Remote tool name, for the error message.

    Returns:
        The ``data`` object of the broker payload.

    Raises:
        RobinhoodShapeError: If the call failed, or the payload is not an
            object whose ``data`` is an object.
    """
    if not isinstance(envelope, dict):
        raise RobinhoodShapeError(f"{tool} returned {type(envelope).__name__}, not an object")
    if str(envelope.get("status") or "").lower() != "ok":
        raise RobinhoodShapeError(str(envelope.get("error") or f"{tool} failed"))
    payload = envelope.get("structured_content")
    if payload is None:
        payload = envelope.get("data")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise RobinhoodShapeError(f"{tool} reply has no data object")
    return payload["data"]


def records(envelope: Any, key: str, tool: str) -> list[dict[str, Any]]:
    """Return the complete record list a Robinhood list read carries.

    Args:
        envelope: ``MCPServerAdapter.call_tool`` result.
        key: The list field inside ``data`` (``positions``, ``orders``,
            ``accounts``).
        tool: Remote tool name, for error messages.

    Returns:
        Every record, each an object.

    Raises:
        RobinhoodShapeError: If the list is missing or null, holds a null or
            non-object item, ``data`` carries a key other than ``key`` and
            ``next``, or a non-empty ``next`` says the reply is one page of
            several.
    """
    data = broker_data(envelope, tool)
    unexpected = sorted(set(data) - {key, "next"})
    if unexpected:
        raise RobinhoodShapeError(f"{tool} reply has unmapped data keys: {', '.join(unexpected)}")
    if data.get("next") not in (None, ""):
        raise RobinhoodShapeError(
            f"{tool} returned more than one page; reading further pages is not mapped yet, "
            "and the first page is not the whole account"
        )
    rows = data.get(key)
    if not isinstance(rows, list):
        raise RobinhoodShapeError(f"{tool} reply has no {key} list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RobinhoodShapeError(f"{tool} {key}[{index}] is not an object")
    return rows


def _decimal_text(value: Any, field: str, tool: str) -> str:
    """Return ``value`` when it is a finite decimal string, else raise."""
    if isinstance(value, bool) or value is None:
        raise RobinhoodShapeError(f"{tool} {field} is missing")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RobinhoodShapeError(f"{tool} {field} is not a number") from None
    if not parsed.is_finite():
        raise RobinhoodShapeError(f"{tool} {field} is not finite")
    return str(value)


def portfolio_summary(envelope: Any) -> dict[str, Any]:
    """Map a ``get_portfolio`` reply to the account summary every consumer reads.

    Args:
        envelope: ``MCPServerAdapter.call_tool`` result for ``get_portfolio``.

    Returns:
        ``portfolio_value``, ``cash``, ``buying_power`` and ``currency``, plus
        ``non_equity_values`` mapping each field in
        :data:`NON_EQUITY_VALUE_FIELDS` to its value, or ``None`` when the
        reply omitted it. Values stay decimal strings.

    Raises:
        RobinhoodShapeError: If ``total_value`` or ``currency`` is missing, or a
            value that is present is not a finite number.
    """
    tool = "get_portfolio"
    data = broker_data(envelope, tool)
    currency = data.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise RobinhoodShapeError(f"{tool} currency is missing")
    buying_power = data.get("buying_power")
    raw_buying_power = buying_power.get("buying_power") if isinstance(buying_power, dict) else None
    return {
        "portfolio_value": _decimal_text(data.get("total_value"), "total_value", tool),
        "cash": _decimal_text(data["cash"], "cash", tool) if data.get("cash") is not None else None,
        "buying_power": (
            _decimal_text(raw_buying_power, "buying_power.buying_power", tool)
            if raw_buying_power is not None
            else None
        ),
        "currency": currency.strip().upper(),
        "non_equity_values": {
            field: _decimal_text(data[field], field, tool) if data.get(field) is not None else None
            for field in NON_EQUITY_VALUE_FIELDS
        },
    }


def position_rows(envelope: Any) -> list[dict[str, Any]]:
    """Map a ``get_equity_positions`` reply to generic position rows.

    Args:
        envelope: ``MCPServerAdapter.call_tool`` result for
            ``get_equity_positions``.

    Returns:
        One ``{"symbol", "quantity", "average_cost", "broker_type"}`` row per
        position. ``average_cost`` is ``None`` when Robinhood omitted
        ``average_buy_price`` (it does while a position reconciles); it is
        never read as zero.

    Raises:
        RobinhoodShapeError: If the reply is not a complete, single-page
            position list, or a row has no symbol or a non-numeric quantity.
    """
    tool = "get_equity_positions"
    rows = []
    for index, row in enumerate(records(envelope, "positions", tool)):
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise RobinhoodShapeError(f"{tool} positions[{index}] has no symbol")
        average = row.get("average_buy_price")
        rows.append(
            {
                "symbol": symbol.strip().upper(),
                "quantity": _decimal_text(row.get("quantity"), f"positions[{index}].quantity", tool),
                "average_cost": (
                    _decimal_text(average, f"positions[{index}].average_buy_price", tool)
                    if average is not None
                    else None
                ),
                "broker_type": row.get("type"),
            }
        )
    return rows


def account_choices(envelope: Any) -> list[dict[str, Any]]:
    """Map a ``get_accounts`` reply to the rows an account picker shows.

    Args:
        envelope: ``MCPServerAdapter.call_tool`` result for ``get_accounts``.

    Returns:
        One row per account: ``account_ref`` (the account number, which is
        what the account-scoped tools take), a ``label`` built from the
        nickname or account type plus the last four digits, and the
        ``is_default`` / ``agentic_allowed`` / ``deactivated`` flags. Every
        other field Robinhood returns is dropped.

    Raises:
        RobinhoodShapeError: If the reply is not a complete account list, or an
            account has no account number.
    """
    tool = "get_accounts"
    choices = []
    for index, row in enumerate(records(envelope, "accounts", tool)):
        number = row.get("account_number")
        if not isinstance(number, str) or not number.strip():
            raise RobinhoodShapeError(f"{tool} accounts[{index}] has no account_number")
        number = number.strip()
        name = next(
            (
                str(row[key]).strip()
                for key in ("nickname", "brokerage_account_type", "type")
                if isinstance(row.get(key), str) and row[key].strip()
            ),
            "Robinhood account",
        )
        choices.append(
            {
                "account_ref": number,
                "label": f"{name} ····{number[-4:]}",
                "is_default": row.get("is_default") is True,
                "agentic_allowed": row.get("agentic_allowed") is True,
                "deactivated": row.get("deactivated") is True or row.get("permanently_deactivated") is True,
            }
        )
    return choices


def normalize_result(operation: str, envelope: dict[str, Any]) -> dict[str, Any]:
    """Add the generic account / positions / accounts view to a Robinhood reply.

    The broker reply is kept as it came. A reply that does not match the mapped
    shape is not turned into an error here, because an agent reading the
    account can still use the raw text. It carries ``mapping_error`` instead,
    and a consumer that needs the mapped view (the portfolio) fails on it.

    Args:
        operation: Generic operation that produced the reply.
        envelope: ``MCPServerAdapter.call_tool`` result.

    Returns:
        A shallow copy with ``account``, ``positions`` or ``accounts`` added, or
        with ``mapping_error`` when the shape did not match.
    """
    mappers = {
        "account": ("account", portfolio_summary),
        "positions": ("positions", position_rows),
        "accounts": ("accounts", account_choices),
    }
    if operation not in mappers or str(envelope.get("status") or "").lower() != "ok":
        return envelope
    key, mapper = mappers[operation]
    normalized = dict(envelope)
    try:
        normalized[key] = mapper(envelope)
    except RobinhoodShapeError as exc:
        normalized["mapping_error"] = str(exc)
    return normalized
