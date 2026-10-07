"""Compaction follows the model's real window, not a fixed estimated 40K.

Reproduced on 2026-09-29 (v0.1.15 + deepseek-v4-pro, "A股和港股通的游戏公司，
找出最值得投资的三家"): layer 1 fired from iteration 3 because the system prompt
alone estimates at ~12.5K of the 20K trigger, kept only the last three tool
results, and the run re-fetched the same seven filings 4-5 times each until
``no_progress`` at iteration 16. Same code with the threshold raised: re-fetches
54 -> 0 over 8 runs. These tests pin both sides: a healthy run of that size
loses nothing, and a small window still compacts before it overflows.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.agent.context_budget as cb
from src.agent.context_budget import (
    CompactionBudget,
    ContextMeter,
    estimate_tokens,
    is_context_overflow,
    parse_context_limit,
    resolve_window,
)
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.config.accessor import reset_env_config
from src.providers.chat import ProviderStreamError

#: Real input tokens of the first request of a research run on 2026-09-29
#: (deepseek-v4-pro llm_usage.json: 47,661) — system prompt plus 107 tool schemas.
STATIC_TOKENS = 48_000
#: The largest healthy run measured that day sent 154K real input tokens.
LARGEST_HEALTHY_PROMPT = 154_000


# --------------------------------------------------------------------------
# Window resolution
# --------------------------------------------------------------------------


def test_window_comes_from_the_catalog_for_the_reported_models() -> None:
    assert resolve_window("openai-codex", "openai-codex/gpt-6-sol")[0] == 272_000
    assert resolve_window("openai-codex", "gpt-6-sol")[0] == 272_000
    assert resolve_window("deepseek", "deepseek-v4-pro")[0] == 1_000_000
    assert resolve_window("openrouter", "deepseek/deepseek-v4-pro")[0] == 1_000_000


def test_provider_scoped_entries_do_not_leak_to_other_providers() -> None:
    # The 272K is what the Codex backend publishes; another provider serving a
    # model of the same name is not covered by that source.
    assert resolve_window("openai", "gpt-6-sol") == (128_000, "default")


def test_resolution_order_env_then_learned_then_catalog() -> None:
    assert resolve_window("deepseek", "deepseek-v4-pro", env_window=64_000, learned_window=32_000) == (
        64_000, "env:VIBE_TRADING_CONTEXT_WINDOW")
    assert resolve_window("deepseek", "deepseek-v4-pro", learned_window=32_000) == (
        32_000, "learned:context_length_error")
    assert resolve_window("someone", "unknown-model") == (128_000, "default")


def test_every_catalog_entry_names_its_source() -> None:
    catalog = json.loads((Path(cb.__file__).resolve().parents[1] / "providers" / "context_windows.json").read_text())
    for entry in catalog["models"]:
        assert entry["source"].strip(), entry
        assert entry["window"] >= 1_000
        re.compile(entry["pattern"])


def test_deprecated_token_threshold_is_ignored_with_a_warning(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TOKEN_THRESHOLD", "40000")
    monkeypatch.setattr(cb, "_warned_token_threshold", False)
    with caplog.at_level(logging.WARNING, logger=cb.logger.name):
        window = resolve_window("deepseek", "deepseek-v4-pro")
        resolve_window("deepseek", "deepseek-v4-pro")
    assert window[0] == 1_000_000
    assert sum("TOKEN_THRESHOLD is deprecated" in r.message for r in caplog.records) == 1


# --------------------------------------------------------------------------
# Thresholds: both sides
# --------------------------------------------------------------------------


@pytest.mark.parametrize("provider,model", [
    ("openai-codex", "openai-codex/gpt-6-sol"),
    ("deepseek", "deepseek-v4-pro"),
])
def test_a_healthy_run_of_the_largest_measured_size_is_never_compacted(provider, model) -> None:
    window, source = resolve_window(provider, model)
    budget = CompactionBudget(window=window, source=source, max_tokens=200_000, static_tokens=STATIC_TOKENS)
    assert budget.micro_at > LARGEST_HEALTHY_PROMPT
    assert budget.compact_at > LARGEST_HEALTHY_PROMPT


@pytest.mark.parametrize("window", [128_000, 200_000, 272_000, 1_000_000])
def test_every_layer_fires_before_the_window_is_full(window) -> None:
    budget = CompactionBudget(window=window, source="t", max_tokens=200_000, static_tokens=STATIC_TOKENS)
    assert budget.micro_at < budget.collapse_at < budget.compact_at <= window * cb.USABLE_FRACTION


def test_cost_cap_bounds_a_huge_window() -> None:
    budget = CompactionBudget(window=1_000_000, source="t", max_tokens=200_000, static_tokens=STATIC_TOKENS)
    assert budget.compact_at == 200_000


def test_a_window_smaller_than_the_static_prompt_still_has_a_floor() -> None:
    budget = CompactionBudget(window=32_000, source="t", max_tokens=200_000, static_tokens=STATIC_TOKENS)
    assert budget.conversation == cb.MIN_CONVERSATION_TOKENS


# --------------------------------------------------------------------------
# Measuring the prompt
# --------------------------------------------------------------------------


def test_meter_anchors_on_reported_tokens_and_tracks_growth_and_shrinkage() -> None:
    messages = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 400}]
    meter = ContextMeter()
    assert meter.tokens(messages, 1_000) == estimate_tokens(messages) + 1_000
    meter.observe(50_000, messages)
    assert meter.static_tokens == 50_000 - estimate_tokens(messages[1:])
    grown = messages + [{"role": "tool", "content": "x" * 4_000}]
    assert meter.tokens(grown, 1_000) == 50_000 + estimate_tokens(grown) - estimate_tokens(messages)
    assert meter.tokens(messages[:1], 1_000) < 50_000


def test_meter_ignores_missing_or_bogus_usage() -> None:
    meter = ContextMeter()
    for value in (None, 0, -5, True, "900"):
        meter.observe(value, [{"role": "system", "content": "s"}])
    assert meter.static_tokens is None


def test_overflow_errors_are_recognised_and_their_limit_read() -> None:
    deepseek = ("Error code: 400 - This model's maximum context length is 131072 tokens. "
                "However, you requested 140000 tokens.")
    assert is_context_overflow(deepseek)
    assert parse_context_limit(deepseek) == 131_072
    assert is_context_overflow('{"error": {"code": "context_length_exceeded"}}')
    assert is_context_overflow("prompt is too long: 210000 tokens > 200000 maximum")
    assert not is_context_overflow("The usage limit has been reached")
    assert not is_context_overflow("Insufficient Balance")


# --------------------------------------------------------------------------
# The loop, end to end with an offline model
# --------------------------------------------------------------------------


class FilingTool(BaseTool):
    """Readonly stand-in for get_financial_statements (~6K tokens per filing)."""

    name = "fetch_filing"
    description = "Fetch one company's annual indicators (offline test double)."
    parameters = {"type": "object", "properties": {"filing": {"type": "string"}}, "required": ["filing"]}
    is_readonly = True

    def __init__(self, payload_chars: int) -> None:
        self.payload_chars = payload_chars
        self.calls: list[str] = []

    def execute(self, **kwargs: object) -> str:
        self.calls.append(str(kwargs["filing"]))
        return json.dumps({"ok": True, "filing": kwargs["filing"], "rows": "7" * self.payload_chars})


class ComparisonLLM:
    """Fetches each filing once, then answers; reports realistic usage.

    It keeps its own progress, the way a model carries on from a compaction
    summary. A model that re-fetches whatever it can no longer see is the
    failure under test; faking that here would test the fake.
    """

    def __init__(self, model: str, codes: list[str], *, overflow_above: int | None = None) -> None:
        self.model_name = model
        self.reasoning = "r" * REASONING_CHARS
        self.codes = codes
        self.overflow_above = overflow_above
        self.sent_tokens: list[int] = []
        self.overflows = 0
        self.fetched = 0

    def _input_tokens(self, messages: list[dict]) -> int:
        return STATIC_TOKENS + estimate_tokens(messages[1:])

    def stream_chat(self, messages: list[dict], **kwargs: object) -> SimpleNamespace:
        tokens = self._input_tokens(messages)
        if self.overflow_above is not None and tokens > self.overflow_above:
            self.overflows += 1
            original = RuntimeError(
                f"Error code: 400 - This model's maximum context length is {self.overflow_above} "
                f"tokens. However, you requested {tokens} tokens."
            )
            original.status_code = 400
            raise ProviderStreamError(provider="deepseek", model=self.model_name, original=original)
        self.sent_tokens.append(tokens)
        usage = {"input_tokens": tokens, "output_tokens": 20, "total_tokens": tokens + 20}
        if self.fetched < len(self.codes):
            code = self.codes[self.fetched]
            call = SimpleNamespace(id=f"call-{self.fetched}", name="fetch_filing", arguments={"filing": code})
            self.fetched += 1
            return SimpleNamespace(content="", reasoning_content=self.reasoning, has_tool_calls=True,
                                   tool_calls=[call], usage_metadata=usage, provider_items=[])
        return SimpleNamespace(content="The comparison is complete.", reasoning_content=None,
                               has_tool_calls=False, tool_calls=[], usage_metadata=usage, provider_items=[])

    def chat(self, messages: list[dict], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(content="## Summary\nFetched filings for the comparison.")


#: Filing ids, not tickers: a symbol-shaped argument sends the call through the
#: grounding identity gate, which is not what these tests exercise.
CODES = [f"filing-{i:02d}" for i in range(1, 21)]
#: Tool results reach the model cut to 10,000 chars (config/limits.py), so what
#: made real runs grow was the reasoning text replayed each turn as well. With
#: both, 20 filings reach ~158K real tokens: past the 154K healthy maximum.
REASONING_CHARS = 12_000


def _run(tmp_path: Path, monkeypatch, *, provider: str, model: str, payload_chars: int = 24_000,
         env_window: int | None = None, overflow_above: int | None = None):
    monkeypatch.setenv("LANGCHAIN_PROVIDER", provider)
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", model)
    if env_window:
        monkeypatch.setenv("VIBE_TRADING_CONTEXT_WINDOW", str(env_window))
    reset_env_config()
    tool = FilingTool(payload_chars)
    registry = ToolRegistry()
    registry.register(tool)
    llm = ComparisonLLM(model, CODES, overflow_above=overflow_above)
    loop = AgentLoop(registry=registry, llm=llm, max_iterations=30)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    loop.memory.run_dir = str(run_dir)
    result = loop.run("Compare these twelve game companies' annual indicators.")
    return result, tool, llm, loop, TraceWriter.read(run_dir)


def _cleared_codes(loop_messages_trace: list[dict]) -> list[str]:
    return [code for event in loop_messages_trace if event.get("type") == "microcompact_cleared"
            for code in event.get("tools", [])]


@pytest.mark.parametrize("provider,model", [
    ("openai-codex", "openai-codex/gpt-6-sol"),
    ("deepseek", "deepseek-v4-pro"),
])
def test_twelve_company_comparison_keeps_every_filing(tmp_path, monkeypatch, provider, model) -> None:
    # A .env still carrying the deprecated setting (the maintainer's did) must
    # not bring the old threshold back.
    monkeypatch.setenv("TOKEN_THRESHOLD", "40000")
    result, tool, llm, _, trace = _run(tmp_path, monkeypatch, provider=provider, model=model)

    assert result["status"] == "success", result.get("reason")
    assert max(llm.sent_tokens) >= LARGEST_HEALTHY_PROMPT  # as large as the real one
    assert tool.calls == CODES  # each filing fetched exactly once
    assert not [e for e in trace if e.get("type") in ("microcompact_cleared", "compact")]


def test_the_old_fixed_threshold_evicts_the_same_run(tmp_path, monkeypatch) -> None:
    """Mutation side: the pre-fix 40K estimate clears filings mid-comparison."""
    import src.agent.loop as loop_mod

    monkeypatch.setattr(loop_mod, "TOKEN_THRESHOLD", 40_000, raising=False)
    _, _, _, _, trace = _run(tmp_path, monkeypatch, provider="openai-codex", model="openai-codex/gpt-6-sol")
    assert [e for e in trace if e.get("type") == "microcompact_cleared"]


def test_a_small_window_compacts_before_it_overflows(tmp_path, monkeypatch) -> None:
    result, tool, llm, _, trace = _run(
        tmp_path, monkeypatch, provider="someone", model="small-model", env_window=100_000
    )
    assert result["status"] == "success", result.get("reason")
    assert max(llm.sent_tokens) <= 100_000 * cb.USABLE_FRACTION + 6_500  # one filing of growth
    cleared = [e for e in trace if e.get("type") in ("microcompact_cleared", "compact")]
    assert cleared


def test_a_context_length_error_teaches_the_window_and_the_run_recovers(tmp_path, monkeypatch) -> None:
    """Unknown model on the 128K default whose real window is 90K."""
    result, tool, llm, loop, trace = _run(
        tmp_path, monkeypatch, provider="someone", model="unknown-model", overflow_above=90_000
    )
    overflow = [e for e in trace if e.get("type") == "context_overflow"]

    assert result["status"] == "success", result.get("reason")
    assert overflow and overflow[0]["stated_limit"] == 90_000
    assert loop._learned_context_window == 90_000
    assert llm.overflows == 1  # recovered once, never overflowed again
    assert max(llm.sent_tokens) <= 90_000
    # A summary keeps static prompt + ~20K tail, so on a 90K window the prompt
    # stays near the line after compacting; each further summary must wait
    # for 8K of regrowth instead of firing every iteration (13 before).
    assert len([e for e in trace if e.get("type") == "compact"]) <= 8


class CompactingLLM(ComparisonLLM):
    """Asks for `compact` after two filings, as gpt/deepseek sometimes do."""

    def stream_chat(self, messages: list[dict], **kwargs: object) -> SimpleNamespace:
        if self.fetched >= 2 and not getattr(self, "asked", False):
            self.asked = True
            tokens = self._input_tokens(messages)
            self.sent_tokens.append(tokens)
            call = SimpleNamespace(id="call-compact", name="compact", arguments={"focus_topic": "games"})
            return SimpleNamespace(content="", reasoning_content=None, has_tool_calls=True, tool_calls=[call],
                                   usage_metadata={"input_tokens": tokens, "output_tokens": 5, "total_tokens": tokens},
                                   provider_items=[])
        return super().stream_chat(messages, **kwargs)


def test_a_model_asking_to_compact_a_small_prompt_is_declined(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai-codex")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "openai-codex/gpt-6-sol")
    reset_env_config()
    tool = FilingTool(4_000)
    registry = ToolRegistry()
    registry.register(tool)
    events: list[tuple[str, dict]] = []
    loop = AgentLoop(registry=registry, llm=CompactingLLM("openai-codex/gpt-6-sol", CODES[:4]),
                     max_iterations=30, event_callback=lambda n, d: events.append((n, d)))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    loop.memory.run_dir = str(run_dir)
    loop.run("Compare four companies.")
    trace = TraceWriter.read(run_dir)

    assert [e for e in trace if e.get("type") == "compact_declined"]
    assert not [e for e in trace if e.get("type") in ("compact", "compact_requested")]
    # The step is visible: a compact call used to emit no tool_call event at all.
    assert ("tool_call", "compact") in [(n, d.get("tool")) for n, d in events]


def test_layer_one_clears_oldest_results_only_until_the_prompt_fits() -> None:
    from src.agent.loop import KEEP_RECENT, _is_cleared, _microcompact

    messages = [{"role": "system", "content": "s"}]
    for i in range(10):
        messages.append({"role": "tool", "name": f"t{i}", "tool_call_id": f"c{i}", "content": "x" * 4_000})
    full = estimate_tokens(messages)
    target = full - 2_500  # needs ~2.5 results' worth cleared

    _microcompact(messages, target_tokens=target, measure=estimate_tokens)

    cleared = [m["name"] for m in messages[1:] if _is_cleared(m["content"])]
    assert cleared == ["t0", "t1", "t2"]  # oldest first, and no further
    assert estimate_tokens(messages) <= target
    # Legacy call (no target) still clears all but the last KEEP_RECENT.
    _microcompact(messages)
    assert sum(_is_cleared(m["content"]) for m in messages[1:]) == 10 - KEEP_RECENT


def test_a_window_too_small_for_the_summary_tail_does_not_resummarise_every_turn(tmp_path, monkeypatch) -> None:
    """80K window: static ~48K + the ~20K tail a summary keeps is over the 64K
    line, so without the regrowth rule every iteration paid for a summary."""
    result, tool, llm, _, trace = _run(
        tmp_path, monkeypatch, provider="someone", model="small-model", env_window=80_000
    )
    compacts = [e for e in trace if e.get("type") == "compact"]
    assert result["status"] == "success", result.get("reason")
    assert compacts
    assert len(compacts) <= len(CODES) // 2
