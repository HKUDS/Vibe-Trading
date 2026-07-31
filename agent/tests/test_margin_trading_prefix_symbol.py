"""Regression test for _extract_code handling prefix-style A-share symbols in margin_trading_tool.

Locks out a bug where _extract_code returned None for prefix-style symbols like
"sh.600519" or "sz.000001" because token.rpartition(".")[0] extracted the prefix part before the dot.
"""

from src.tools.margin_trading_tool import _extract_code


def test_extract_code_supports_prefix_style_symbols():
    """Prove that _extract_code extracts bare 6-digit codes from both suffix and prefix style A-share symbols."""
    # Suffix style
    assert _extract_code("600519.SH") == "600519"
    assert _extract_code("000001.SZ") == "000001"
    assert _extract_code("600519") == "600519"

    # Prefix style (previously returned None on un-fixed code)
    assert _extract_code("sh.600519") == "600519"
    assert _extract_code("sz.000001") == "000001"
    assert _extract_code("SH.600519") == "600519"
