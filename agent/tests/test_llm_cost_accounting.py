"""Paid responses remain accounted for when compaction or Stop interrupts work."""

from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest
from langchain_core.messages import AIMessageChunk

from src.agent.llm_usage import _normalize_llm_usage
from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.agent.trace import TraceWriter
from src.config.accessor import reset_env_config
from src.providers.chat import ChatLLM, LLMResponse, ToolCallRequest


USAGE = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}


def _messages():
    return [{"role": "system", "content": "system"}, *[
        {"role": "user", "content": f"part {index} " + "x" * 29900}
        for index in range(8)
    ]]


def _agent(tmp_path, callback=None):
    llm = SimpleNamespace(
        model_name="offline-test",
        chat=Mock(return_value=LLMResponse(content="Summary retained.", usage_metadata=USAGE)),
        stream_chat=Mock(return_value=LLMResponse(content="Done.", usage_metadata=USAGE)),
    )
    agent = AgentLoop(registry=ToolRegistry(), llm=llm, event_callback=callback)
    agent.memory.run_dir = str(tmp_path)
    return agent, llm


def test_every_summary_chunk_is_persisted_and_reported(tmp_path):
    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))
    trace = TraceWriter(tmp_path)
    try:
        agent._auto_compact(_messages(), tmp_path, trace, iteration=7)
    finally:
        trace.close()
    assert llm.chat.call_count == 3
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["calls"] == 3
    assert report["totals"]["total_tokens"] == 3300
    assert all(row["purpose"] == "compaction" for row in report["per_iteration"])
    assert [data["total_tokens"] for kind, data in events if kind == "llm_usage"] == [1100] * 3


def test_summary_budget_cancellation_prevents_more_summaries_and_agent_call(tmp_path, monkeypatch):
    def monitor(kind, data):
        if kind == "llm_usage":
            agent.cancel()

    agent, llm = _agent(tmp_path, monitor)

    def compact(messages, run_dir, trace, iteration, current_iter):
        messages[:] = _messages()
        agent._auto_compact(messages, run_dir, trace, iteration=current_iter)

    monkeypatch.setattr(agent, "_compact_to_budget", compact)
    result = agent.run("Summarize the earlier work.")
    assert result["status"] == "cancelled"
    assert llm.chat.call_count == 1
    llm.stream_chat.assert_not_called()
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["total_tokens"] == 1100


@pytest.mark.parametrize("budget,summary_calls,agent_calls,status", [
    (1000, 1, 0, "failed"), (5000, 3, 1, "success"),
])
def test_summary_usage_obeys_goal_budget_without_stopping_funded_work(
    tmp_path, monkeypatch, budget, summary_calls, agent_calls, status,
):
    from src.goal import GoalStore

    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 0, raising=False)
    store = GoalStore()
    goal = store.replace_goal(
        session_id="summary-cost", objective="Summarize the earlier work.",
        criteria=["Summarize"], token_budget=budget,
    )
    agent, llm = _agent(tmp_path)

    def compact(messages, run_dir, trace, iteration, current_iter):
        messages[:] = _messages()
        agent._auto_compact(messages, run_dir, trace, iteration=current_iter)

    monkeypatch.setattr(agent, "_compact_to_budget", compact)
    result = agent.run("Summarize the earlier work.", session_id="summary-cost")
    assert result["status"] == status
    assert llm.chat.call_count == summary_calls
    assert llm.stream_chat.call_count == agent_calls
    updated = store.get_goal(goal.goal_id)
    assert updated.tokens_used == (summary_calls + agent_calls) * USAGE["total_tokens"]
    assert updated.turns_used == 1


def test_failed_summary_without_timeout_reports_unknown_usage(tmp_path, monkeypatch):
    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))
    llm.chat.side_effect = RuntimeError("Provider disconnected")
    monkeypatch.setattr("src.agent.loop._llm_timeout_seconds", lambda: 0)
    trace = TraceWriter(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="Provider disconnected"):
            agent._auto_compact(_messages(), tmp_path, trace, iteration=7)
    finally:
        trace.close()
    # Counted as unreported rather than announced: the live decision budget
    # halts on llm_usage_unavailable (see the live-budget test below).
    assert not [event for event in events if event[0] == "llm_usage_unavailable"]
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["unreported_calls"] == 1
    assert report["totals"]["calls"] == report["totals"]["total_tokens"] == 0


def test_cancelled_agent_response_keeps_reported_usage(tmp_path):
    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))

    def cancel_response(*args, **kwargs):
        agent.cancel()
        return LLMResponse(content="Do not release this partial text.", usage_metadata=USAGE)

    llm.stream_chat.side_effect = cancel_response
    result = agent.run("Say hello.")
    assert result["status"] == "cancelled"
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["total_tokens"] == 1100
    assert len([event for event in events if event[0] == "llm_usage"]) == 1
    llm.stream_chat.assert_called_once()


def test_cancelled_stream_keeps_usage_from_already_received_chunk():
    client = object.__new__(ChatLLM)
    import threading
    cancel = threading.Event()
    def stream(*args, **kwargs):
        cancel.set()  # Usage arrived before cancellation was observed by the host.
        yield AIMessageChunk(content="", usage_metadata=USAGE)
    client._llm = SimpleNamespace(stream=stream)
    client._prompt_cache_request = lambda messages: (messages, {})
    on_text = Mock()
    response = client.stream_chat(
        [{"role": "user", "content": "hello"}], should_cancel=cancel.is_set,
        on_text_chunk=on_text,
    )
    assert response.usage_metadata == USAGE
    on_text.assert_not_called()


def test_reasoning_is_a_reported_subset_of_output_not_added_again():
    normalized = _normalize_llm_usage({**USAGE, "output_token_details": {"reasoning": 80}})
    assert normalized["reasoning_tokens"] == 80
    assert normalized["output_tokens"] == 100
    assert normalized["total_tokens"] == 1100
    assert "reasoning_tokens" not in _normalize_llm_usage(USAGE)


def test_goal_token_budget_stops_current_turn_and_blocks_unfunded_retry(tmp_path, monkeypatch):
    from src.goal import GoalStore

    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    goal = store.replace_goal(
        session_id="cost-test", objective="Summarize the project files.",
        criteria=["Read the file"], token_budget=1000,
    )
    agent, llm = _agent(tmp_path)
    llm.stream_chat.side_effect = [
        LLMResponse(content="", tool_calls=[ToolCallRequest(
            id="should-not-run", name="read_file", arguments={"path": "report.txt"},
        )], usage_metadata=USAGE),
        LLMResponse(content="Done.", usage_metadata=USAGE),
    ]
    result = agent.run("Continue the goal.", session_id="cost-test")
    assert result["status"] == "failed"
    assert "goal_token_budget_exhausted" in result["reason"]
    llm.stream_chat.assert_called_once()
    assert result["react_trace"] == []
    assert store.get_goal(goal.goal_id).tokens_used == 1100

    # An ordinary retry cannot silently restart spending on the exhausted goal.
    agent.run("Continue.", session_id="cost-test")
    llm.stream_chat.assert_called_once()


@pytest.mark.parametrize("limit", [None, 2048])
def test_native_deepseek_forwards_configured_output_limit(monkeypatch, limit):
    from src.providers import llm as provider

    factory = Mock(return_value=object())
    monkeypatch.setattr(provider, "import_module", lambda name: SimpleNamespace(ChatDeepSeek=factory))
    monkeypatch.setattr(provider, "get_llm_credentials", lambda *args: {
        "api_key": "test-key", "base_url": "https://example.invalid",
    })
    if limit is None:
        monkeypatch.delenv("LANGCHAIN_MAX_TOKENS", raising=False)
    else:
        monkeypatch.setenv("LANGCHAIN_MAX_TOKENS", str(limit))
    reset_env_config()
    provider._build_native_deepseek(model="configured-model", temperature=0)
    kwargs = factory.call_args.kwargs
    assert kwargs.get("max_tokens") == limit
    assert ("max_tokens" in kwargs) == (limit is not None)
    assert kwargs["model"] == "configured-model"


def test_native_deepseek_output_limit_reaches_http_request(monkeypatch):
    """Exercise the optional real adapter and SDK without contacting a provider."""
    import httpx
    from src.providers import llm as provider

    native = pytest.importorskip("langchain_deepseek")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline-response", "object": "chat.completion", "created": 0,
            "model": "deepseek-chat", "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello"},
            }], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        })

    monkeypatch.setenv("LANGCHAIN_MAX_TOKENS", "2048")
    monkeypatch.setattr(provider, "get_llm_credentials", lambda *args: {
        "api_key": "offline-test-key", "base_url": "https://example.invalid/v1",
    })
    reset_env_config()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        def factory(**kwargs):
            return native.ChatDeepSeek(**kwargs, http_client=client)

        monkeypatch.setattr(provider, "import_module", lambda name: SimpleNamespace(ChatDeepSeek=factory))
        adapter = provider._build_native_deepseek(model="deepseek-chat", temperature=0)
        response = adapter.invoke("Hello")

    assert response.content == "Hello"
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 2048


@pytest.mark.parametrize("provider_name,model,field", [
    ("deepseek", "deepseek-v4-pro", "max_tokens"),
    ("openai", "gpt-4o", "max_completion_tokens"),
])
def test_compatible_output_limit_uses_the_provider_wire_field(provider_name, model, field):
    import httpx
    from src.providers.llm import ChatOpenAIWithReasoning

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline", "object": "chat.completion", "created": 0,
            "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Done"}}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = ChatOpenAIWithReasoning(
            model=model, api_key="offline", base_url="https://example.invalid/v1",
            max_tokens=8192, http_client=client,
        )
        adapter._vibe_provider = provider_name
        adapter.invoke("Hello")
    assert requests[0][field] == 8192
    other = "max_completion_tokens" if field == "max_tokens" else "max_tokens"
    assert other not in requests[0]


@pytest.mark.parametrize("recover", [True, False])
def test_failed_stream_usage_is_counted_before_retry(tmp_path, monkeypatch, recover):
    from src.providers.chat import ProviderStreamError
    agent, llm = _agent(tmp_path)
    monkeypatch.setattr("src.agent.loop._stream_retry_backoff_s", lambda _: 0)
    def error():
        return ProviderStreamError(
            provider="deepseek", model="deepseek-v4-pro",
            original=ConnectionError("EOF"), usage_metadata=USAGE,
        )
    llm.stream_chat.side_effect = [error(), LLMResponse(content="Hello", usage_metadata=USAGE)
                                   if recover else error()]
    result = agent.run("Say hello.")
    assert result["status"] == ("success" if recover else "failed")
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["calls"] == 2
    assert report["totals"]["total_tokens"] == USAGE["total_tokens"] * 2
    assert report["per_iteration"][0]["purpose"] == "failed_stream"


def _usage_events(events):
    return [(kind, data) for kind, data in events if kind.startswith("llm_usage")]


def test_failed_stream_without_usage_is_counted_not_announced(tmp_path, monkeypatch):
    from src.providers.chat import ProviderStreamError

    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))
    monkeypatch.setattr("src.agent.loop._stream_retry_backoff_s", lambda _: 0)
    llm.stream_chat.side_effect = [
        ProviderStreamError(provider="deepseek", model="m", original=ConnectionError("reset")),
        LLMResponse(content="Hello", usage_metadata=USAGE),
    ]
    result = agent.run("Say hello.")
    assert result["status"] == "success"
    assert [kind for kind, _ in _usage_events(events)] == ["llm_usage"]
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["calls"] == 1
    assert report["totals"]["unreported_calls"] == 1


def test_live_decision_budget_survives_a_retried_connection_reset(tmp_path, monkeypatch):
    """A reset then a successful retry used to halt live decisions for the day."""
    from datetime import datetime, timezone

    from src.live.runtime.decision_budget import DecisionBudget
    from src.providers.chat import ProviderStreamError

    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))
    monkeypatch.setattr("src.agent.loop._stream_retry_backoff_s", lambda _: 0)
    llm.stream_chat.side_effect = [
        ProviderStreamError(provider="deepseek", model="m", original=ConnectionError("reset")),
        LLMResponse(content="Hold.", usage_metadata=USAGE),
    ]
    agent.run("Decide.")
    budget = DecisionBudget("alpaca", path=tmp_path / "budget.db")
    settings, now = budget.settings(), datetime.now(timezone.utc)
    decision = budget.begin(settings, now)
    for kind, data in _usage_events(events):
        # The way live_routes forwards events to the budget.
        budget.record(decision, data if kind == "llm_usage" else {}, settings, now)
    budget.finish(decision, settings, now)


def test_an_ordinary_response_without_usage_is_still_announced(tmp_path):
    events = []
    agent, llm = _agent(tmp_path, lambda kind, data: events.append((kind, data)))
    llm.stream_chat.return_value = LLMResponse(content="Hello", usage_metadata=None)
    agent.run("Say hello.")
    assert ("llm_usage_unavailable", {"iter": 1}) in _usage_events(events)


def test_a_text_answer_that_crosses_the_goal_budget_is_released(tmp_path, monkeypatch):
    from src.goal import GoalStore

    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    goal = store.replace_goal(
        session_id="cost-test", objective="Answer.", criteria=["answer"], token_budget=1000,
    )
    agent, llm = _agent(tmp_path)
    llm.stream_chat.return_value = LLMResponse(content="Here is the full answer.", usage_metadata=USAGE)
    result = agent.run("Answer it.", session_id="cost-test")
    assert result["status"] == "success"
    assert result["content"] == "Here is the full answer."
    assert "goal_token_budget_exhausted" in result["reason"]
    assert store.get_goal(goal.goal_id).tokens_used == 1100

    # The exhausted goal still refuses further spending.
    agent.run("Continue.", session_id="cost-test")
    llm.stream_chat.assert_called_once()



def test_retry_billing_does_not_inflate_context_meter(tmp_path, monkeypatch):
    agent, llm = _agent(tmp_path, lambda *args: None)
    llm.stream_chat.side_effect = lambda *args, **kwargs: LLMResponse(
        content="Hello.", usage_metadata={"input_tokens": 3000, "output_tokens": 90,
            "total_tokens": 3090, "calls": 3, "context_input_tokens": 1000})
    observed = []
    monkeypatch.setattr(type(agent._context_meter), "observe", lambda self, n, *a, **kw: observed.append(n))
    agent.run("Say hello.")
    assert observed == [1000]
    report = json.loads((tmp_path / "llm_usage.json").read_text())
    assert report["totals"]["input_tokens"] == 3000
    assert report["totals"]["calls"] == 3
