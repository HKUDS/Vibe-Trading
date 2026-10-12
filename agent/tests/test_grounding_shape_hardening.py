"""Shape-layer hardening: a number is read the way the reader sees it.

Every smuggle below is a spelling that rendered as a measurement while the
shape rules read it as something unchecked — a zero-width character splitting
"0.888" into two bare integers, a lone "```注```" line fencing off the rest of
the answer, a bare-year exemption covering "$2050". Each rule is pinned from
both sides on the sparse two-bar ledger: the smuggle is refused AND the
legitimate spelling of the same thing still passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from tests.grounding_parameter_helpers import declared_parameter
from src.agent.grounding.figures import Figure, parse_figures_block, scan_figures, strip_figures_block

pytestmark = pytest.mark.unit

SYMBOL = "159516.SZ"
HDR = "159516.SZ（akshare，CNY）最新收盘 0.666 元。"
HDR_ROW = "0.666 | observed | close 2026-09-09 | c1"
LEAD = "159516.SZ（akshare，CNY）"

BACKSLASH = chr(92)
NBSP, NNBSP, FIGURE_SPACE = chr(0x00A0), chr(0x202F), chr(0x2007)
MINUS, EN_DASH = chr(0x2212), chr(0x2013)
FULLWIDTH_STOP, ARABIC_DECIMAL, ARABIC_GROUP = chr(0xFF0E), chr(0x066B), chr(0x066C)
INVISIBLE = (chr(0x200B), chr(0x200C), chr(0x200D), chr(0x2060), chr(0xFEFF))


def _market_payload() -> str:
    """A sparse two-bar ledger: 0.567–1.053, so a probe value is unambiguous."""
    return json.dumps(
        {
            SYMBOL: [
                {"trade_date": "2026-05-06", "open": 1.020, "high": 1.053, "low": 1.001,
                 "close": 1.040, "volume": 123456},
                {"trade_date": "2026-09-09", "open": 0.670, "high": 0.681, "low": 0.567,
                 "close": 0.666, "volume": 234567},
            ],
            "_provenance": {
                SYMBOL: {"source": "akshare", "requested_source": "auto",
                         "detected_source": "akshare", "fallback_used": False,
                         "currency_conversion": "none"}
            },
        }
    )


def _ledger(tmp_path: Path) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析 159516.SZ 并给出买入价")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=_market_payload(),
        call_id="c1",
        success=True,
    )
    return ledger


def _block(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


def _figures(text: str) -> list[Figure]:
    return scan_figures(text, parse_figures_block(text))


def _shapes(text: str) -> dict[str, str]:
    return {figure.text: figure.shape for figure in _figures(text)}


def _values(result) -> list[str]:
    return [issue["value"] for issue in result.issues if issue.get("value") is not None]


# ---------------------------------------------------------------------------
# A1 — numerals are normalized, offsets stay in the original text
# ---------------------------------------------------------------------------


_DISGUISED = [
    *[(f"0{char}.888", f"0{char}.666") for char in INVISIBLE],
    (f"0{FULLWIDTH_STOP}888", f"0{FULLWIDTH_STOP}666"),
    (f"0{ARABIC_DECIMAL}888", f"0{ARABIC_DECIMAL}666"),
    (f"0{BACKSLASH}.888", f"0{BACKSLASH}.666"),
    ("0&#46;888", "0&#46;666"),
    ("0&#x2e;888", "0&#X2E;666"),
    ("0&period;888", "0&period;666"),
]


@pytest.mark.parametrize(("smuggled", "legitimate"), _DISGUISED)
def test_a_disguised_decimal_is_checked_as_the_decimal_it_renders(
    tmp_path: Path, smuggled: str, legitimate: str
) -> None:
    """Split by an invisible or escaped separator, "0.888" used to be two bare integers."""
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(f"{LEAD}最新收盘 {smuggled}。")
    passed = ledger.validate_final_answer(f"{LEAD}最新收盘 {legitimate}。")

    assert _values(refused) == [smuggled]
    assert passed.valid, passed.issues


def test_every_figure_keeps_its_original_spelling_and_offsets() -> None:
    text = f"A 0{chr(0x200B)}.888 B 5{BACKSLASH}% C 0&#46;5 D 52{NBSP}% E CNY0.888"

    figures = _figures(text)

    assert [figure.text for figure in figures] == [
        f"0{chr(0x200B)}.888", f"5{BACKSLASH}%", "0&#46;5", f"52{NBSP}%", "0.888"
    ]
    assert all(text[figure.start : figure.end] == figure.text for figure in figures)
    assert [figure.digits for figure in figures] == ["0.888", "5", "0.5", "52", "0.888"]
    assert text[slice(*figures[-1].extent)] == "CNY0.888"


@pytest.mark.parametrize("space", [NBSP, NNBSP, FIGURE_SPACE])
def test_a_no_break_space_before_the_percent_sign_is_still_a_percent(
    tmp_path: Path, space: str
) -> None:
    ledger = _ledger(tmp_path)
    derived = "37% | derived | (0.666 − 1.053) / 1.053 | c1"

    refused = ledger.validate_final_answer(f"{HDR} 较高点回撤 52{space}%。")
    passed = ledger.validate_final_answer(
        f"{HDR} 较高点回撤 37{space}%。" + _block(HDR_ROW, derived)
    )

    assert _values(refused) == [f"52{space}%"]
    assert passed.valid, passed.issues


def test_an_arabic_group_separator_keeps_a_grouped_number_whole() -> None:
    assert [figure.value for figure in _figures(f"1{ARABIC_GROUP}234 سهم")] == [1234.0]
    assert [figure.value for figure in _figures("1 234")] == [1.0, 234.0]


def test_a_unicode_minus_is_a_sign_and_an_en_dash_is_a_range() -> None:
    figures = _figures(f"回撤 {MINUS}37%，区间 0.632{EN_DASH}0.636，差 0.632-0.636")

    assert [(figure.value, figure.sign) for figure in figures] == [
        (-37.0, "-"), (0.632, ""), (0.636, ""), (0.632, ""), (0.636, "")
    ]


@pytest.mark.parametrize(("written", "value"), [("5\\%", 5.0), ("12&#37;", 12.0)])
def test_an_escaped_percent_sign_is_a_percent(written: str, value: float) -> None:
    [figure] = _figures(f"回撤 {written.replace(chr(92) + chr(92), BACKSLASH)}")

    assert (figure.percent, figure.value, figure.shape) == (True, value, "measured")


def test_an_iso_code_glued_to_digits_is_a_currency_mark(tmp_path: Path) -> None:
    """The identifier lookbehind used to turn "CNY0.888" into a bare "888"."""
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(f"{LEAD}最新收盘 CNY0.888。")
    passed = ledger.validate_final_answer(f"{LEAD}最新收盘 CNY0.666。")

    assert _values(refused) == ["0.888"]
    assert passed.valid, passed.issues
    assert _shapes("成本 USD100")["100"] == "measured"
    assert _figures("成本 USD100")[0].currency is True
    # A code inside a longer identifier is not a currency mark.
    assert _shapes("见 XUSD100 与 SMA20") == {}


# ---------------------------------------------------------------------------
# A2 — a decimal comma (#1418)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "percent"),
    [
        ("Schlusskurs 0,666 CNY", 0.666, False),
        ("0,5 im Mittel", 0.5, False),
        ("12,5 %", 12.5, True),
        ("3,95 EUR", 3.95, False),
        ("€3,95", 3.95, False),
        ("drawdown −5,13%", -5.13, True),
        ("3,50 美元", 3.5, False),
    ],
)
def test_a_decimal_comma_is_read_as_a_decimal(text: str, value: float, percent: bool) -> None:
    [figure] = _figures(text.replace("−", MINUS))

    assert (figure.value, figure.percent, figure.shape) == (value, percent, "measured")


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("-1,250.00 total", [-1250.0]),
        ("1,234 shares", [1234.0]),
        ("2,237 rows", [2237.0]),
        ("VaR −5,132%", [-5132.0]),
        ("1,50 without a mark", [1.0, 50.0]),
        ("choose 3,95 or 4", [3.0, 95.0, 4.0]),
    ],
)
def test_a_thousands_grouping_stays_grouped(text: str, values: list[float]) -> None:
    assert [figure.value for figure in _figures(text.replace("−", MINUS))] == values


def test_a_true_decimal_comma_close_passes_against_its_print(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    passed = ledger.validate_final_answer(f"{LEAD}Schlusskurs 0,666 CNY.")
    refused = ledger.validate_final_answer(f"{LEAD}Schlusskurs 0,888 CNY.")

    assert passed.valid, passed.issues
    assert _values(refused) == ["0,888"]


# ---------------------------------------------------------------------------
# A3 — fences follow CommonMark
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "measured"),
    [
        ("```注```\n收盘 0.888 元", {"0.888"}),                       # info holds a backtick
        ("```注```\n收盘 0.888 元\n```\n", {"0.888"}),               # ...so it opens nothing
        ("见下：\n```python\nentry = 9.99", {"9.99"}),                # unterminated
        ("    ```python\nentry = 9.99\n    ```", {"9.99"}),         # indented four spaces
        ("   ```python\nentry = 9.99\n   ```\n收盘 0.888 元", {"0.888"}),  # three is a fence
        ("````python\nx = 9.99\n```\ny = 1.5\n````\n收盘 0.888 元", {"0.888"}),  # short closer
        ("~~~python\nx = 9.99\n```\ny = 1.5\n~~~\n收盘 0.888 元", {"0.888"}),    # other char
        ("```python\nx = 9.99\n```js\ny = 1.5\n```\n收盘 0.888 元", {"0.888"}),  # closer with info
    ],
)
def test_only_a_commonmark_fence_exempts_what_it_holds(text: str, measured: set[str]) -> None:
    shapes = _shapes(text)

    assert {figure for figure, shape in shapes.items() if shape == "measured"} == measured
    assert set(shapes.values()) <= {"measured", "exempt"}


def test_a_stray_opener_cannot_swallow_the_declaration_block(tmp_path: Path) -> None:
    """A stray "```python" used to pair with "```figures" and leave the block in the answer."""
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(
        "```python\n" + HDR + " 建议买入价 0.888 元。" + _block(HDR_ROW)
    )
    passed = ledger.validate_final_answer("```python\n" + HDR + _block(HDR_ROW))

    assert _values(refused) == ["0.888"]
    assert passed.valid, passed.issues
    assert passed.released_text == "```python\n" + HDR
    assert "observed" not in refused.released_text


def test_a_figures_fence_quoted_inside_a_longer_fence_declares_nothing() -> None:
    quoted = "````markdown\n```figures\n0.95 | proposed | entry\n```\n````\n" + HDR

    assert parse_figures_block(quoted).present is False
    assert [d.value for d in parse_figures_block(quoted + _block(HDR_ROW)).declarations] == [0.666]


# ---------------------------------------------------------------------------
# A4 — years, compact dates and times
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "figure"),
    [
        ("黄金报价 $2050", "2050"),
        ("成本 1999 元", "1999"),
        ("目标 2050 USDT", "2050"),
        ("涨幅 2020%", "2020%"),
        ("| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | 2050 |", "2050"),
        ("| 批次 | 收盘 |\n|---|---|\n| 20260909 元 | 0.666 |", "20260909"),
    ],
)
def test_a_year_shaped_number_with_a_measurement_mark_is_measured(text: str, figure: str) -> None:
    assert _shapes(text)[figure] == "measured"


@pytest.mark.parametrize(
    ("text", "figure"),
    [
        ("回顾 2024 年的行情", "2024"),
        ("On 2024 levels", "2024"),
        ("| 年份 | 收益率 |\n|---|---|\n| 2024 | 12% |", "2024"),
        ("| 批次 | 收盘 |\n|---|---|\n| 20260909 | 0.666 |", "20260909"),
        ("trade_date 20260909 收盘", "20260909"),
        ("2026.09.09 收盘", "2026.09"),
        ("09:30:00.123 成交", "00.123"),
        ("| 时段 | 收盘 |\n|---|---|\n| 09:30 | 0.666 |", "30"),
    ],
)
def test_dates_years_and_times_without_marks_are_structure(text: str, figure: str) -> None:
    shapes = _shapes(text)

    assert shapes[figure] == "exempt"


@pytest.mark.parametrize(
    ("text", "figure"),
    [
        ("区间 2001.5 - 2002.5", "2001.5"),     # a dotted date needs both dots, unspaced
        ("12:30.5 分位", "30.5"),               # a fraction on minutes is not a time
        ("| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | 20261399 |", "20261399"),  # no month 13
    ],
)
def test_near_dates_are_still_measurements(text: str, figure: str) -> None:
    assert _shapes(text)[figure] == "measured"


def test_a_year_under_a_price_column_is_checked(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(
        HDR + "\n\n| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | 2050 |\n"
    )
    passed = ledger.validate_final_answer(
        HDR + "\n\n| 批次 | 收盘 |\n|---|---|\n| 20260909 | 0.666 |\n\n09:30:00.123 成交。"
    )

    assert _values(refused) == ["2050"]
    assert passed.valid, passed.issues


# ---------------------------------------------------------------------------
# A5 — a table's date / time / symbol column exempts structure only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "cell"),
    [("日期", "0.888"), ("时间", "12.5%"), ("代码", "$3"), ("date", "0,95 EUR")],
)
def test_a_measurement_under_a_structural_column_is_checked(header: str, cell: str) -> None:
    text = f"| {header} | 收盘 |\n|---|---|\n| {cell} | 0.666 |"

    assert _shapes(text)[cell.split(" ")[0].lstrip("$")] == "measured"


@pytest.mark.parametrize(
    ("header", "cell", "figure"),
    [
        ("代码", "159516", "159516"),
        ("日期", "2026.09.09", "2026.09"),
        ("日期", "20260909", "20260909"),
        ("时间", "09:30", "09"),
    ],
)
def test_structure_under_a_structural_column_stays_exempt(header: str, cell: str, figure: str) -> None:
    text = f"| {header} | 收盘 |\n|---|---|\n| {cell} | 0.666 |"

    assert _shapes(text)[figure] == "exempt"


def test_a_price_under_the_date_column_is_refused(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    row = HDR + "\n\n| 日期 | 收盘 |\n|---|---|\n| {} | 0.666 |\n"

    # The price itself is refused; the close beside it loses its date too.
    assert "0.888" in _values(ledger.validate_final_answer(row.format("0.888")))
    # evidence.py reads no dotted date, so the ledger arm uses the ISO spelling;
    # the dotted date's own shape is pinned above.
    passed = ledger.validate_final_answer(row.format("2026-09-09"))
    assert passed.valid, passed.issues


# ---------------------------------------------------------------------------
# A6 — the block parser
# ---------------------------------------------------------------------------


def _parse(*rows: str):
    return parse_figures_block("text" + _block(*rows))


@pytest.mark.parametrize(
    "rows",
    [
        ("value | role | note | ref", "---|---|---|---", "0.666 | observed | close | c1"),
        ("| Value | ROLE | note | ref |", "|:---|---:|:-:|---|", "| 0.666 | observed | close | c1 |"),
    ],
)
def test_a_header_and_a_separator_row_are_skipped(rows: tuple[str, ...]) -> None:
    block = _parse(*rows)

    assert block.malformed == ()
    assert [(d.value, d.role, d.note, d.ref) for d in block.declarations] == [
        (0.666, "observed", "close", "c1")
    ]


@pytest.mark.parametrize("row", ["value | observed | close | c1", "values | role | note", "--- 0.5"])
def test_a_line_that_only_resembles_a_header_is_still_malformed(row: str) -> None:
    assert len(_parse(row).malformed) == 1


def test_an_empty_interior_field_keeps_its_place(tmp_path: Path) -> None:
    """"0.888 | cited |  | c1" used to make "c1" the citation."""
    [declaration] = _parse("0.888 | cited |  | c1").declarations
    assert (declaration.note, declaration.ref) == ("", "c1")
    [trailing] = _parse("0.666 | observed | close |").declarations
    assert (trailing.note, trailing.ref) == ("close", "")

    ledger = _ledger(tmp_path)
    prose = HDR + " Fama-French 2024 论文报告夏普 1.8。"
    refused = ledger.validate_final_answer(prose + _block(HDR_ROW, "1.8 | cited |  | c1"))
    passed = ledger.validate_final_answer(prose + _block(HDR_ROW, "1.8 | cited | Fama-French 2024 | c1"))
    assert [issue["reason"] for issue in refused.issues] == ["citation_without_source"]
    assert passed.valid, passed.issues


@pytest.mark.parametrize(
    ("written", "value", "percent", "canonical"),
    [
        ("HK$320.5", 320.5, False, "320.5"),
        ("182.4 USD", 182.4, False, "182.4"),
        ("0.95 港元", 0.95, False, "0.95"),
        ("¥0.95元", 0.95, False, "0.95"),
        ("100 원", 100.0, False, "100"),
        ("100 KRW", 100.0, False, "100"),
        (f"{MINUS}0.5", -0.5, False, "-0.5"),
        ("0.235M", 0.235, False, "0.235"),
        ("2.4万元", 2.4, False, "2.4"),
        ("37 %", 37.0, True, "37%"),
        ("52pp", 52.0, True, "52%"),
        ("5200bp", 52.0, True, "52.00%"),
        ("4.5 bps", 0.045, True, "0.045%"),
        ("0,666", 0.666, False, "0.666"),
        ("3,95 EUR", 3.95, False, "3.95"),
        ("1,234.50", 1234.5, False, "1234.50"),
    ],
)
def test_a_declared_value_tolerates_its_marks(
    written: str, value: float, percent: bool, canonical: str
) -> None:
    block = _parse(f"{written} | observed | close | c1")

    assert block.malformed == (), written
    [declaration] = block.declarations
    assert (declaration.value, declaration.percent, declaration.value_text) == (
        value, percent, canonical
    )


@pytest.mark.parametrize(
    "written", ["0.95 is entry", "0.95 0.97", "0.95 元/股", "ABCD$3", "3.6ppm", "2026-09-09"]
)
def test_a_declared_value_with_anything_else_is_malformed(written: str) -> None:
    assert len(_parse(f"{written} | proposed | entry").malformed) == 1, written


# ---------------------------------------------------------------------------
# A7 — several blocks
# ---------------------------------------------------------------------------


def test_every_figures_block_declares_and_every_one_is_stripped(tmp_path: Path) -> None:
    first = _block(HDR_ROW, "junk line")
    draft = HDR + first + "\n\n第一档 0.646 元。" + _block("0.646 | derived | 0.666 × 0.97 | c1")

    block = parse_figures_block(draft)
    assert [d.value for d in block.declarations] == [0.666, 0.646]
    assert [raw for _, raw in block.malformed] == ["junk line"]
    assert block.span == (len(HDR) + 2, len(HDR) + len(first))
    assert len(block.spans) == 2

    stripped = strip_figures_block(draft, block)
    assert stripped == HDR + "\n\n第一档 0.646 元。"

    ledger = _ledger(tmp_path)
    passed = ledger.validate_final_answer(HDR + declared_parameter("97%") + _block(HDR_ROW) + "\n\n第一档 0.646 元。" + _block("0.646 | derived | 0.666 × 0.97 | c1"))
    refused = ledger.validate_final_answer(HDR + declared_parameter("97%") + _block(HDR_ROW) + "\n\n第一档 0.700 元。" + _block("0.700 | derived | 0.666 × 0.97 | c1"))
    assert passed.valid, passed.issues
    assert passed.released_text == HDR + "\n\nChosen coefficient: 97%." + "\n\n第一档 0.646 元。"
    assert _values(refused) == ["0.700"]
    assert "```" not in refused.released_text


def test_a_second_figures_opener_ends_an_unclosed_first_block() -> None:
    block = parse_figures_block("t\n\n```figures\n0.666 | observed | close | c1\n```figures\n0.5 | count | n\n```")

    assert [d.value for d in block.declarations] == [0.666, 0.5]
    assert block.malformed == ()


def test_streaming_holds_back_from_the_first_block() -> None:
    lead = "先说结论。"
    text = lead + _block(HDR_ROW) + "\n\n更多。" + _block("3 | count | n")

    assert GroundingLedger.streamable_length(text) == len(lead) + 2
    # A measurement before the block holds the stream earlier still.
    assert GroundingLedger.streamable_length(HDR + _block(HDR_ROW)) == HDR.index("0.666")


# ---------------------------------------------------------------------------
# A8 — glued pp / bp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [("溢价扩大 52pp", 52.0), ("利差 5200bp", 52.0), ("spread 4.5bps wider", 0.045), ("down 3PP", 3.0)],
)
def test_a_glued_point_mark_is_a_measured_percent(text: str, value: float) -> None:
    [figure] = _figures(text)

    assert (figure.shape, figure.percent, figure.value, figure.scale) == ("measured", True, value, 1.0)


@pytest.mark.parametrize("text", ["3.6ppm impurity", "a 52 pp gap", "500bpm tempo", "52pages"])
def test_a_point_mark_must_be_glued_and_whole(text: str) -> None:
    assert not any(figure.percent for figure in _figures(text))


def test_a_basis_point_figure_is_the_percent_it_scales_to(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(HDR + " 据研报，溢价扩大 52pp。")
    as_percent = ledger.validate_final_answer(HDR + " 据研报溢价 5200bp。" + _block(HDR_ROW, "52% | cited | 研报 2026"))
    as_points = ledger.validate_final_answer(HDR + " 据研报溢价扩大 52pp。" + _block(HDR_ROW, "52pp | cited | 研报 2026"))

    assert _values(refused) == ["52pp"]
    assert as_percent.valid, as_percent.issues
    assert as_points.valid, as_points.issues


# ---------------------------------------------------------------------------
# A9 — yen and won
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "shape"), [("100 円", "measured"), ("100円です", "measured"),
                                             ("100 원", "measured"), ("100 回", "bare"), ("100 人", "bare")])
def test_yen_and_won_are_currency_marks(text: str, shape: str) -> None:
    assert _shapes(text)["100"] == shape


# ---------------------------------------------------------------------------
# A10 — the release path
# ---------------------------------------------------------------------------


def test_a_cut_figure_is_also_cut_where_a_code_fence_restates_it(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = (
        HDR + " 建议买入价 2.50 元。\n\n```python\nentry = 2.50\nalso = 2" + BACKSLASH
        + ".50\nstop = 0.60\n```\n" + _block(HDR_ROW, "2.50 | proposed | entry")
    )

    released = ledger.redacted_release(draft, ledger.validate_final_answer(draft))

    assert released is not None
    assert "2.50" not in released and "2" + BACKSLASH + ".50" not in released
    assert "stop = 0.60" in released
    assert "最新收盘 0.666 元" in released
    assert "※ 略去 3 处" in released
    assert ledger.figures_removed == 3


def test_a_malformed_block_is_dropped_and_the_draft_is_cut_as_usual(tmp_path: Path) -> None:
    """An unreadable declaration used to force the canned fallback."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 0.65 元，止损 2.50 元。" + _block(HDR_ROW, "0.65 | proposed | entry", "2.50 is my stop")

    validation = ledger.validate_final_answer(draft)
    assert "figures_block_malformed" in [issue["code"] for issue in validation.issues]
    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "最新收盘 0.666 元" in released
    # Without the block, 0.65 is an observed claim like any other and is cut too.
    assert "0.65" not in released and "2.50" not in released
    assert "figures" not in released and "observed" not in released
    assert "※ 略去 2 处" in released


def test_a_malformed_line_with_nothing_to_cut_releases_the_checked_text(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = HDR + _block(HDR_ROW, "see above")

    released = ledger.redacted_release(draft, ledger.validate_final_answer(draft))

    assert released == HDR


def test_a_malformed_block_does_not_release_what_still_fails(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = "600000.SH 最新收盘 9.99 元。" + _block("9.99 | observed | close", "see above")

    assert ledger.redacted_release(draft, ledger.validate_final_answer(draft)) is None


def test_a_flagged_span_that_is_not_a_located_figure_refuses_release(tmp_path: Path) -> None:
    """The cut anchors on a figure the scan found; any other span fails closed."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 2.50 元。"
    validation = ledger.validate_final_answer(draft)
    [issue] = validation.issues
    shifted = dict(issue, span=[issue["span"][0] - 2, issue["span"][1]])

    assert ledger.redacted_release(draft, validation) is not None
    assert ledger.redacted_release(draft, type(validation)(False, [shifted])) is None
    # A locatable issue beside it does not carry the unlocatable one through.
    assert ledger.redacted_release(draft, type(validation)(False, [issue, shifted])) is None


def test_an_undeclared_figure_on_the_last_draft_is_cut_not_fallen_back(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议持有 3.5 个月。" + _block(HDR_ROW)

    validation = ledger.validate_final_answer(draft)
    assert [issue["code"] for issue in validation.issues] == ["figure_undeclared"]
    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "3.5" not in released and "最新收盘 0.666 元" in released
    assert "※ 略去 1 处" in released


# ---------------------------------------------------------------------------
# A11 — the currency-word bound and the ordinal's whitespace
# ---------------------------------------------------------------------------


def test_a_three_character_currency_word_is_money_and_a_four_character_run_is_not(
    tmp_path: Path,
) -> None:
    assert _shapes("报价 100 人民币")["100"] == "measured"
    assert _shapes("报价 100 人民币元宵")["100"] == "bare"

    ledger = _ledger(tmp_path)
    draft = HDR + " 另报价 100 人民币。"
    released = ledger.redacted_release(draft, ledger.validate_final_answer(draft))
    assert released is not None
    assert "另报价（略※）。" in released and "人民币" not in released


def test_a_line_opening_with_a_figure_is_not_an_ordinal(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    refused = ledger.validate_final_answer(LEAD + "\n1.171 元是收盘价")
    passed = ledger.validate_final_answer(LEAD + "\n0.666 元是收盘价\n1. 第一条")

    assert _values(refused) == ["1.171"]
    assert passed.valid, passed.issues


def test_an_ordinal_needs_the_space_after_its_punctuation() -> None:
    """A row number glued to the pipe is a table cell, like "| 1 |" — not a list marker."""
    table = "| 序号 | 收盘 |\n|---|---|\n{}\n"

    assert _shapes(table.format("| 1 | 0.666 |"))["1"] == "measured"
    assert _shapes(table.format("1.| 0.666 |"))["1"] == "measured"
    assert _shapes("1. 第一条")["1"] == "exempt"


def _measured_values(text: str) -> list[float]:
    return [f.value for f in scan_figures(text, parse_figures_block(text)) if f.shape != "exempt"]


def test_a_decimal_comma_document_reads_three_digit_fractions_as_decimals() -> None:
    """#1418: "−5,132%" beside "1,57%" is −5.132%, and "2,237" is 2.237."""
    values = _measured_values("VaR 95%: 1,57%. Drawdown máximo −5,132%. Ratio 2,237 EUR.")

    assert -5.132 in values and 2.237 in values and 1.57 in values
    assert -5132.0 not in values and 2237.0 not in values


@pytest.mark.parametrize(
    ("text", "grouped"),
    [
        ("Revenue 2,237 million, down 1,5% on 1,234,567 units.", 2237.0),  # a grouping anywhere wins
        ("Close 2,237.50 USD, volume 1,500 USD.", 1500.0),                 # comma-and-dot is grouping
        ("Revenue 2,237 million.", 2237.0),                                 # no decimal-comma evidence
    ],
)
def test_a_grouping_document_keeps_its_thousands(text: str, grouped: float) -> None:
    assert grouped in _measured_values(text)
