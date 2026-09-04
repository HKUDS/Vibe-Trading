from __future__ import annotations

import pytest

from src.portfolio.compatibility import (
    PortfolioContractError,
    adapt_and_validate_payloads,
    ensure_supported_currencies,
    profile_compatibility,
)
from src.portfolio.config import eligible_profiles
from src.portfolio.normalization import normalize_position
from src.trading.types import TradingProfile


def test_every_builtin_portfolio_connector_has_an_explicit_compatibility_tier():
    expected = {
        "alpaca": "contract_tested",
        "binance": "native",
        "dhan": "experimental",
        "etoro": "experimental",
        "futu": "experimental",
        "ibkr": "native",
        "longbridge": "native",
        "mt5": "experimental",
        "okx": "contract_tested",
        "shoonya": "experimental",
        "tiger": "experimental",
        "trading212": "experimental",
    }

    observed = {profile.connector: profile_compatibility(profile)["level"] for profile in eligible_profiles()}

    assert observed == expected


def test_unknown_local_connector_is_experimental_by_default():
    profile = TradingProfile(
        id="sample-live-readonly",
        connector="sample",
        label="Sample",
        environment="live",
        transport="local_plugin",
        capabilities=("account.read", "positions.read"),
        readonly=True,
    )

    compatibility = profile_compatibility(profile)

    assert compatibility["level"] == "experimental"
    assert compatibility["contract_version"] == 1


def test_contract_rejects_position_rows_without_symbol_or_quantity():
    with pytest.raises(PortfolioContractError, match="no symbol"):
        adapt_and_validate_payloads("sample", {"account": {}}, {"positions": [{"quantity": 1}]})

    with pytest.raises(PortfolioContractError, match="no quantity"):
        adapt_and_validate_payloads("sample", {"account": {}}, {"positions": [{"symbol": "DEMO"}]})


def test_okx_account_details_are_adapted_to_spot_positions():
    account, positions = adapt_and_validate_payloads(
        "okx",
        {
            "account": {
                "total_equity": "65250",
                "details": [
                    {
                        "currency": "BTC",
                        "equity": "1.5",
                        "available": "1.0",
                        "frozen": "0.5",
                    },
                    {
                        "currency": "USDT",
                        "equity": "250",
                        "available": "250",
                        "frozen": "0",
                    },
                    {"currency": "ETH", "equity": "0"},
                ],
            }
        },
        {"positions": []},
    )

    assert account["account"]["total_equity"] == "65250"
    assert positions["positions"] == [
        {
            "symbol": "BTC",
            "quantity": "1.5",
            "currency": "USD",
            "quote_symbol": "BTC-USDT",
            "asset_type": "crypto",
            "free": "1.0",
            "used": "0.5",
            "source": "spot",
        },
        {
            "symbol": "USDT",
            "quantity": "250",
            "currency": "USD",
            "quote_symbol": "USDT",
            "asset_type": "stablecoin",
            "free": "250",
            "used": "0",
            "source": "spot",
        },
    ]


def test_contract_propagates_account_currency_and_rejects_unsupported_fx():
    account, positions = adapt_and_validate_payloads(
        "dhan",
        {"account": {"currency": "INR"}},
        {"positions": [{"symbol": "RELIANCE", "quantity": 1}]},
    )
    assert positions["positions"][0]["currency"] == "INR"

    with pytest.raises(PortfolioContractError, match="INR"):
        ensure_supported_currencies(positions["positions"], account)


def test_cash_only_unsupported_currency_fails_closed() -> None:
    with pytest.raises(PortfolioContractError, match="INR"):
        ensure_supported_currencies([], {"account": {"currency": "INR"}})


@pytest.mark.parametrize(
    ("connector", "raw", "expected"),
    [
        (
            "trading212",
            {
                "ticker": "AAPL_US_EQ",
                "quantity": 2,
                "average_price": 150,
                "current_price": 151.25,
                "currency": "USD",
            },
            ("AAPL_US_EQ", 2.0, 150.0, 151.25),
        ),
        (
            "shoonya",
            {"symbol": "INFY", "quantity": 3, "average_cost": 10, "ltp": 12},
            ("INFY", 3.0, 10.0, 12.0),
        ),
        (
            "mt5",
            {
                "symbol": "EURUSD",
                "volume": 0.5,
                "price_open": 1.1,
                "price_current": 1.2,
            },
            ("EURUSD", 0.5, 1.1, 1.2),
        ),
        (
            "etoro",
            {"symbol": "Apple", "units": 4, "open_rate": 180},
            ("APPLE", 4.0, 180.0, None),
        ),
    ],
)
def test_generic_normalizer_accepts_builtin_connector_aliases(connector, raw, expected):
    row = normalize_position(connector, raw)

    assert (
        row["symbol"],
        row["quantity"],
        row["cost_price"],
        row["market_price"],
    ) == expected
