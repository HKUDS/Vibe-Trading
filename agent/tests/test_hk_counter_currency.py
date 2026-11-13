"""Hong Kong counters traded in CNY or USD never enter the HKD pool.

HKEX's Stock Code Allocation Plan (updated 2026-03-12) assigns 80000-89999 to
"Products traded in Renminbi" and a set of 09xxx / 10900-10999 / 41500-41599
sub-ranges to products traded in USD. Before this, 80700.HK (Tencent's RMB
counter, 375.40 CNY on 2026-09-24) and 9834.HK (a USD ETF) were booked in the
HKD pool and quoted as HKD by the grounding gate, because the hk_equity chain
leads with sources that declare no currency.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import code_currency, hk_counter_currency
from backtest.runner import _create_market_engine
from src.agent.instrument_identity import _infer_currency

# The currency Yahoo declared for each code on 2026-09-24.
_LIVE = {
    "80700": "CNY", "82318": "CNY", "80388": "CNY", "83188": "CNY", "82800": "CNY",
    "89988": "CNY", "9010": "USD", "9067": "USD", "9081": "USD", "9141": "USD",
    "9173": "USD", "9403": "USD", "9807": "USD", "9820": "USD", "9834": "USD",
    "9846": "USD", "9988": "HKD", "9618": "HKD", "9999": "HKD", "9868": "HKD",
    "9626": "HKD", "0700": "HKD", "2800": "HKD", "3188": "HKD",
}


@pytest.mark.parametrize(("code", "currency"), sorted(_LIVE.items()))
def test_the_code_range_gives_the_currency_the_venue_quotes(code: str, currency: str) -> None:
    assert hk_counter_currency(f"{code}.HK") == currency


@pytest.mark.parametrize(
    ("code", "currency"),
    [
        ("79999", "HKD"), ("80000", "CNY"), ("89999", "CNY"),
        ("8999", "HKD"), ("9000", "USD"), ("9599", "USD"), ("9600", "HKD"),
        ("9699", "HKD"), ("9700", "USD"), ("9849", "USD"), ("9850", "HKD"),
        ("10899", "HKD"), ("10900", "USD"), ("10999", "USD"), ("11000", "HKD"),
        ("41499", "HKD"), ("41500", "USD"), ("41599", "USD"), ("41600", "HKD"),
    ],
)
def test_both_sides_of_every_range_boundary(code: str, currency: str) -> None:
    assert hk_counter_currency(f"{code}.HK") == currency


def test_codes_outside_hong_kong_are_not_classified() -> None:
    assert hk_counter_currency("AAPL.US") is None
    assert hk_counter_currency("600519.SH") is None


def test_the_settlement_currency_and_the_grounding_currency_follow_the_counter() -> None:
    assert code_currency("80700.HK") == "CNY"
    assert code_currency("local:9834.HK") == "USD"
    assert code_currency("00700.HK") == "HKD"
    assert _infer_currency("80700.HK") == "CNY"
    assert _infer_currency("9834.HK") == "USD"
    assert _infer_currency("00700.HK") == "HKD"


@pytest.mark.parametrize(
    "codes",
    [["00700.HK", "80700.HK"], ["80700.HK"], ["9834.HK"], ["80700.HK", "AAPL.US"]],
)
def test_a_backtest_holding_a_foreign_counter_is_refused(codes: list[str]) -> None:
    with pytest.raises(ValueError, match="HKEX counters traded in another currency"):
        _create_market_engine("tencent", {}, codes)


def test_hkd_counters_still_build_an_engine() -> None:
    engine = _create_market_engine("tencent", {}, ["00700.HK", "09988.HK"])
    assert engine is not None
