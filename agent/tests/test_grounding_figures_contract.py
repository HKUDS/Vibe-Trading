"""The figures-block contract: parsing, shape, roles, and what is released.

This is the contract the word catalogue was replaced with. The catalogue tried
to infer a number's ROLE from the prose around it — price words, target/stop
words, ATH spellings, indicator names, attribution verbs, forecast frames — and
it could never close: the same sentence got different verdicts in its two
translations, and every new phrasing cost either a revision round or a leak.

Three things replace it, and this file pins all three:

* the model DECLARES each figure's role in a fenced ``figures`` block;
* the gate infers only SHAPE — date, symbol, ordinal, measurement, bare
  integer — which is the same in every language;
* the block is stripped before release, so the contract never reaches the user.

Every rule below is tested from both sides. A gate whose tests only assert
rejection cannot see itself closing on everything, and a gate whose tests only
assert acceptance cannot see itself opening on everything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import (
    ROLES,
    parse_figures_block,
    scan_figures,
    strip_figures_block,
)

pytestmark = pytest.mark.unit

SYMBOL = "159516.SZ"


def _market_payload() -> str:
    """A sparse two-bar ledger: 0.567–1.053, so a probe value is unambiguous."""
    return json.dumps(
        {
            SYMBOL: [
                {
                    "trade_date": "2026-05-06",
                    "open": 1.020,
                    "high": 1.053,
                    "low": 1.001,
                    "close": 1.040,
                    "volume": 123456,
                },
                {
                    "trade_date": "2026-09-09",
                    "open": 0.670,
                    "high": 0.681,
                    "low": 0.567,
                    "close": 0.666,
                    "volume": 234567,
                },
            ],
            "_provenance": {
                SYMBOL: {
                    "source": "akshare",
                    "requested_source": "auto",
                    "detected_source": "akshare",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        }
    )


def _ledger(tmp_path: Path, *, message: str = "分析 159516.SZ 并给出买入价") -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=_market_payload(),
        call_id="c1",
        success=True,
    )
    return ledger


HDR = "159516.SZ（akshare，CNY）最新收盘 0.666 元。"

HDR_ROW = "0.666 | observed | close 2026-09-09 | c1"


def _block(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


# ---------------------------------------------------------------------------
# §2 — parsing the block
# ---------------------------------------------------------------------------


def test_the_block_parses_the_spec_example() -> None:
    """Every role, every optional field, exactly as §2 writes it."""
    block = parse_figures_block(
        "answer text\n\n```figures\n"
        "0.666 | observed | 159516.SZ close 2026-09-09 | c1\n"
        "0.646 | derived  | 0.666 × 0.97 | c1\n"
        "37%   | derived  | (0.666 − 1.053) / 1.053 | c1\n"
        "0.95  | proposed | entry\n"
        "1.8   | cited    | 论文 Sharpe\n"
        "3     | count    | 月\n"
        "```"
    )

    assert block.present is True
    assert block.malformed == ()
    assert [d.role for d in block.declarations] == [
        "observed", "derived", "derived", "proposed", "cited", "count"
    ]
    assert [d.value for d in block.declarations] == [0.666, 0.646, 37.0, 0.95, 1.8, 3.0]
    assert [d.percent for d in block.declarations] == [
        False, False, True, False, False, False
    ]
    assert block.declarations[3].note == "entry"
    assert block.declarations[3].ref == ""
    assert block.declarations[0].ref == "c1"


@pytest.mark.parametrize(
    "line",
    [
        "0.666 ｜ observed ｜ close ｜ c1",          # full-width pipes
        "0.666|observed|close|c1",                    # no spacing at all
        "  0.666   |   observed   |   close  ",       # run-on spacing, no ref
        "0.666 | OBSERVED | close | c1",              # role case
        "￥0.666 | observed | close | c1",            # currency mark on the value
        "1,234.50 | observed | close | c1",           # grouped thousands
        "0.235M | observed | volume | c1",            # magnitude mark on the value
    ],
)
def test_the_parser_is_lenient_about_form(line: str) -> None:
    """§2: full-width pipes, run-on spacing and a missing ref are all accepted."""
    block = parse_figures_block(f"text\n\n```figures\n{line}\n```")

    assert block.malformed == (), line
    assert len(block.declarations) == 1, line
    assert block.declarations[0].role == "observed", line


@pytest.mark.parametrize(
    "line",
    [
        "this is not a declaration",       # no pipes at all
        "0.666",                            # value with no role
        "0.666 | observado | close | c1",  # role outside the five
        "close | observed | c1",           # first field is not a number
        "| observed | close | c1",         # empty value
    ],
)
def test_a_line_that_cannot_be_read_is_reported_not_skipped(line: str) -> None:
    """A declaration the gate skipped is a figure the gate never checked."""
    block = parse_figures_block(f"text\n\n```figures\n{line}\n```")

    assert block.declarations == (), line
    assert len(block.malformed) == 1, line


def test_a_malformed_line_fails_the_draft(tmp_path: Path) -> None:
    """It reaches the verdict, with the offending text in the message."""
    result = _ledger(tmp_path).validate_final_answer(
        HDR + _block(HDR_ROW, "0.95 is my entry")
    )

    assert result.valid is False
    assert [issue["code"] for issue in result.issues] == ["figures_block_malformed"]
    assert "0.95 is my entry" in result.issues[0]["message"]


def test_the_last_block_wins_and_earlier_fences_are_code() -> None:
    """A draft may show code; only the trailing ``figures`` fence declares."""
    block = parse_figures_block(
        "```python\nprice = 9.99\n```\n\n"
        "```figures\n0.666 | observed | close | c1\n```"
    )

    assert [d.value for d in block.declarations] == [0.666]


def test_an_unterminated_block_still_parses() -> None:
    """A truncated answer must not silently un-declare its own figures."""
    block = parse_figures_block("text\n\n```figures\n0.666 | observed | close | c1")

    assert [d.value for d in block.declarations] == [0.666]


def test_a_declaration_matches_by_value_at_written_precision() -> None:
    """§2: ``37%`` and ``37 %`` are one assertion; ``37%`` and ``0.37`` are not."""
    block = parse_figures_block("t\n\n```figures\n37 % | derived | (a-b)/b | c1\n```")

    assert block.match(37.0, True) is not None
    assert block.match(0.37, False) is None
    assert block.match(37.0, False) is None
    assert block.match(36.9, True) is None


def test_every_role_in_the_contract_is_accepted() -> None:
    """The five roles are the contract; nothing else parses."""
    for role in ROLES:
        block = parse_figures_block(f"t\n\n```figures\n1.5 | {role} | note | c1\n```")
        assert block.declarations[0].role == role
    assert parse_figures_block("t\n\n```figures\n1.5 | guess | n | c1\n```").malformed


# ---------------------------------------------------------------------------
# §2 — stripping
# ---------------------------------------------------------------------------


def test_the_block_is_stripped_from_the_released_text(tmp_path: Path) -> None:
    """The contract is between the model and the gate; the user never sees it."""
    answer = HDR + _block(HDR_ROW)

    result = _ledger(tmp_path).validate_final_answer(answer)

    assert result.valid is True, result.issues
    assert result.released_text == HDR
    assert "figures" not in result.released_text
    assert "observed" not in result.released_text


def test_stripping_a_draft_without_a_block_changes_nothing(tmp_path: Path) -> None:
    result = _ledger(tmp_path).validate_final_answer(HDR)

    assert result.released_text == HDR


def test_the_raw_block_is_kept_in_the_artifact(tmp_path: Path) -> None:
    """Stripped from the answer, preserved in the audit record."""
    ledger = _ledger(tmp_path)
    ledger.validate_final_answer(HDR + _block(HDR_ROW))

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )

    assert HDR_ROW in artifact["validations"][0]["figures_block"]


def test_strip_is_addressable_on_its_own() -> None:
    text = "line one\n\n```figures\n1.0 | count | n\n```"
    assert strip_figures_block(text, parse_figures_block(text)) == "line one"


# ---------------------------------------------------------------------------
# §3 — the three shapes
# ---------------------------------------------------------------------------


def _shapes(text: str) -> dict[str, str]:
    block = parse_figures_block(text)
    return {figure.text: figure.shape for figure in scan_figures(text, block)}


@pytest.mark.parametrize(
    "text",
    [
        "2026-09-09 的收盘",                    # ISO date
        "2026/09/09 的收盘",                    # slash date
        "2026年9月9日 的收盘",                  # localized date
        "回顾 2024 年的行情",                    # bare year
        "159516.SZ 的走势",                     # symbol digits
        "HK.00700 的走势",                      # prefixed symbol digits
        "1. 第一条结论",                         # ordered-list marker
        "### 6. 关键价位",                      # numbered heading
        "The 2026-09-09 close",                 # ISO date, English prose
        "On 2024 levels",                       # bare year, English prose
        "3. First conclusion",                  # ordered-list marker, English
        "8月17–18日高点",                        # CJK month with a day range (real run)
        "6月初低点，8月中旬平台",                  # CJK month alone (real run)
        "| 次级支撑 | 9月11/14日盘中低点 |",       # CJK month with a day list (real run)
        "| 阻力 | 含义 |\n|---|---|\n| 前高 | 8月17–18日高点 |",  # in a table cell
        "2026-09-11 / 09-14 两次盘中低点",       # zero-padded MM-DD after a full date
        "09-14 收盘",                           # zero-padded MM-DD alone
        "2026-10-11 / 10-14 两次盘中低点",       # unpadded MM-DD opened by a full date
        "| 价位 | 含义 |\n|---|---|\n| 近端支撑 | 2026-09-11 / 09-14 盘中低点 |",  # real run
    ],
)
def test_structural_shapes_need_no_declaration(text: str) -> None:
    """§3: a date, a year, a symbol's digits and an ordinal are structure."""
    assert set(_shapes(text).values()) == {"exempt"}, text


@pytest.mark.parametrize(
    "text",
    [
        "收盘 0.666 元",                          # decimal
        "回撤 37%",                               # percent
        "回撤 37 ％",                             # full-width percent
        "成本 820 CNY",                           # integer + ISO code
        "entry at $100",                          # integer + currency symbol
        "报价 100 元",                            # integer + CJK currency
        "| 收盘 |\n|---|\n| 0.666 |",             # table cell
        "The close was 0.666",                    # decimal, English prose
        "Down 37% from the high",                 # percent, English prose
        "revenue of 400.5 billion",               # decimal, English prose
        "| 区间 |\n|---|\n| 17–18 |",              # a range with no month mark is checked
        "| 区间 |\n|---|\n| 11-12 |",            # unpadded MM-DD shape may be a price range
        "| 日期 | 区间 |\n|---|---|\n| 2026-09-09 | 11-12 |",  # a date in ANOTHER cell
    ],
)
def test_measurement_shapes_must_be_declared(text: str) -> None:
    """§3: a decimal, a percent, a currency mark or a table cell is a claim."""
    assert "measured" in _shapes(text).values(), text


@pytest.mark.parametrize(
    "text",
    [
        "观察窗口 20 日",                          # lookback window
        "持有 3 个月",                             # horizon
        "买入 100 股",                             # lot size
        "第 206 行提到",                           # line citation
        "CONFIDENCE: 6",                          # conviction score
        "折算比例 6:1",                            # ratio
        "20/50/200-day 均线",                      # window enumeration
        "共 16 个交易日",                          # count noun
        "a 52-week high",                          # window, English prose
        "over 3 sessions",                         # horizon, English prose
        "a 6M holding horizon",                    # magnitude mark does not make a measurement
    ],
)
def test_bare_integers_are_not_checked(text: str) -> None:
    """§3: a plain integer is a count, a window or an index, never a price.

    Each of these had a mask of its own — a labelled-score mask, a
    quantity-with-unit mask, a line-reference mask, a ratio mask — and each
    mask was a list that had to be complete. None of them is needed: none of
    these numbers is measurement-shaped.
    """
    assert "measured" not in _shapes(text).values(), text


def test_a_bare_integer_inside_a_table_cell_is_still_a_measurement(
    tmp_path: Path,
) -> None:
    """A table row is a quotation, whatever precision its cells are written at.

    Outside a table an integer is a count and is not checked; inside one it is
    a value the report is presenting as data, so it is. The pair below is the
    whole rule: the same "300" passes in prose and is checked in a cell.
    """
    prose = "159516.SZ（akshare，CNY）指数覆盖 300 只成分股。"
    cell = "| 代码 | 收盘 |\n|---|---|\n| 159516.SZ | 300 |\n"

    assert _shapes(prose)["300"] == "bare"
    assert _shapes(cell)["300"] == "measured"
    assert _ledger(tmp_path).validate_final_answer(prose).valid is True
    rejected = _ledger(tmp_path).validate_final_answer(
        "159516.SZ（akshare，CNY）\n\n" + cell
    )
    assert [issue["value"] for issue in rejected.issues] == ["300"]


def test_a_market_data_rows_own_volume_is_evidence(tmp_path: Path) -> None:
    """A row is one observation, and its volume is part of that row.

    Restricting the pool to price fields alone rejected every report that
    quoted the turnover beside the close — a figure the same tool call
    returned. The pool is the row, not the whole ledger: a number no call
    produced is still refused.
    """
    ledger = _ledger(tmp_path)
    row = "| 日期 | 收盘 | 成交量 |\n|---|---|---|\n| 2026-09-09 | 0.666 | {} |\n"

    quoted = ledger.validate_final_answer(HDR + "\n\n" + row.format("234567"))
    invented = ledger.validate_final_answer(HDR + "\n\n" + row.format("999999"))

    assert quoted.valid is True, quoted.issues
    assert [issue["value"] for issue in invented.issues] == ["999999"]


def test_a_currency_word_is_bounded_so_a_cjk_word_is_not_money() -> None:
    """"3 元宵节后" is not three yuan; "3 美元" is three dollars."""
    assert _shapes("买入 3 美元")["3"] == "measured"
    assert _shapes("3 元宵节后关注")["3"] == "bare"


def _measured(text: str) -> set[str]:
    return {
        figure for figure, shape in _shapes(text).items() if shape == "measured"
    }


def test_a_fenced_code_block_is_not_prose() -> None:
    text = "见下：\n\n```python\nentry = 9.99\n```\n\n" + HDR
    assert _measured(text) == {"0.666"}


def test_a_date_column_and_a_symbol_column_are_exempt_inside_a_table() -> None:
    """A table declares its own columns; its date is not a measurement."""
    text = "| 日期 | 代码 | 收盘 |\n|---|---|---|\n| 2026-09-09 | 159516.SZ | 0.666 |"
    assert _measured(text) == {"0.666"}


# ---------------------------------------------------------------------------
# §4 — the five roles, both sides each
# ---------------------------------------------------------------------------


def test_observed_passes_on_evidence_and_fails_off_it(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    grounded = ledger.validate_final_answer(HDR + _block(HDR_ROW))
    invented = ledger.validate_final_answer(
        "159516.SZ（akshare，CNY）最新收盘 0.888 元。"
        + _block("0.888 | observed | close | c1")
    )

    assert grounded.valid is True, grounded.issues
    assert [issue["reason"] for issue in invented.issues] == ["not_in_referenced_call"]


def test_observed_with_a_ref_is_scoped_to_that_call(tmp_path: Path) -> None:
    """A ref is the tightest scoping there is, and it cuts both ways."""
    ledger = _ledger(tmp_path)
    ledger.ingest_tool_result(
        tool_name="get_fundamentals",
        arguments={"symbol": SYMBOL},
        result=json.dumps({"ok": True, "data": {"pe_ttm": 18.4}}),
        call_id="c2",
        success=True,
    )

    right_call = ledger.validate_final_answer(
        HDR + " 市盈率 18.4。" + _block(HDR_ROW, "18.4 | observed | pe_ttm | c2")
    )
    wrong_call = ledger.validate_final_answer(
        HDR + " 市盈率 18.4。" + _block(HDR_ROW, "18.4 | observed | pe_ttm | c1")
    )

    assert right_call.valid is True, right_call.issues
    assert wrong_call.valid is False


def test_derived_passes_on_its_own_arithmetic_and_fails_without_it(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)

    correct = ledger.validate_final_answer(
        HDR + " 第一档 0.646 元。" + _block(HDR_ROW, "0.646 | derived | 0.666 × 0.97 | c1")
    )
    wrong_result = ledger.validate_final_answer(
        HDR + " 第一档 0.700 元。" + _block(HDR_ROW, "0.700 | derived | 0.666 × 0.97 | c1")
    )
    unanchored = ledger.validate_final_answer(
        HDR + " 第一档 0.646 元。" + _block(HDR_ROW, "0.646 | derived | 0.500 × 1.292 | c1")
    )

    assert correct.valid is True, correct.issues
    assert [i["reason"] for i in wrong_result.issues] == ["derivation_result_mismatch"]
    assert [i["reason"] for i in unanchored.issues] == ["formula_not_anchored"]


def test_derived_covers_only_the_value_it_declares(tmp_path: Path) -> None:
    """§4: the exemption is the declaration, and a declaration names one value."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + " 第一档 0.646 元，第二档 0.400 元。"
        + _block(HDR_ROW, "0.646 | derived | 0.666 × 0.97 | c1", "0.400 | proposed | 第二档")
    )

    assert [issue["value"] for issue in result.issues] == ["0.400"]


def test_proposed_passes_inside_the_observed_range_and_fails_outside_it(
    tmp_path: Path,
) -> None:
    """§1 decision 2, with the spec's own two numbers.

    0.65 is inside 159516.SZ's observed 0.567–1.053 and passes; 0.881 against
    a session that only observed 1.110–1.180 does not.
    """
    ledger = _ledger(tmp_path)

    inside = ledger.validate_final_answer(
        HDR + " 建议买入价 0.65 元。" + _block(HDR_ROW, "0.65 | proposed | entry")
    )
    outside = ledger.validate_final_answer(
        HDR + " 建议买入价 2.50 元。" + _block(HDR_ROW, "2.50 | proposed | entry")
    )

    assert inside.valid is True, inside.issues
    assert [i["reason"] for i in outside.issues] == ["outside_observed_range"]


def test_proposed_outside_the_range_passes_with_a_derivation(tmp_path: Path) -> None:
    """The other half of decision 2: derived OR in range, not derived AND."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + " 目标价 1.332 元。" + _block(HDR_ROW, "1.332 | proposed | 0.666 × 2 | c1")
    )

    assert result.valid is True, result.issues


def test_cited_needs_a_source_and_may_not_pose_as_a_print(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    with_source = ledger.validate_final_answer(
        HDR + " Fama-French（2024）论文报告夏普 1.8。"
        + _block(HDR_ROW, "1.8 | cited | Fama-French 2024 table 3")
    )
    without_source = ledger.validate_final_answer(
        HDR + " 论文报告夏普 1.8。" + _block(HDR_ROW, "1.8 | cited | ")
    )
    posing_as_a_close = ledger.validate_final_answer(
        HDR + "\n\n| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | 1.8 |\n"
        + _block(HDR_ROW, "1.8 | cited | 论文")
    )

    assert with_source.valid is True, with_source.issues
    assert [i["reason"] for i in without_source.issues] == ["citation_without_source"]
    assert [i["reason"] for i in posing_as_a_close.issues] == ["cited_as_observed"]


def test_count_is_not_checked_but_is_still_declared(tmp_path: Path) -> None:
    """``count`` covers a plain integer, and using it is a statement on the record.

    A plain integer is measurement-shaped only inside a table. A count with a
    decimal point, percent or currency mark is checked as observed instead
    (``test_grounding_role_hardening``).
    """
    ledger = _ledger(tmp_path)
    table = "\n\n| 持有期（月） |\n|---|\n| 3 |\n"

    declared = ledger.validate_final_answer(HDR + table + _block(HDR_ROW, "3 | count | 月"))
    undeclared = ledger.validate_final_answer(HDR + table + _block(HDR_ROW))

    assert declared.valid is True, declared.issues
    assert [issue["code"] for issue in undeclared.issues] == ["figure_undeclared"]


# ---------------------------------------------------------------------------
# §4 — undeclared mode
# ---------------------------------------------------------------------------


def test_undeclared_mode_validates_measurements_as_observed(tmp_path: Path) -> None:
    """§1 decision 1: no block means every measurement is an observed assertion."""
    ledger = _ledger(tmp_path)

    correct = ledger.validate_final_answer(HDR)
    invented = ledger.validate_final_answer("159516.SZ（akshare，CNY）最新收盘 0.888 元。")

    assert correct.valid is True, correct.issues
    assert [issue["code"] for issue in invented.issues] == ["numeric_claim_conflict"]


def test_undeclared_mode_does_not_guess_proposed_or_derived(tmp_path: Path) -> None:
    """§4: it names the figures to declare instead of inventing a role for them."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(HDR + " 建议买入价 0.646 元（0.666 × 0.97）。")

    assert result.valid is False
    assert {issue["role"] for issue in result.issues} == {"observed"}
    # The formula written in the prose grounds nothing: its result and its
    # multiplier are both undeclared measurements, and the gate names both.
    assert [issue["value"] for issue in result.issues] == ["0.646", "0.97"]


def test_the_correction_prompt_names_each_figure_and_its_reason(
    tmp_path: Path,
) -> None:
    """§6: the feedback is per number, not a restatement of the policy.

    Three things per figure — what was written, what was declared, what the
    evidence says — plus the three fixes stated once.
    """
    ledger = _ledger(tmp_path)
    validation = ledger.validate_final_answer(
        HDR + " 建议买入价 2.50 元。" + _block(HDR_ROW, "2.50 | proposed | entry")
    )

    prompt = ledger.correction_prompt(validation)
    line = next(row for row in prompt.splitlines() if row.startswith("- 2.50"))

    assert "declared proposed" in line
    assert "0.567" in line and "1.053" in line
    # The nearest values are the symbol's closes, not every field of every bar.
    assert "nearest observed 1.04, 0.666" in line
    assert "figures" in prompt
    assert "DECLARE" in prompt and "REWRITE" in prompt and "REMOVE" in prompt


def test_a_value_is_called_repeated_only_from_its_second_rejection(
    tmp_path: Path,
) -> None:
    """The current draft is not its own predecessor.

    Comparing against every recorded validation, the current one included,
    told the model on its FIRST rejection that the figure had been refused
    "repeatedly", which is false and trains it to ignore the line.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 2.50 元。" + _block(HDR_ROW, "2.50 | proposed | entry")

    first = ledger.correction_prompt(ledger.validate_final_answer(draft))
    second = ledger.correction_prompt(ledger.validate_final_answer(draft))

    assert "more than one draft" not in first
    assert "more than one draft: 2.50." in second


def test_a_derived_percent_is_corrected_in_its_own_units(tmp_path: Path) -> None:
    """A model that wrote "12%" is told what its formula gives in percent."""
    ledger = _ledger(tmp_path)
    validation = ledger.validate_final_answer(
        HDR
        + " 较 5 月高点回撤 12%。"
        + _block(HDR_ROW, "12% | derived | (0.666 − 1.053) / 1.053 | c1")
    )

    prompt = ledger.correction_prompt(validation)
    line = next(row for row in prompt.splitlines() if row.startswith("- 12"))

    assert "declared derived" in line
    assert "evaluates to -36.7521%" in line
    assert "-0.36" not in prompt


# ---------------------------------------------------------------------------
# The property the whole refactor exists for
# ---------------------------------------------------------------------------


def test_the_verdict_does_not_depend_on_the_words_around_the_figure(
    tmp_path: Path,
) -> None:
    """One figure, one declaration, twelve sentences, one verdict.

    Every sentence below used to route through a different branch of the word
    catalogue — a price word, a level word, a target word, an indicator name, a
    citation subject, a forecast frame — and the branch decided the verdict.
    """
    sentences = [
        "收盘 0.666 元。", "现价 0.666 元。", "目标位 0.666 元。", "支撑位 0.666 元。",
        "SMA20 位于 0.666 元。", "预计 0.666 元。", "论文称 0.666 元。", "0.666 元。",
        "The close was 0.666.", "Target 0.666.", "Support at 0.666.",
        "It last traded at 0.666.",
    ]
    ledger = _ledger(tmp_path)

    verdicts = {
        sentence: ledger.validate_final_answer(
            "159516.SZ（akshare，CNY）" + sentence + _block(HDR_ROW)
        ).valid
        for sentence in sentences
    }

    assert set(verdicts.values()) == {True}, verdicts


def test_a_fabricated_figure_is_refused_under_all_the_same_words(
    tmp_path: Path,
) -> None:
    """The other side of the same property, so it is not satisfied by "accept"."""
    sentences = [
        "收盘 0.888 元。", "现价 0.888 元。", "目标位 0.888 元。", "支撑位 0.888 元。",
        "SMA20 位于 0.888 元。", "论文称 0.888 元。", "0.888 元。",
        "The close was 0.888.", "Support at 0.888.", "It last traded at 0.888.",
    ]
    ledger = _ledger(tmp_path)

    verdicts = {
        sentence: ledger.validate_final_answer(
            "159516.SZ（akshare，CNY）" + sentence
            + _block("0.888 | observed | close | c1")
        ).valid
        for sentence in sentences
    }

    assert set(verdicts.values()) == {False}, verdicts


# ---------------------------------------------------------------------------
# The prompt's own examples, and streaming
# ---------------------------------------------------------------------------


def _prompt_blocks() -> list[str]:
    from src.agent.context import _SYSTEM_PROMPT

    return [
        "```figures" + chunk.split("```")[0] + "```"
        for chunk in _SYSTEM_PROMPT.split("```figures")[1:]
    ]


def test_every_figures_example_in_the_system_prompt_parses() -> None:
    """A malformed example teaches every run to write a malformed block."""
    blocks = [parse_figures_block("answer\n\n" + raw) for raw in _prompt_blocks()]

    assert len(blocks) == 2
    assert all(block.malformed == () for block in blocks)
    assert {d.role for block in blocks for d in block.declarations} == set(ROLES)


def test_the_chinese_prompt_example_passes_the_gate_it_describes(tmp_path: Path) -> None:
    """The example sits on the same two bars this module probes with."""
    ledger = _ledger(tmp_path)
    prose = (
        "159516.SZ（akshare，CNY）最新收盘 0.666 元，第一档 0.646 元，"
        "较 5 月高点回撤 37%，买入参考 0.62 元。"
    )

    result = ledger.validate_final_answer(prose + "\n\n" + _prompt_blocks()[0])

    assert result.valid, result.issues
    assert result.released_text == prose


@pytest.mark.parametrize(
    ("text", "safe"),
    [
        ("答案。", len("答案。")),
        ("答案。\n\n```figures\n0.666 | observed", len("答案。\n\n")),
        ("答案。\n\n``", len("答案。\n\n")),
        ("答案。\n\n```fig", len("答案。\n\n")),
        ("答案。\n```python\nx = 1\n", len("答案。\n```python\nx = 1\n")),
        ("收盘 0.666 元。", len("收盘 ")),            # an unchecked measurement waits
        ("复盘 3", len("复盘 ")),                     # a number still being written waits
        ("复盘 3 次。", len("复盘 3 次。")),          # a finished bare integer streams
    ],
)
def test_streaming_holds_back_the_figures_fence_and_nothing_else(text: str, safe: int) -> None:
    assert GroundingLedger.streamable_length(text) == safe


def test_a_magnitude_mark_scales_the_comparison_not_the_shape(tmp_path: Path) -> None:
    """A real run quoted volume as "24.6M" and had every one cut.

    The row's volume is 234567. "0.235M" and "23.46万" are that print; "0.300M"
    is not, and is refused like any other invented figure.
    """
    ledger = _ledger(tmp_path)

    in_millions = ledger.validate_final_answer(
        HDR + " 成交量 0.235M 手。" + _block(HDR_ROW, "0.235M | observed | volume 2026-09-09 | 159516.SZ")
    )
    in_wan = ledger.validate_final_answer(
        HDR + " 成交量 23.46万 手。" + _block(HDR_ROW, "23.46 | observed | volume 2026-09-09 | c1")
    )
    invented = ledger.validate_final_answer(
        HDR + " 成交量 0.300M 手。" + _block(HDR_ROW, "0.300M | observed | volume | 159516.SZ")
    )

    assert in_millions.valid, in_millions.issues
    assert in_wan.valid, in_wan.issues
    assert [issue["value"] for issue in invented.issues] == ["0.300"]


def test_a_cut_figure_takes_its_magnitude_mark_with_it(tmp_path: Path) -> None:
    """A real release read "(omitted※)M → (omitted※)M" before this."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 成交量 0.300M 手。"

    released = ledger.redacted_release(draft, ledger.validate_final_answer(draft))

    assert released is not None
    assert "0.300" not in released
    assert "M" not in released


@pytest.mark.parametrize(
    ("text", "end", "expected"),
    [
        ("24.6M lots", 4, (1e6, 5)),
        ("2.4万手", 3, (1e4, 4)),
        ("5MB of data", 1, (1.0, 1)),
        ("3 months", 1, (1.0, 1)),
    ],
)
def test_a_magnitude_mark_is_a_glued_symbol_not_a_word(
    text: str, end: int, expected: tuple[float, int]
) -> None:
    from src.agent.grounding.figures import magnitude_suffix

    assert magnitude_suffix(text, end) == expected


def test_an_untagged_fence_is_prose_and_a_tagged_one_is_code() -> None:
    """A trading plan set off in a bare fence was released unchecked."""
    untagged = "交易计划：\n```\n入场 0.881\n止损 0.800\n```"
    tagged = "代码：\n```python\nentry = 0.881\n```"

    measured = {f.text for f in scan_figures(untagged, parse_figures_block(untagged)) if f.shape == "measured"}

    assert measured == {"0.881", "0.800"}
    assert not [f for f in scan_figures(tagged, parse_figures_block(tagged)) if f.shape == "measured"]


# ---------------------------------------------------------------------------
# #1471 — a table's row numbers and the words in its cells are not measurements
# ---------------------------------------------------------------------------

_RANKED = (
    "| # | 代码 | 市盈率 |\n|---|---|---|\n"
    "| 1 | 159516.SZ | 45 |\n| 2 | 159516.SZ | 38 |\n| 3 | 159516.SZ | 52 |\n"
)


def test_a_column_that_numbers_its_rows_is_structure() -> None:
    """1, 2, 3 down a column is the table's index; the metric beside it is still checked."""
    shapes = {figure.text: figure.shape for figure in scan_figures(_RANKED, parse_figures_block(_RANKED))}

    assert [shapes[number] for number in ("1", "2", "3")] == ["exempt"] * 3
    assert [shapes[metric] for metric in ("45", "38", "52")] == ["measured"] * 3


@pytest.mark.parametrize(
    "table",
    [
        "| 序号 | 值 |\n|---|---|\n| 1. | 45 |\n| 2. | 38 |\n",          # numbered with a dot
        "| 序号 | 值 |\n|---|---|\n| 1) | 45 |\n| — | 40 |\n| 2) | 38 |\n",  # a row without a number
        "| 值 | 名次 |\n|---|---|\n| 45 | 1 |\n| 38 | 2 |\n",              # the index need not be first
    ],
)
def test_an_index_column_is_recognised_by_its_sequence(table: str) -> None:
    measured = {f.text for f in scan_figures(table, parse_figures_block(table)) if f.shape == "measured"}
    assert measured <= {"45", "40", "38"} and {"45", "38"} <= measured


@pytest.mark.parametrize(
    ("table", "still_measured"),
    [
        ("| # | 值 |\n|---|---|\n| 1 | 45 |\n", {"1", "45"}),                       # one row proves no sequence
        ("| 手数 | 值 |\n|---|---|\n| 1 | 45 |\n| 2 | 38 |\n| 4 | 52 |\n", {"1", "2", "4"}),   # not consecutive
        ("| 手数 | 值 |\n|---|---|\n| 2 | 45 |\n| 3 | 38 |\n", {"2", "3"}),          # does not start at 1
        ("| 手数 | 值 |\n|---|---|\n| 3 | 45 |\n| 2 | 38 |\n| 1 | 52 |\n", {"3", "2", "1"}),   # descending
        ("| 收盘 | 值 |\n|---|---|\n| 1 | 45 |\n| 2 | 38 |\n", {"1", "2"}),          # a price column is never an index
    ],
)
def test_a_column_that_is_not_a_plain_sequence_is_still_checked(table: str, still_measured: set[str]) -> None:
    measured = {f.text for f in scan_figures(table, parse_figures_block(table)) if f.shape == "measured"}
    assert still_measured <= measured


@pytest.mark.parametrize(
    ("cell", "figure", "shape"),
    [
        ("12m mean return", "12", "bare"),          # a horizon inside a label
        ("Mean beta (9 reported)", "9", "bare"),    # a count inside a label
        ("30 days", "30", "bare"),
        ("12个月平均收益", "12", "bare"),
        ("45", "45", "measured"),                    # a number alone is the table's data
        ("25x", "25", "measured"),                   # a glued unit letter is not a word
        ("25 倍", "25", "measured"),
        ("1.35 (est.)", "1.35", "measured"),         # a decimal is a measurement wherever it stands
        ("up 37% YoY", "37%", "measured"),
        ("$950 consensus", "950", "measured"),
    ],
)
def test_a_cell_is_read_as_prose_only_where_it_holds_words(cell: str, figure: str, shape: str) -> None:
    table = f"| Metric | Value |\n|---|---|\n| {cell} | n/a |\n"
    shapes = {f.text: f.shape for f in scan_figures(table, parse_figures_block(table))}
    assert shapes[figure] == shape, shapes


def test_words_in_a_price_column_cell_do_not_unbind_it() -> None:
    """The header bound the column to a close; "300 est" under it is still a close."""
    table = "| 代码 | 收盘 |\n|---|---|\n| 159516.SZ | 300 est |\n"
    shapes = {f.text: f.shape for f in scan_figures(table, parse_figures_block(table))}
    assert shapes["300"] == "measured"
