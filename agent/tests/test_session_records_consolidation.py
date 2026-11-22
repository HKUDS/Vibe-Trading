"""Regression coverage for the thread-backed record projections."""

from __future__ import annotations

from pathlib import Path

from src.session.checkpoint import ResponseCheckpoint
from src.session.models import Attempt, Session
from src.session.runtime import SessionRuntime
from src.session.store import SessionStore
from src.session.replay import replay
from src.session.thread import ThreadLog


def _call(call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"key":"us"}'},
    }


def test_replay_applies_recorded_microcompact_and_collapse_views(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="q")
    assistant = log.append("assistant", "t1", content="", tool_calls=[_call("c1")])
    result = log.append(
        "tool_result", "t1", tool_call_id="c1", name="lookup", content="full result", status="ok"
    )
    collapsed = {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "lookup",
        "content": "[CLEARED FROM CONTEXT]",
    }
    log.append(
        "compaction", "t1", summary="", replaces_through_seq=0, layer=1,
        changes=[{"seq": result.seq, "message": collapsed}],
    )
    compacted_call = {**_call("c1"), "function": {"name": "lookup", "arguments": "{}"}}
    log.append(
        "compaction", "t1", summary="", replaces_through_seq=0, layer=2,
        changes=[{"seq": assistant.seq, "message": {"role": "assistant", "content": "", "tool_calls": [compacted_call]}}],
    )

    messages = replay(log.read())

    assert messages[1]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert messages[2]["content"] == "[CLEARED FROM CONTEXT]"
    assert not any(item.type == "compaction" and item.get("layer") == 3 for item in log.read())


def test_stream_checkpoint_is_thread_backed_for_new_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create_session(Session(title="checkpoint"))
    runtime = SessionRuntime(store.thread_log(session.session_id), session.session_id)
    attempt = Attempt(session_id=session.session_id, prompt="write")
    recorder = runtime.begin_turn(attempt.attempt_id)
    recorder.start(prompt="write", message={"role": "user", "content": "write"}, model=None, provider=None)
    checkpoint = ResponseCheckpoint(store, attempt, runtime=runtime, min_interval_seconds=0)
    checkpoint.handle_event('item.delta', {"kind": 'text.delta', 'delta': 'partial'})
    checkpoint.flush()

    assert runtime.partial_response(attempt.attempt_id) == "partial"
    assert not (tmp_path / "sessions" / session.session_id / "attempts" / attempt.attempt_id / "partial_response.json").exists()
    assert any(item.type == "checkpoint" for item in runtime.thread.read())


def test_loop_compaction_projection_calls_thread_sink() -> None:
    from types import SimpleNamespace

    from src.agent.runtime import AgentRuntime

    calls: list[tuple[int, list[dict]]] = []
    loop = AgentRuntime(registry=SimpleNamespace(get=lambda name: None), llm=SimpleNamespace())
    loop._conversation.thread = SimpleNamespace(
        compaction_layer=lambda layer, messages: calls.append((layer, messages)),
        seq_of=lambda message: 1,
    )
    current = {"role": "tool", "tool_call_id": "c1", "content": "after"}
    loop._context_compactor._record_compaction_layer([current], 1, [{"role": "tool", "tool_call_id": "c1", "content": "before"}])

    assert calls == [(1, [current])]



def test_channel_poll_waits_for_terminal_thread_reply(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from src.channels.runtime import ChannelRuntime
    from src.channels.bus.queue import MessageBus

    async def scenario():
        store = SessionStore(tmp_path / "sessions")
        runtime = SessionRuntime(store.thread_log("s"), "s")
        recorder = runtime.begin_turn("t")
        recorder.start(prompt="q", message={"content": "q"}, provider=None, model=None)
        recorder.assistant({"content": "draft"}, phase="final")
        channel = ChannelRuntime(bus=MessageBus(), session_service=SimpleNamespace(get_messages=store.get_messages),
                                 manager=None, session_map_path=tmp_path / "channels.json", poll_interval_s=0.001)
        task = asyncio.create_task(channel._wait_for_reply("s", "t"))
        await asyncio.sleep(0.01)
        assert not task.done(), "streamed draft must not be delivered as the completed reply"
        runtime.finish_turn("t", prompt="q", status="completed", summary="released", metadata={"generated_reports": []})
        reply = await asyncio.wait_for(task, 1)
        assert reply.content == "released"
        assert reply.linked_attempt_id == "t"
        assert not list(tmp_path.rglob("messages.jsonl"))

    asyncio.run(scenario())


def test_compaction_keeps_assistant_tool_arguments_redacted(tmp_path: Path) -> None:
    import copy
    import json

    runtime = SessionRuntime(ThreadLog(tmp_path / "thread.jsonl"), "s")
    recorder = runtime.begin_turn("t", provider="one", model="first")
    call = _call("c1")
    call["function"]["arguments"] = json.dumps({"api_key": "private-argument", "region": "us"})
    call["extra_content"] = {"google": {"thought_signature": "signature"}}
    message = {
        "role": "assistant", "content": "before", "tool_calls": [call],
        "additional_kwargs": {"tool_calls": [copy.deepcopy(call)]},
    }
    recorder.assistant(message, phase="commentary")
    message["content"] = "folded"
    recorder.compaction_layer(2, [message])

    stored = runtime.thread.path.read_text()
    assert "private-argument" not in stored
    assert "private-argument" in call["function"]["arguments"]
    replayed = runtime.replay_history(provider="one", model="first")[0][0]
    assert replayed["content"] == "folded"
    assert replayed["tool_calls"] == replayed["additional_kwargs"]["tool_calls"]
    assert json.loads(replayed["tool_calls"][0]["function"]["arguments"]) == {
        "region": "us", "api_key": "[redacted]",
    }


def test_model_switch_filters_reasoning_in_compacted_calls(tmp_path: Path) -> None:
    runtime = SessionRuntime(ThreadLog(tmp_path / "thread.jsonl"), "s")
    recorder = runtime.begin_turn("t", provider="one", model="first")
    call = _call("c1")
    call["extra_content"] = {"google": {"thought_signature": "native-signed-data"}}
    message = {
        "role": "assistant", "content": "before", "tool_calls": [call],
        "reasoning_content": "private thought", "provider_items": [{"type": "reasoning"}],
    }
    recorder.assistant(message, phase="commentary")
    message["content"] = "folded"
    recorder.compaction_layer(2, [message])
    same, same_seqs, _ = runtime.replay_history(provider="one", model="first")
    other, other_seqs, _ = runtime.replay_history(provider="one", model="second")
    assert same[0]["reasoning_content"] == "private thought"
    assert same[0]["provider_items"] == message["provider_items"]
    assert same[0]["tool_calls"][0]["extra_content"] == call["extra_content"]
    assert other[0]["content"] == "folded"
    assert "provider_items" not in other[0] and "reasoning_content" not in other[0]
    assert "native-signed-data" not in str(other[0])
    assert other_seqs == same_seqs == [1, None]


def test_replay_tracks_image_and_synthetic_message_source_sequences(tmp_path: Path) -> None:
    runtime = SessionRuntime(ThreadLog(tmp_path / "thread.jsonl"), "s")
    runtime.thread.append("assistant", "t", content="", tool_calls=[_call("missing"), _call("image")])
    image = runtime.thread.append("tool_result", "t", tool_call_id="image", name="lookup",
                                  content="chart", status="ok", images=[{"path": "chart.png"}])
    messages, seqs, _ = runtime.replay_history()
    assert messages[1]["content"][1]["image_url"]["url"] == "chart.png"
    assert seqs == [1, image.seq, None]


def test_replay_scrubs_arguments_in_preexisting_compaction_items(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    item = log.append("assistant", "t", content="before", tool_calls=[_call("c1")])
    call = _call("c1")
    call["function"]["arguments"] = '{"password":"historical-private-value"}'
    log.append("compaction", "t", layer=2, replaces_through_seq=0, summary="",
               changes=[{"seq": item.seq, "message": {
                   "role": "assistant", "content": "after", "tool_calls": [call],
               }}])
    before = log.path.read_bytes()
    projected = replay(log.read())
    assert projected[0]["content"] == "after"
    assert "historical-private-value" not in str(projected)
    assert log.path.read_bytes() == before


def test_compaction_ignores_synthetic_result_with_real_call_id(tmp_path: Path) -> None:
    runtime = SessionRuntime(ThreadLog(tmp_path / "thread.jsonl"), "s")
    runtime.thread.append("assistant", "t", content="", tool_calls=[_call("missing")])
    recorder = runtime.begin_turn("next")
    repaired = recorder.history[-1]
    assert repaired["tool_call_id"] == "missing"
    recorder.compaction_layer(1, [repaired])
    assert all(item.type != "compaction" for item in runtime.thread.read())
