"""Regression: count and range expressions must be masked from price-claim checks.

Real-user failure: an answer to "list the first 10 SPCX alphas" cited
"105 missing", "loaded 462", "the per-zoo counts (12+191+154=357) sum to
less than 462" and was rejected by ``numeric_claim_unavailable`` three
times in a row before ``safe_fallback`` ran. None of those digits are
prices — they are counts, aggregates, and range bounds — and the
grounding gate should not treat them as price claims.

The fix adds ``_COUNT_CONTEXT_RE`` to ``_numbers_without_dates_or_percent``
to mask:
  * numbers preceded by a count word ("105 missing", "loaded 462",
    "总数 105", "至少 10 个")
  * numbers followed by a count word ("12 alphas", "105 missing alphas",
    "the 357 total", "loaded=462 alphas")
  * arithmetic chains attached to either side ("12+191+154=357 alphas")
  * range/comparison bounds ("less than 462", "at most 5 trades",
    "超过 100")

Bare unitless numbers in price prose ("the 96.45 close", "loss 105",
"some price 105 HKD") are still checked against observed OHLC ranges so
the gate does not lose its price-fabrication defence. Indicator values
("RSI 67.3") are masked separately by ``_INDICATOR_VALUE_RE`` and are
not regressed here.
"""

from __future__ import annotations

from pathlib import Path

from src.agent.grounding import GroundingLedger


def _numbers(text: str) -> list[float]:
    ledger = GroundingLedger(
        run_dir=Path("/tmp/test_count_context"),
        user_message="test",
    )
    return ledger._numbers_without_dates_or_percent(text)


def test_mask_count_word_preceding_number() -> None:
    assert _numbers("the 105 missing alphas") == []


def test_mask_loaded_total_equals_pattern() -> None:
    assert _numbers("loaded 462 total") == []
    assert _numbers("loaded=462") == []
    assert _numbers("loaded=462 alphas") == []


def test_mask_chinese_count_words() -> None:
    assert _numbers("总数 105") == []
    assert _numbers("至少 10 个交易日") == []
    assert _numbers("共 12 个") == []
    assert _numbers("missing 105") == []


def test_mask_arithmetic_chain_after_count_word() -> None:
    # The exact failure case from c3300c640ab9 run. Every digit in the
    # "12+191+154=357" chain plus the trailing "462" comparison bound
    # should be masked; only the price 96.45 (none here) would remain.
    assert _numbers("the per-zoo counts (12+191+154=357) sum to less than 462") == []


def test_mask_range_comparison_words() -> None:
    assert _numbers("fewer than 100 missing") == []
    assert _numbers("at most 5 trades") == []
    assert _numbers("at least 10") == []
    assert _numbers("more than 5 records") == []


def test_mask_count_word_following_number_with_chain() -> None:
    # "12+191+154=357 alphas" — number chain on the left, count word on
    # the right. The chain tokens and the trailing "357" must all be
    # masked; the trailing "alphas" is the count word.
    assert _numbers("12+191+154=357 alphas") == []


def test_does_not_mask_legitimate_prices() -> None:
    # "96.45 close" is a real price claim; the gate should still flag
    # the "96.45" so it can be matched against the observed OHLC range.
    assert _numbers("the 96.45 close") == [96.45]
    assert _numbers("some price 105 HKD") == [105]
    assert _numbers("loss 105") == [105]


def test_does_not_mask_prices_mixed_with_indicators() -> None:
    # The price 96.45 must survive; the indicator 30 must be masked by
    # the existing _INDICATOR_VALUE_RE pass (which runs earlier in the
    # same chain).
    assert _numbers("the 96.45 close and RSI 30") == [96.45]


def test_does_not_mask_bare_unitless_numbers() -> None:
    # "alone 105" with no count context is the only kind of unitless
    # digit the gate should still try to verify against price evidence.
    # The "alone" here has no count word on either side, so 105 stays.
    assert _numbers("alone 105") == [105]
