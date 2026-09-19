"""Portfolio FX contract: currency identity is separate from rate availability."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.portfolio.compatibility import PortfolioContractError
from src.portfolio.config import parse_settings
from src.portfolio.fx import build_rates, from_usd, to_usd
from src.portfolio.normalization import account_total_usd, value_position

RATES = build_rates(Decimal("7"), Decimal("8"))


def test_build_rates_anchors_on_usd() -> None:
    assert RATES == {
        "USD": Decimal("1"),
        "CNY": Decimal("7"),
        "HKD": Decimal("8"),
    }


@pytest.mark.parametrize(
    "bad",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_build_rates_rejects_non_positive_or_non_finite_rates(bad: Decimal) -> None:
    with pytest.raises(PortfolioContractError, match="USD/CNY"):
        build_rates(bad, Decimal("8"))


def test_to_usd_converts_and_names_a_missing_rate() -> None:
    assert to_usd(Decimal("800"), "HKD", RATES) == Decimal("100")
    with pytest.raises(PortfolioContractError, match="KRW"):
        to_usd(Decimal("130000"), "KRW", RATES)


def test_from_usd_round_trip() -> None:
    assert from_usd(Decimal("100"), "CNY", RATES) == Decimal("700")


def _krw_row() -> dict:
    return {
        "symbol": "005930.KS",
        "currency": "KRW",
        "price_currency": "KRW",
        "quantity": 10,
        "cost_price": 50000,
        "market_price": 60000,
    }


def test_value_position_without_rate_fails_closed() -> None:
    with pytest.raises(PortfolioContractError, match="KRW"):
        value_position(_krw_row(), rates=RATES)


def test_value_position_converts_when_rate_exists() -> None:
    row = value_position(_krw_row(), rates={**RATES, "KRW": Decimal("1000")})
    assert row["market_value_usd"] == pytest.approx(600.0)
    assert row["unrealized_pnl_usd"] == pytest.approx(100.0)
    assert row["market_value_cny"] == pytest.approx(4200.0)


def test_account_total_converts_a_valid_iso_currency_when_rated() -> None:
    account = {"account": {"currency": "EUR", "total_equity": "920"}}
    total = account_total_usd("sample", account, {**RATES, "EUR": Decimal("0.92")})
    assert total == Decimal("1000")


def test_parse_settings_rejects_valid_iso_display_currency_without_production_rate() -> (
    None
):
    with pytest.raises(ValueError, match="EUR.*no production FX rate"):
        parse_settings({"display_currency": "EUR", "sources": []})


def test_parse_settings_accepts_rateable_display_currency() -> None:
    settings = parse_settings({"display_currency": "hkd", "sources": []})
    assert settings.display_currency == "HKD"


def test_parse_settings_rejects_non_iso_display_currency() -> None:
    with pytest.raises(ValueError, match="ISO-4217"):
        parse_settings({"display_currency": "USDT", "sources": []})
