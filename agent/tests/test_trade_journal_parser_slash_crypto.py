"""Regression test for _infer_market_from_symbol handling slash-delimited crypto symbols in trade_journal_parsers.

Locks out a bug where _infer_market_from_symbol returned "other" instead of "crypto" for
slash-formatted crypto trading pairs (e.g. "ETH/USDT" or "BTC/USD").
"""

from src.tools.trade_journal_parsers import _infer_market_from_symbol


def test_infer_market_from_symbol_supports_slash_crypto_pairs():
    """Prove that _infer_market_from_symbol classifies slash-delimited crypto pairs as 'crypto'."""
    assert _infer_market_from_symbol("BTC-USDT") == "crypto"
    
    # Slash delimited crypto pairs (previously returned "other" on un-fixed code)
    assert _infer_market_from_symbol("ETH/USDT") == "crypto"
    assert _infer_market_from_symbol("BTC/USD") == "crypto"
    assert _infer_market_from_symbol("SOL/USDC") == "crypto"
