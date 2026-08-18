"""Regression: ``safe_fallback`` must distinguish two different rejection causes.

The old code returned the same "I could not safely lock the instrument
identity or price evidence, so I did not produce a trading conclusion.
Please confirm the candidate symbol and venue." for every failed draft
that did not have price evidence in the ledger. That message was
confusing for non-finance drafts (e.g. an alpha-zoo enumeration that cited
"105 missing") because it asked the user to confirm a ticker they never
named. The fix:

  * When ``_identity_required`` is False (a non-market question, such as
    "list 10 SPCX alphas" or "summarise my trade journal"), the fallback
    blames the cited numbers, not the missing identity, and tells the user
    the answer will be re-derived from tool calls in a follow-up turn.
  * When ``_identity_required`` is True, the original "instrument
    identity or price evidence" message is preserved, because in that
    case the user really did name a tradable instrument that the gate
    could not lock.

The language is selected from the user message (zh vs en), matching
the existing ``safe_fallback`` behavior.
"""

from __future__ import annotations

from pathlib import Path

from src.agent.grounding import GroundingLedger


def _safe_fallback(user_message: str) -> str:
    ledger = GroundingLedger(
        run_dir=Path("/tmp/test_safe_fallback"),
        user_message=user_message,
    )
    return ledger.safe_fallback()


def test_non_market_question_chinese() -> None:
    """An alpha-zoo enumeration should not ask for a ticker confirmation."""
    msg = _safe_fallback("列出你有 462 个预置 alpha 中的前 10 个spcx  alpha，给中文一句话简介")
    assert "标的身份" not in msg, (
        "non-finance question was told to confirm an instrument identity; "
        f"got: {msg!r}"
    )
    assert "数字" in msg, (
        "non-finance fallback should blame the cited numbers; "
        f"got: {msg!r}"
    )
    assert "工具" in msg, "fallback should reference tool calls"
    assert "spcx" not in msg, "fallback should not parrot the user's failed prompt"


def test_non_market_question_english() -> None:
    msg = _safe_fallback("Summarise my recent trade journal")
    assert "instrument identity" not in msg
    assert "numbers" in msg.lower() or "evidence" in msg.lower()


def test_market_question_preserves_identity_message() -> None:
    """A real ticker query keeps the identity-or-evidence message."""
    msg = _safe_fallback("AAPL 股价是多少")
    assert "标的身份" in msg
    assert "证券代码" in msg
    assert "数字" not in msg


def test_market_question_english_preserves_identity_message() -> None:
    msg = _safe_fallback("AAPL target price")
    assert "instrument identity" in msg
    assert "symbol" in msg.lower()


def test_safe_fallback_does_not_include_failed_user_prompt() -> None:
    """The fallback must not echo the user's failed input verbatim."""
    # The most common confusion was the old message repeating the user's
    # own question back at them ("Please confirm the candidate symbol and
    # venue") when the question had no candidate symbol at all.
    msg = _safe_fallback("统计一下今天 5 个 alpha 的均值")
    assert "5 个 alpha" not in msg, "fallback should not parrot the user's wording"
    assert "均值" not in msg


def test_safe_fallback_with_tool_failure_hint() -> None:
    """If tool_failures is populated, the fallback surfaces which tool failed."""
    ledger = GroundingLedger(
        run_dir=Path("/tmp/test_safe_fallback_hint"),
        user_message="列出 spcx 前 10 个 alpha",
    )
    # _record_tool_failure appends a dict; mimic that shape so the test
    # exercises the same code path as the runtime.
    ledger._tool_failures.append(
        {
            "call_id": "call_test",
            "tool": "alpha_zoo",
            "status": "unavailable",
            "error_code": None,
            "message": "alpha_id 'spcx_001' not in registry",
            "recorded_at": "2026-08-18T00:00:00Z",
        }
    )
    msg = ledger.safe_fallback()
    assert "alpha_zoo" in msg, (
        f"fallback should mention which tool failed; got: {msg!r}"
    )
