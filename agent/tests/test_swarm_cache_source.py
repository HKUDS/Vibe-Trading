"""Cache-token capture and usage-provenance labeling in the swarm worker.

Companion to ``test_swarm_token_tracking.py`` (which pins the 2-tuple
contract of ``_estimate_tokens`` — untouched here). These tests pin the
extended contract:

* ``worker._measure_usage`` captures prompt-cache counts from provider
  ``usage_metadata`` using exactly the main loop's normalization contract
  (``src.product.usage._normalize_llm_usage``) and labels the counts'
  provenance (``"provider"`` vs ``"estimated"``);
* ``_estimate_tokens`` remains a thin 2-tuple wrapper over ``_measure_usage``;
* ``WorkerResult`` / ``SwarmRun`` carry cache fields + ``token_source`` with
  defaults, so ``run.json`` files persisted before this change still
  deserialize and runtime timeout/error constructions stay valid;
* worker exits (``completed`` AND ``cancelled``) carry real measured values,
  not silent defaults;
* the runtime retry wrapper preserves cache/``token_source`` across all three
  of its ``model_copy`` rewrites (cancel-before-retry, success, exhausted).
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.product.usage import _normalize_llm_usage
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmRun, SwarmTask, WorkerResult
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore
import src.swarm.worker as worker_mod
from src.swarm.worker import _estimate_tokens, _measure_usage, run_worker


# --------------------------------------------------------------------------- #
# _measure_usage — provider branch: cache capture + "provider" label
# --------------------------------------------------------------------------- #


def test_measure_usage_captures_cache_read_and_labels_provider() -> None:
    usage = {
        "input_tokens": 1200,
        "output_tokens": 30,
        "total_tokens": 1230,
        "input_token_details": {"cache_read": 70000},
    }
    m = _measure_usage([], LLMResponse(content="x", usage_metadata=usage))
    assert m.input_tokens == 1200
    assert m.output_tokens == 30
    assert m.cache_read_tokens == 70000
    assert m.cache_creation_tokens == 0
    assert m.token_source == "provider"


def test_measure_usage_cache_creation_sums_all_three_keys() -> None:
    usage = {
        "input_tokens": 500,
        "output_tokens": 12,
        "input_token_details": {
            "cache_creation": 10,
            "ephemeral_5m_input_tokens": 20,
            "ephemeral_1h_input_tokens": 30,
        },
    }
    m = _measure_usage([], LLMResponse(content="x", usage_metadata=usage))
    assert m.cache_creation_tokens == 60
    assert m.cache_read_tokens == 0
    assert m.token_source == "provider"


@pytest.mark.parametrize("details", [
    None,
    {},
    {"cache_read": 700},
    {"cache_creation": 900},
    {"ephemeral_5m_input_tokens": 50},
    {"ephemeral_1h_input_tokens": 25},
    {"cache_read": 700, "cache_creation": 10,
     "ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 30},
    {"cache_read": None},
])
def test_measure_usage_matches_normalize_llm_usage_per_key(details: dict | None) -> None:
    """The swarm must not grow a second cache-normalization contract: for
    every payload shape, ``_measure_usage`` returns exactly what
    ``_normalize_llm_usage`` — the main loop's normalizer behind
    ``llm_usage.json`` — reports per key."""
    usage: dict = {"input_tokens": 1200, "output_tokens": 30}
    if details is not None:
        usage["input_token_details"] = details
    normalized = _normalize_llm_usage(usage)
    assert normalized is not None
    m = _measure_usage([], LLMResponse(content="x", usage_metadata=usage))
    assert m.input_tokens == normalized["input_tokens"]
    assert m.output_tokens == normalized["output_tokens"]
    assert m.cache_read_tokens == normalized.get("cache_read_tokens", 0)
    assert m.cache_creation_tokens == normalized.get("cache_creation_tokens", 0)
    assert m.token_source == "provider"


# --------------------------------------------------------------------------- #
# _measure_usage — fallback branch: len//4 + "estimated" label
# --------------------------------------------------------------------------- #


def test_measure_usage_falls_back_to_len_heuristic_and_labels_estimated() -> None:
    messages = [{"role": "user", "content": "hello world"}]
    response = LLMResponse(content="abcdefgh", usage_metadata=None)
    m = _measure_usage(messages, response)
    assert m.input_tokens == len(json.dumps(messages, ensure_ascii=False)) // 4
    assert m.output_tokens == len("abcdefgh") // 4
    assert m.cache_read_tokens == 0
    assert m.cache_creation_tokens == 0
    assert m.token_source == "estimated"


def test_measure_usage_labels_all_zero_usage_metadata_as_estimated() -> None:
    """An all-zero usage payload is 'no real data' — the heuristic takes over
    and the label must say so, never 'provider'."""
    response = LLMResponse(
        content="hi back",
        usage_metadata={"input_tokens": 0, "output_tokens": 0},
    )
    m = _measure_usage([{"role": "user", "content": "hello"}], response)
    assert m.input_tokens > 0
    assert m.token_source == "estimated"


@pytest.mark.parametrize("usage_metadata", [
    None,
    {"input_tokens": 100, "output_tokens": 20},
    {"input_tokens": 100, "output_tokens": 20,
     "input_token_details": {"cache_read": 70, "cache_creation": 30}},
])
def test_estimate_tokens_stays_a_two_tuple_wrapper(usage_metadata: dict | None) -> None:
    """The legacy 2-tuple signature is a contract (6 call sites in
    test_swarm_token_tracking.py unpack it); it must equal the first two
    fields of _measure_usage for every payload class."""
    messages = [{"role": "user", "content": "abc"}]
    response = LLMResponse(content="some text", usage_metadata=usage_metadata)
    m = _measure_usage(messages, response)
    assert _estimate_tokens(messages, response) == (m.input_tokens, m.output_tokens)


# --------------------------------------------------------------------------- #
# Models — defaults keep old persisted data and runtime constructions valid
# --------------------------------------------------------------------------- #

# A real pre-cache-tracking run.json shape: every SwarmRun field that existed
# before this change, and none of the new ones.
_OLD_RUN_JSON = """
{
  "id": "9f1c0a7e-4c2e-4b7a-9f1c-0a7e4c2e4b7a",
  "preset_name": "investment_committee",
  "status": "completed",
  "user_vars": {"target": "AAPL.US"},
  "agents": [
    {
      "id": "bull",
      "role": "Bull analyst",
      "system_prompt": "Argue the bull case.",
      "tools": ["get_market_data"],
      "skills": [],
      "max_iterations": 8,
      "timeout_seconds": 300,
      "model_name": null,
      "max_retries": 1
    }
  ],
  "tasks": [
    {
      "id": "t-bull",
      "agent_id": "bull",
      "prompt_template": "Argue the bull case for {target}.",
      "depends_on": [],
      "blocked_by": [],
      "input_from": {},
      "status": "completed",
      "summary": "Bull case delivered.",
      "artifacts": [],
      "error": null,
      "started_at": "2026-09-01T10:00:00+00:00",
      "completed_at": "2026-09-01T10:05:00+00:00",
      "worker_iterations": 3
    }
  ],
  "created_at": "2026-09-01T10:00:00+00:00",
  "completed_at": "2026-09-01T10:05:00+00:00",
  "final_report": "Consensus: hold.",
  "total_input_tokens": 12345,
  "total_output_tokens": 678,
  "provider": "anthropic",
  "model": "claude-x",
  "reasoning_effort": null,
  "use_responses_api": null,
  "grounding_data": null
}
"""


def test_old_run_json_deserializes_with_default_cache_fields() -> None:
    """stale_state guard: run.json files written before cache tracking must
    still load, with the new fields at honest defaults (0 / None — never a
    fabricated 'provider' label)."""
    run = SwarmRun.model_validate_json(_OLD_RUN_JSON)
    assert run.total_input_tokens == 12345
    assert run.total_output_tokens == 678
    assert run.cache_read_tokens == 0
    assert run.cache_creation_tokens == 0
    assert run.token_source is None


def test_runtime_style_worker_result_construction_defaults_new_fields() -> None:
    """runtime.py builds WorkerResult(status=..., summary="", error=...) at its
    timeout/exception paths without any token fields; that must stay valid."""
    timeout = WorkerResult(
        status="timeout", summary="", error="Worker exceeded layer deadline of 600s",
    )
    assert timeout.cache_read_tokens == 0
    assert timeout.cache_creation_tokens == 0
    assert timeout.token_source is None

    failed = WorkerResult(status="failed", summary="", error="boom")
    assert failed.cache_read_tokens == 0
    assert failed.cache_creation_tokens == 0
    assert failed.token_source is None


# --------------------------------------------------------------------------- #
# Worker exits — real values, not defaults (misleading_success_output guard)
# --------------------------------------------------------------------------- #

_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "noop_tool", "description": "no-op",
        "parameters": {"type": "object", "properties": {}},
    },
}

_PROVIDER_USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "input_token_details": {"cache_read": 70, "cache_creation": 30},
}


class _Registry:
    """Registry stand-in exposing one no-op tool."""

    def __init__(self) -> None:
        self.policy = ToolPolicy.from_config(get_env_config())

    def get_definitions(self) -> list[dict]:
        """Return the single scripted tool definition."""
        return [_TOOL_DEF]

    def get(self, name: str):
        """Local-only registry: no MCPRemoteTool metadata."""
        return None

    def execute(self, name: str, args: dict) -> str:
        """Return a benign JSON envelope for any dispatch."""
        return '{"ok": true, "data": {}}'

    def check_policy(self, name, arguments):
        return self.policy(name, arguments)


class _ScriptedLLM:
    """``ChatLLM`` stand-in returning scripted responses in order; optionally
    flips a cancel event during a chosen call, like ``should_cancel`` firing
    mid-stream."""

    def __init__(
        self,
        responses: list[LLMResponse],
        cancel_event: threading.Event | None = None,
        cancel_on_call: int | None = None,
    ) -> None:
        self._responses = responses
        self._cancel_event = cancel_event
        self._cancel_on_call = cancel_on_call
        self.calls = 0

    def __call__(self, *args, **kwargs) -> "_ScriptedLLM":
        """Support ``ChatLLM(model_name=...)`` constructor-style patching."""
        return self

    def close(self) -> None:
        """No-op: the stub owns no HTTP client."""
        return None

    def stream_chat(self, messages, tools=None, on_text_chunk=None, timeout=None,
                    should_cancel=None, on_waiting_chunk=None) -> LLMResponse:
        """Return the next scripted response, optionally cancelling first."""
        idx = self.calls
        self.calls += 1
        if (
            self._cancel_on_call is not None
            and idx == self._cancel_on_call
            and self._cancel_event is not None
        ):
            self._cancel_event.set()
        return self._responses[min(idx, len(self._responses) - 1)]


def _drive_worker(
    tmp_path: Path,
    llm: _ScriptedLLM,
    *,
    tools: list[str],
    max_iterations: int = 3,
    cancel_event: threading.Event | None = None,
) -> WorkerResult:
    agent = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="You analyse.",
        tools=tools,
        skills=[],
        max_iterations=max_iterations,
        timeout_seconds=60,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Do the thing.")
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: _Registry()),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        return run_worker(
            policy=ToolPolicy.from_config(get_env_config()),
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
            event_callback=None,
            cancel_event=cancel_event,
        )


def test_completed_exit_carries_real_cache_values_and_provider_label(tmp_path) -> None:
    final = LLMResponse(
        content=(
            "Momentum is positive: price closed above its 20-day average on "
            "rising volume, so the trend currently favors buyers."
        ),
        usage_metadata=_PROVIDER_USAGE,
    )
    result = _drive_worker(tmp_path, _ScriptedLLM([final]), tools=[])
    assert result.status == "completed"
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cache_read_tokens == 70, "completed exit must carry real cache reads, not the 0 default"
    assert result.cache_creation_tokens == 30, "completed exit must carry real cache creation, not the 0 default"
    assert result.token_source == "provider"


def test_cancelled_exit_carries_accumulated_cache_values(tmp_path) -> None:
    """Cancellation retains the usage reported on both responses."""
    cancel_event = threading.Event()
    tool_turn = LLMResponse(
        content="",
        tool_calls=[ToolCallRequest(id="c1", name="noop_tool", arguments={})],
        finish_reason="tool_calls",
        usage_metadata=_PROVIDER_USAGE,
    )
    llm = _ScriptedLLM([tool_turn], cancel_event=cancel_event, cancel_on_call=1)

    result = _drive_worker(
        tmp_path, llm, tools=["noop_tool"], max_iterations=3, cancel_event=cancel_event,
    )

    assert result.status == "cancelled"
    assert llm.calls == 2
    assert result.input_tokens == 200
    assert result.output_tokens == 40
    assert result.cache_read_tokens == 140
    assert result.cache_creation_tokens == 60
    assert result.token_source == "provider"


_FINAL_TEXT = (
    "Momentum is positive: price closed above its 20-day average on "
    "rising volume, so the trend currently favors buyers."
)


def _two_iteration_result(tmp_path: Path, usage0: dict | None,
                          usage1: dict | None) -> WorkerResult:
    """Drive a worker through exactly two measured iterations: a tool turn
    (usage0) then a final text turn (usage1)."""
    tool_turn = LLMResponse(
        content="",
        tool_calls=[ToolCallRequest(id="c1", name="noop_tool", arguments={})],
        finish_reason="tool_calls",
        usage_metadata=usage0,
    )
    final = LLMResponse(content=_FINAL_TEXT, usage_metadata=usage1)
    return _drive_worker(
        tmp_path, _ScriptedLLM([tool_turn, final]), tools=["noop_tool"],
    )


def test_estimated_then_provider_total_stays_estimated(tmp_path) -> None:
    """D1 regression: iteration 0 falls back to the heuristic (no usage),
    iteration 1 reports real usage. The cumulative total mixes heuristic +
    real counts, so the label must stay sticky-'estimated' — a later
    provider iteration never launders a partly-heuristic total into billed
    data."""
    result = _two_iteration_result(tmp_path, None, _PROVIDER_USAGE)
    assert result.status == "completed"
    assert result.token_source == "estimated"
    # Mixed sum: provider's 100 input tokens PLUS iteration 0's heuristic
    # contribution (system+user prompt chars // 4, necessarily > 0).
    assert result.input_tokens > 100
    assert result.output_tokens == 20  # "" // 4 + provider 20
    assert result.cache_read_tokens == 70
    assert result.cache_creation_tokens == 30


def test_provider_then_provider_total_stays_provider(tmp_path) -> None:
    result = _two_iteration_result(tmp_path, _PROVIDER_USAGE, _PROVIDER_USAGE)
    assert result.status == "completed"
    assert result.token_source == "provider"
    assert result.input_tokens == 200
    assert result.output_tokens == 40
    assert result.cache_read_tokens == 140
    assert result.cache_creation_tokens == 60


def test_provider_then_estimated_total_stays_estimated(tmp_path) -> None:
    result = _two_iteration_result(tmp_path, _PROVIDER_USAGE, None)
    assert result.status == "completed"
    assert result.token_source == "estimated"
    assert result.input_tokens > 100
    assert result.output_tokens == 20 + len(_FINAL_TEXT) // 4
    assert result.cache_read_tokens == 70
    assert result.cache_creation_tokens == 30


# --------------------------------------------------------------------------- #
# Runtime retry wrapper — cache/token_source survive all 3 model_copy sites
# --------------------------------------------------------------------------- #


def _runtime(tmp_path: Path) -> SwarmRuntime:
    return SwarmRuntime(SwarmStore(base_dir=tmp_path / "runs"), policy=ToolPolicy.from_config(get_env_config()))


def _run_with_retries(
    runtime: SwarmRuntime,
    tmp_path: Path,
    results: list[WorkerResult],
    *,
    cancelled_during_wait: bool = False,
    max_retries: int = 2,
) -> WorkerResult:
    agent = SwarmAgentSpec(
        id="analyst", role="Analyst", system_prompt="Analyze", max_retries=max_retries,
    )
    task = SwarmTask(id="task-1", agent_id="analyst", prompt_template="Analyze")
    with (
        patch("src.swarm.runtime.run_worker", side_effect=results),
        patch("src.swarm.runtime._worker_retry_delay_s", return_value=0.0),
        patch(
            "src.swarm.runtime._wait_for_worker_retry",
            return_value=cancelled_during_wait,
        ),
    ):
        return runtime._run_worker_with_retries(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path / "run-1",
            event_callback=None,
            run_id="run-1",
            cancel_event=threading.Event() if cancelled_during_wait else None,
        )


def _result(status: str, in_tok: int, cache_read: int, cache_creation: int,
            source: str | None) -> WorkerResult:
    return WorkerResult(
        status=status,  # type: ignore[arg-type]
        summary=f"{status}-{in_tok}",
        error="overloaded" if status == "failed" else None,
        input_tokens=in_tok,
        output_tokens=in_tok // 2,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        token_source=source,
    )


def test_retry_cancel_before_retry_preserves_cache_and_source(tmp_path) -> None:
    """model_copy site 1 (the trap): cancelling during the retry wait rewrites
    the failed result — cache/token_source must be in the update dict, or the
    cancelled worker silently mislabels its usage."""
    result = _run_with_retries(
        _runtime(tmp_path), tmp_path,
        [_result("failed", 12, 70, 30, "provider")],
        cancelled_during_wait=True,
    )
    assert result.status == "cancelled"
    assert result.input_tokens == 12
    assert result.cache_read_tokens == 70
    assert result.cache_creation_tokens == 30
    assert result.token_source == "provider"


def test_retry_success_accumulates_cache_and_source(tmp_path) -> None:
    """model_copy site 2: the success rewrite carries cumulative cache."""
    result = _run_with_retries(
        _runtime(tmp_path), tmp_path,
        [
            _result("failed", 10, 100, 40, "provider"),
            _result("completed", 6, 200, 0, "provider"),
        ],
    )
    assert result.status == "completed"
    assert result.input_tokens == 16
    assert result.cache_read_tokens == 300
    assert result.cache_creation_tokens == 40
    assert result.token_source == "provider"


def test_retry_success_keeps_estimated_label_sticky(tmp_path) -> None:
    """One estimated attempt contaminates the cumulative total — the merged
    label must stay 'estimated' even when the final attempt was provider."""
    result = _run_with_retries(
        _runtime(tmp_path), tmp_path,
        [
            _result("failed", 10, 0, 0, "estimated"),
            _result("completed", 6, 200, 5, "provider"),
        ],
    )
    assert result.status == "completed"
    assert result.token_source == "estimated"


def test_retry_exhausted_accumulates_cache_and_source(tmp_path) -> None:
    """model_copy site 3: the exhausted rewrite carries cumulative cache."""
    result = _run_with_retries(
        _runtime(tmp_path), tmp_path,
        [
            _result("failed", 10, 100, 40, "provider"),
            _result("failed", 8, 40, 10, "provider"),
        ],
        max_retries=1,
    )
    assert result.status == "failed"
    assert result.input_tokens == 18
    assert result.cache_read_tokens == 140
    assert result.cache_creation_tokens == 50
    assert result.token_source == "provider"
