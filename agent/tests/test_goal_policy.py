"""Tests for the finance research goal execution filter."""

from __future__ import annotations

import pytest

from src.goal.policy import reject_live_execution_objective


@pytest.mark.parametrize(
    "objective",
    [
        "Research whether Coinbase should buy more BTC reserves this quarter",
        "Assess if the fund should sell its GOOGL shares given antitrust risk",
        "Determine whether to short TSLA contracts based on delivery numbers",
        "Evaluate a long AAPL thesis versus a short thesis on valuation grounds",
        "Evaluate whether to buy NVDA at this valuation",
        "Long-term outlook for AAPL versus its sector",
        "Short interest trends in regional banks",
        "Short-term momentum in semiconductors",
        "研究茅台是否值得买入",
    ],
)
def test_ordinary_research_objectives_are_accepted(objective: str) -> None:
    # This is a research product whose whole purpose is evaluating whether to
    # buy/sell/short a security, so mentioning a buy/sell verb near an asset
    # noun (shares, contracts, btc) in a research objective is the normal
    # case, not an execution request.
    reject_live_execution_objective(objective)


@pytest.mark.parametrize(
    "objective",
    [
        "Buy AAPL now at market order",
        "Sell TSLA immediately, submit the order right away",
        "Place an order to buy BTC right away",
        "Buy 100 shares of NVDA right away using a limit order",
        # Rejected before #1562 through the asset-noun list, and still orders.
        "Buy 100 shares of NVDA",
        "Short 2 ES contracts",
        "buy 0.5 BTC",
        "Please buy AAPL",
        "Research the setup, then sell 50 TSLA",
        "买入100股贵州茅台",
        # Reversed word order: the immediacy cue comes before the verb.
        "Immediately buy TSLA",
        "Right away sell my AAPL position",
        "Now sell GOOGL",
    ],
)
def test_genuine_execution_requests_are_still_rejected(objective: str) -> None:
    with pytest.raises(ValueError, match="live trading or execution"):
        reject_live_execution_objective(objective)
