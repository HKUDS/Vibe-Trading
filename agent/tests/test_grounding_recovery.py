"""Bounded grounding recovery (#1081): recoverable missing evidence.

When identity is unresolved or price evidence is missing, the loop must
keep driving the original task through read-only tool turns
(``search_symbol`` -> ``get_market_data``) instead of stopping at the
three-draft cap with the "confirm and continue" safe fallback. Recovery
has its own budgets, separate from the rejected-draft count, and the user
is only involved when state is genuinely ambiguous, conflicting, or
exhausted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.release import (
    MAX_GROUNDING_RECOVERY_ROUNDS,
    MAX_PRICE_EVIDENCE_ATTEMPTS,
    MAX_SYMBOL_RESOLUTION_ATTEMPTS,
)
from src.providers.chat import LLMResponse
from tests.message_roles_helpers import assert_system_messages_only_lead

pytestmark = pytest.mark.unit


def _ledger(
    tmp_path: Path,
    *,
    message: str = "分析机器人ETF并给出买入价",
) -> GroundingLedger:
    return GroundingLedger(run_dir=tmp_path, user_message=message)


def _resolver_payload(symbol: str = "562500.SS") -> str:
    return json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": "机器人ETF",
                "count": 1,
                "candidates": [
                    {
                        "symbol": symbol,
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


def _market_payload(symbol: str = "562500.SS") -> str:
    return json.dumps(
        {
            symbol: [
                {
                    "trade_date": "2026-06-23",
                    "open": 1.141,
                    "high": 1.164,
                    "low": 1.121,
                    "close": 1.137,
                    "volume": 123456,
                }
            ],
            "_provenance": {
                symbol: {
                    "source": "yahoo",
                    "requested_source": "auto",
                    "detected_source": "yahoo",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        }
    )


class TestRecoveryAction:
    def test_unresolved_identity_instructs_symbol_search(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        validation = ledger.validate_final_answer("机器人ETF 现价 1.171。")

        assert ledger.identity_status == "unresolved"
        assert ledger.recovery_action(validation) == "search_symbol"

    def test_locked_identity_with_missing_price_instructs_market_data(
        self, tmp_path: Path
    ) -> None:
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        validation = ledger.validate_final_answer("562500.SS 现价 9.999。")

        assert ledger.identity_status == "locked"
        assert ledger.recovery_action(validation) == "get_market_data"

    def test_percent_only_fundamentals_issue_does_not_instruct_market_data(
        self, tmp_path: Path
    ) -> None:
        """#GGAL-B(14A): a ROE/ROA/efficiency/capital-ratio-shaped percent must
        not steer the model toward ``get_market_data`` — it can never answer a
        ratio. Only the RECOVERY ACTION changes; the figure still fails.
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        validation = ledger.validate_final_answer("562500.SS ROE 33.98%。")

        assert ledger.identity_status == "locked"
        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue["percent"] is True
        assert ledger.recovery_action(validation) != "get_market_data"

    def test_real_price_gap_still_instructs_market_data(self, tmp_path: Path) -> None:
        """#GGAL-B(14B): a genuine market/price claim keeps recommending
        ``get_market_data`` — the fix narrows the trigger, it does not remove it.
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        validation = ledger.validate_final_answer("562500.SS 现价 9.999。")

        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue["percent"] is False
        assert ledger.recovery_action(validation) == "get_market_data"

    def test_cited_fundamentals_figure_passes_without_metric_pool(
        self, tmp_path: Path
    ) -> None:
        """#GGAL-B(14C, requirement 5): a fundamentals ratio declared ``cited``
        with a visible source passes without ever touching ``metric_pool`` —
        the existing mechanism for SEC/IR text figures, not new text parsing.
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        draft = (
            "根据 SEC 年报，562500.SS 的 ROE 为 33.98%。\n\n"
            "```figures\n33.98% | cited | SEC 年报 | filing\n```"
        )

        validation = ledger.validate_final_answer(draft)

        assert validation.valid is True, validation.issues

    def test_grounded_answer_offers_no_recovery(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": ["562500.SS"]},
            result=_market_payload(),
            call_id="market",
            success=True,
        )
        validation = ledger.validate_final_answer(
            "562500.SS（yahoo，CNY）2026-06-23 收盘价 1.137。"
        )

        assert validation.valid is True
        assert ledger.recovery_action(validation) is None

    def test_ambiguous_identity_offers_no_recovery(self, tmp_path: Path) -> None:
        candidates = [
            {"symbol": "ABC.US", "name": "ABC Holdings", "source": "yahoo"},
            {"symbol": "ABC.HK", "name": "ABC Group", "source": "eastmoney"},
        ]
        payload = json.dumps(
            {
                "ok": True,
                "data": {
                    "query": "ABC",
                    "candidates": candidates,
                    "sources": {"yahoo": "ok", "eastmoney": "ok"},
                },
            }
        )
        ledger = _ledger(tmp_path, message="分析 ABC 并给出买入价")
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "ABC"},
            result=payload,
            call_id="resolve",
            success=True,
        )
        validation = ledger.validate_final_answer("ABC 现价 5.0。")

        assert ledger.identity_status == "ambiguous"
        assert ledger.recovery_action(validation) is None

    def test_conflicting_identity_offers_no_recovery(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(symbol="562500.SS"),
            call_id="resolve-1",
            success=True,
        )
        # A later resolution of the same query contradicts the lock.
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(symbol="000300.SH"),
            call_id="resolve-2",
            success=True,
        )
        validation = ledger.validate_final_answer("000300.SH 现价 5.0。")

        assert ledger.identity_status == "conflicting"
        assert ledger.recovery_action(validation) is None

    def test_symbol_resolution_budget_is_bounded(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        broken = ledger.validate_final_answer("机器人ETF 现价 1.171。")

        for _ in range(MAX_SYMBOL_RESOLUTION_ATTEMPTS):
            assert ledger.recovery_action(broken) == "search_symbol"
            ledger.record_recovery("search_symbol")

        assert ledger.recovery_action(broken) is None

    def test_price_evidence_budget_is_bounded(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        validation = ledger.validate_final_answer("562500.SS 现价 9.999。")

        for _ in range(MAX_PRICE_EVIDENCE_ATTEMPTS):
            assert ledger.recovery_action(validation) == "get_market_data"
            ledger.record_recovery("get_market_data")

        assert ledger.recovery_action(validation) is None

    # Hardcoded on purpose. Every bound below is written as a literal rather
    # than derived from the constant it is guarding: a test that loops
    # ``range(MAX_GROUNDING_RECOVERY_ROUNDS)`` and then asserts the budget ran
    # out passes for any value of that constant, including infinity.
    _ROUND_CAP_CEILING = 6
    _NEVER_MORE_THAN = 20

    def test_total_recovery_rounds_are_bounded(self, tmp_path: Path) -> None:
        """The round cap binds once no per-action cap does.

        Spending the round budget with ``record_recovery("search_symbol")``
        also spends the symbol budget, so a ``None`` afterwards proves only that
        the symbol cap works. Both per-action caps are patched out of the way so
        the round cap is the one thing left to stop it, and the loop is driven
        by a literal ceiling so widening the cap fails here instead of just
        making the test slower.
        """
        ledger = _ledger(tmp_path)
        validation = ledger.validate_final_answer("机器人ETF 现价 1.171。")

        with patch.multiple(
            "src.agent.grounding.release",
            MAX_SYMBOL_RESOLUTION_ATTEMPTS=10_000,
            MAX_PRICE_EVIDENCE_ATTEMPTS=10_000,
        ):
            spent = 0
            while ledger.recovery_action(validation) is not None:
                ledger.record_recovery("search_symbol")
                spent += 1
                if spent > self._NEVER_MORE_THAN:
                    pytest.fail(
                        f"recovery still available after {spent} rounds with the "
                        "per-action caps lifted; the round cap is not binding"
                    )
            assert spent <= self._ROUND_CAP_CEILING

    def test_per_action_budgets_are_what_actually_binds_today(self, tmp_path: Path) -> None:
        """With shipped values the per-action caps bind before the round cap.

        ``MAX_SYMBOL_RESOLUTION_ATTEMPTS + MAX_PRICE_EVIDENCE_ATTEMPTS`` is the
        real ceiling on the recovery turns one run can spend, and those turns
        come out of the loop's iteration budget. The round cap is the outer
        backstop for when those are raised; it has to stay at or above their sum
        or it silently becomes the real limit, and at or below the literal
        ceiling or recovery could crowd out the run itself.
        """
        assert MAX_SYMBOL_RESOLUTION_ATTEMPTS + MAX_PRICE_EVIDENCE_ATTEMPTS <= 5
        assert (
            MAX_SYMBOL_RESOLUTION_ATTEMPTS + MAX_PRICE_EVIDENCE_ATTEMPTS
            <= MAX_GROUNDING_RECOVERY_ROUNDS
            <= self._ROUND_CAP_CEILING
        )

        ledger = _ledger(tmp_path)
        unresolved = ledger.validate_final_answer("机器人ETF 现价 1.171。")
        spent = 0
        while (action := ledger.recovery_action(unresolved)) is not None:
            ledger.record_recovery(action)
            spent += 1
            if spent > self._NEVER_MORE_THAN:
                pytest.fail(f"recovery did not converge within {spent} rounds")
        assert spent == MAX_SYMBOL_RESOLUTION_ATTEMPTS


class TestRecoveryActionMarketPriceContext:
    """#GGAL-B follow-up: a currency mark alone is not "market data" — an
    EPS, net income, revenue, assets, equity, capex or FCF figure is
    currency-marked too, and ``get_market_data`` can never answer any of
    them. ``recovery_action`` now needs a POSITIVE signal (an OHLC table
    column, or price/quote/target/support/resistance context in the
    figure's own clause or declared note) before it recommends fetching a
    quote — see ``_figure_is_market_price`` in ``policies.py``.
    """

    @staticmethod
    def _ledger_with_locked_symbol(tmp_path: Path) -> GroundingLedger:
        """An identity-locked ledger with no resolver/market-data evidence,
        so any rejected figure's ``numeric_claim_unavailable`` is purely
        about whether THIS figure's own context looks like a price.
        """
        return GroundingLedger(run_dir=tmp_path, user_message="GGAL.US fundamentals")

    def test_a_eps_in_currency_does_not_instruct_market_data(self, tmp_path: Path) -> None:
        """14A: EPS ``ARS 361,58`` is ``numeric_claim_unavailable`` but never
        market-price context.
        """
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer(
            "Ganancia por acción trimestral de ARS 361,58."
        )

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is not True
        assert ledger.recovery_action(validation) != "get_market_data"

    def test_b_net_income_in_currency_does_not_instruct_market_data(
        self, tmp_path: Path
    ) -> None:
        """14B: net income ``ARS 200 millones`` never instructs get_market_data."""
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer("Resultado neto de ARS 200 millones.")

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is not True
        assert ledger.recovery_action(validation) != "get_market_data"

    def test_c_revenue_in_currency_does_not_instruct_market_data(
        self, tmp_path: Path
    ) -> None:
        """14C: revenue ``USD 1,200 million`` never instructs get_market_data."""
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer("Revenue of USD 1,200 million for the quarter.")

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is not True
        assert ledger.recovery_action(validation) != "get_market_data"

    def test_d_closing_price_still_instructs_market_data(self, tmp_path: Path) -> None:
        """14D: a genuine closing price still positively identifies as a quote."""
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer("GGAL.US cerró en USD 52.30.")

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is True
        assert ledger.recovery_action(validation) == "get_market_data"

    def test_e_price_target_still_instructs_market_data(self, tmp_path: Path) -> None:
        """14E: a price target still positively identifies as a quote context.

        Worded as the compound phrase ("price target"), not a bare "target" —
        round 2 of the conservative fix (#GGAL-B) requires the full bursátil
        phrase, since a bare word ("objetivo", "target") also reads a plain
        fundamentals sentence ("Objetivo de eficiencia: 45%").
        """
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer("Analyst price target of USD 60 for GGAL.US.")

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is True
        assert ledger.recovery_action(validation) == "get_market_data"

    def test_f_percent_fundamentals_still_do_not_instruct_market_data(
        self, tmp_path: Path
    ) -> None:
        """14F: a percent fundamentals ratio (ROE) still never instructs
        get_market_data, now via the positive condition rather than the
        earlier ``not percent`` exclusion.
        """
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer("GGAL.US ROE 33.98%.")

        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is not True
        assert ledger.recovery_action(validation) != "get_market_data"


class TestRecoveryActionMarketPriceContextConservative:
    """#GGAL-B follow-up, round 2: a bare word ("cierre", "objetivo",
    "máximo", "mínimo", "open", "high", "low") is not enough either — a
    fundamentals sentence uses those words too ("Ratio de capital al
    CIERRE de FY2024", "OBJETIVO de eficiencia: 45%"). ``market_price`` now
    requires a full bursátil PHRASE (closing/opening price, closed/opened
    AT a value, intraday high/low, price target, ...), not a single word —
    see the updated ``_MARKET_PRICE_CONTEXT_RE``.
    """

    @staticmethod
    def _ledger_with_locked_symbol(tmp_path: Path) -> GroundingLedger:
        return GroundingLedger(run_dir=tmp_path, user_message="GGAL.US fundamentals")

    def _assert_not_market_price(self, tmp_path: Path, draft: str) -> None:
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer(draft)

        assert validation.valid is False, draft
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is not True, draft
        assert ledger.recovery_action(validation) != "get_market_data", draft

    def _assert_market_price(self, tmp_path: Path, draft: str) -> None:
        ledger = self._ledger_with_locked_symbol(tmp_path)
        validation = ledger.validate_final_answer(draft)

        assert validation.valid is False, draft
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is True, draft
        assert ledger.recovery_action(validation) == "get_market_data", draft

    def test_a_ratio_at_period_close_is_not_market_price(self, tmp_path: Path) -> None:
        """A: bare "cierre" (period close, not a quote) must stay False."""
        self._assert_not_market_price(
            tmp_path, "Ratio de capital al cierre de FY2024: 21,61%."
        )

    def test_b_efficiency_target_is_not_market_price(self, tmp_path: Path) -> None:
        """B: bare "objetivo" (a target ratio, not a price target) must stay False."""
        self._assert_not_market_price(tmp_path, "Objetivo de eficiencia: 45%.")

    def test_c_minimum_required_capital_is_not_market_price(self, tmp_path: Path) -> None:
        """C: bare "mínimo" (a regulatory minimum, not an intraday low) must stay False."""
        self._assert_not_market_price(tmp_path, "Capital mínimo requerido: 11,5%.")

    def test_d_result_at_fiscal_year_end_is_not_market_price(self, tmp_path: Path) -> None:
        """D: bare "cierre" (fiscal year end, not a quote) must stay False."""
        self._assert_not_market_price(
            tmp_path, "Resultado al cierre del ejercicio: ARS 200 millones."
        )

    def test_e_closed_at_a_value_is_market_price(self, tmp_path: Path) -> None:
        """E: "cerró en" (closed AT a value) is an explicit quote phrase."""
        self._assert_market_price(tmp_path, "GGAL.US cerró en USD 52.30.")

    def test_f_closing_price_phrase_is_market_price(self, tmp_path: Path) -> None:
        """F: "precio de cierre" (closing price) is an explicit quote phrase."""
        self._assert_market_price(tmp_path, "precio de cierre USD 52.30.")

    def test_g_price_target_phrase_is_market_price(self, tmp_path: Path) -> None:
        """G: "precio objetivo" (price target) is an explicit quote phrase."""
        self._assert_market_price(tmp_path, "precio objetivo USD 60.")

    def test_h_intraday_high_phrase_is_market_price(self, tmp_path: Path) -> None:
        """H: "máximo intradiario" (intraday high) is an explicit quote phrase."""
        self._assert_market_price(tmp_path, "máximo intradiario USD 54.")


class TestRecoveryPrompts:
    def test_correction_names_symbol_search_when_identity_unresolved(
        self, tmp_path: Path
    ) -> None:
        ledger = _ledger(tmp_path)
        validation = ledger.validate_final_answer("机器人ETF 现价 1.171。")

        prompt = ledger.correction_prompt(validation)

        assert "search_symbol" in prompt
        assert "get_market_data" in prompt
        assert "Do NOT ask the user to confirm or continue" in prompt

    def test_correction_asks_when_recovery_exhausted(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        validation = ledger.validate_final_answer("机器人ETF 现价 1.171。")
        for _ in range(MAX_GROUNDING_RECOVERY_ROUNDS):
            ledger.record_recovery("search_symbol")

        prompt = ledger.correction_prompt(validation)

        assert "Do NOT ask the user" not in prompt
        assert "ask for clarification" in prompt

    def test_recovery_prompt_points_at_the_tool(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        validation = ledger.validate_final_answer("机器人ETF 现价 1.171。")

        prompt = ledger.recovery_prompt("search_symbol", validation)

        assert "search_symbol" in prompt
        assert "Do NOT ask the user to confirm or continue" in prompt

    def test_recovery_summary_reflects_budget_state(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.record_recovery("search_symbol")

        summary = ledger.recovery_summary()

        assert summary["rounds"] == 1
        assert summary["max_rounds"] == MAX_GROUNDING_RECOVERY_ROUNDS
        assert summary["symbol_resolution_attempts"] == 1
        assert summary["price_evidence_attempts"] == 0


class _FailingDraftLLM:
    """Always produces an ungrounded premium conclusion with no tool calls."""

    def __init__(self) -> None:
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
    ) -> LLMResponse:
        self.calls += 1
        self.messages_history.append(list(messages))
        draft = "机器人ETF 现价 1.171，建议买入。"
        if on_text_chunk:
            on_text_chunk(draft)
        return LLMResponse(content=draft)

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        return LLMResponse(content="")


def _run_direct_loop(
    tmp_path: Path,
    llm: Any,
    max_iterations: int = 8,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    user_message: str = "分析机器人ETF并给出买入价",
) -> dict[str, Any]:
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        max_iterations=max_iterations,
        persistent_memory=pm,
        event_callback=(lambda event, data: events.append((event, data)))
        if events is not None
        else None,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    return agent.run(user_message=user_message)


def test_loop_runs_recovery_before_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rejected draft must drive search_symbol recovery before falling back."""
    from src.agent.trace import TraceWriter

    llm = _FailingDraftLLM()
    events: list[tuple[str, dict[str, Any]]] = []

    result = _run_direct_loop(tmp_path, llm, max_iterations=6, events=events)

    trace = TraceWriter.read(tmp_path / "run")
    recovery_entries = [e for e in trace if e.get("type") == "grounding_recovery"]
    # Symbol resolution budget is two: two recovery turns, then fallback.
    assert [e.get("action") for e in recovery_entries] == ["search_symbol", "search_symbol"]
    # Two recovery drafts, then the correction path: one draft handed back
    # and the one that ends revising. Recovery does not spend the revision
    # cap, and every rejection that leads to another draft is announced.
    assert llm.calls == 4
    statuses = [data for event, data in events if event == "grounding_status"]
    assert [(status["stage"], status["round"]) for status in statuses] == [
        ("revising", 1),
        ("revising", 2),
        ("revising", 3),
    ]
    # Recovery and correction steering must never be mid-conversation system
    # messages: Anthropic only accepts a single leading system block.
    assert_system_messages_only_lead(llm.messages_history)
    # The run still terminates fail-closed once recovery is exhausted: with no
    # observed price at all there is nothing a redacted release could stand
    # on, so the canned refusal is the answer, not a cut-down draft.
    assert result["content"]
    assert "安全门槛拒绝" in result["content"]


# ---------------------------------------------------------------------------
# #GGAL-D: a validated reply after a declined recovery must not silently
# replace the rejected research draft as "success". The detection is
# structural (figure count), never a length or natural-language-word
# heuristic — see ``pending_recovery_stub``'s own docstring.
# ---------------------------------------------------------------------------


class TestPendingRecoveryStub:
    def test_stub_after_declined_recovery_is_detected(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        rejected_draft = "562500.SS 现价 9.999。"
        validation = ledger.validate_final_answer(rejected_draft)
        recovery = ledger.recovery_action(validation)
        assert recovery == "get_market_data"
        ledger.record_recovery(recovery, draft=rejected_draft, validation=validation)

        # The model declines the tool and replies with a short operational
        # message instead — no measured figure at all.
        stub_reply = "无法调用 get_market_data，本次分析不涉及市场价格。"
        stub_validation = ledger.validate_final_answer(stub_reply)
        assert stub_validation.valid is True  # nothing to check, passes trivially

        stub = ledger.pending_recovery_stub(stub_reply)

        assert stub is not None
        assert stub[0] == rejected_draft
        assert stub[1] is validation

    def test_a_reply_with_a_measured_figure_is_not_treated_as_a_stub(
        self, tmp_path: Path
    ) -> None:
        """Even a still-wrong revision that carries a real figure is a
        genuine attempt, not an operational meta-comment — length alone
        never decides this (#GGAL requirement 13).
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        rejected_draft = "562500.SS 现价 9.999。"
        validation = ledger.validate_final_answer(rejected_draft)
        recovery = ledger.recovery_action(validation)
        ledger.record_recovery(recovery, draft=rejected_draft, validation=validation)

        revised = "562500.SS 现价 8.888。"
        ledger.validate_final_answer(revised)

        assert ledger.pending_recovery_stub(revised) is None

    def test_fulfilled_recovery_clears_the_pending_stub_check(
        self, tmp_path: Path
    ) -> None:
        """Once the requested tool actually succeeds, whatever the model
        answers next is a real revision, never a stub.
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        rejected_draft = "562500.SS 现价 9.999。"
        validation = ledger.validate_final_answer(rejected_draft)
        recovery = ledger.recovery_action(validation)
        ledger.record_recovery(recovery, draft=rejected_draft, validation=validation)

        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": ["562500.SS"]},
            result=_market_payload(),
            call_id="market",
            success=True,
        )

        stub_reply = "稍后确认。"
        ledger.validate_final_answer(stub_reply)

        assert ledger.pending_recovery_stub(stub_reply) is None

    def test_pending_recovery_stub_is_consumed_once(self, tmp_path: Path) -> None:
        """Checking is one-shot: a second, unrelated valid reply later in the
        same run must not resurrect a resolved recovery.
        """
        ledger = _ledger(tmp_path)
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": "机器人ETF"},
            result=_resolver_payload(),
            call_id="resolve",
            success=True,
        )
        rejected_draft = "562500.SS 现价 9.999。"
        validation = ledger.validate_final_answer(rejected_draft)
        recovery = ledger.recovery_action(validation)
        ledger.record_recovery(recovery, draft=rejected_draft, validation=validation)

        stub_reply = "无法调用 get_market_data。"
        ledger.validate_final_answer(stub_reply)
        first = ledger.pending_recovery_stub(stub_reply)
        second = ledger.pending_recovery_stub(stub_reply)

        assert first is not None
        assert second is None


class _StubAfterRecoveryLLM:
    """A rich first draft with one ungrounded price claim; if the loop asks
    for ``get_market_data``, it declines with a short operational reply
    instead of calling the tool or revising the substantive research.
    """

    def __init__(self, first_draft: str, stub_reply: str) -> None:
        self.calls = 0
        self.first_draft = first_draft
        self.stub_reply = stub_reply
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
    ) -> LLMResponse:
        self.calls += 1
        self.messages_history.append(list(messages))
        content = self.first_draft if self.calls == 1 else self.stub_reply
        if on_text_chunk:
            on_text_chunk(content)
        return LLMResponse(content=content)

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResponse:
        return LLMResponse(content="")


def test_declined_recovery_stub_does_not_replace_the_research(
    tmp_path: Path,
) -> None:
    """#GGAL-D (14G/14H): a rejected substantive draft, followed by a
    declined ``get_market_data`` recovery and a short operational reply,
    must not end the run with that reply as the released "success" content
    (14G). With no observed price anywhere in the run, ``redacted_release``
    has nothing to stand on (same fail-closed rule
    ``test_loop_runs_recovery_before_fallback`` above pins), so this run
    falls through to ``safe_fallback`` instead — the important assertion is
    that the STUB never becomes "the" answer. See
    ``test_redacted_release_keeps_substantive_research_and_cuts_only_the_bad_figure``
    below for the companion case where a redaction CAN succeed (14H).
    """
    from src.agent.trace import TraceWriter

    first_draft = (
        "562500.SS 基本面回顾：过去一年跟踪指数表现稳定，规模持续增长，"
        "管理费率维持行业低位，流动性充足，机构持仓占比上升。"
        "现价约为 9.999 元，"
        "综合来看该基金长期跟踪误差较小，适合作为核心配置工具持有。"
    )
    stub_reply = "无法调用 get_market_data，本次分析不涉及市场价格。"
    llm = _StubAfterRecoveryLLM(first_draft, stub_reply)

    result = _run_direct_loop(tmp_path, llm, max_iterations=6)

    trace = TraceWriter.read(tmp_path / "run")
    assert any(entry.get("type") == "grounding_recovery" for entry in trace)
    assert any(entry.get("type") == "recovery_stub_discarded" for entry in trace)
    # The stub itself must never become the released content.
    assert stub_reply not in result["content"]
    assert result["content"]
    # A degraded release is explicitly flagged (#GGAL requirement 11/12) —
    # the API contract's "status" is untouched, but this signal is not.
    assert result.get("degraded") is True


def test_redacted_release_keeps_substantive_research_and_cuts_only_the_bad_figure(
    tmp_path: Path,
) -> None:
    """#GGAL-D (14H): once some real price evidence exists for the symbol,
    ``redacted_release`` cuts only the one figure that fails and keeps the
    rest of a substantive draft — this is what ``pending_recovery_stub``
    routes into instead of releasing an operational stub.
    """
    ledger = _ledger(tmp_path)
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "机器人ETF"},
        result=_resolver_payload(),
        call_id="resolve",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["562500.SS"]},
        result=_market_payload(),
        call_id="market",
        success=True,
    )
    draft = (
        "562500.SS 基本面回顾：过去一年跟踪指数表现稳定，规模持续增长，"
        "管理费率维持行业低位，流动性充足，机构持仓占比上升。"
        "现价约为 9.999 元，"
        "综合来看该基金长期跟踪误差较小，适合作为核心配置工具持有。"
    )
    validation = ledger.validate_final_answer(draft)
    assert validation.valid is False
    issue = next(
        issue for issue in validation.issues if issue["code"] == "numeric_claim_conflict"
    )
    assert issue["percent"] is False

    released = ledger.redacted_release(draft, validation)

    assert released is not None
    assert "跟踪误差较小" in released
    assert "机构持仓占比上升" in released
    assert "9.999" not in released


class TestFundamentalsGroundingRelease:
    """Closing four fundamentals/GGAL follow-ups in the release path:

    - ``safe_fallback`` narrates only the LAST validation's issues, so a
      stale draft's price problem cannot color the final message once the
      run has moved on to a purely fundamentals rejection;
    - ``redacted_release`` is fail-closed *selectively*: with zero
      ``price_records`` it can still redact a draft whose only relevant
      issues are explicitly ``market_price is False`` (a known fundamental),
      but still refuses when any relevant issue is ``True`` or unclassified
      (missing/None).

    ``market_price`` here is read exactly as ``policies.py`` produces it,
    never re-derived from wording in these tests.
    """

    @staticmethod
    def _ledger_ggal(tmp_path: Path) -> GroundingLedger:
        """Identity-locked on "GGAL.US" from the user message alone, with no
        resolver/market-data evidence — ``_price_records()`` stays empty.
        """
        return GroundingLedger(run_dir=tmp_path, user_message="GGAL.US fundamentals")

    def test_a_last_validation_wins_over_a_stale_price_issue(self, tmp_path: Path) -> None:
        """A. The first (rejected) draft carries a price issue; the second
        (also rejected) draft carries only a fundamentals issue. The final
        ``safe_fallback`` message must not mention price/prices/OHLC because
        of the FIRST draft — only the LAST validation decides the wording.
        """
        ledger = self._ledger_ggal(tmp_path)
        price_draft = "GGAL.US cerró en USD 52.30, con buen volumen en la sesión."
        price_validation = ledger.validate_final_answer(price_draft)
        assert price_validation.valid is False
        assert any(
            issue.get("market_price") is True for issue in price_validation.issues
        )

        fundamentals_draft = "GGAL.US ROE trimestral de 33.98%, estable frente al trimestre anterior."
        fundamentals_validation = ledger.validate_final_answer(fundamentals_draft)
        assert fundamentals_validation.valid is False
        assert all(
            issue.get("market_price") is not True
            for issue in fundamentals_validation.issues
        )

        message = ledger.safe_fallback()

        lowered = message.lower()
        for word in ("price", "prices", "ohlc", "market price"):
            assert word not in lowered, message
        assert "价格" not in message
        assert "行情" not in message

    def test_b_fundamentals_redaction_without_price_records(self, tmp_path: Path) -> None:
        """B. Identity locked, zero price_records, a substantive draft with one
        invalid fundamentals figure (market_price=False). ``redacted_release``
        must return substantive content with only the bad figure cut — not
        None.
        """
        ledger = self._ledger_ggal(tmp_path)
        draft = (
            "GGAL.US ROE trimestral de 33.98%, en línea con el promedio del sector "
            "bancario. La rentabilidad sobre activos también se mantuvo estable "
            "durante el período bajo análisis."
        )
        validation = ledger.validate_final_answer(draft)
        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is False
        assert not ledger._price_records()

        released = ledger.redacted_release(draft, validation)

        assert released is not None
        assert "33.98" not in released
        assert "rentabilidad sobre activos también se mantuvo estable" in released

    def test_c_real_price_still_fails_closed_without_price_records(
        self, tmp_path: Path
    ) -> None:
        """C. Identity locked, zero price_records, issue market_price=True.
        ``redacted_release`` must return None: a real price claim has nothing
        to stand on without any observed price anywhere in the run.
        """
        ledger = self._ledger_ggal(tmp_path)
        draft = "GGAL.US cerró en USD 52.30, tras una sesión con buen volumen."
        validation = ledger.validate_final_answer(draft)
        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "numeric_claim_unavailable"
        )
        assert issue.get("market_price") is True
        assert not ledger._price_records()

        assert ledger.redacted_release(draft, validation) is None

    def test_d_unclassified_market_price_still_fails_closed(self, tmp_path: Path) -> None:
        """D. Identity locked, zero price_records, a relevant issue whose
        market_price is missing/None (never classified by policies.py).
        ``redacted_release`` must return None: an unclassified figure is
        treated as a possible price, not a known fundamental.
        """
        ledger = self._ledger_ggal(tmp_path)
        draft = (
            "GGAL.US análisis fundamental: buen desempeño operativo con ratios "
            "estables.\n\n```figures\n1 | count | placeholder | \n```\n\n"
            "Además se observa un margen de 41.5% en el trimestre."
        )
        validation = ledger.validate_final_answer(draft)
        assert validation.valid is False
        issue = next(
            issue for issue in validation.issues if issue["code"] == "figure_undeclared"
        )
        assert issue.get("market_price") is None
        assert not ledger._price_records()

        assert ledger.redacted_release(draft, validation) is None

    def test_e_safe_fallback_wording_by_market_price(self, tmp_path: Path) -> None:
        """E. ``safe_fallback`` wording follows the LAST validation's
        market_price, not the issue code alone: a non-price
        ``numeric_claim_unavailable``/``figure_undeclared`` gets neutral
        wording, and an explicit ``market_price is True`` keeps price wording.
        """
        neutral_ledger = self._ledger_ggal(tmp_path)
        neutral_draft = "GGAL.US ROE trimestral de 33.98%, estable frente al trimestre anterior."
        neutral_validation = neutral_ledger.validate_final_answer(neutral_draft)
        assert neutral_validation.valid is False
        assert all(
            issue.get("market_price") is not True for issue in neutral_validation.issues
        )
        neutral_message = neutral_ledger.safe_fallback().lower()
        assert "price" not in neutral_message

        price_ledger = self._ledger_ggal(tmp_path / "price")
        price_draft = "GGAL.US cerró en USD 52.30, con buen volumen en la sesión."
        price_validation = price_ledger.validate_final_answer(price_draft)
        assert price_validation.valid is False
        assert any(issue.get("market_price") is True for issue in price_validation.issues)
        price_message = price_ledger.safe_fallback().lower()
        assert "price" in price_message
