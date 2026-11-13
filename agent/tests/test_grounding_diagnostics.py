"""Offline numeric diagnostics retained after removal of answer rewriting."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from evals.grounding import GroundingLedger, ValidationResult
from tests.grounding_parameter_helpers import declared_parameter
from evals.grounding.evidence import (
    _REGISTERED_PRICE_INDICATORS,
    _is_registered_price_indicator,
)
from evals.grounding.figures import _lines_with_offsets
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry

pytestmark = pytest.mark.unit

SYMBOL = "562500.SS"
HDR = "562500.SS（Yahoo，CNY）最新收盘价 1.171 元。"


def _market_payload() -> str:
    return json.dumps(
        {
            SYMBOL: [
                {"trade_date": "2026-06-23", "open": 1.141, "high": 1.164, "low": 1.121, "close": 1.137, "volume": 1},
                {"trade_date": "2026-06-24", "open": 1.137, "high": 1.180, "low": 1.110, "close": 1.171, "volume": 1},
            ],
            "_provenance": {
                SYMBOL: {
                    "source": "yahoo",
                    "requested_source": "auto",
                    "detected_source": "yahoo",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        }
    )


def _indicator_payload(**extra: Any) -> str:
    indicators: dict[str, Any] = {
        "rsi_14": 55.2,
        "sma_20": 1.150,
        "sma_50": 1.090,
        "bollinger": {"upper": 1.21, "middle": 1.15, "lower": 1.09},
        "macd": {"macd_line": -0.0187, "signal_line": -0.0134, "histogram": -0.0053},
    }
    indicators.update(extra)
    return json.dumps(
        {
            "ok": True,
            "symbol": SYMBOL,
            "interval": "1d",
            "latest_close": 1.171,
            "latest_date": "2026-06-24",
            "indicators": indicators,
        }
    )


def _resolver_payload() -> str:
    return json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": "机器人ETF",
                "count": 1,
                "candidates": [
                    {
                        "symbol": SYMBOL,
                        "name": "机器人ETF",
                        "market": "cn",
                        "type": "ETF",
                        "source": "yahoo",
                        "also_from": ["eastmoney"],
                    }
                ],
                "sources": {"eastmoney": "ok", "yahoo": "ok"},
            },
        },
        ensure_ascii=False,
    )


def _ledger(
    tmp_path: Path,
    message: str = "请分析 562500.SS 并给出买入价",
    *,
    market: bool = True,
    indicators: bool = True,
    **extra_indicators: Any,
) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)
    if market:
        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": [SYMBOL]},
            result=_market_payload(),
            call_id="prices",
            success=True,
        )
    if indicators:
        ledger.ingest_tool_result(
            tool_name="technical_indicators",
            arguments={"symbol": SYMBOL},
            result=_indicator_payload(**extra_indicators),
            call_id="indicators",
            success=True,
        )
    return ledger


def _codes(result: ValidationResult) -> list[str]:
    return [str(issue.get("code")) for issue in result.issues]


#: The declaration that covers HDR's own quoted close.
HDR_ROW = "1.171 | observed | close 2026-06-24 | prices"


def _block(*rows: str) -> str:
    """Render a figures block, which every draft with a role needs."""
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


# ---------------------------------------------------------------------------
# Price-denominated indicator values are observed evidence
# ---------------------------------------------------------------------------


def test_price_denominated_indicator_values_are_observed(tmp_path: Path) -> None:
    """A moving average or band the session fetched is a quoted tool value."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(HDR + " SMA20 位于 1.150，布林下轨 1.09 为支撑位。")

    assert result.valid is True, result.issues


def test_non_price_indicator_values_still_do_not_ground_a_price(tmp_path: Path) -> None:
    """RSI and a volume average are not prices; quoting one as a price stays rejected."""
    ledger = _ledger(tmp_path, volume_ma_20=1.30)

    rsi_as_price = ledger.validate_final_answer(HDR + " 现价 55.2 元。")
    volume_ma_as_price = ledger.validate_final_answer(HDR + " 现价 1.30 元。")

    assert "numeric_claim_conflict" in _codes(rsi_as_price)
    assert "numeric_claim_conflict" in _codes(volume_ma_as_price)


def test_indicator_evidence_never_satisfies_a_labelled_ohlc_cell(tmp_path: Path) -> None:
    """A close COLUMN must match a close; an SMA equal to the cell does not count."""
    ledger = _ledger(tmp_path, sma_20=1.150)

    table = HDR + "\n\n| 日期 | 收盘价 |\n|---|---|\n| 2026-06-24 | 1.150 |\n"
    result = ledger.validate_final_answer(table)

    assert result.valid is False
    assert any(issue.get("value") == "1.150" for issue in result.issues)


# ---------------------------------------------------------------------------
# A derivation is a declaration, not a spelling
# ---------------------------------------------------------------------------


def test_a_declared_derivation_is_checked_by_its_own_arithmetic(tmp_path: Path) -> None:
    """The note IS the formula, so no result-separator vocabulary is involved.

    The prose used to have to carry the equation, and the gate had to
    recognise the separator the model happened to write — "=" worked, then
    "≈" and "约" were added, then "approximately" had to be added because the
    English spelling was still burning a revision round. The separator list is
    gone: the arithmetic is in the declaration and the prose says what it likes.
    """
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + declared_parameter("97%") + " 建议买入价 1.136 元。"
        + _block(HDR_ROW, "1.136 | derived | 1.171 × 0.97 | prices")
    )

    assert result.valid is True, result.issues


def test_a_derivation_whose_arithmetic_misses_is_rejected(tmp_path: Path) -> None:
    """The declared value has to be what the note actually computes."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + declared_parameter("97%") + " 建议买入价 1.20 元。"
        + _block(HDR_ROW, "1.20 | derived | 1.171 × 0.97 | prices")
    )

    assert result.valid is False
    assert [issue["value"] for issue in result.issues] == ["1.20"]
    assert [issue["reason"] for issue in result.issues] == ["derivation_result_mismatch"]


def test_a_derivation_may_take_a_registered_indicator_as_its_input(tmp_path: Path) -> None:
    """`SMA20 1.150 × 0.95`: the operand is a tool value, the arithmetic holds."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + declared_parameter("95%") + " 第一档 1.093 元。"
        + _block(HDR_ROW, "1.093 | derived | 1.150 × 0.95 | indicators")
    )

    assert result.valid is True, result.issues


def test_a_derivation_from_an_unregistered_leaf_stays_rejected(tmp_path: Path) -> None:
    """RSI is not a registered price leaf, so it anchors nothing."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + " 第一档 1.104 元。"
        + _block(HDR_ROW, "1.104 | derived | 55.3 × 0.02 | prices")
    )

    assert result.valid is False
    assert [issue["reason"] for issue in result.issues] == ["formula_not_anchored"]


def test_a_note_that_is_not_arithmetic_is_not_a_derivation(tmp_path: Path) -> None:
    """A derivation needs an operation, not a restatement or a claim.

    "1.171" alone and "回测得出" are both refused, which is what makes it safe
    for the note to carry no keyword precondition: the two-operand rule in
    ``_evaluate_formula`` is the thing that refuses them.
    """
    ledger = _ledger(tmp_path)

    for note, reason in (
        ("1.171", "formula_not_evaluable"),
        ("回测得出", "formula_not_evaluable"),
    ):
        result = ledger.validate_final_answer(
            HDR + " 建议买入价 1.136 元。"
            + _block(HDR_ROW, f"1.136 | derived | {note} | prices")
        )
        assert result.valid is False, note
        assert [issue["reason"] for issue in result.issues] == [reason], note


def test_an_entry_without_a_role_that_survives_is_still_rejected(tmp_path: Path) -> None:
    """The product rule stands: a proposed entry must be derived or in range."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(HDR + " 建议买入价 1.10 元。")

    assert _codes(result) == ["numeric_claim_conflict"]
    assert [issue["value"] for issue in result.issues] == ["1.10"]


# ---------------------------------------------------------------------------
# Analysis figures that are arithmetic on observed endpoints
# ---------------------------------------------------------------------------


def test_a_drawdown_is_the_arithmetic_its_note_states(tmp_path: Path) -> None:
    """(1.110 − 1.180) / 1.180 = −5.93%: "约 6%" rounds to it, "约 8%" does not.

    The direction used to be inferred from the word 回撤 — a drawdown was
    compared by magnitude, a return by sign — so the same two endpoints
    grounded a +5.9% or a −5.9% depending on the noun beside them. The note
    states which subtraction was done, and the gate checks that subtraction.
    """
    ledger = _ledger(tmp_path)
    note = "(1.110 - 1.180) / 1.180"

    for claim in ("6%", "5.9%", "-5.9%"):
        result = ledger.validate_final_answer(
            HDR + f" 最低价 1.110 元，较高点 1.180 元已回撤约 {claim}。"
            + _block(
                HDR_ROW,
                "1.110 | observed | low | prices",
                "1.180 | observed | high | prices",
                f"{claim} | derived | {note} | prices",
            )
        )
        assert result.valid is True, (claim, result.issues)

    for claim in ("8%", "6.31%"):
        result = ledger.validate_final_answer(
            HDR + f" 最低价 1.110 元，较高点 1.180 元已回撤约 {claim}。"
            + _block(
                HDR_ROW,
                "1.110 | observed | low | prices",
                "1.180 | observed | high | prices",
                f"{claim} | derived | {note} | prices",
            )
        )
        assert result.valid is False, claim
        assert [issue["reason"] for issue in result.issues] == [
            "derivation_result_mismatch"
        ], claim

    unanchored = ledger.validate_final_answer(HDR + " 策略最大回撤 6%。")
    assert _codes(unanchored) == ["numeric_claim_unavailable"]


def test_a_return_figure_is_matched_at_its_written_precision(tmp_path: Path) -> None:
    """1.121 → 1.180 is +5.26%: "约 5%" and "5.3%" round to it; "6%" does not."""
    ledger = _ledger(tmp_path)
    note = "(1.180 - 1.121) / 1.121"

    def check(claim: str) -> bool:
        return ledger.validate_final_answer(
            HDR + f" 从最低价 1.121 元涨到最高价 1.180 元，区间收益率{claim}。"
            + _block(
                HDR_ROW,
                "1.121 | observed | low | prices",
                "1.180 | observed | high | prices",
                f"{claim.lstrip('约 ')} | derived | {note} | prices",
            )
        ).valid

    for claim in ("约 5%", "5.3%", "5.26%"):
        assert check(claim) is True, claim
    for claim in ("约 6%", "5.4%", "5.20%"):
        assert check(claim) is False, claim


# ---------------------------------------------------------------------------
# Provenance repair: a missing word is appended, not regenerated
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# Redacted release: the analysis survives, the rejected figure does not
# ---------------------------------------------------------------------------


























# ---------------------------------------------------------------------------
# Loop integration
# ---------------------------------------------------------------------------


# Both stubs take ``result`` in ``__init__`` on purpose. ``build_registry`` walks
# ``BaseTool.__subclasses__()`` and caches whatever it can instantiate, so a
# no-argument stub named ``get_market_data`` defined at collection time REPLACES
# the real tool for every later test in the session — fifteen MCP market-data
# tests failed that way on 2026-09-09. A required constructor argument makes
# discovery skip the stub (logged as "Failed to register"), which is the
# convention the other grounding test modules already rely on.
class _ResolverTool(BaseTool):
    name = "search_symbol"
    description = "Resolve a company or instrument name."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    repeatable = True

    def __init__(self, result: str) -> None:
        self.result = result

    def execute(self, **kwargs: Any) -> str:
        return self.result


class _MarketTool(BaseTool):
    name = "get_market_data"
    description = "Fetch OHLCV bars."
    parameters = {
        "type": "object",
        "properties": {"codes": {"type": "array", "items": {"type": "string"}}},
        "required": ["codes"],
    }
    repeatable = True

    def __init__(self, result: str) -> None:
        self.result = result

    def execute(self, **kwargs: Any) -> str:
        return self.result


class _Response:
    def __init__(self, *, content: str = "", tool_calls: list[SimpleNamespace] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.reasoning_content = None
        self.has_tool_calls = bool(self.tool_calls)


class _ScriptedLLM:
    """Plays a script, then keeps returning its last response forever."""

    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.messages_history: list[list[dict[str, Any]]] = []
        self.tools_history: list[list[Any] | None] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_waiting_chunk=None,
    ) -> _Response:
        self.calls += 1
        self.messages_history.append(list(messages))
        self.tools_history.append(tools)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if response.content and on_text_chunk:
            on_text_chunk(response.content)
        return response

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> _Response:
        return _Response()


def _tool_call(call_id: str, tool_name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=tool_name, arguments=arguments)


def _run(
    tmp_path: Path, llm: _ScriptedLLM, *, max_iterations: int, session_id: str = ""
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]], AgentLoop]:
    registry = ToolRegistry()
    registry.register(_ResolverTool(_resolver_payload()))
    registry.register(_MarketTool(_market_payload()))
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        max_iterations=max_iterations,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    return agent.run("请分析机器人ETF并给出买入价", session_id=session_id), events, agent




















# ---------------------------------------------------------------------------
# Endpoint arithmetic: direction and units
#
# The four cases below were all live escapes on the first cut of this change
# and every one of them left the rest of this module green, which is the
# mutation signal that the exemption had only positive-side coverage.
# ---------------------------------------------------------------------------

WIDE_BARS = [
    {"trade_date": "2026-05-10", "open": 1.050, "high": 1.053, "low": 1.040, "close": 1.050, "volume": 1},
    {"trade_date": "2026-09-09", "open": 0.670, "high": 0.680, "low": 0.660, "close": 0.666, "volume": 1},
]
WIDE_HDR = "562500.SS（Yahoo，CNY）最新收盘价 0.666 元。"


def _wide_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger whose two observed endpoints are 1.053 (high) and 0.666 (close).

    The fall is −36.75%; the same pair read the other way is +58.11%. A dense
    real frame cannot probe this — 83 bars × 4 fields put some print within
    0.5% of almost any two-decimal number — so the endpoints are sparse and
    far apart on purpose.
    """
    ledger = GroundingLedger(run_dir=tmp_path, user_message="请分析 562500.SS 的回撤")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=json.dumps(
            {
                SYMBOL: WIDE_BARS,
                "_provenance": {
                    SYMBOL: {
                        "source": "yahoo",
                        "requested_source": "auto",
                        "detected_source": "yahoo",
                        "fallback_used": False,
                        "currency_conversion": "none",
                    }
                },
            }
        ),
        call_id="prices",
        success=True,
    )
    return ledger


def _wide_block(figure: str, note: str) -> str:
    """Declare the wide ledger's two endpoints and one derived figure."""
    return _block(
        "0.666 | observed | close | prices",
        "1.053 | observed | 5 月高点 | prices",
        f"{figure} | derived | {note} | prices",
    )


def test_the_note_states_which_direction_was_taken(tmp_path: Path) -> None:
    """A fall and the rise back between the same endpoints are different notes.

    The direction used to be inferred from the word beside the figure — 回撤
    compared by magnitude, 收益率 by sign — so one noun swap changed the
    verdict on identical arithmetic. Both directions are now writable, and
    each grounds only the figure it actually produces.
    """
    fall = "(0.666 - 1.053) / 1.053"
    rise = "(1.053 - 0.666) / 0.666"
    line = "最新收盘 0.666 元 较 5 月高点 1.053 元，{}。"

    for figure, note in (("36.8%", fall), ("37%", fall), ("58.1%", rise), ("58%", rise)):
        result = _wide_ledger(tmp_path).validate_final_answer(
            WIDE_HDR + " " + line.format(figure) + _wide_block(figure, note)
        )
        assert result.valid is True, (figure, note, result.issues)

    for figure, note in (("58.1%", fall), ("37%", rise), ("45%", fall)):
        result = _wide_ledger(tmp_path).validate_final_answer(
            WIDE_HDR + " " + line.format(figure) + _wide_block(figure, note)
        )
        assert result.valid is False, (figure, note)
        assert [issue["reason"] for issue in result.issues] == [
            "derivation_result_mismatch"
        ]


def test_a_percent_figure_is_compared_in_percentage_points_only(tmp_path: Path) -> None:
    """"约 0%" is not within half a unit of a 58% move — the half unit is in pp.

    A bare integer percent carries a half unit of 0.5, and running that band
    against the FRACTION (0.5811) instead of the percentage points made 0.5 a
    band of fifty points wide: "区间收益率约 0%" validated against a real +58%
    move.
    """
    rise = "(1.053 - 0.666) / 0.666"
    line = "最新收盘 0.666 元 较 5 月高点 1.053 元，区间收益率约 {}。"

    for figure in ("0%", "1%", "-1%", "2%"):
        result = _wide_ledger(tmp_path).validate_final_answer(
            WIDE_HDR + " " + line.format(figure) + _wide_block(figure, rise)
        )
        assert result.valid is False, figure
    for figure in ("58%", "58.1%", "58.11%"):
        result = _wide_ledger(tmp_path).validate_final_answer(
            WIDE_HDR + " " + line.format(figure) + _wide_block(figure, rise)
        )
        assert result.valid is True, (figure, result.issues)


def test_the_written_precision_band_is_half_a_unit_not_more(tmp_path: Path) -> None:
    """The band is exactly half a unit of the last written digit, from both sides.

    1.110 → 1.171 is +5.4955%. An integer 5% is 0.4955 away and must be
    accepted; 6% is 0.5045 away and must be rejected. The pair straddles 0.5
    by a twentieth of a point, so widening the multiplier even to 0.7 flips the
    second assertion.
    """
    ledger = _ledger(tmp_path)
    note = "(1.171 - 1.110) / 1.110"

    def verdict(figure: str) -> bool:
        return ledger.validate_final_answer(
            HDR + f" 从最低价 1.110 元涨到收盘 1.171 元，区间收益率约 {figure}。"
            + _block(
                HDR_ROW,
                "1.110 | observed | low | prices",
                f"{figure} | derived | {note} | prices",
            )
        ).valid

    assert verdict("5%") is True
    assert verdict("6%") is False
    # One decimal narrows the band to 0.05: 5.4% is 0.0955 away.
    assert verdict("5.4%") is False
    assert verdict("5.5%") is True


# ---------------------------------------------------------------------------
# What a derivation justifies, and in which language
# ---------------------------------------------------------------------------


def test_a_declaration_covers_its_own_value_and_nothing_beside_it(
    tmp_path: Path,
) -> None:
    """One valid derivation used to exempt the whole clause it sat in.

    The exemption is now the declaration, and a declaration names exactly one
    value — so an invented entry price beside a correct derivation is reported
    even when the two share a sentence, and even when the invented one is the
    derivation's own multiplier.
    """
    ledger = _ledger(tmp_path)

    riding_along = ledger.validate_final_answer(
        HDR + declared_parameter("97%") + " 建议买入价 0.95 元（收盘 1.171 × 0.97 = 1.136 参考）。"
        + _block(
            HDR_ROW,
            "0.97 | count | 折扣系数",
            "1.136 | derived | 1.171 × 0.97 | prices",
        )
    )
    formula_only = ledger.validate_final_answer(
        HDR + declared_parameter("97%") + " 参考价 1.136 元。"
        + _block(HDR_ROW, "1.136 | derived | 1.171 × 0.97 | prices")
    )

    assert [issue["value"] for issue in riding_along.issues] == ["0.95"]
    assert formula_only.valid is True, formula_only.issues


def test_the_same_figure_gets_the_same_verdict_under_any_prose(
    tmp_path: Path,
) -> None:
    """Prose cannot change a verdict, because no prose word is read.

    This replaces the price-word / level-word / observation-binder catalogues
    outright. Every sentence below states the same declared figure; the gate
    reaches one verdict for all of them, in both scripts, because the only
    inputs are the declaration and the evidence.
    """
    ledger = _ledger(tmp_path, sma_20=1.150)
    sentences = [
        "现价 1.150 元。", "最新价 1.150 元。", "成交价 1.150 元。", "报价 1.150 元。",
        "股价 1.150 元。", "收盘价为 1.150 元。", "20 日均线 1.150 元。",
        "The current price is 1.150.", "The closing price was 1.150.",
        "It last traded at 1.150.", "The 20-day moving average is 1.150.",
        "1.150 is where it sits.",
    ]

    verdicts = {
        sentence: ledger.validate_final_answer(
            HDR + " " + sentence + _block(HDR_ROW, "1.150 | observed | sma_20 | indicators")
        ).valid
        for sentence in sentences
    }

    assert set(verdicts.values()) == {True}, verdicts

    # And the same one verdict when the declaration points somewhere the value
    # is not: the ref is what moves it, never the wording.
    misrefs = {
        sentence: ledger.validate_final_answer(
            HDR + " " + sentence + _block(HDR_ROW, "1.150 | observed | 收盘 | prices")
        ).valid
        for sentence in sentences
    }
    assert set(misrefs.values()) == {False}, misrefs


# ---------------------------------------------------------------------------
# Which evidence may back which claim
# ---------------------------------------------------------------------------


def test_a_declared_ref_is_what_separates_an_indicator_from_a_close(
    tmp_path: Path,
) -> None:
    """Two surfaces still scope evidence: a table column, and a declared ref.

    The prose surface does not. "收盘价为 1.150 元" was refused because the
    clause named an OHLC field and the session's sma_20 happened to equal the
    figure — a verdict a word decided, and one whose mirror in the other
    language leaked for a year. What separates them now is what the model
    says: a ref pointing at the market-data call is checked against that
    call's own bars.
    """
    ledger = _ledger(tmp_path, sma_20=1.150)

    labelled_column = ledger.validate_final_answer(
        HDR + "\n\n| 代码 | 收盘价 |\n|---|---|\n| 562500.SS | 1.150 |\n"
        + _block(HDR_ROW, "1.150 | observed | close | prices")
    )
    wrong_ref = ledger.validate_final_answer(
        HDR + " 收盘价为 1.150 元。" + _block(HDR_ROW, "1.150 | observed | 收盘 | prices")
    )
    right_ref = ledger.validate_final_answer(
        HDR + " SMA20 位于 1.150。"
        + _block(HDR_ROW, "1.150 | observed | sma_20 | indicators")
    )

    assert "numeric_claim_conflict" in _codes(labelled_column)
    assert "numeric_claim_conflict" in _codes(wrong_ref)
    assert right_ref.valid is True, right_ref.issues


def _two_symbol_ledger(tmp_path: Path) -> GroundingLedger:
    """Prices for two symbols, an indicator for one of them only."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="对比 562500.SH 和 600519.SH")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["562500.SH", "600519.SH"]},
        result=json.dumps(
            {
                "562500.SH": [
                    {"trade_date": "2026-06-24", "open": 1.137, "high": 1.180, "low": 1.110, "close": 1.171}
                ],
                "600519.SH": [
                    {"trade_date": "2026-06-24", "open": 1400.0, "high": 1425.0, "low": 1395.0, "close": 1420.0}
                ],
                "_provenance": {
                    "562500.SH": {"source": "yahoo", "currency_conversion": "none"},
                    "600519.SH": {"source": "yahoo", "currency_conversion": "none"},
                },
            }
        ),
        call_id="prices",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="technical_indicators",
        arguments={"symbol": "562500.SH"},
        result=json.dumps({"ok": True, "symbol": "562500.SH", "indicators": {"sma_20": 1.150}}),
        call_id="indicators",
        success=True,
    )
    return ledger


def test_one_symbols_indicator_does_not_ground_an_unattributed_claim(tmp_path: Path) -> None:
    """The cross-symbol union is for observed quotes; an indicator is symbol-bound.

    ``technical_indicators`` returns a level for one symbol, so 562500's SMA
    must not ground a figure on a line that names two instruments and
    attributes it to neither.
    """
    header = "562500.SH 与 600519.SH（Yahoo，CNY）对比。"

    unattributed_indicator = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "布林下轨 1.150 元为支撑位。"
    )
    # Both halves of the rule the union was argued for stay intact.
    unattributed_ohlc = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "现价 1420 元。"
    )
    attributed_indicator = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "562500.SH 布林下轨 1.150 元为支撑位。"
    )

    assert "numeric_claim_conflict" in _codes(unattributed_indicator)
    assert unattributed_ohlc.valid is True, unattributed_ohlc.issues
    assert attributed_indicator.valid is True, attributed_indicator.issues


def test_an_unregistered_tools_leaf_never_grounds_a_price(tmp_path: Path) -> None:
    """A price-shaped leaf name from an unregistered tool is not price evidence.

    ``_ingest_generic_numeric`` classifies every non-market tool result, so a
    tool that returns ``{"indicators": {"volume": {"sma_20": 1.30}}}`` is all
    it took: the leaf ``sma_20`` is a price NAME, and the rule that read names
    admitted it. Names are no longer read — a tool has to be registered, leaf
    by leaf, before any of its output can answer a price claim.
    """
    ledger = GroundingLedger(run_dir=tmp_path, user_message="请分析 562500.SS")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=_market_payload(),
        call_id="prices",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="custom_indicator_tool",
        arguments={"symbol": SYMBOL},
        result=json.dumps({"symbol": SYMBOL, "indicators": {"volume": {"sma_20": 1.30}}}),
        call_id="custom",
        success=True,
    )

    result = ledger.validate_final_answer(HDR + " 现价 1.30 元。")

    assert "numeric_claim_conflict" in _codes(result)


@pytest.mark.parametrize(
    ("tool", "path", "registered"),
    [
        ("technical_indicators", "latest_close", True),
        ("technical_indicators", "indicators.sma_20", True),
        ("technical_indicators", "indicators.ema_50", True),
        ("technical_indicators", "indicators.bollinger.upper", True),
        ("technical_indicators", "indicators.bollinger.middle", True),
        ("technical_indicators", "indicators.bollinger.lower", True),
        # Same tool, leaves it does not register: an oscillator, a histogram,
        # and the derived shapes the old name-reading rule kept admitting.
        ("technical_indicators", "indicators.rsi_14", False),
        ("technical_indicators", "indicators.macd.histogram", False),
        ("technical_indicators", "indicators.bollinger.bandwidth", False),
        ("technical_indicators", "indicators.sma_cross", False),
        # Same leaf names, a tool nobody registered.
        ("custom_indicator_tool", "indicators.sma_20", False),
        ("custom_indicator_tool", "latest_close", False),
    ],
)
def test_only_registered_leaves_are_price_evidence(
    tool: str, path: str, registered: bool
) -> None:
    """Registration is per tool AND per leaf, in both directions."""
    assert _is_registered_price_indicator(tool, path) is registered


def test_every_registration_prefix_matches_something_it_names() -> None:
    """A registered prefix must actually classify the leaf it describes.

    The list it replaces carried six pivot spellings that no lookup could ever
    reach, because the digit strip turned ``r1`` into ``r``. A registration
    that matches nothing is the same defect wearing a different shape.
    """
    for tool, prefixes in _REGISTERED_PRICE_INDICATORS.items():
        for prefix in prefixes:
            assert _is_registered_price_indicator(tool, prefix) is True, (tool, prefix)
            assert _is_registered_price_indicator("other_tool", prefix) is False


# ---------------------------------------------------------------------------
# Locating what to cut
#
# The claim string a validator records is normalised — thousands separators
# stripped, a table cell rendered as "label: value" — so it is not a substring
# of the draft. Every case here either shipped the canned refusal or rewrote
# the wrong characters before the clause span was carried on the issue.
# ---------------------------------------------------------------------------










def test_a_metric_cell_restating_observed_closes_is_not_an_invented_metric(
    tmp_path: Path,
) -> None:
    """"| 峰值→当前 | 1.180 → 1.110 |" states two observed closes, not a drawdown figure.

    The prose path exempts an observed value from the analysis check; the
    table path did not, so a peak-to-current row was reported as an
    unevidenced drawdown and the release cut the observed prices out of it
    (deepseek 159516.SZ E2E, 2026-09-09). A figure the ledger does NOT hold
    stays rejected in the same table.
    """
    ledger = _ledger(tmp_path)

    observed_pair = ledger.validate_final_answer(
        HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 1.180 → 1.110 |\n"
    )
    invented = ledger.validate_final_answer(
        HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 1.180 → 0.900 |\n"
    )
    invented_percent = ledger.validate_final_answer(
        HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | -39.32% |\n"
    )

    assert observed_pair.valid is True, observed_pair.issues
    assert [issue.get("value") for issue in invented.issues] == ["0.900"]
    assert _codes(invented_percent) == ["numeric_claim_unavailable"]
















# ---------------------------------------------------------------------------
# Provenance repair: what it may and may not fill in
# ---------------------------------------------------------------------------












def test_a_derivation_anchored_to_another_symbol_grounds_nothing(tmp_path: Path) -> None:
    """The cross-symbol bail, for derivations as well as for indicators.

    In a comparison run the expensive instrument's close is arithmetically
    fine and attached to the wrong symbol.
    """
    header = "562500.SH 与 600519.SH（Yahoo，CNY）对比。"
    block = _block(
        "1.171 | observed | close | prices",
        "1420 | observed | close | prices",
        "1377.4 | derived | 1420 × 0.97 | prices",
    )

    unattributed = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "买入价 1377.4。" + block + declared_parameter("97%")
    )
    attributed = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "600519.SH 买入价 1377.4。" + block + declared_parameter("97%")
    )

    assert "numeric_claim_conflict" in _codes(unattributed)
    assert attributed.valid is True, attributed.issues


# ---------------------------------------------------------------------------
# An analysis metric needs analysis evidence
# ---------------------------------------------------------------------------


def test_a_declaration_grounds_only_the_figure_it_names(tmp_path: Path) -> None:
    """One correct ratio used to carry every other figure in its clause out.

    The exemption was measured over a clause, then over a line for the operand
    scan, and the boundary between them decided verdicts: "基于 40 × 1.171 =
    46.84 计算，策略最大回撤 40%" released a max drawdown no backtest produced.
    A declaration names one value, so there is no span for a neighbour to ride
    in on.
    """
    ledger = _wide_ledger(tmp_path)
    block = _block(
        "0.666 | observed | close | prices",
        "1.053 | observed | 5 月高点 | prices",
        "37% | derived | (0.666 - 1.053) / 1.053 | prices",
    )

    both = ledger.validate_final_answer(
        WIDE_HDR + " 当前 0.666 元 较 5 月高点 1.053 元已回撤约 37%，最大回撤 60%。" + block
    )
    only_the_derived = _wide_ledger(tmp_path).validate_final_answer(
        WIDE_HDR + " 当前 0.666 元 较 5 月高点 1.053 元已回撤约 37%。" + block
    )

    assert [issue["value"] for issue in both.issues] == ["60%"]
    assert only_the_derived.valid is True, only_the_derived.issues


def test_a_metric_needs_metric_evidence_or_its_own_arithmetic(tmp_path: Path) -> None:
    """A percentage is never answered by a price, however close the number is.

    A run holds hundreds of observed values spanning the instrument's range, so
    any percent-free metric written in that range collides with one. Percent
    figures are structurally immune: an OHLC close is not a ratio, so the price
    pool is not consulted for them at all.
    """
    ledger = _ledger(tmp_path)

    percent_metric = ledger.validate_final_answer(HDR + " 策略最大回撤 1.171%。")
    metric_cell = ledger.validate_final_answer(
        HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 1.171% |\n"
    )

    assert _codes(percent_metric) == ["numeric_claim_unavailable"]
    assert _codes(metric_cell) == ["numeric_claim_unavailable"]


def test_a_metric_backed_by_a_risk_tool_passes_in_prose_and_in_a_table(
    tmp_path: Path,
) -> None:
    """The other side: kind-mapped leaves ARE evidence, at either scale."""
    ledger = _ledger(tmp_path)
    ledger.ingest_tool_result(
        tool_name="portfolio_risk_xray",
        arguments={"symbols": [SYMBOL]},
        result=json.dumps({"annualized_vol": 0.182, "max_drawdown": -0.094}),
        call_id="risk",
        success=True,
    )

    prose = ledger.validate_final_answer(HDR + " 年化波动率 18.2%，最大回撤 9.4%。")
    table = ledger.validate_final_answer(
        HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 年化波动率 | 18.2% |\n"
    )

    assert prose.valid is True, prose.issues
    assert table.valid is True, table.issues


# ---------------------------------------------------------------------------
# The release path: what the footnote is allowed to claim
# ---------------------------------------------------------------------------




def test_an_accepted_figure_is_never_cut_for_sharing_a_value(tmp_path: Path) -> None:
    """A validated derivation and an invented metric can be the same percentage.

    Percent literals were cut everywhere they appeared, so endpoint arithmetic
    this same gate accepted in this same run was removed and footnoted as
    "could not be matched to this session's tool data".
    """
    ledger = _ledger(tmp_path)
    draft = (
        HDR + "\n从 1.110 涨到 1.171，区间收益率约 5.5%。\n策略年化波动率 5.5%。"
        + _block(
            HDR_ROW,
            "1.110 | observed | low | prices",
            "5.5% | derived | (1.171 - 1.110) / 1.110 | prices",
        )
    )
    validation = ledger.validate_final_answer(draft)
    assert [issue["value"] for issue in validation.issues] == []

    # Both occurrences are covered by one declaration, so both are accepted:
    # a declaration is a statement about a VALUE, and the answer states the
    # same derived value twice.
    assert validation.valid is True, validation.issues
















def test_line_offsets_are_a_monotone_scan() -> None:
    """A line that also occurs inside an earlier line must not borrow its offset.

    ``content.find(line)`` without the cursor anchors line 2 inside line 1;
    the slice still equals the line, so only monotonicity catches it, and
    every issue span in the module is built on these offsets.
    """
    content = "备注：策略最大回撤 12%。\n策略最大回撤 12%\n结束"

    positions = _lines_with_offsets(content)

    cursor = 0
    expected: list[int] = []
    for line in content.splitlines():
        expected.append(cursor)
        cursor += len(line) + 1
    assert [offset for _, offset in positions] == expected
    assert [offset for _, offset in positions] == sorted(
        offset for _, offset in positions
    )
    assert all(
        content[offset : offset + len(line)] == line for line, offset in positions
    )


# ---------------------------------------------------------------------------
# Revision cap 2 plumbing: the released text, the status events, the sweep
# ---------------------------------------------------------------------------










class _ChunkedLLM:
    """Streams its one answer in three-character chunks, like a provider."""

    model_name = "grounding-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_waiting_chunk=None,
    ) -> _Response:
        self.calls += 1
        if on_text_chunk:
            for start in range(0, len(self.content), 3):
                on_text_chunk(self.content[start : start + 3])
        return _Response(content=self.content)

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> _Response:
        return _Response()


def _stream(tmp_path: Path, content: str) -> tuple[dict[str, Any], str, AgentLoop]:
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=ToolRegistry(),
        llm=_ChunkedLLM(content),
        max_iterations=3,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    result = agent.run("总结一下这周的复盘心得")
    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    return result, streamed, agent




def test_a_held_back_line_that_never_became_a_fence_is_still_shown(tmp_path: Path) -> None:
    content = "复盘要点如下：\n`先写结论，再写过程`"

    result, streamed, _ = _stream(tmp_path, content)

    assert result["content"] == content
    assert streamed == content




def test_the_tool_call_syntax_fallback_reaches_the_stream_once(tmp_path: Path) -> None:
    """A buffered run released the fallback in its own branch and again as the answer."""
    llm = _ScriptedLLM([_Response(content='<invoke name="get_market_data">')])

    result, events, _ = _run(tmp_path, llm, max_iterations=1)

    deltas = [data.get("delta", "") for event, data in events if event == "text_delta"]
    assert sum("tool-call syntax" in delta for delta in deltas) == 1
    visible = ""
    for event, data in events:
        if event == "stream_reset":
            visible = ""
        elif event == "text_delta":
            visible += data["delta"]
    assert result["content"] == visible




class _NoteTool(BaseTool):
    name = "note_progress"
    description = "Record a note."
    parameters = {"type": "object", "properties": {}}
    repeatable = True

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def execute(self, **kwargs: Any) -> str:
        return json.dumps({"status": "ok", "note": self.reply})


def test_a_held_back_line_in_a_tool_call_turn_is_shown(tmp_path: Path) -> None:
    """The last line could only have become a fence while the turn was streaming."""
    registry = ToolRegistry()
    registry.register(_NoteTool("ok"))
    llm = _ScriptedLLM(
        [
            _Response(content="先记一笔：\n`先写结论`", tool_calls=[_tool_call("n1", "note_progress")]),
            _Response(content="记好了。"),
        ]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        max_iterations=4,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    agent.run("总结一下这周的复盘心得")

    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    assert "`先写结论`" in streamed








# ---------------------------------------------------------------------------
# #1471 — a redaction cuts the invented figures, not the table's furniture
# ---------------------------------------------------------------------------

_SCREEN = (
    "562500.SS (Yahoo, CNY) last close 1.171.\n\n"
    "| # | Ticker | Sector | 9/16 Close | 12m | 6m | Fwd PE |\n"
    "|---|---|---|---|---|---|---|\n"
    "| 1 | 562500.SS | ETF (robotics) | 1.171 | +8.0% | +3.0% | 22.5 |\n"
    "| 2 | 562500.SS | ETF (robotics) | 1.137 | +5.0% | +2.0% | 18.1 |\n"
    "| 3 | 562500.SS | ETF (robotics) | 1.171 | +4.0% | +1.0% | 30.2 |\n\n"
    "| Metric | Value |\n|---|---|\n| 12m mean return | +5.7% |\n| Mean beta (3 reported) | 1.35 |\n\n"
    "1. Names 1 to 3 are up over 12m and 6m; the sleeve is 3 names in 1 sector.\n"
    "2. Name 2 trades lower vs the 9/16 close.\n"
)






# ---------------------------------------------------------------------------
# The correction prompt's keep list (#1622 post-failure action semantics)
# ---------------------------------------------------------------------------








