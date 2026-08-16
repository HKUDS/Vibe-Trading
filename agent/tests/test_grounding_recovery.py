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

from src.agent.grounding import (
    MAX_GROUNDING_RECOVERY_ROUNDS,
    MAX_PRICE_EVIDENCE_ATTEMPTS,
    MAX_SYMBOL_RESOLUTION_ATTEMPTS,
    GroundingLedger,
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
            "src.agent.grounding",
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


def _run_direct_loop(tmp_path: Path, llm: Any, max_iterations: int = 8) -> dict[str, Any]:
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        max_iterations=max_iterations,
        persistent_memory=pm,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent.memory.run_dir = str(run_dir)
    return agent.run(user_message="分析机器人ETF并给出买入价")


def test_loop_runs_recovery_before_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rejected draft must drive search_symbol recovery before falling back."""
    from src.agent.trace import TraceWriter

    llm = _FailingDraftLLM()

    result = _run_direct_loop(tmp_path, llm, max_iterations=6)

    trace = TraceWriter.read(tmp_path / "run")
    recovery_entries = [e for e in trace if e.get("type") == "grounding_recovery"]
    # Symbol resolution budget is two: two recovery turns, then fallback.
    assert [e.get("action") for e in recovery_entries] == ["search_symbol", "search_symbol"]
    assert llm.calls >= 3
    # Recovery and correction steering must never be mid-conversation system
    # messages: Anthropic only accepts a single leading system block.
    assert_system_messages_only_lead(llm.messages_history)
    # The run still terminates fail-closed once recovery is exhausted.
    assert result["content"]
