"""Portfolio compatibility metadata and connector payload contracts.

The trading layer exposes a deliberately broad connector interface.  The
portfolio page has a narrower contract: account and position reads must be
read-only, position rows must identify a symbol and quantity, and every value
must be convertible without guessing.  This module keeps that distinction
explicit so a newly registered connector is shown as experimental until its
portfolio payload has dedicated or fixture-backed coverage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping

from src.portfolio.iso4217 import is_iso_currency
from src.trading.types import TradingProfile

CompatibilityLevel = Literal["native", "contract_tested", "experimental"]
_SYMBOL_FIELDS = ("symbol", "code", "ticker")
_QUANTITY_FIELDS = (
    "quantity",
    "qty",
    "position",
    "position_qty",
    "volume",
    "units",
)


@dataclass(frozen=True)
class PortfolioCompatibility:
    """Public, credential-free compatibility metadata for one connector."""

    level: CompatibilityLevel
    contract_version: int
    asset_scope: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        """Return the metadata in its API wire shape."""
        return asdict(self)


_CONNECTOR_COMPATIBILITY: dict[str, PortfolioCompatibility] = {
    "ibkr": PortfolioCompatibility("native", 1, "stocks_etfs", "Dedicated IBKR account and position mapping."),
    "longbridge": PortfolioCompatibility(
        "native",
        1,
        "stocks_etfs",
        "Dedicated Longbridge mapping and quote fallback.",
    ),
    "binance": PortfolioCompatibility("native", 1, "spot", "Dedicated spot and Simple Earn balance handling."),
    "alpaca": PortfolioCompatibility(
        "contract_tested",
        1,
        "stocks_etfs",
        "Canonical USD account and position payloads are covered by contract tests.",
    ),
    "okx": PortfolioCompatibility(
        "contract_tested",
        1,
        "spot_and_positions",
        "Spot balances are adapted alongside open OKX positions.",
    ),
    "dhan": PortfolioCompatibility("experimental", 1, "positions", "INR valuation is not supported yet."),
    "shoonya": PortfolioCompatibility("experimental", 1, "positions", "INR valuation is not supported yet."),
    "zerodha": PortfolioCompatibility("experimental", 1, "positions", "INR valuation is not supported yet."),
    "futu": PortfolioCompatibility(
        "experimental",
        1,
        "stocks_etfs",
        "Multi-market currency metadata still requires live verification.",
    ),
    "tiger": PortfolioCompatibility(
        "experimental",
        1,
        "stocks_etfs",
        "Multi-market account totals still require live verification.",
    ),
    "trading212": PortfolioCompatibility(
        "experimental",
        1,
        "stocks_etfs",
        "Position aliases are supported; cash totals still require verification.",
    ),
    "mt5": PortfolioCompatibility(
        "experimental",
        1,
        "open_positions",
        "Contract-size and non-USD account valuation require verification.",
    ),
    "etoro": PortfolioCompatibility(
        "experimental",
        1,
        "open_positions",
        "Account totals and instrument quote resolution require verification.",
    ),
    "toss": PortfolioCompatibility("experimental", 1, "positions", "KRW valuation is not supported yet."),
    "robinhood": PortfolioCompatibility(
        "experimental",
        1,
        "stocks_etfs",
        "Equity positions for one selected account, unpriced until the quote reply is mapped.",
    ),
    # No "scalable" entry: its profile does not declare account.read /
    # positions.read, so it is not a portfolio-eligible connection. The
    # holdings reply shape is unverified (no published tool argument schemas),
    # so a portfolio read could not be mapped; add the entry with the
    # normalisation once a live tools/list settles the shape (#1367).
}

_EXPERIMENTAL_DEFAULT = PortfolioCompatibility(
    "experimental",
    1,
    "declared_by_connector",
    "The connector declares portfolio reads but has no built-in contract fixture.",
)


class PortfolioContractError(RuntimeError):
    """Raised when a connector payload cannot be aggregated without guessing."""


def profile_compatibility(profile: TradingProfile) -> dict[str, Any]:
    """Return compatibility metadata for a built-in or local profile."""
    return _CONNECTOR_COMPATIBILITY.get(profile.connector, _EXPERIMENTAL_DEFAULT).to_dict()


def adapt_and_validate_payloads(
    connector: str,
    account_payload: dict[str, Any],
    positions_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt connector-specific reads and validate the portfolio contract.

    The returned payloads are shallow copies.  Connector responses are never
    mutated because the trading service may reuse them for another consumer.
    """
    if not isinstance(account_payload, dict):
        raise PortfolioContractError("account read must return an object")
    if not isinstance(positions_payload, dict):
        raise PortfolioContractError("positions read must return an object")

    for label, payload in (("account", account_payload), ("positions", positions_payload)):
        if payload.get("mapping_error"):
            raise PortfolioContractError(f"{label} read could not be mapped: {payload['mapping_error']}")
    account = dict(account_payload)
    positions = dict(positions_payload)
    if connector == "robinhood":
        _require_equity_only_robinhood_account(account)
    # No default: a read that never produced a positions list (an unmapped MCP
    # envelope, a text-only reply) is not an empty portfolio. Reading it as one
    # would store a complete snapshot of a source that holds nothing.
    raw_rows = positions.get("positions")
    if not isinstance(raw_rows, list):
        raise PortfolioContractError("positions payload must contain a list")
    rows = [dict(row) if isinstance(row, dict) else row for row in raw_rows]

    if connector == "okx":
        rows.extend(_okx_spot_rows(account, rows))

    default_currency = _account_currency(account)
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PortfolioContractError(f"position {index} must be an object")
        if not any(str(row.get(field) or "").strip() for field in _SYMBOL_FIELDS):
            raise PortfolioContractError(f"position {index} has no symbol")
        if not any(field in row and row.get(field) is not None for field in _QUANTITY_FIELDS):
            raise PortfolioContractError(f"position {index} has no quantity")
        if default_currency and not row.get("currency"):
            row["currency"] = default_currency
        validated.append(row)
    positions["positions"] = validated
    return account, positions


def _require_equity_only_robinhood_account(account_payload: dict[str, Any]) -> None:
    """Refuse a Robinhood account whose holdings reach beyond equities.

    ``get_equity_positions`` lists equities only, while ``get_portfolio`` reports
    options, crypto, futures, event contracts, mutual funds and fixed income as
    separate values. Showing the equity rows for an account that also holds any
    of those would be a quietly shorter portfolio, so the source fails instead,
    naming what it cannot list. An omitted value is unknown, not zero.

    Args:
        account_payload: The mapped ``get_portfolio`` read.

    Raises:
        PortfolioContractError: If the mapped summary is missing, or any
            non-equity value is non-zero or not reported.
    """
    summary = account_payload.get("account")
    values = summary.get("non_equity_values") if isinstance(summary, dict) else None
    if not isinstance(values, dict):
        raise PortfolioContractError("Robinhood account read carries no mapped portfolio summary")
    unreported = sorted(field for field, value in values.items() if value is None)
    held = sorted(field for field, value in values.items() if value is not None and _decimal(value) != 0)
    if unreported:
        raise PortfolioContractError(
            "Robinhood did not report " + ", ".join(unreported) + ", so an equity-only view cannot be shown as complete"
        )
    if held:
        raise PortfolioContractError(
            "this Robinhood account holds " + ", ".join(held) + ", which equity positions do not cover; "
            "an equity-only view would be incomplete"
        )


def ensure_supported_currencies(
    rows: list[dict[str, Any]],
    account_payload: dict[str, Any] | None = None,
    rates: Mapping[str, Decimal] | None = None,
) -> None:
    """Validate currency identity separately from current FX availability.

    A real ISO-4217 currency is valid portfolio metadata even when the current
    rates map cannot convert it. Valuation callers pass a rates map to fail
    closed on such gaps instead of silently assuming a 1:1 USD rate.
    """
    currencies = {
        str(row.get("price_currency") or row.get("currency") or "USD").upper()
        for row in rows
    }
    account_currency = _account_currency(account_payload or {})
    if account_currency:
        currencies.add(account_currency)

    invalid = sorted(code for code in currencies if not is_iso_currency(code))
    if invalid:
        raise PortfolioContractError(
            "portfolio currency is not a valid ISO-4217 code: " + ", ".join(invalid)
        )

    if rates is not None:
        missing = sorted(code for code in currencies if rates.get(code) is None)
        if missing:
            raise PortfolioContractError(
                "portfolio FX conversion is not available for: " + ", ".join(missing)
            )


def _account_currency(payload: dict[str, Any]) -> str | None:
    account = payload.get("account")
    if isinstance(account, dict):
        currency = account.get("currency")
        if currency:
            return str(currency).upper()
        aggregate = account.get("aggregated_portfolio")
        if isinstance(aggregate, dict) and aggregate.get("accountCurrency"):
            return str(aggregate["accountCurrency"]).upper()
    cash = payload.get("cash")
    if isinstance(cash, dict):
        currency = cash.get("currencyCode") or cash.get("currency")
        if currency:
            return str(currency).upper()
    return None


def _okx_spot_rows(account_payload: dict[str, Any], existing_rows: list[object]) -> list[dict[str, Any]]:
    account = account_payload.get("account")
    details = account.get("details", []) if isinstance(account, dict) else []
    if not isinstance(details, list):
        return []
    existing_symbols = {str(row.get("symbol") or "").upper() for row in existing_rows if isinstance(row, dict)}
    result = []
    stablecoins = {"USDT", "USDC", "FDUSD", "TUSD", "BUSD"}
    for detail in details:
        if not isinstance(detail, dict):
            continue
        symbol = str(detail.get("currency") or "").strip().upper()
        quantity = _decimal(detail.get("equity"))
        if not symbol or quantity <= 0 or symbol in existing_symbols:
            continue
        result.append(
            {
                "symbol": symbol,
                "quantity": str(quantity),
                "currency": "USD",
                "quote_symbol": symbol if symbol in stablecoins else f"{symbol}-USDT",
                "asset_type": "stablecoin" if symbol in stablecoins else "crypto",
                "free": detail.get("available"),
                "used": detail.get("frozen"),
                "source": "spot",
            }
        )
    return result


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value or "0"))
        return result if result.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
