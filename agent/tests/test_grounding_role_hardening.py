"""Each declared role carries only what it can honestly carry.

The figures block lets the model name a number's role, and every role was a way
to smuggle a number past the evidence: a price declared ``count``, a source only
the gate could see, an invented operand added to an observed one, a percent
grounded by a close that happened to share its digits. Every rule here is
pinned from both sides on a sparse ledger — two bars per symbol — so a probe
value matches evidence only when it is meant to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.evidence import _metric_kind_for_path
from src.agent.grounding.policies import _note_tokens

pytestmark = pytest.mark.unit

A = "159516.SZ"
B = "600519.SH"
C = "510300.SH"
D = "600000.SH"

_A_ROWS = [
    {
        "trade_date": "2026-05-06",
        "open": 1.020,
        "high": 1.053,
        "low": 1.001,
        "close": 1.040,
        "volume": 123456,
        "amount": 1234567,
    },
    {
        "trade_date": "2026-09-09",
        "open": 0.670,
        "high": 0.681,
        "low": 0.567,
        "close": 0.666,
        "volume": 234567,
    },
]

_B_ROWS = [
    {"trade_date": "2026-05-06", "open": 1400.0, "high": 1500.0, "low": 1390.0, "close": 1450.0, "volume": 1000},
    {"trade_date": "2026-09-09", "open": 1420.0, "high": 1440.0, "low": 1395.0, "close": 1410.0, "volume": 2000},
]


def _bars(symbol: str, rows: list[dict[str, Any]]) -> str:
    return json.dumps(
        {symbol: rows, "_provenance": {symbol: {"source": "akshare", "currency_conversion": "none"}}}
    )


MARKET_A = ("get_market_data", {"codes": [A]}, _bars(A, _A_ROWS), "c1")
MARKET_B = ("get_market_data", {"codes": [B]}, _bars(B, _B_ROWS), "c2")
MARKET_C = (
    "get_market_data",
    {"codes": [C]},
    _bars(C, [{"trade_date": "2026-09-09", "open": 3.9, "high": 3.95, "low": 3.88, "close": 3.912, "volume": 5}]),
    "c3",
)
MARKET_D = (
    "get_market_data",
    {"codes": [D]},
    _bars(D, [{"trade_date": "2026-09-09", "open": 17.8, "high": 18.2, "low": 17.7, "close": 18.0, "volume": 9}]),
    "cd",
)
INDICATORS_A = (
    "technical_indicators",
    {"symbol": A},
    {"ok": True, "symbol": A, "latest_close": 0.666, "indicators": {"rsi_14": 55.2, "sma_20": 0.700}},
    "ind",
)
FACTOR_A = ("factor_analysis", {"symbol": A}, {"status": "ok", "sharpe": 0.888, "win_rate": 0.573}, "fa")

HDR = f"{A}（akshare，CNY）最新收盘 0.666 元。"
ROW = "0.666 | observed | close 2026-09-09 | c1"
TWO = f"{A} 与 {B}（akshare，CNY）对比。\n"
HDR_B = f"{B}（akshare，CNY）最新收盘 1410.00 元。"
ROW_B = "1410.00 | observed | close 2026-09-09 | c2"


def _ledger(tmp_path: Path, *calls: tuple[str, dict[str, Any], Any, str], message: str = "") -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message or f"分析 {A} 并给出买入价")
    for tool, arguments, payload, call_id in calls:
        ledger.ingest_tool_result(
            tool_name=tool,
            arguments=arguments,
            result=payload if isinstance(payload, str) else json.dumps(payload),
            call_id=call_id,
            success=True,
        )
    return ledger


def _block(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


def _reasons(result: Any) -> list[str]:
    return [str(issue.get("reason")) for issue in result.issues]


# ---------------------------------------------------------------------------
# B1 — count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        ("最新收盘价 9.99 元。", "9.99 | count | n"),  # decimal and currency
        ("成本 820 元。", "820 | count | n"),  # integer with a currency mark
        ("entry at $12.5 today.", "12.5 | count | n"),  # currency symbol before
    ],
)
def test_a_count_cannot_carry_a_currency_mark(tmp_path: Path, prose: str, row: str) -> None:
    """A price or an amount declared count is checked as the observation it claims to be."""
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + "\n" + prose + _block(ROW, row))

    assert result.valid is False
    assert [issue["role"] for issue in result.issues] == ["count"]
    assert "a count cannot carry a currency mark" in result.issues[0]["message"]


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        ("建议持有 3.5 个月。", "3.5 | count | 月"),
        ("建议持有 3.0 个月。", "3.0 | count | 月"),
        ("仓位上限 5%。", "5% | count | 仓位参数"),
        ("权重 0.30。", "0.30 | count | 权重"),
        ("主观判断上涨概率 70%。", "70% | count | 主观判断"),
    ],
)
def test_a_parameter_without_a_currency_mark_is_a_count(
    tmp_path: Path, prose: str, row: str
) -> None:
    """A window, weight, threshold, multiplier or probability is the model's own choice."""
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + "\n" + prose + _block(ROW, row))

    assert result.valid is True, result.issues


def test_a_plain_integer_is_a_count(tmp_path: Path) -> None:
    table = "\n\n| 持有期（月） | 成分股数 |\n|---|---|\n| 3 | 12 |\n"

    result = _ledger(tmp_path, MARKET_A).validate_final_answer(
        HDR + table + _block(ROW, "3 | count | 月", "12 | count | 只")
    )

    assert result.valid is True, result.issues


def test_a_measurement_declared_count_is_checked_not_refused(tmp_path: Path) -> None:
    """It is checked as the observation it is, so a real print still passes."""
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(
        HDR + " 最高 0.681 元。" + _block(ROW, "0.681 | count | n")
    )

    assert result.valid is True, result.issues


# ---------------------------------------------------------------------------
# B2 — cited
# ---------------------------------------------------------------------------


def test_a_source_only_the_note_names_is_no_citation(tmp_path: Path) -> None:
    """The block is stripped before release, so the reader must see the source."""
    ledger = _ledger(tmp_path, MARKET_A)
    row = "9.99 | cited | 新浪财经"

    invisible = ledger.validate_final_answer(HDR + "\n最新收盘价 9.99 元。" + _block(ROW, row))
    on_another_line = ledger.validate_final_answer(
        HDR + "\n新浪财经另有报道。\n单位净值 9.99 元。" + _block(ROW, row)
    )
    digits_only = ledger.validate_final_answer(
        HDR + "\n2024 年报单位净值 9.99 元。" + _block(ROW, "9.99 | cited | 2024")
    )
    visible = ledger.validate_final_answer(HDR + "\n新浪财经报道其单位净值 9.99 元。" + _block(ROW, row))
    visible_english = ledger.validate_final_answer(
        HDR + "\nFama-French (2024) report a Sharpe of 1.8."
        + _block(ROW, "1.8 | cited | FAMA-FRENCH 2024 table 3")
    )

    assert _reasons(invisible) == ["citation_not_visible"]
    assert _reasons(on_another_line) == ["citation_not_visible"]
    assert _reasons(digits_only) == ["citation_not_visible"]
    assert visible.valid is True, visible.issues
    assert visible_english.valid is True, visible_english.issues


def test_a_note_token_is_a_cjk_pair_or_a_four_letter_word() -> None:
    assert _note_tokens("2026 Q2 财报毛利率, WSJ ok 新") == {"财报", "报毛", "毛利", "利率"}
    assert _note_tokens("新浪 abc Reuters") == {"新浪", "reuters"}
    assert _note_tokens("新 ab the 12") == set()


# ---------------------------------------------------------------------------
# B3 — derived
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        ("第一档 0.888 元。", "0.888 | derived | 0.666 + 0.222 | c1"),
        ("第一档 9.99 元。", "9.99 | derived | 9.99 + 0.666 − 0.666 | c1"),
        ("第一档 0.888 元。", "0.888 | derived | (0.666 + 0.222) × 1 | c1"),
        ("第一档 0.866 元。", "0.866 | derived | 0.1 × 2 + 0.666 | c1"),
    ],
)
def test_an_added_operand_must_be_observed(tmp_path: Path, prose: str, row: str) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + " " + prose + _block(ROW, row))

    assert _reasons(result) == ["additive_operand_not_observed"]


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        ("第一档 0.646 元。", "0.646 | derived | 0.666 × 0.97 | c1"),
        ("第一档 0.646 元。", "0.646 | derived | 0.666 × (1 − 0.03) | c1"),
        ("较高点回撤 36.8%。", "36.8% | derived | (0.666 − 1.053) / 1.053 | c1"),
        ("中枢 0.860 元。", "0.860 | derived | (0.666 + 1.053) / 2 | c1"),
    ],
)
def test_observed_sums_and_free_multipliers_still_derive(tmp_path: Path, prose: str, row: str) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + " " + prose + _block(ROW, row))

    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        # Far from any print of 1, so only the structure can admit these.
        ("第一档 1358.00 元。", "1358.00 | derived | 1400 × (1 − 0.03) | c2"),
        ("较高点 -7.3%。", "-7.3% | derived | 1390 / 1500 − 1 | c2"),
    ],
)
def test_a_percentage_factor_and_a_return_ratio_are_not_offsets(tmp_path: Path, prose: str, row: str) -> None:
    result = _ledger(tmp_path, MARKET_B, message=f"分析 {B}").validate_final_answer(
        HDR_B + " " + prose + _block(ROW_B, row)
    )

    assert result.valid is True, result.issues


def test_a_derived_result_is_compared_at_the_prose_precision(tmp_path: Path) -> None:
    """A declaration written coarser than the prose cannot widen the band."""
    ledger = _ledger(tmp_path, MARKET_A)

    coarse = ledger.validate_final_answer(HDR + " 目标价 1.00 元。" + _block(ROW, "1 | derived | 0.666 × 0.9 | c1"))
    exact = ledger.validate_final_answer(HDR + " 目标价 0.60 元。" + _block(ROW, "0.6 | derived | 0.666 × 0.9 | c1"))

    assert _reasons(coarse) == ["derivation_result_mismatch"]
    assert exact.valid is True, exact.issues


def test_an_explicit_sign_must_agree_with_the_formula(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A)
    fall = "(0.666 − 1.053) / 1.053 | c1"

    rise_claimed = ledger.validate_final_answer(HDR + " 较高点 +36.8%。" + _block(ROW, "36.8% | derived | " + fall))
    fall_signed = ledger.validate_final_answer(HDR + " 较高点 -36.8%。" + _block(ROW, "-36.8% | derived | " + fall))
    unsigned = ledger.validate_final_answer(HDR + " 较高点回撤 36.8%。" + _block(ROW, "36.8% | derived | " + fall))
    rise_signed = ledger.validate_final_answer(
        HDR + " 低点以来 +58.1%。" + _block(ROW, "58.1% | derived | (1.053 − 0.666) / 0.666 | c1")
    )

    assert _reasons(rise_claimed) == ["derivation_result_mismatch"]
    assert fall_signed.valid is True, fall_signed.issues
    assert unsigned.valid is True, unsigned.issues
    assert rise_signed.valid is True, rise_signed.issues


# ---------------------------------------------------------------------------
# B4 — an OHLC column holds prints
# ---------------------------------------------------------------------------

_CLOSE_TABLE = "\n\n| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | {} |\n"


@pytest.mark.parametrize(
    "row",
    ["0.700 | proposed | entry", "0.700 | derived | 0.666 × 1.051 | c1", "0.700 | count | n"],
)
def test_a_price_column_holds_observed_prints_only(tmp_path: Path, row: str) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + _CLOSE_TABLE.format("0.700") + _block(ROW, row))

    assert _reasons(result) == ["role_in_price_column"]


def test_a_print_in_a_price_column_and_a_level_in_another_column_pass(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A)

    print_ = ledger.validate_final_answer(HDR + _CLOSE_TABLE.format("0.666") + _block(ROW))
    level = ledger.validate_final_answer(
        HDR + "\n\n| 档位 | 建议价 |\n|---|---|\n| 第一档 | 0.700 |\n" + _block(ROW, "0.700 | proposed | entry")
    )

    assert print_.valid is True, print_.issues
    assert level.valid is True, level.issues


def test_a_price_column_cell_is_not_grounded_by_a_metric(tmp_path: Path) -> None:
    """A close cell is compared with closes; a Sharpe of 0.888 is not one."""
    ledger = _ledger(tmp_path, MARKET_A, FACTOR_A)

    metric = ledger.validate_final_answer(HDR + _CLOSE_TABLE.format("0.888"))
    close = ledger.validate_final_answer(HDR + _CLOSE_TABLE.format("0.666"))

    assert _reasons(metric) == ["value_mismatch"]
    assert close.valid is True, close.issues


# ---------------------------------------------------------------------------
# B5 — proposed
# ---------------------------------------------------------------------------


def test_a_proposed_level_needs_an_instrument_when_the_run_holds_several(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_B, message=f"对比 {A} 和 {B}")

    unattributed = ledger.validate_final_answer(TWO + "建议买入价 800.00 元。" + _block("800.00 | proposed | entry"))
    in_prose = ledger.validate_final_answer(TWO + f"{B} 建议买入价 1400.00 元。" + _block("1400.00 | proposed | entry"))
    in_note = ledger.validate_final_answer(TWO + "建议买入价 1400.00 元。" + _block(f"1400.00 | proposed | {B} entry"))

    assert _reasons(unattributed) == ["no_symbol"]
    assert in_prose.valid is True, in_prose.issues
    assert in_note.valid is True, in_note.issues


@pytest.mark.parametrize("row", ["30% | proposed | position", "30% | proposed | 0.666 × 0.45 | c1"])
def test_a_percent_is_never_a_proposed_level(tmp_path: Path, row: str) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + " 建议仓位 30%。" + _block(ROW, row))

    assert _reasons(result) == ["proposed_not_a_price"]
    assert "a proposed level is a price" in result.issues[0]["message"]


def test_the_same_percent_declared_derived_passes(tmp_path: Path) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(
        HDR + " 建议仓位 30%。" + _block(ROW, "30% | derived | 0.666 × 0.45 | c1")
    )

    assert result.valid is True, result.issues


@pytest.mark.parametrize(("level", "inside"), [("0.567", True), ("1.053", True), ("0.566", False), ("1.054", False)])
def test_the_observed_range_includes_its_extremes(tmp_path: Path, level: str, inside: bool) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(
        HDR + f" 建议买入价 {level} 元。" + _block(ROW, f"{level} | proposed | entry")
    )

    assert result.valid is inside, result.issues


# ---------------------------------------------------------------------------
# B6 — observed with a ref
# ---------------------------------------------------------------------------


def test_a_ref_is_filtered_to_the_figures_own_symbol(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_C)
    row = "3.912 | observed | close | c3"

    borrowed = ledger.validate_final_answer(f"{A}（akshare，CNY）最新收盘 3.912 元。" + _block(row))
    own = ledger.validate_final_answer(f"{C}（akshare，CNY）最新收盘 3.912 元。" + _block(row))

    assert _reasons(borrowed) == ["not_in_referenced_call"]
    assert own.valid is True, own.issues


def test_a_percent_is_never_grounded_by_a_price(tmp_path: Path) -> None:
    by_close = _ledger(tmp_path, MARKET_D, message=f"分析 {D}").validate_final_answer(
        f"{D}（akshare，CNY）本周上涨 18%。" + _block("18% | observed | weekly | cd")
    )
    by_scaled_low = _ledger(tmp_path, MARKET_A).validate_final_answer(
        HDR + " 胜率 56.7%。" + _block(ROW, "56.7% | observed | win_rate | c1")
    )
    by_metric = _ledger(tmp_path, MARKET_A, FACTOR_A).validate_final_answer(
        HDR + " 胜率 57.3%。" + _block(ROW, "57.3% | observed | win_rate | fa")
    )

    assert _reasons(by_close) == ["not_in_referenced_call"]
    assert _reasons(by_scaled_low) == ["not_in_referenced_call"]
    assert by_metric.valid is True, by_metric.issues


def test_a_currency_figure_is_grounded_only_by_a_price_kind_value(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, INDICATORS_A)

    rsi_as_price = ledger.validate_final_answer(HDR + " 现价 55.2 元。" + _block(ROW, "55.2 | observed | price | ind"))
    sma_level = ledger.validate_final_answer(HDR + " SMA20 位于 0.700 元。" + _block(ROW, "0.700 | observed | sma_20 | ind"))
    # Money is never a percent of a print: 66.6 元 is not the close 0.666.
    hundredfold = ledger.validate_final_answer(HDR + " 现价 66.6 元。" + _block(ROW, "66.6 | observed | close | c1"))

    assert _reasons(rsi_as_price) == ["not_in_referenced_call"]
    assert _reasons(hundredfold) == ["not_in_referenced_call"]
    assert sma_level.valid is True, sma_level.issues


def test_a_ref_may_name_the_tool(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, INDICATORS_A)

    right_tool = ledger.validate_final_answer(HDR + " RSI 为 55.2。" + _block(ROW, "55.2 | observed | rsi_14 | technical_indicators"))
    wrong_tool = ledger.validate_final_answer(HDR + " RSI 为 55.2。" + _block(ROW, "55.2 | observed | rsi_14 | get_market_data"))

    assert right_tool.valid is True, right_tool.issues
    assert _reasons(wrong_tool) == ["not_in_referenced_call"]


def test_a_symbol_the_declaration_names_outranks_the_prose(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_B, message=f"对比 {A} 和 {B}")
    prose = TWO + "最新收盘 1410.00 元。"

    right = ledger.validate_final_answer(prose + _block(f"1410.00 | observed | close | {B}"))
    wrong = ledger.validate_final_answer(prose + _block(f"1410.00 | observed | close | {A}"))

    assert right.valid is True, right.issues
    assert _reasons(wrong) == ["value_mismatch"]


# ---------------------------------------------------------------------------
# B7 — observed without a ref
# ---------------------------------------------------------------------------


def test_a_currency_figure_is_not_grounded_by_volume_or_a_metric(tmp_path: Path) -> None:
    by_volume = _ledger(tmp_path, MARKET_A).validate_final_answer(f"{A}（akshare，CNY）最新收盘 234567.0 元。")
    by_sharpe = _ledger(tmp_path, MARKET_A, FACTOR_A).validate_final_answer(f"{A}（akshare，CNY）最新收盘 0.888 元。")

    assert _reasons(by_volume) == ["value_mismatch"]
    assert _reasons(by_sharpe) == ["value_mismatch"]


def test_a_currency_figure_is_grounded_by_a_price_or_an_amount(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A)

    price = ledger.validate_final_answer(HDR)
    amount = ledger.validate_final_answer(HDR + " 成交额 1234567.0 元。")
    plain_volume = ledger.validate_final_answer(HDR + " 成交量 234567.0。")

    assert price.valid is True, price.issues
    assert amount.valid is True, amount.issues
    # A plain decimal keeps the row pool: without a mark there is no kind to narrow to.
    assert plain_volume.valid is True, plain_volume.issues


# ---------------------------------------------------------------------------
# B8 — an undeclared figure in a draft that has a block
# ---------------------------------------------------------------------------


def test_an_undeclared_observed_value_is_not_refused(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A)

    observed = ledger.validate_final_answer(HDR + " 最高 0.681 元。" + _block(ROW))
    invented = ledger.validate_final_answer(HDR + " 目标 0.900 元。" + _block(ROW))

    assert observed.valid is True, observed.issues
    assert [issue["code"] for issue in invented.issues] == ["figure_undeclared"]
    assert "declare it as observed / derived / proposed / cited / count" in invented.issues[0]["message"]


# ---------------------------------------------------------------------------
# B10 — metadata counts and tail risk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leaf",
    [
        "return_obs",
        "return_observations",
        "n_returns",
        "return_window",
        "vol_lookback",
        "max_drawdown_duration",
        "aligned_days",
        "sharpe_count",
        "stats.drawdown_days",
        "returns[3]",
    ],
)
def test_a_metadata_count_leaf_has_no_metric_kind(leaf: str) -> None:
    expected = "return" if leaf == "returns[3]" else None

    assert _metric_kind_for_path(leaf) == expected


@pytest.mark.parametrize(
    ("leaf", "kind"),
    [
        ("annualized_return", "return"),
        ("strategy_max_drawdown", "drawdown"),
        ("var", "tail_risk"),
        ("var_95", "tail_risk"),
        ("var_99", "tail_risk"),
        ("cvar", "tail_risk"),
        ("es", "tail_risk"),
        ("expected_shortfall", "tail_risk"),
        ("risk.portfolio_cvar_95", "tail_risk"),
    ],
)
def test_a_metric_leaf_keeps_its_kind(leaf: str, kind: str) -> None:
    assert _metric_kind_for_path(leaf) == kind


def test_a_sample_size_does_not_ground_a_return(tmp_path: Path) -> None:
    meta = ("factor_analysis", {"symbol": A}, {"status": "ok", "return_observations": 81, "aligned_days": 63}, "meta")
    real = ("factor_analysis", {"symbol": A}, {"status": "ok", "annualized_return": 0.81}, "ret")

    unreferenced = _ledger(tmp_path, MARKET_A, meta).validate_final_answer(HDR + " 年化收益 81%。")
    referenced = _ledger(tmp_path, MARKET_A, meta).validate_final_answer(
        HDR + " 胜率 63%。" + _block(ROW, "63% | observed | win_rate | meta")
    )
    honest = _ledger(tmp_path, MARKET_A, real).validate_final_answer(HDR + " 年化收益 81%。")

    assert unreferenced.valid is False
    assert _reasons(referenced) == ["not_in_referenced_call"]
    assert honest.valid is True, honest.issues


def test_a_tail_risk_figure_a_tool_returned_is_grounded(tmp_path: Path) -> None:
    var = ("quantlib_call", {"action": "call", "function": "var"}, {"ok": True, "result": {"var_95": -0.0234}}, "q1")
    ledger = _ledger(tmp_path, MARKET_A, var)

    returned = ledger.validate_final_answer(HDR + " 单日 VaR 为 2.34%。")
    invented = ledger.validate_final_answer(HDR + " 单日 VaR 为 3.10%。")

    assert returned.valid is True, returned.issues
    assert invented.valid is False


# ---------------------------------------------------------------------------
# B11 — what a rejected figure is pointed at
# ---------------------------------------------------------------------------


def _nearest(result: Any, value: str) -> list[float]:
    return next(issue for issue in result.issues if issue["value"] == value)["observed_nearest"]


def test_a_rejected_figure_is_pointed_at_its_own_symbols_closes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_B, message=f"对比 {A} 和 {B}")

    validation = ledger.validate_final_answer(TWO + f"{A} 最新收盘 0.900 元。")
    line = next(row for row in ledger.correction_prompt(validation).splitlines() if row.startswith("- 0.900"))

    assert _nearest(validation, "0.900") == [1.04, 0.666]
    assert "nearest observed 1.04, 0.666" in line


def test_a_rejected_figure_of_no_instrument_is_pointed_at_nothing(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_B, message=f"对比 {A} 和 {B}")

    validation = ledger.validate_final_answer(TWO + "最新收盘 0.900 元。")

    assert _nearest(validation, "0.900") == []


def test_a_rejected_ref_figure_is_pointed_at_the_referenced_closes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A, MARKET_C)

    validation = ledger.validate_final_answer(
        f"{A}（akshare，CNY）最新收盘 0.900 元。" + _block("0.900 | observed | close | c1")
    )

    assert _nearest(validation, "0.900") == [1.04, 0.666]


def test_a_rejected_table_cell_is_pointed_at_its_own_column(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, MARKET_A)
    table = HDR + "\n\n| 最高 |\n|---|\n| 0.700 |\n"

    unreferenced = ledger.validate_final_answer(table)
    # A ref scopes to the whole call, so the column is what narrows it to highs.
    referenced = ledger.validate_final_answer(table + _block(ROW, "0.700 | observed | high | c1"))

    assert _nearest(unreferenced, "0.700") == [0.681, 1.053]
    assert _nearest(referenced, "0.700") == [0.681, 1.053]


# ---------------------------------------------------------------------------
# Review follow-ups: a declaration cannot move a figure, and money derives from money
# ---------------------------------------------------------------------------


def test_a_declaration_may_not_move_a_figure_to_another_instrument(tmp_path: Path) -> None:
    """"159516.SZ 最新收盘 3.912 元" is wrong even if 3.912 is 510300.SH's close."""
    block = _block("3.912 | observed | 510300.SH close | c3")

    moved = _ledger(tmp_path / "moved", MARKET_A, MARKET_C).validate_final_answer(
        "159516.SZ（akshare，CNY）最新收盘 3.912 元。" + block
    )
    kept = _ledger(tmp_path / "kept", MARKET_A, MARKET_C).validate_final_answer(
        "510300.SH（akshare，CNY）最新收盘 3.912 元。" + block
    )

    assert moved.valid is False
    assert "symbol_mismatch" in _reasons(moved)
    assert kept.valid is True, kept.issues


@pytest.mark.parametrize(
    ("markets", "prose", "row"),
    [
        ((MARKET_A, INDICATORS_A), " 第一档 1.104 元。", "1.104 | derived | 55.2 × 0.02 | ind"),
        ((MARKET_A,), " 目标价 2.346 元。", "2.346 | derived | 234567 / 100000 | c1"),
    ],
)
def test_a_money_figure_is_derived_from_money(
    tmp_path: Path, markets: tuple[Any, ...], prose: str, row: str
) -> None:
    result = _ledger(tmp_path, *markets).validate_final_answer(HDR + prose + _block(ROW, row))

    assert result.valid is False
    assert "formula_not_anchored" in _reasons(result)


@pytest.mark.parametrize(
    ("prose", "row"),
    [
        (" 第一档 0.646 元。", "0.646 | derived | 0.666 × 0.97 | c1"),
        (" 较高点回撤 37%。", "37% | derived | (1.053 − 0.666) / 1.053 | c1"),
    ],
)
def test_a_price_discount_and_a_drawdown_still_derive(tmp_path: Path, prose: str, row: str) -> None:
    result = _ledger(tmp_path, MARKET_A).validate_final_answer(HDR + prose + _block(ROW, row))

    assert result.valid is True, result.issues


def test_a_formula_may_be_followed_by_its_explanation(tmp_path: Path) -> None:
    """A real run wrote "(0.648 − 0.997) / 0.997，自7月1日收盘高点回撤" and lost a round."""
    explained = _ledger(tmp_path / "ok", MARKET_A).validate_final_answer(
        HDR + " 较高点回撤 37%。" + _block(ROW, "37% | derived | (1.053 − 0.666) / 1.053，自 5 月高点回撤 | c1")
    )
    wrong = _ledger(tmp_path / "bad", MARKET_A).validate_final_answer(
        HDR + " 较高点回撤 12%。" + _block(ROW, "12% | derived | (1.053 − 0.666) / 1.053，自 5 月高点回撤 | c1")
    )

    assert explained.valid is True, explained.issues
    assert "derivation_result_mismatch" in _reasons(wrong)


def test_a_referenced_table_cell_is_checked_against_its_own_column(tmp_path: Path) -> None:
    """A close cell declared with the call's ref may not borrow that call's high."""
    table = "\n\n| 日期 | 收盘 |\n|---|---|\n| 2026-09-09 | {} |\n"

    high_as_close = _ledger(tmp_path / "high", MARKET_A).validate_final_answer(
        HDR + table.format("0.681") + _block("0.681 | observed | close | c1")
    )
    close = _ledger(tmp_path / "close", MARKET_A).validate_final_answer(
        HDR + table.format("0.666") + _block("0.666 | observed | close | c1")
    )

    assert high_as_close.valid is False
    assert close.valid is True, close.issues


@pytest.mark.parametrize("function", ["historical_var", "parametric_var", "historical_cvar"])
def test_a_real_quantlib_tail_risk_result_grounds_its_own_figure(tmp_path: Path, function: str) -> None:
    """#1464: the scalar result of a real ``quantlib_call`` is evidence for the figure it returned."""
    from src.tools.quantlib_tool import QuantlibCallTool

    returns = [0.01, -0.02, 0.003, -0.0157, 0.004, -0.01, 0.02, -0.005, 0.007, -0.012] * 3
    arguments = {
        "action": "call",
        "module": "risk",
        "function": function,
        "kwargs": {"returns": returns, "confidence": 0.95},
    }
    raw = QuantlibCallTool().execute(**arguments)
    quoted = f"{json.loads(raw)['result'] * 100:.2f}%"
    ledger = _ledger(tmp_path, MARKET_A, ("quantlib_call", arguments, raw, "q1"))
    confidence = _block(ROW, "95% | count | confidence level")

    returned = ledger.validate_final_answer(HDR + f" 单日 95% 尾部损失为 {quoted}。" + confidence)
    invented = ledger.validate_final_answer(HDR + " 单日 95% 尾部损失为 9.87%。" + confidence)

    assert returned.valid is True, returned.issues
    assert invented.valid is False


@pytest.mark.parametrize(
    ("leaf", "kind"),
    [
        ("var", "tail_risk"),
        ("var_95", "tail_risk"),
        ("strategy_var_95", "tail_risk"),
        ("cvar", "tail_risk"),
        ("es", "tail_risk"),
        ("historical_var", "tail_risk"),
        ("parametric_var", "tail_risk"),
        ("var_explained", None),
        ("sales_es", None),
        # A variance is not a VaR: only the named quantlib VaR functions are added.
        ("residual_var", None),
        ("conditional_var", None),
    ],
)
def test_short_tail_risk_names_count_only_as_the_whole_leaf(leaf: str, kind: str | None) -> None:
    assert _metric_kind_for_path(leaf) == kind


def test_an_integer_price_of_an_instrument_quoted_in_the_thousands_is_checked(tmp_path: Path) -> None:
    """"最新收盘 1520" was unchecked for 600519.SH; "200 日均线" and a 0.6-yuan ETF's "20 日" stay so."""
    head = "600519.SH（akshare，CNY）"

    def verdict(name: str, markets: tuple[Any, ...], text: str, message: str):
        return _ledger(tmp_path / name, *markets, message=message).validate_final_answer(text)

    invented = verdict("bad", (MARKET_B,), head + "最新收盘 1520。", f"分析 {B}")
    observed = verdict("good", (MARKET_B,), head + "最新收盘 1450。", f"分析 {B}")
    window = verdict("window", (MARKET_B,), head + "最新收盘 1450，跌破 200 日均线。", f"分析 {B}")
    small = verdict("small", (MARKET_A,), HDR + " 跌破 20 日均线。", f"分析 {A}")

    assert invented.valid is False
    assert observed.valid is True, observed.issues
    assert window.valid is True, window.issues
    assert small.valid is True, small.issues


def test_a_count_inside_the_price_range_needs_a_derivation(tmp_path: Path) -> None:
    """An unmarked price declared count is checked; a multiplier its derivation uses is not."""
    posing = _ledger(tmp_path / "posing", MARKET_A).validate_final_answer(
        HDR + " 最新收盘 0.888。" + _block(ROW, "0.888 | count | n")
    )
    factor = _ledger(tmp_path / "factor", MARKET_A).validate_final_answer(
        HDR + " 第一档 0.646 元，折扣系数 0.97。"
        + _block(ROW, "0.646 | derived | 0.666 × 0.97 | c1", "0.97 | count | 系数")
    )
    weight = _ledger(tmp_path / "weight", MARKET_A).validate_final_answer(
        HDR + " 权重 0.30。" + _block(ROW, "0.30 | count | 权重")
    )

    assert posing.valid is False
    assert "observed price range" in posing.issues[0]["message"]
    assert factor.valid is True, factor.issues
    assert weight.valid is True, weight.issues


@pytest.mark.parametrize(
    ("leaf", "kind"),
    [
        ("strategy_max_drawdown", "drawdown"),
        ("cvar_95", "tail_risk"),
        ("portfolio_var_95", "tail_risk"),
        ("hit_rate_daily", "win_rate"),
        ("rolling_vol_60", "vol"),
        ("sharpe_sample_size", None),
        ("drawdown_threshold", None),
        ("sharpe_ci_upper", None),
        ("return_var", None),
    ],
)
def test_only_the_head_of_a_compound_leaf_names_its_metric(leaf: str, kind: str | None) -> None:
    """#1426: a metric word that qualifies another noun does not make the field that metric."""
    assert _metric_kind_for_path(leaf) == kind


def test_the_spanish_var_report_from_1418_grounds_once_its_confidence_is_declared(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        (
            "portfolio_risk_xray",
            {},
            {"ok": True, "var_95": -0.0157, "max_drawdown": -0.05132},
            "risk",
        ),
        message="Analiza el riesgo de la cartera",
    )

    declared = ledger.validate_final_answer(
        "VaR 95%: 1,57%. Drawdown máximo −5,132%." + _block("95% | count | nivel de confianza")
    )
    invented = ledger.validate_final_answer(
        "VaR 95%: 2,57%. Drawdown máximo −5,132%." + _block("95% | count | nivel de confianza")
    )

    assert declared.valid is True, declared.issues
    assert invented.valid is False


def test_a_worded_cell_still_checks_an_integer_price_in_the_thousands(tmp_path: Path) -> None:
    """#1471 reads "1520 (limit)" as prose, and prose checks an integer price of 600519.SH."""
    head = "600519.SH（akshare，CNY）\n\n| 项目 | 说明 |\n|---|---|\n"

    invented = _ledger(tmp_path / "bad", MARKET_B, message=f"分析 {B}").validate_final_answer(
        head + "| 入场 | 1520 (limit) |\n"
    )
    observed = _ledger(tmp_path / "good", MARKET_B, message=f"分析 {B}").validate_final_answer(
        head + "| 入场 | 1450 (last close) |\n"
    )
    horizon = _ledger(tmp_path / "horizon", MARKET_B, message=f"分析 {B}").validate_final_answer(
        head + "| 周期 | 200 日均线 |\n"
    )

    assert invented.valid is False
    assert observed.valid is True, observed.issues
    assert horizon.valid is True, horizon.issues
