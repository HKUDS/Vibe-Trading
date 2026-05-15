"""Regression tests for the Market data routing policy in the agent system prompt.

These tests pin three immutable substrings inside `_SYSTEM_PROMPT`. Removing
or altering any of them breaks the LLM-facing contract that forces market
data requests (price, OHLCV, ticker) to use ccxt/yfinance/akshare skills
first, and forbids web_search/read_url for quantitative market data.

Risk level: 3 (system prompt is an external behavioural contract).
"""

from __future__ import annotations

import pytest

from src.agent.context import _SYSTEM_PROMPT


@pytest.mark.unit
def test_market_data_routing_section_is_present() -> None:
    assert "**Market data** — user asks for" in _SYSTEM_PROMPT, (
        "Market data routing section was removed from _SYSTEM_PROMPT. "
        "Restore the rule that forces ccxt/yfinance/akshare before web tools."
    )


@pytest.mark.unit
def test_market_data_section_forbids_web_as_first_action() -> None:
    assert (
        "NEVER use web_search or read_url as the first action for price/OHLCV"
        in _SYSTEM_PROMPT
    ), (
        "Market data section no longer forbids web_search/read_url as the "
        "first action. This is the core guard against the LLM falling back "
        "to a browser for quantitative market data."
    )


@pytest.mark.unit
def test_guidelines_forbid_web_tools_for_market_data() -> None:
    assert (
        "web_search and read_url are FORBIDDEN for" in _SYSTEM_PROMPT
    ), (
        "Guidelines no longer carry the negative policy forbidding web "
        "tools for price/ticker/OHLCV. Restore the bullet."
    )


@pytest.mark.unit
def test_market_data_section_points_to_get_market_data_tool() -> None:
    """Patch 2: the routing rule must direct the LLM to the get_market_data
    tool as the first action (not load_skill+write_file+bash anymore)."""
    assert "get_market_data" in _SYSTEM_PROMPT, (
        "Market data routing section no longer references the get_market_data "
        "tool. The deterministic dispatch path is broken."
    )
