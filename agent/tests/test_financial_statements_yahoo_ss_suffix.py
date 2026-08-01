"""Regression test for _classify_market handling Yahoo .SS suffix in financial_statements_tool.

Locks out a bug where _classify_market returned None for Shanghai A-share symbols using Yahoo's
standard .SS suffix (e.g. "600519.SS"), rejecting valid financial statement queries.
"""

from src.tools.financial_statements_tool import _classify_market


def test_classify_market_supports_yahoo_ss_suffix():
    """Prove that _classify_market classifies both .SH and Yahoo .SS as 'a_share'."""
    assert _classify_market("600519.SH") == "a_share"
    assert _classify_market("000001.SZ") == "a_share"
    assert _classify_market("430139.BJ") == "a_share"
    
    # Yahoo Shanghai suffix .SS (previously returned None on un-fixed code)
    assert _classify_market("600519.SS") == "a_share"
    assert _classify_market("600000.SS") == "a_share"
