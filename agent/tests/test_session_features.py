"""Session fork, manual compaction, and model-switch replay contracts."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.session.events import EventBus
from src.session.models import SessionBusyError
from src.session.service import SessionService
from src.session.store import SessionStore
from src.session.replay import replay
from src.session.thread import ThreadLog


def _service(tmp_path: Path) -> SessionService:
    return SessionService(
        policy=ToolPolicy.from_config(get_env_config()),
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )


def _turn(log: ThreadLog, turn_id: str, prompt: str, *, identity: list[str]) -> None:
    log.append("turn_start", turn_id, prompt=prompt, provider="openrouter", model="m")
    log.append("user", turn_id, content=prompt, llm_content=prompt)
    log.append(
        "state", turn_id,
        identity={"records": identity},
        loaded_tools=["search_symbol"],
        workspace_dir="old",
        workspace="old",
    )
    log.append("assistant", turn_id, content="done", tool_calls=[], phase="final", provider="openrouter", model="m")
    log.append("turn_end", turn_id, status="completed", provider="openrouter", model="m")


def test_fork_copies_only_the_selected_turn_state_and_keeps_source_untouched(tmp_path):
    service = _service(tmp_path)
    source = service.create_session("source")
    log = service.store.thread_log(source.session_id)
    _turn(log, "turn-1", "first", identity=["AAPL"])
    _turn(log, "turn-2", "second", identity=["AAPL", "MSFT"])

    fork = service.fork_session(source.session_id, "turn-1")
    copied = service.store.thread_log(fork.session_id).read()
    states = [item for item in copied if item.type == "state"]

    assert fork.forked_from_session_id == source.session_id
    assert fork.forked_from_turn_id == "turn-1"
    assert {item.turn_id for item in copied} == {"turn-1"}
    assert states[-1].get("identity") == {"records": ["AAPL"]}
    assert states[-1].get("workspace_dir") == str(Path(tmp_path / "sessions" / fork.session_id / "workspace"))
    assert service.store.thread_log(source.session_id).read()[-1].turn_id == "turn-2"


def test_compaction_refuses_a_running_or_queued_session(tmp_path):
    service = _service(tmp_path)
    session = service.create_session("busy")
    service._inflight.add(session.session_id)
    with pytest.raises(SessionBusyError, match="running or queued"):
        asyncio.run(service.compact_session(session.session_id))
    service._inflight.clear()
    service.pending_inputs.add(session.session_id, "waiting", queued_during=None, include_shell_tools=False)
    with pytest.raises(SessionBusyError, match="running or queued"):
        asyncio.run(service.compact_session(session.session_id))


def test_manual_compaction_uses_the_existing_summary_path_and_records_a_compaction(
    tmp_path, monkeypatch
):
    service = _service(tmp_path)
    session = service.create_session("compact")
    log = service.store.thread_log(session.session_id)
    for index in range(3):
        _turn(log, f"turn-{index}", f"prompt {index}", identity=[])

    class FakeLLM:
        runtime_snapshot = SimpleNamespace(provider="openrouter", configured_model="m")
        model_name = "m"

        def chat(self, *_args, **_kwargs):
            return SimpleNamespace(content="focused summary", usage_metadata=None)

        async def aclose(self):
            return None

    monkeypatch.setattr("src.session.model_selection.chat_llm_for_session", lambda _config, **kwargs: FakeLLM())
    result = asyncio.run(service.compact_session(session.session_id, "risk"))

    assert result["focus"] == "risk"
    items = log.read()
    compacted = [item for item in items if item.type == "compaction"]
    assert compacted and "focused summary" in compacted[-1].get("summary")
    assert compacted[-1].get("replaces_through_seq", 0) > 0


def test_replay_strips_foreign_provider_reasoning_state_after_a_model_switch(tmp_path):
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="hello", provider="openrouter", model="model-a")
    log.append("user", "t1", content="hello", llm_content="hello")
    log.append(
        "assistant", "t1", content="answer", tool_calls=[],
        reasoning_content="private thought", provider_items=[{"signature": "a"}],
        provider="openrouter", model="model-a", phase="final",
    )
    log.append("turn_end", "t1", status="completed", provider="openrouter", model="model-a")

    switched = replay(log.read(), provider="groq", model="model-b")
    same = replay(log.read(), provider="openrouter", model="model-a")

    assert "reasoning_content" not in switched[-1]
    assert "provider_items" not in switched[-1]
    assert switched[-1]["content"] == "answer"
    assert same[-1]["reasoning_content"] == "private thought"
    assert same[-1]["provider_items"] == [{"signature": "a"}]


def test_manual_compaction_closes_resources_when_setup_fails(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from src.session.runtime import TurnRecorder

    service = _service(tmp_path)
    session = service.create_session("compact")
    _turn(service.store.thread_log(session.session_id), "turn-1", "hello", identity=[])
    Path(service.runs_dir).mkdir(parents=True, exist_ok=True)
    (Path(service.runs_dir) / "compactions").touch()
    llm = SimpleNamespace(aclose=AsyncMock(), runtime_snapshot=None)
    monkeypatch.setattr("src.session.model_selection.chat_llm_for_session", lambda config, **kwargs: llm)
    closed = []
    original_close = TurnRecorder.close

    def record_close(recorder):
        closed.append(recorder)
        original_close(recorder)

    monkeypatch.setattr(TurnRecorder, "close", record_close)
    with pytest.raises(OSError):
        asyncio.run(service.compact_session(session.session_id))
    llm.aclose.assert_awaited_once()
    assert len(closed) == 1
