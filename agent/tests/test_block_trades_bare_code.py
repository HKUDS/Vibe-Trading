"""Regression test for _resolve_code handling bare 6-digit A-share symbols in block_trades_tool.

Locks out a bug where _resolve_code returned None for bare 6-digit A-share codes
(e.g. "600519" or "000001") because symbol.rpartition(".")[0] returned an empty string
when symbol contained no dot.
"""

from src.tools.block_trades_tool import _resolve_code


def test_resolve_code_accepts_bare_a_share_code():
    """Prove that _resolve_code resolves both market-suffixed and bare A-share tickers."""
    # Market-suffixed A-shares
    assert _resolve_code("600519.SH") == "600519"
    assert _resolve_code("000001.SZ") == "000001"
    
    # Bare 6-digit A-shares (previously returned None on un-fixed code)
    assert _resolve_code("600519") == "600519"
    assert _resolve_code("000001") == "000001"
