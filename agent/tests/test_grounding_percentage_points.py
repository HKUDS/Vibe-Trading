"""Percentage-point deltas: one shape, one verdict, in both languages.

Regression history for HKUDS/Vibe-Trading#1341: the price scan masked "%" but
not the percentage-point spellings, so "~3.6pp below Penumbra" yielded 3.0 (the
".6" consumed as a decimal) and that number reached the OHLC comparator as an
unsourced price claim — rejecting a correct fundamentals answer and demanding
`get_market_data` to substantiate a statement that had nothing to do with
price. The mask that fixed it then had to grow: 个百分点 and 基点 were missing,
the Chinese measure word broke the word boundary, and each gap was one more
rejected answer.

There is no mask now. A percentage-point delta is a decimal, which is
measurement-shaped, which means the model declares what it is — and the twelve
spellings below stop being twelve cases. What this file pins is that they are
ONE case: the same shape, the same verdict, whatever unit token trails the
number and whichever language it is written in.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import parse_figures_block, scan_figures


def _shapes(text: str) -> list[str]:
    """The shape of every number in ``text``, in document order."""
    return [figure.shape for figure in scan_figures(text, parse_figures_block(text))]


def _verdict(text: str) -> bool:
    """Validate a fundamentals answer against a run with no market evidence."""
    ledger = GroundingLedger(
        run_dir=pathlib.Path(tempfile.mkdtemp()),
        user_message="compare the gross margins",
    )
    return ledger.validate_final_answer(text).valid


_SPELLINGS = [
    "gross margin ~3.6pp below Penumbra",
    "gross margin 3.6 pp below Penumbra",
    "operating margin improved 2.4ppt year over year",
    "operating margin improved 12.5 ppts sequentially",
    "spread widened 4.5bps after the print",
    "yield moved 7.0bp on the day",
    "margin fell -1.8pp sequentially",
    "margin rose +0.9pp sequentially",
    "毛利率下降 3.6 个百分点",
    "毛利率下降3.6个百分点",
    "同比下降 3.6 百分点",
    "利差扩大 250.0 个基点",
    "毛利率下降 3.6 个百分点后企稳",
]


@pytest.mark.parametrize("text", _SPELLINGS)
def test_every_spelling_is_the_same_measurement_shape(text: str) -> None:
    """A decimal is a decimal, whatever unit token follows it.

    The unit used to decide the verdict, which is why the mask kept growing.
    ``3.6ppm`` was the worst case: the number scan fenced off trailing letters,
    truncated the figure to ``3``, and the same statement was a decimal in
    Chinese and a bare integer in English.
    """
    assert "measured" in _shapes(text), text


def test_the_unit_no_longer_truncates_the_figure() -> None:
    """``3.6ppm`` is 3.6, not 3 — the fence is on digits, not on letters."""
    text = "3.6ppm impurity"
    figures = scan_figures(text, parse_figures_block(text))

    assert [figure.text for figure in figures] == ["3.6"]


@pytest.mark.parametrize("text", _SPELLINGS)
def test_an_undeclared_delta_is_reported_in_every_spelling(text: str) -> None:
    """The lower arm: a figure with no origin is named, not silently masked."""
    assert _verdict(text) is False, text


@pytest.mark.parametrize("text", _SPELLINGS)
def test_a_declared_delta_passes_in_every_spelling(text: str) -> None:
    """The upper arm: one declaration settles it, in either language.

    Without this arm the file is satisfied by a gate that rejects everything,
    which is the failure mode the mask had in the other direction. The source
    is written on the figure's line because the block never reaches the reader.
    """
    figure = next(
        figure.text
        for figure in scan_figures(text, parse_figures_block(text))
        if figure.shape == "measured"
    )
    declared = text + " (2026 Q2 filing)" + (
        "\n\n```figures\n" + f"{figure} | cited | 2026 Q2 filing, margin bridge\n```"
    )

    assert _verdict(declared) is True, text


# ---------------------------------------------------------------------------
# #2107: the percentage-point unit itself, declared the conventional way.
# A CN filing states its moves in 个百分点; the block convention declares the
# bare number, and the gate used to redact the prose figure for lacking a
# matching percent declaration.


_BARE_DECLARED = {
    "bare": "1.13",
    "unit word": "1.13个百分点",
    "percent": "1.13%",
    "pct": "1.13 pct",
}


@pytest.mark.parametrize("spelling", _BARE_DECLARED.values(), ids=_BARE_DECLARED.keys())
def test_every_conventional_declaration_grounded_the_same_delta(spelling: str) -> None:
    """``1.13`` and ``1.13个百分点`` declare the same figure, one verdict (#2107).

    The delta is written in the answer with its unit word glued, as a CN filing
    writes it, and the declaration spells the same figure each way the
    convention allows. All four are ONE case: declared → passes.
    """
    text = "ROE同比增加1.13个百分点 (2026 Q3 filing)。"
    declared = text + "\n\n```figures\n" + f"{spelling} | cited | 2026 Q3 filing, ROE bridge\n```"

    assert _verdict(declared) is True, spelling


def test_a_bare_declaration_does_not_ground_a_plain_percent_figure() -> None:
    """The borrow is one-way: ``37%`` in the prose needs a percent declaration.

    ``1.13`` may ground ``1.13个百分点`` because the unit word carries the
    percent-ness. ``37%`` written with a real percent sign cannot borrow the
    count declaration ``37`` — that is the assertion-vs-fraction distinction
    the contract pins (§2).
    """
    text = "市占率 37%。"
    declared = text + "\n\n```figures\n" + "37 | count | 客户数 | c1\n```"

    assert _verdict(declared) is False, "a count declaration must not ground 37%"


def test_a_declared_percent_range_is_two_endpoints_not_malformed() -> None:
    """``20%-30%`` declares both endpoints; the scan reads no bogus ``-30%`` (#2107).

    A quarterly report's forward guidance is frequently a range. The block
    used to reject the value as malformed and the scan then emitted ``20%``
    and ``-30%`` as two undeclared figures.
    """
    text = "业绩指引：预计年度营收增长 20%-30%。"
    declared = text + "\n\n```figures\n" + "20%-30% | cited | 2026 Q3 filing, guidance\n```"

    block = parse_figures_block(declared)
    figures = scan_figures(text, block)

    assert not block.malformed
    assert [round(item.value, 2) for item in block.declarations] == [20.0, 30.0]
    assert all(figure.sign != "-" for figure in figures if figure.percent)
