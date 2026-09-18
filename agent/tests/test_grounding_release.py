"""Release path for a rejected draft: repair, redact, derivation spellings.

A rejected draft used to end one of two ways: corrected by the model inside
the revision cap, or replaced wholesale by the canned safe fallback. The
second threw away every sentence the gate had no issue with, after the user
had waited through every revision — a ten-minute run that ends in three
sentences of refusal (owner-forwarded screenshot, 2026-09-09). These tests pin
the third outcome: the draft is released with the rejected figures cut out
and re-checked by the same gate. They also pin the zero-round provenance
repair, and the derivation spellings a correcting model actually writes,
which the gate rejected with the multiplier read as a quoted price.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.agent.grounding import GroundingLedger, ValidationResult
from src.agent.grounding.evidence import (
    _REGISTERED_PRICE_INDICATORS,
    _is_registered_price_indicator,
)
from src.agent.grounding.figures import _lines_with_offsets
from src.agent.grounding.release import _REDACTION_MARKER_EN, _REDACTION_MARKER_ZH
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from tests.message_roles_helpers import assert_system_messages_only_lead

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
        HDR + " 建议买入价 1.136 元。"
        + _block(HDR_ROW, "1.136 | derived | 1.171 × 0.97 | prices")
    )

    assert result.valid is True, result.issues


def test_a_derivation_whose_arithmetic_misses_is_rejected(tmp_path: Path) -> None:
    """The declared value has to be what the note actually computes."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + " 建议买入价 1.20 元。"
        + _block(HDR_ROW, "1.20 | derived | 1.171 × 0.97 | prices")
    )

    assert result.valid is False
    assert [issue["value"] for issue in result.issues] == ["1.20"]
    assert [issue["reason"] for issue in result.issues] == ["derivation_result_mismatch"]


def test_a_derivation_may_take_a_registered_indicator_as_its_input(tmp_path: Path) -> None:
    """`SMA20 1.150 × 0.95`: the operand is a tool value, the arithmetic holds."""
    ledger = _ledger(tmp_path)

    result = ledger.validate_final_answer(
        HDR + " 第一档 1.093 元。"
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


def test_repair_provenance_appends_the_missing_words(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = "562500.SS 最新收盘价 1.171 元，处于下行趋势。"
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["data_source_not_surfaced"]

    repaired = ledger.repair_provenance(draft, validation)

    assert repaired is not None
    assert repaired.startswith(draft)
    assert "yahoo" in repaired and "CNY" in repaired
    assert ledger.validate_final_answer(repaired).valid is True


def test_repair_provenance_refuses_a_draft_with_a_numeric_issue(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = "562500.SS 最新收盘价 1.50 元。"
    validation = ledger.validate_final_answer(draft)
    assert "numeric_claim_conflict" in _codes(validation)

    assert ledger.repair_provenance(draft, validation) is None


def test_repair_provenance_refuses_without_price_evidence(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, market=False, indicators=False)
    validation = ValidationResult(valid=False, issues=[{"code": "data_source_not_surfaced"}])

    assert ledger.repair_provenance("x", validation) is None


# ---------------------------------------------------------------------------
# Redacted release: the analysis survives, the rejected figure does not
# ---------------------------------------------------------------------------


def test_redacted_release_keeps_the_analysis_and_cuts_the_figure(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = HDR + " 均线空头排列，处于下行趋势。建议买入价 1.10 元，分批建仓。"
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["numeric_claim_conflict"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "1.171" in released and "下行趋势" in released and "分批建仓" in released
    assert "1.10" not in released
    assert _REDACTION_MARKER_ZH in released
    assert "※ 略去 1 处" in released
    assert "（略※）元" not in released and "建议买入价（略※）" in released
    assert "1.11–1.18 CNY" in released
    assert ledger.validate_final_answer(released).valid is True


def test_redacted_release_reports_every_cut(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 1.10 元。目标买入价 1.05 元。"
    validation = ledger.validate_final_answer(draft)
    assert sorted(issue["value"] for issue in validation.issues) == ["1.05", "1.10"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "2 处" in released
    assert "1.10" not in released and "1.05" not in released


def test_redacted_release_cuts_every_flagged_figure_in_one_pass(tmp_path: Path) -> None:
    """Every figure is located and checked, so none of them waits for a recheck.

    The validators used to report the FIRST unmatched figure in a clause, so a
    second one only surfaced after the first was cut and the whole document
    re-validated — a cut/recheck cascade with a pass bound, and four figures
    in one sentence exhausted it and shipped the canned refusal instead.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 策略最大回撤 12% 夏普 2.5 胜率 55% 年化收益 30% 处于下行趋势。"
    validation = ledger.validate_final_answer(draft)
    assert [issue.get("value") for issue in validation.issues] == [
        "12%", "2.5", "55%", "30%",
    ]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "下行趋势" in released and "※ 略去 4 处" in released
    for figure in ("12%", "2.5", "55%", "30%"):
        assert figure not in released


def test_redacted_release_adds_provenance_the_cut_draft_still_lacks(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    draft = "562500.SS 最新收盘价 1.171 元。建议买入价 1.10 元。"
    validation = ledger.validate_final_answer(draft)
    assert set(_codes(validation)) == {"numeric_claim_conflict", "data_source_not_surfaced"}

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "yahoo" in released and "1.10" not in released


def test_redacted_release_never_cuts_ticker_digits(tmp_path: Path) -> None:
    """A clause attributing figures to an unhandled symbol loses its figures, not the ticker."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 同业 000001.SZ 收盘价 12.3 元。"
    validation = ledger.validate_final_answer(draft)
    assert "unsourced_symbol_figures" in _codes(validation)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "000001.SZ" in released
    assert "12.3" not in released


def test_redacted_release_writes_english_for_an_english_user(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, message="Analyse 562500.SS and give me an entry price")
    draft = "562500.SS (Yahoo, CNY) last close 1.171. Suggested entry price $1.10."
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["numeric_claim_conflict"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert _REDACTION_MARKER_EN in released and "※ 1 figure(s)" in released
    assert "1.10" not in released and "$" not in released.split("※")[0]


def test_redacted_release_refuses_without_price_evidence(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, market=False, indicators=False)
    draft = HDR + " 建议买入价 1.10 元。"
    validation = ledger.validate_final_answer(draft)
    assert "numeric_claim_unavailable" in _codes(validation)

    assert ledger.redacted_release(draft, validation) is None


def test_redacted_release_refuses_an_unlocked_identity(tmp_path: Path) -> None:
    """A failed resolution leaves identity invalidated; no cut-down draft may ship."""
    ledger = _ledger(tmp_path, message="分析机器人ETF并给出买入价", indicators=False)
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "机器人ETF"},
        result=json.dumps({"ok": False, "error": "timeout"}),
        call_id="resolve",
        success=False,
    )
    draft = HDR + " 建议买入价 1.10 元。"
    validation = ledger.validate_final_answer(draft)
    assert "identity_not_locked" in _codes(validation)

    assert ledger.redacted_release(draft, validation) is None


def test_redacted_release_refuses_a_code_it_cannot_cut(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    validation = ValidationResult(
        valid=False,
        issues=[
            {"code": "numeric_claim_conflict", "claim": "建议买入价 1.10 元", "value": 1.1},
            {"code": "listed_identity_relabelled_private", "symbols": [SYMBOL]},
        ],
    )

    assert ledger.redacted_release(HDR + " 建议买入价 1.10 元。", validation) is None


def test_redacted_release_refuses_when_the_clause_cannot_be_located(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    validation = ValidationResult(
        valid=False,
        issues=[{"code": "numeric_claim_conflict", "claim": "not in the draft 1.10", "value": 1.1}],
    )

    assert ledger.redacted_release(HDR + " 建议买入价 1.10 元。", validation) is None


def test_redacted_release_cuts_a_figure_the_recheck_finds_in_a_table(tmp_path: Path) -> None:
    """A figure withheld from the first pass is still a gate finding on recheck, so it is cut."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 1.10 元。\n\n| 日期 | 收盘价 |\n|---|---|\n| 2026-06-24 | 1.10 |\n"
    validation = ledger.validate_final_answer(draft)
    prose_only = ValidationResult(
        valid=False,
        issues=[issue for issue in validation.issues if issue.get("field") is None],
    )
    assert prose_only.issues

    released = ledger.redacted_release(draft, prose_only)

    assert released is not None
    assert "1.10" not in released and "2 处" in released


def test_redacted_release_refuses_when_the_recheck_finds_what_it_cannot_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only text that passes the gate is released; an identity finding on recheck ends it."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 1.10 元。"
    validation = ledger.validate_final_answer(draft)
    # The release path re-checks through ``_validate(..., record=False)`` so
    # its rechecks are not counted as rejected model drafts.
    monkeypatch.setattr(
        ledger,
        "_validate",
        lambda content, *, record: ValidationResult(
            valid=False, issues=[{"code": "identity_not_locked", "status": "conflicting"}]
        ),
    )

    assert ledger.redacted_release(draft, validation) is None


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

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> _Response:
        self.calls += 1
        self.messages_history.append(list(messages))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if response.content and on_text_chunk:
            on_text_chunk(response.content)
        return response

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> _Response:
        return _Response()


def _tool_call(call_id: str, tool_name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=tool_name, arguments=arguments)


def _run(
    tmp_path: Path, llm: _ScriptedLLM, *, max_iterations: int
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
    return agent.run("请分析机器人ETF并给出买入价"), events, agent


_SCRIPT_HEAD = [
    _Response(tool_calls=[_tool_call("resolve", "search_symbol", query="机器人ETF")]),
    _Response(
        tool_calls=[
            _tool_call(
                "prices",
                "get_market_data",
                codes=[SYMBOL],
                start_date="2026-06-23",
                end_date="2026-06-24",
                source="auto",
            )
        ]
    ),
]


def test_loop_releases_the_redacted_draft_instead_of_the_canned_refusal(tmp_path: Path) -> None:
    """A model that never drops its invented entry still delivers its analysis."""
    stubborn = (
        "562500.SS（Yahoo，CNY）在 2026-06-23 的已观测收盘价为 1.137，均线空头排列。"
        "建议买入价为 0.881。"
    )
    llm = _ScriptedLLM(_SCRIPT_HEAD + [_Response(content=stubborn)])

    result, events, agent = _run(tmp_path, llm, max_iterations=8)

    assert result["status"] == "success"
    assert result.get("degraded") is True
    content = result["content"]
    assert "1.137" in content and "均线空头排列" in content
    assert "0.881" not in content
    assert _REDACTION_MARKER_ZH in content and "※ 略去" in content
    assert "已拒绝上一版答案" not in content
    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    assert "0.881" not in streamed and _REDACTION_MARKER_ZH in streamed
    trace = TraceWriter.read(tmp_path / "run")
    assert [e for e in trace if e.get("type") == "answer_released_redacted"]
    end = next(e for e in trace if e.get("type") == "end")
    assert "redacted" in end.get("reason", "")
    # The count in that reason is the one number the user and the offline
    # verifier have for how much of the run was spent being refused, and the
    # release path's own rechecks must not inflate it.
    reported = re.search(r"after (\d+) rejected drafts", end["reason"])
    assert reported is not None, end["reason"]
    assert int(reported.group(1)) == agent._grounding.validation_count
    # Revision cap 2: the first draft is corrected, the second is released cut.
    assert int(reported.group(1)) == 2
    assert llm.calls == len(_SCRIPT_HEAD) + 2
    statuses = [data for event, data in events if event == "grounding_status"]
    assert [status["stage"] for status in statuses] == ["revising", "released_redacted"]
    assert statuses[0]["round"] == 1 and statuses[0]["issues"] >= 1
    assert statuses[1]["removed"] == 1
    assert_system_messages_only_lead(llm.messages_history)


def test_loop_repairs_a_missing_source_word_without_another_model_round(tmp_path: Path) -> None:
    missing_source = "562500.SS 在 2026-06-23 的已观测收盘价为 1.137 CNY，均线空头排列。"
    llm = _ScriptedLLM(
        _SCRIPT_HEAD + [_Response(content=missing_source), _Response(content="MUST NOT BE ASKED")]
    )

    result, events, agent = _run(tmp_path, llm, max_iterations=8)

    assert result["status"] == "success"
    assert result.get("degraded") is None
    assert llm.calls == 3
    content = result["content"]
    assert content.startswith(missing_source)
    assert "yahoo" in content and "数据说明" in content
    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    assert "yahoo" in streamed
    trace = TraceWriter.read(tmp_path / "run")
    assert [e for e in trace if e.get("type") == "answer_repaired"]
    assert not [e for e in trace if e.get("type") == "answer_rejected"]
    # The repair costs no model round, so it must cost no revision either.
    # ``validation_count`` is both the revision budget and the rejected-draft
    # number in the run reason; recording the recheck spent one of each on a
    # draft the model never wrote.
    assert agent._grounding.validation_count == 1


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
        HDR + " 建议买入价 0.95 元（收盘 1.171 × 0.97 = 1.136 参考）。"
        + _block(
            HDR_ROW,
            "0.97 | count | 折扣系数",
            "1.136 | derived | 1.171 × 0.97 | prices",
        )
    )
    formula_only = ledger.validate_final_answer(
        HDR + " 参考价 1.136 元。"
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


def test_redacted_release_locates_a_grouped_number(tmp_path: Path) -> None:
    """A price above 999 written the ordinary way must still reach the release path."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="请分析 562500.SS 并给出买入价")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=json.dumps(
            {
                SYMBOL: [
                    {"trade_date": "2026-06-23", "open": 1300.0, "high": 1363.35, "low": 1280.0, "close": 1309.22},
                    {"trade_date": "2026-06-24", "open": 1310.0, "high": 1360.0, "low": 1300.01, "close": 1350.0},
                ],
                "_provenance": {SYMBOL: {"source": "yahoo", "currency_conversion": "none"}},
            }
        ),
        call_id="prices",
        success=True,
    )
    draft = "562500.SS（Yahoo，CNY）最新收盘价 1309.22 元。建议买入价 1,450.50 元。"
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["numeric_claim_conflict"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "1,450.50" not in released and "建议买入价（略※）。" in released
    assert "1309.22" in released
    assert "※ 略去 1 处" in released


def test_redacted_release_cuts_a_metric_cell_in_a_table(tmp_path: Path) -> None:
    """A metrics table is the ordinary shape of the report this path exists to rescue."""
    ledger = _ledger(tmp_path)
    draft = HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 12% |\n| 夏普比率 | 2.5 |\n"
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["numeric_claim_unavailable", "numeric_claim_conflict"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "12%" not in released and "2.5" not in released
    assert "最大回撤" in released and "夏普比率" in released
    assert "※ 略去 2 处" in released


def test_redacted_release_never_cuts_inside_another_number(tmp_path: Path) -> None:
    """A bare table cell "1.10" must not be located inside "21.10 亿元"."""
    ledger = _ledger(tmp_path)
    draft = (
        "562500.SS（Yahoo，CNY）最新收盘价 1.171 元。成交额约 21.10 亿元。"
        "\n\n| 日期 | 收盘价 |\n|---|---|\n| 2026-06-24 | 1.10 |\n"
        + _block(HDR_ROW, "21.10 | cited | 成交额（亿元）", "1.10 | observed | close | prices")
    )
    validation = ledger.validate_final_answer(draft)
    assert [i["value"] for i in validation.issues] == ["1.10"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "成交额约 21.10 亿元" in released
    assert "| 2026-06-24 |" in released and "| 2026-06-24 | 1.10 |" not in released
    assert "※ 略去 1 处" in released


def test_every_surviving_occurrence_was_checked_where_it_stands(tmp_path: Path) -> None:
    """The footnote says the figure was removed, so it must be removed everywhere.

    That used to need a document-wide second stage, because neither a table
    under a non-OHLC header nor a bullet without a price word was scanned by
    the validators: cutting the flagged clause left the rejected number
    standing while the footnote asserted it was gone. Every occurrence is now
    a figure the gate located and checked on its own, so each is flagged and
    cut where it stands — and one that was NOT flagged is one the evidence
    supports, which the sweep used to remove anyway.
    """
    ledger = _ledger(tmp_path)
    in_a_table = HDR + " 建议买入价 1.30 元。\n\n| 档位 | 建议买入价 |\n|---|---|\n| 第一档 | 1.30 |\n"
    in_a_bullet = HDR + " 建议买入价 1.30 元。\n- 关键位：1.30 / 1.15\n"

    for draft in (in_a_table, in_a_bullet):
        validation = ledger.validate_final_answer(draft)
        assert len([i for i in validation.issues if i["value"] == "1.30"]) == 2, draft
        released = ledger.redacted_release(draft, validation)

        assert released is not None, draft
        assert "1.30" not in released, draft
        assert "※ 略去" in released, draft
    # 1.15 sits inside the observed range and is checked like the rest, so it
    # survives on its own merits rather than by being missed.
    assert "1.15" in ledger.redacted_release(
        in_a_bullet, ledger.validate_final_answer(in_a_bullet)
    )


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


def test_a_declared_derivation_survives_the_cut_beside_a_rejected_figure(
    tmp_path: Path,
) -> None:
    """A rejected entry price is often the multiplier of the correct derivation.

    "建议买入价 0.95 元" is cut, but the 0.95 inside a valid derivation is a
    figure this gate accepted where it stands, so it is not flagged and not
    cut — which is what the document-wide sweep used to get wrong, leaving
    "× （略※） =" and destroying the one derivation the answer got right.
    """
    ledger = _ledger(tmp_path)
    draft = (
        HDR + " 第一档 1.093 元。建议买入价 0.95 元。"
        + _block(
            HDR_ROW,
            "1.093 | derived | 1.150 × 0.95 | indicators",
            "0.95 | proposed | 系数",
        )
    )
    validation = ledger.validate_final_answer(draft)
    assert [issue.get("value") for issue in validation.issues] == ["0.95"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "第一档 1.093 元。" in released
    assert "建议买入价（略※）。" in released
    assert "※ 略去 1 处" in released


def test_redacted_release_never_cuts_an_observed_price(tmp_path: Path) -> None:
    """A correctly quoted close sharing a sentence with an ungrounded metric survives.

    The analysis validator reported the FIRST unmatched figure in a clause, and
    an observed close was that figure — so the release cut the one number the
    ledger holds and footnoted it as unverifiable. Each figure is checked on
    its own now, so only the metric is flagged.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 最新收盘 1.171 元且策略最大回撤 12%。"
    validation = ledger.validate_final_answer(draft)
    assert [issue.get("value") for issue in validation.issues] == ["12%"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "最新收盘 1.171 元" in released
    assert "12%" not in released
    assert "※ 略去 1 处" in released


def test_redacted_release_swallows_the_unit_flush_against_the_marker(tmp_path: Path) -> None:
    """The marker replaces the figure AND its unit, in either language."""
    zh = _ledger(tmp_path)
    zh_draft = HDR + " 建议买入价 1.10 元，分批建仓。"
    zh_released = zh.redacted_release(zh_draft, zh.validate_final_answer(zh_draft))

    no_space = _ledger(tmp_path)
    no_space_draft = HDR + " 建议买入价 1.10元，分批建仓。"
    no_space_released = no_space.redacted_release(
        no_space_draft, no_space.validate_final_answer(no_space_draft)
    )

    en = _ledger(tmp_path, message="Analyse 562500.SS and give me an entry price")
    en_draft = "562500.SS (Yahoo, CNY) last close 1.171. Suggested entry price 1.10 USD."
    en_released = en.redacted_release(en_draft, en.validate_final_answer(en_draft))

    assert zh_released is not None and "建议买入价（略※），分批建仓。" in zh_released
    assert no_space_released is not None and "建议买入价（略※），分批建仓。" in no_space_released
    assert en_released is not None and "Suggested entry price (omitted※)." in en_released


def test_a_unit_character_that_starts_a_word_is_not_swallowed(tmp_path: Path) -> None:
    """"0.95 元宵节" must not become "（略※）宵节"."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 0.95 元宵节后关注。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "元宵节后关注" in released
    assert "（略※）宵节" not in released
    assert "0.95" not in released


def test_the_marker_follows_the_script_of_the_text_it_cuts(tmp_path: Path) -> None:
    """A Chinese user gets English tables; the marker must match the clause, not the user."""
    ledger = _ledger(tmp_path)  # Chinese user message
    draft = "562500.SS (Yahoo, CNY) last close 1.171. Suggested entry price $0.95 per share."
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert _REDACTION_MARKER_EN in released and _REDACTION_MARKER_ZH not in released.split("※ 略去")[0]
    # The footnote stays in the user's language.
    assert "※ 略去 1 处" in released


def test_redacted_release_releases_three_figures_in_one_clause(tmp_path: Path) -> None:
    """The pass bound is pinned from below as well as above.

    ``test_redacted_release_gives_up_after_the_pass_bound`` only proves the
    bound is under four; without this, lowering it to two would silently push
    more runs back onto the canned refusal — the failure this change exists
    to fix.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 策略最大回撤 12% 夏普 2.5 胜率 55% 处于下行趋势。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "下行趋势" in released
    assert "12%" not in released and "2.5" not in released and "55%" not in released
    assert "※ 略去 3 处" in released


def test_redacted_release_declines_a_provenance_only_validation(tmp_path: Path) -> None:
    """Nothing to cut means no release; the loop's repair path owns that case."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 均线空头排列。"
    validation = ValidationResult(
        valid=False, issues=[{"code": "data_source_not_surfaced", "claim": draft}]
    )

    assert ledger.redacted_release(draft, validation) is None


# ---------------------------------------------------------------------------
# Provenance repair: what it may and may not fill in
# ---------------------------------------------------------------------------


def test_repair_provenance_refuses_a_misattributed_symbol(tmp_path: Path) -> None:
    """The symbol is the figure's subject, not metadata about it.

    Appending "562500.SH: 行情来源 yahoo" under an answer that calls the
    instrument 贵州茅台 releases Kweichow Moutai's close as 1.171 with a
    footnote naming a different instrument, in zero model rounds.
    """
    ledger = _ledger(tmp_path)
    draft = "贵州茅台（雅虎，CNY）最新收盘价 1.171 元，日内最高 1.180 元。"
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["canonical_symbol_not_surfaced"]

    assert ledger.repair_provenance(draft, validation) is None
    assert ledger.redacted_release(draft, validation) is None


def test_repair_provenance_writes_english_for_an_english_user(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, message="Analyse 562500.SS and give me an entry price")
    draft = "562500.SS last close 1.171 CNY, trending down."
    validation = ledger.validate_final_answer(draft)
    assert _codes(validation) == ["data_source_not_surfaced"]

    repaired = ledger.repair_provenance(draft, validation)

    assert repaired is not None
    # The note spells the symbol the way the answer does, not the canonical form.
    assert "Data note: 562500.SS: price source yahoo, quote currency CNY." in repaired
    assert ledger.validate_final_answer(repaired).valid is True


def test_the_release_note_prints_a_large_price_in_full(tmp_path: Path) -> None:
    """``%g`` turns an index level into "1.23457e+06" six significant digits in."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="请分析 562500.SS 并给出买入价")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=json.dumps(
            {
                SYMBOL: [
                    {"trade_date": "2026-06-24", "open": 1240000.0, "high": 1250000.5,
                     "low": 1234567.0, "close": 1245000.0}
                ],
                "_provenance": {SYMBOL: {"source": "yahoo", "currency_conversion": "none"}},
            }
        ),
        call_id="prices",
        success=True,
    )
    draft = "562500.SS（Yahoo，CNY）最新收盘价 1245000.0 元。建议买入价 999.0 元。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "1234567–1250000.5" in released
    assert "e+06" not in released


def test_the_released_document_is_validated_with_its_footnote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The footnote is answer text, so the gate must see it before release.

    The note carries the observed range and the symbols, and it used to be
    concatenated AFTER the recheck — the one part of a released answer with
    nothing behind it. A note that would not pass must refuse the release,
    which is what the method's fail-closed docstring promises.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 1.10 元，分批建仓。"
    validation = ledger.validate_final_answer(draft)
    assert ledger.redacted_release(draft, validation) is not None

    monkeypatch.setattr(
        ledger,
        "_release_note",
        lambda removed, content=None: "※ 参考买入价 9.99 元。",
    )

    assert ledger.redacted_release(draft, validation) is None


def test_a_gate_recheck_is_not_counted_as_a_rejected_draft(tmp_path: Path) -> None:
    """``validation_count`` is the revision budget and a user-facing number."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 1.10 元，分批建仓。"
    validation = ledger.validate_final_answer(draft)
    assert ledger.validation_count == 1

    assert ledger.redacted_release(draft, validation) is not None
    assert ledger.validation_count == 1


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
        header + "买入价 1377.4。" + block
    )
    attributed = _two_symbol_ledger(tmp_path).validate_final_answer(
        header + "600519.SH 买入价 1377.4。" + block
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


def test_a_restatement_of_a_rejected_figure_is_cut_where_it_stands(
    tmp_path: Path,
) -> None:
    """The rejected figure is usually also the multiplier of a valid derivation.

    Protecting it by VALUE protected every restatement of it document-wide;
    protecting it by SPAN needed a second document-wide stage to find those
    restatements again. Neither exists now: the derivation's operand is inside
    a declaration the gate accepted, and the restatement is its own figure,
    checked and flagged where it stands.
    """
    ledger = _ledger(tmp_path)
    draft = (
        HDR + " 第一档 1.093 元。\n\n| 档位 | 建议买入价 |\n|---|---|\n| 第一档 | 0.95 |\n"
        + _block(HDR_ROW, "1.093 | derived | 1.150 × 0.95 | indicators", "0.95 | proposed | 系数")
    )
    validation = ledger.validate_final_answer(draft)
    assert [issue["value"] for issue in validation.issues] == ["0.95"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "第一档 1.093 元。" in released
    assert "| 第一档 | （略※） |" in released
    assert "※ 略去 1 处" in released


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


def test_an_observed_value_is_never_cut(tmp_path: Path) -> None:
    """A correctly quoted close beside an ungrounded metric survives the cut."""
    ledger = _ledger(tmp_path, sma_20=1.150)
    draft = HDR + " 收盘价为 1.150 元。策略最大回撤 12%。"
    validation = ledger.validate_final_answer(draft)
    assert [issue["value"] for issue in validation.issues] == ["12%"]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "收盘价为 1.150 元。" in released
    assert "12%" not in released
    assert "※ 略去 1 处" in released


def test_a_model_authored_release_note_is_stripped_before_redacting(
    tmp_path: Path,
) -> None:
    """The marker and the footnote mean only what the gate put there.

    A draft carrying its own "※ 略去 0 处……" shipped two contradictory
    footnotes, and a "（略※）" pasted into the body read as a redaction that
    never happened.
    """
    ledger = _ledger(tmp_path)
    draft = (
        HDR
        + " 建议买入价 0.95 元。第二档（略※）。"
        + "\n\n※ 略去 0 处无法与本会话工具数据对上的数值。"
    )
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert released.count("※ 略去") == 1
    assert "※ 略去 0 处" not in released
    assert "第二档。" in released


def test_the_marker_follows_each_lines_script_not_the_documents(
    tmp_path: Path,
) -> None:
    """The document-wide sweep picked ONE marker for every line it touched.

    A Chinese report containing an English table released "| First |（略※） |",
    the failure the per-clause rule was written to stop. The column padding
    survives too: the Chinese flush-against-the-word rule must not eat the
    space after a table pipe.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + "\n\n建议买入价 0.95 元。\n\n| Entry | Price |\n|---|---|\n| First | 0.95 |\n"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "建议买入价（略※）。" in released
    assert "| First | (omitted※) |" in released
    assert "※ 略去 2 处" in released


def test_a_compound_unit_is_not_split_by_the_marker(tmp_path: Path) -> None:
    """"0.95 元/股" is one unit; swallowing its first half leaves "/股" dangling."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 0.95 元/股，仓位 3 成。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "0.95" not in released
    assert "（略※）/股" not in released
    assert "元/股" in released


def test_overlapping_issue_spans_are_cut_once(tmp_path: Path) -> None:
    """Two checks can flag the same figure; the cut still happens once.

    A metric row carrying a foreign ticker raises the figure check on the cell
    and ``unsourced_symbol_figures`` on the same figure. Without the
    already-consumed guard the row is emitted once per overlapping span and
    the released table is a fragment-duplicated mess with an inflated count.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + "\n\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 12%，同业 000001.SZ 5.0 |\n"
    validation = ledger.validate_final_answer(draft)
    # The row's own figures are flagged once each, and the unsourced-symbol
    # finding covers the same line a second time.
    assert len(validation.issues) == 3

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "| 最大回撤 | （略※），同业 000001.SZ（略※） |" in released
    assert "※ 略去 2 处" in released


def test_the_released_document_is_recorded_in_the_artifact(tmp_path: Path) -> None:
    """Every recheck on the release path is unrecorded, so the release itself is.

    Without this the artifact carried no evidence at all for the fail-closed
    promise that the document that shipped passed the same gate.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 0.95 元。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)
    assert released is not None

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    assert ledger.validation_count == 1
    assert len(artifact["validations"]) == 1
    assert artifact["released"]["figures_removed"] == 1
    assert artifact["released"]["revalidated"] is True


def test_provenance_repair_no_longer_needs_an_unchecked_column_veto(
    tmp_path: Path,
) -> None:
    """The surface the veto guarded does not exist any more.

    "| 档位 | 挂单价 |" was a price column ``_validate_price_tables`` did not
    key on and the prose scan skipped, so a zero-round provenance note would
    have attested for a figure nothing checked. Every table cell is a
    measurement-shaped figure now, so such a column raises its own issue and
    the repair declines it for the ordinary reason: the issues are not
    provenance-only.
    """
    ledger = _ledger(tmp_path)
    with_column = (
        "562500.SS 最新收盘价 1.171 元。\n\n| 档位 | 挂单价 |\n|---|---|\n| 第一档 | 0.95 |\n"
    )
    without_column = (
        "562500.SS 最新收盘价 1.171 元。\n\n| 档位 | 比例 |\n|---|---|\n| 第一档 | 30 |\n"
        + _block(HDR_ROW, "30 | count | 仓位比例")
    )

    flagged = ledger.validate_final_answer(with_column)
    assert [issue["value"] for issue in flagged.issues if issue["value"]] == ["0.95"]
    declined = ledger.repair_provenance(with_column, flagged)
    repaired = ledger.repair_provenance(
        without_column, ledger.validate_final_answer(without_column)
    )

    assert declined is None
    assert repaired is not None and "行情来源 yahoo" in repaired


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


def test_loop_releases_a_valid_draft_without_its_figures_block(tmp_path: Path) -> None:
    """The block is the model's declaration to the gate, never answer text."""
    prose = "562500.SS（Yahoo，CNY）在 2026-06-23 的已观测收盘价为 1.137。"
    draft = prose + "\n\n```figures\n1.137 | observed | 562500.SS close 2026-06-23 | prices\n```"
    llm = _ScriptedLLM(_SCRIPT_HEAD + [_Response(content=draft)])

    result, events, agent = _run(tmp_path, llm, max_iterations=8)

    assert result["status"] == "success"
    assert result.get("degraded") is None
    assert result["content"] == prose
    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    assert streamed == prose
    assert llm.calls == len(_SCRIPT_HEAD) + 1
    assert not [event for event, _ in events if event == "grounding_status"]
    artifact = json.loads(
        (tmp_path / "run" / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    assert "1.137 | observed" in artifact["validations"][-1]["figures_block"]


def test_the_sweep_cuts_a_bare_restatement_of_a_cut_figure(tmp_path: Path) -> None:
    """The footnote's count is where the figure no longer appears.

    "37%" is a measurement and is cut at its span; "37 个百分点" is a bare
    integer the shape rules never check, so without the sweep the number the
    footnote says was removed would still be on the page.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 较高点回撤 37%，即回撤 37 个百分点；20 日均线走平。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "37" not in released
    assert "20 日均线" in released and "1.171" in released
    assert "※ 略去 2 处" in released
    assert ledger.figures_removed == 2


def test_the_sweep_leaves_a_bare_integer_with_different_digits(tmp_path: Path) -> None:
    """Cutting "0.95" must not take the "95" of an unrelated count with it."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 建议买入价 0.95 元，计划持有 95 天。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "0.95" not in released
    assert "持有 95 天" in released
    assert "※ 略去 1 处" in released
    assert ledger.figures_removed == 1


def test_the_sweep_never_cuts_a_figure_the_gate_checked(tmp_path: Path) -> None:
    """Only bare integers are swept; a decimal sharing the cut figure's digits stays.

    "1.171%" is cut, and the observed close "1.171 元" carries the same digits.
    The close is a measurement the gate checked and grounded, so sweeping it
    would delete a figure the evidence supports.
    """
    ledger = _ledger(tmp_path)
    draft = HDR + " 日内振幅 1.171%。"
    validation = ledger.validate_final_answer(draft)
    assert [issue for issue in validation.issues if issue.get("value") is not None]

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "最新收盘价 1.171 元" in released
    assert "1.171%" not in released
    assert "※ 略去 1 处" in released


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


def test_a_streamed_answer_never_shows_its_figures_block(tmp_path: Path) -> None:
    """A run with no evidence streams live, and the block still stays out."""
    prose = "建议每周复盘 3 次。"

    result, streamed, agent = _stream(tmp_path, prose + "\n\n```figures\n3 | count | 次/周\n```")

    assert agent._grounding.should_buffer_output is False
    assert result["content"] == prose
    assert "figures" not in streamed and "`" not in streamed
    assert streamed.strip() == prose


def test_a_held_back_line_that_never_became_a_fence_is_still_shown(tmp_path: Path) -> None:
    content = "复盘要点如下：\n`先写结论，再写过程`"

    result, streamed, _ = _stream(tmp_path, content)

    assert result["content"] == content
    assert streamed == content


def test_prose_after_the_figures_block_still_reaches_the_stream(tmp_path: Path) -> None:
    """The block is held back from its fence on; what follows it is flushed at the end."""
    content = "建议每周复盘 3 次。\n\n```figures\n3 | count | 次/周\n```\n\n补充：先写结论。"

    result, streamed, _ = _stream(tmp_path, content)

    assert "figures" not in streamed
    assert "补充：先写结论。" in result["content"]
    assert streamed.rstrip().endswith("补充：先写结论。")


def test_the_tool_call_syntax_fallback_reaches_the_stream_once(tmp_path: Path) -> None:
    """A buffered run released the fallback in its own branch and again as the answer."""
    llm = _ScriptedLLM([_Response(content='<invoke name="get_market_data">')])

    result, events, _ = _run(tmp_path, llm, max_iterations=1)

    deltas = [data.get("delta", "") for event, data in events if event == "text_delta"]
    assert len(deltas) == 1, deltas
    assert "tool-call syntax" in deltas[0]
    assert result["content"] == deltas[0]


def test_thinking_done_never_carries_the_figures_block(tmp_path: Path) -> None:
    content = "建议每周复盘 3 次。\n\n```figures\n3 | count | 次/周\n```"
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

    agent.run("总结一下这周的复盘心得")

    thoughts = [data.get("content", "") for event, data in events if event == "thinking_done"]
    assert thoughts
    assert all("figures" not in thought for thought in thoughts)


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


def test_a_figures_block_ending_a_tool_call_turn_is_not_shown(tmp_path: Path) -> None:
    """Completing the last line reveals a fence; the block after it stays held."""
    registry = ToolRegistry()
    registry.register(_NoteTool("ok"))
    llm = _ScriptedLLM(
        [
            _Response(
                content="先记一笔。\n\n```figures\n3 | count | 次\n```",
                tool_calls=[_tool_call("n1", "note_progress")],
            ),
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
    assert "先记一笔。" in streamed
    assert "figures" not in streamed


def test_an_unchecked_measurement_never_streams_before_the_gate(tmp_path: Path) -> None:
    """An unbuffered draft stops streaming at its first measurement; a rejection resets it."""
    llm = _ScriptedLLM(
        [_Response(content="本周收益约 12.5%，好于上周。"), _Response(content="本周整体不错。")]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    agent = AgentLoop(
        registry=ToolRegistry(),
        llm=llm,
        max_iterations=4,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run("总结一下这周的复盘心得")

    streamed = "".join(data.get("delta", "") for event, data in events if event == "text_delta")
    assert "12.5" not in streamed
    assert [data for event, data in events if event == "stream_reset"]
    assert result["content"] == "本周整体不错。"


def test_a_checked_measurement_streams_once_the_gate_passes(tmp_path: Path) -> None:
    prose = "仓位上限 5%。"

    result, streamed, _ = _stream(tmp_path, prose + "\n\n```figures\n5% | count | 仓位参数\n```")

    assert result["content"] == prose
    assert streamed == prose


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


def test_a_redacted_screen_keeps_its_row_numbers_and_labels(tmp_path: Path) -> None:
    """The reporter's table came back with its ranks, "12m" and "3 names" all omitted.

    Every row number was a table cell, so a measurement, so cut; and each cut
    digit was then swept out of the prose. Only the invented returns, multiples
    and beta may go.
    """
    ledger = _ledger(tmp_path, message="Screen a few names and rank them")
    validation = ledger.validate_final_answer(_SCREEN)
    flagged = sorted(str(issue["value"]) for issue in validation.issues)
    assert flagged == sorted(
        ["+8.0%", "+3.0%", "22.5", "+5.0%", "+2.0%", "18.1", "+4.0%", "+1.0%", "30.2", "+5.7%", "1.35"]
    )

    released = ledger.redacted_release(_SCREEN, validation)

    assert released is not None
    for kept in (
        "| 1 | 562500.SS", "| 2 | 562500.SS", "| 3 | 562500.SS", "| 9/16 Close | 12m | 6m |",
        "| 12m mean return |", "| Mean beta (3 reported) |",
        "Names 1 to 3 are up over 12m and 6m; the sleeve is 3 names in 1 sector.",
        "Name 2 trades lower vs the 9/16 close.",
    ):
        assert kept in released, kept
    for invented in ("8.0%", "22.5", "18.1", "30.2", "5.7%", "1.35"):
        assert invented not in released, invented
    assert "11 figure(s)" in released
    assert ledger.validate_final_answer(released).valid is True


def test_the_sweep_does_not_key_on_a_single_digit(tmp_path: Path) -> None:
    """Cutting "5%" must not take every "5" on the page; two digits still sweep (37 above)."""
    ledger = _ledger(tmp_path)
    draft = HDR + " 较高点回撤 5%，跌破 5 日均线，关注 5 只同类基金。"
    validation = ledger.validate_final_answer(draft)

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "5%" not in released
    assert "跌破 5 日均线，关注 5 只同类基金" in released
    assert "※ 略去 1 处" in released
