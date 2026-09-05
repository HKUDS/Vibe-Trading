"""Percentage-point deltas must not be read as quoted prices.

Regression test for the false positive described in HKUDS/Vibe-Trading#1341:
`_numbers_without_dates_or_percent` masked "%" but not the percentage-point
spellings, so "~3.6pp below Penumbra" yielded 3.0 (the ".6" consumed as a
decimal). That number reached the OHLC comparator as an unsourced price claim,
which rejected a correct fundamentals answer and demanded `get_market_data` to
substantiate a statement that had nothing to do with price.

Both directions are pinned here: percentage-point deltas are masked, and a
genuine price is still extracted.
"""

import pytest

from src.agent.grounding import GroundingLedger

_extract = GroundingLedger._numbers_without_dates_or_percent


@pytest.mark.parametrize(
    "text",
    [
        "gross margin ~3.6pp below Penumbra",
        "gross margin 3.6 pp below Penumbra",
        "operating margin improved 2.4ppt year over year",
        "operating margin improved 12.5 ppts sequentially",
        "spread widened 45bps after the print",
        "spread widened 45 bps after the print",
        "yield moved 7bp on the day",
        "\u6bdb\u5229\u7387\u4e0b\u964d 3.6 \u767e\u5206\u70b9",
        "margin fell -1.8pp sequentially",
        "margin rose +0.9pp sequentially",
        "roughly \u22483.6pp of dilution",
    ],
)
def test_percentage_point_deltas_are_not_prices(text):
    """No percentage-point delta should survive as a candidate price."""
    assert _extract(text) == [], f"leaked a price candidate from: {text!r}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("closing price 48.20", 48.20),
        ("the stock closed at 48.20 on heavy volume", 48.20),
        ("last trade 152.75", 152.75),
        ("opened at 1,204.50 and faded", 1204.50),
    ],
)
def test_genuine_prices_are_still_extracted(text, expected):
    """The mask must not swallow real quoted prices -- that would blind the
    grounding check it exists to feed."""
    assert expected in _extract(text), f"lost a real price from: {text!r}"


def test_mixed_sentence_keeps_price_drops_percentage_point():
    """A sentence carrying both must yield only the price."""
    values = _extract("closed at 48.20, with gross margin ~3.6pp below peers")
    assert 48.20 in values
    assert 3.0 not in values
    assert 3.6 not in values


def test_bare_number_still_extracted():
    """Guard against the mask being over-broad: a plain number is untouched."""
    assert 48.20 in _extract("48.20")


# The English spellings above were the ones the report named, but this gate
# sees whatever language the model answered in, and the UI ships seven locales.
# The first version of the mask required the number to sit directly against
# "百分点", which is the rare Chinese spelling — the ordinary one puts the
# measure word 个 in between, and "基点" was not covered at all. Both were
# still being read as prices, so a Chinese fundamentals answer kept getting
# rejected while the identical English answer passed.
@pytest.mark.parametrize(
    "text",
    [
        "毛利率下降 3.6 个百分点",
        "毛利率下降3.6个百分点",
        "净利率提升 2 个百分点。",
        "同比下降 3.6 百分点",
        "利差扩大 250 个基点",
        "利差扩大250基点",
        # A trailing CJK character rather than punctuation: \b after a CJK
        # unit needs a non-word char to follow, so this is the case that
        # breaks if the boundary is reintroduced there.
        "毛利率下降 3.6 个百分点后企稳",
    ],
)
def test_chinese_percentage_point_deltas_are_masked(text: str) -> None:
    assert _extract(text) == [], f"{text!r} leaked a price-like number"


# The other arm. Narrowing the false positives must not blind the gate to a
# real unsourced price, in either language.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TSLA.US last traded at 412.35 USD", [412.35]),
        ("closed at 412.35", [412.35]),
        ("现价 412.35 元", [412.35]),
        ("收盘价 412.35", [412.35]),
        # "ppm" is not "pp": the ASCII units keep their word boundary, so the
        # mask does not apply and a number still reaches the comparator. The
        # value is 3.0 rather than 3.6 because the extractor drops a decimal
        # tail followed immediately by letters — the same quirk the pp report
        # describes, pre-existing and untouched here. Pinned as-is so a future
        # change to either behaviour is visible.
        ("3.6ppm impurity", [3.0]),
    ],
)
def test_real_prices_still_extracted(text: str, expected: list) -> None:
    assert _extract(text) == expected
