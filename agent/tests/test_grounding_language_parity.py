"""The gate must reach the same verdict in every language it reads.

The gate used to key on a phrase list, and a phrase list is written in
whatever language the bug report arrived in. Twice that left it strictly
leakier on one side than the other:

- ``\\bclose\\b`` does not match "closed at", which is how an answer actually
  states an observed price. "The stock closed at 412.35." with zero tool calls
  passed, while "该股收盘 412.35。" — the same fabricated claim — was caught.
- Chinese had the mirror-image hole: 成交价 / 最新价 / 股价 / 收报 are as
  ordinary as 收盘价 and none of them matched.

There is no phrase list any more: a number's role is declared by the model and
its shape is language-independent. This file is what proves the property
survived the change, so the assertion is deliberately NOT a literal per
language. Each case runs the same figure through both spellings and asserts
the two verdicts are EQUAL.

Both arms are pinned. A gate whose tests only assert rejection cannot see
itself closing on everything.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from evals.grounding import GroundingLedger


def _has_issues(text: str) -> bool:
    """Validate a final answer with no tool evidence at all."""
    ledger = GroundingLedger(
        run_dir=pathlib.Path(tempfile.mkdtemp()),
        user_message="analyze",
        history=None,
    )
    return bool(ledger.validate_final_answer(text).issues)


# Unsourced measurements: no tool ran, so both spellings must be rejected.
_MUST_REJECT = [
    ("The stock closed at 412.35.", "该股收盘 412.35。"),
    ("The stock last traded at 412.35.", "该股最新成交价 412.35。"),
    ("Shares were quoted at 412.35.", "该股报价 412.35。"),
    ("The share price is 412.35.", "该股股价 412.35。"),
    ("It opened at 400.10.", "开盘 400.10。"),
    ("The closing price was 412.35.", "收盘价为 412.35。"),
    # The claim the old gate could only catch on one side of the language
    # border, in the phrasings that crossed it.
    ("The deal closed at a 30.5% premium.", "交易以 30.5% 溢价成交。"),
    ("Gross margin fell 3.6pp.", "毛利率下降 3.6 个百分点。"),
]

# Not measurements at all, or declared: both spellings must pass. Without this
# arm the suite is satisfied by a gate that rejects everything.
_MUST_ACCEPT = [
    ("The meeting closed at 5pm.", "会议 5 点结束。"),
    ("Volume traded 1200000 shares.", "成交量 1200000 股。"),
    ("I could not retrieve the price.", "我没能取到价格。"),
    ("The position closed 3 days later.", "该仓位 3 天后平掉。"),
    ("They traded 8 times last week.", "他们上周交易了 8 次。"),
    # The same figure, declared: the declaration is what moves the verdict,
    # and it moves both languages together.
    (
        "Per the merger announcement, the deal closed at a 30.5% premium.\n\n```figures\n"
        "30.5% | cited | merger announcement 2026-08-03\n```",
        "据并购公告，交易以 30.5% 溢价成交。\n\n```figures\n"
        "30.5% | cited | 并购公告 2026-08-03\n```",
    ),
    (
        "Gross margin fell 3.6pp.\n\n```figures\n"
        "3.6pp | cited | 2026 Q2 filing, gross margin bridge\n```",
        "毛利率下降 3.6 个百分点。\n\n```figures\n"
        "3.6 | cited | 2026 Q2 财报毛利率桥\n```",
    ),
]


@pytest.mark.parametrize(("english", "chinese"), _MUST_REJECT)
def test_unsourced_measurements_rejected_in_both_languages(
    english: str, chinese: str
) -> None:
    en, zh = _has_issues(english), _has_issues(chinese)
    assert en == zh, (
        f"verdicts disagree by language: EN={en} ZH={zh}\n"
        f"  EN: {english}\n  ZH: {chinese}"
    )
    assert en, "an unsourced measurement must be rejected"


@pytest.mark.parametrize(("english", "chinese"), _MUST_ACCEPT)
def test_non_measurements_and_declarations_accepted_in_both_languages(
    english: str, chinese: str
) -> None:
    en, zh = _has_issues(english), _has_issues(chinese)
    assert en == zh, (
        f"verdicts disagree by language: EN={en} ZH={zh}\n"
        f"  EN: {english}\n  ZH: {chinese}"
    )
    assert not en, "a bare integer or a declared figure must not be rejected"
