"""A CLI turn is recorded and replayed like a web turn.

Every test drives the real CLI entry (``_run_agent`` and the commands built on
it) -> ``AgentRuntime`` -> ``thread.jsonl`` with a scripted offline model; only the
registry builder, the LLM factory and persistent memory are replaced. The model
is a *policy*: it calls the ``lookup`` tool only when the request it receives
does not already hold the result, so "no second lookup" is an outcome of what
the CLI replays, not of a fixed script.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import cli.commands.common as _cmd_common
import cli.commands.execution as _cmd_execution
import cli.commands.sessions as _cmd_sessions
import cli.ui.rail as _cmd_rail

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.providers.messages import INTERRUPTED_RESULT_CONTENT
from src.agent.runtime import AgentRuntime
from src.agent.tools import BaseTool, ToolRegistry
from src.session.models import Message, Session
from src.session.attempts import STOPPED_MARKER
from src.session.store import SessionStore
from src.session.replay import project_turn, STOPPED_TURN_NOTES

cli_main = importlib.import_module("cli.main")

LOOKUP_PAYLOAD = json.dumps({"ok": True, "value": "value-of-us"})


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


class _NoMemory:
    snapshot = ""

    def find_relevant(self, *args: Any, **kwargs: Any) -> list:
        del args, kwargs
        return []


class _LookupTool(BaseTool):
    name = "lookup"
    description = "Read a value (offline double)."
    parameters = {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}
    is_readonly = True
    repeatable = True

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return LOOKUP_PAYLOAD


def _call(call_id: str, name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=name, arguments=arguments)


def _response(content: str = "", calls: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        reasoning_content=None,
        has_tool_calls=bool(calls),
        tool_calls=list(calls),
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )


class _PolicyLLM:
    """Offline model: records each request, answers through ``policy``."""

    model_name = "offline"

    def __init__(self, policy: Callable[..., SimpleNamespace]) -> None:
        self.policy = policy
        self.requests: list[dict] = []

    def stream_chat(self, messages: list, tools=None, on_text_chunk=None, **kwargs: Any):
        del kwargs
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        return self.policy(self, messages, tools or [], on_text_chunk)

    def chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:
        del messages, kwargs
        return SimpleNamespace(content="SUMMARY", usage_metadata=None)

    async def aclose(self) -> None:
        return None


def _tool_messages(messages: list, name: str) -> list[dict]:
    return [m for m in messages if m.get("role") == "tool" and m.get("name") == name]


def _lookup_once_policy(llm: _PolicyLLM, messages: list, tools: list, on_text) -> SimpleNamespace:
    """Look the value up unless the request already holds it, then answer."""
    del tools, on_text
    if not _tool_messages(messages, "lookup"):
        return _response(calls=(_call(f"call-{len(llm.requests)}", "lookup", key="us"),))
    return _response(content="The US value is 42.")


class _Harness:
    """The patched CLI environment of one test."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sessions = tmp_path / "sessions"
        self.sessions.mkdir()
        self.lookup_calls: list = []
        self.agents: list[AgentRuntime] = []
        self.provider_policies = []
        self.llm = _PolicyLLM(_lookup_once_policy)
        harness = self

        class _CapturingLoop(AgentRuntime):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                harness.agents.append(self)

        def registry(**kwargs: Any) -> ToolRegistry:
            built = ToolRegistry(policy=kwargs["policy"])
            built.register(_LookupTool(self.lookup_calls))
            return built

        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        monkeypatch.setattr(_cmd_common, "SESSIONS_DIR", self.sessions)
        monkeypatch.setattr(_cmd_common, "RUNS_DIR", tmp_path / "runs")
        monkeypatch.setattr(cli_main, "_SESSION_STORE_CACHE", SessionStore(self.sessions))
        monkeypatch.setattr("src.session.search.get_shared_index", lambda: _DummyIndex())
        monkeypatch.setattr("src.agent.runtime.AgentRuntime", _CapturingLoop)
        monkeypatch.setattr("src.tools.build_registry", registry)
        def chat(*, policy):
            self.provider_policies.append(policy)
            return self.llm

        monkeypatch.setattr("src.providers.chat.ChatLLM", chat)
        monkeypatch.setattr("src.memory.persistent.PersistentMemory", _NoMemory)
        monkeypatch.setattr("src.config.loader.load_agent_config", lambda: object())
        self.store = SessionStore(self.sessions)

    def new_session(self, title: str = "cli") -> str:
        session = Session(title=title)
        self.store.create_session(session)
        return session.session_id

    def run(self, prompt: str, session_id: str, **kwargs: Any) -> dict:
        return _cmd_execution._run_agent(
            prompt, max_iter=8, no_rich=True, stream_output=False, session_id=session_id, **kwargs
        )

    def thread(self, session_id: str) -> list:
        return self.store.thread_log(session_id).read()

    def rows(self, session_id: str) -> list[Message]:
        return self.store.get_messages(session_id, limit=None)


@pytest.fixture()
def cli(tmp_path, monkeypatch) -> _Harness:
    return _Harness(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# A CLI turn writes what a web turn writes
# ---------------------------------------------------------------------------


def test_cli_uses_the_same_configured_policy_for_the_provider_and_registry(cli, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_DENY_TOOL_PREFIXES", "forbidden_")
    result = cli.run("Quote Apple", cli.new_session())
    assert result["status"] == "success"
    assert cli.agents[0].registry.policy is cli.provider_policies[0]
    assert cli.provider_policies[0].denies("forbidden_probe")


def test_cli_turn_writes_the_thread_items_and_the_display_rows_of_a_web_turn(cli):
    sid = cli.new_session()

    result = cli.run("Quote Apple", sid)

    assert result["status"] == "success"
    items = cli.thread(sid)
    kinds = [item.type for item in items]
    assert kinds[:2] == ["turn_start", "user"]
    assert kinds[-1] == "turn_end"
    assert {"assistant", "tool_result", "state"} <= set(kinds)
    assert len({item.turn_id for item in items}) == 1
    assistants = [item for item in items if item.type == "assistant"]
    assert [item.get("phase") for item in assistants] == ["commentary", "final"]
    assert assistants[0].get("tool_calls")[0]["function"]["name"] == "lookup"
    assert assistants[1].get("content") == "The US value is 42."
    tool_result = next(item for item in items if item.type == "tool_result")
    assert (tool_result.get("name"), tool_result.get("status")) == ("lookup", "ok")
    assert tool_result.get("content") == LOOKUP_PAYLOAD
    user = next(item for item in items if item.type == "user")
    assert user.get("content") == "Quote Apple"
    assert user.get("llm_content").endswith("Quote Apple") or "Quote Apple" in user.get("llm_content")
    end = items[-1]
    assert end.get("status") == "completed"
    assert end.get("usage")["input_tokens"] == 200
    assert result["usage"]["input_tokens"] == 200

    # messages.jsonl keeps one user row and one reply row per turn, the reply
    # carrying the tool trail the web UI hydrates from.
    user_row, reply = cli.rows(sid)
    assert (user_row.role, user_row.content) == ("user", "Quote Apple")
    assert reply.role == "assistant"
    assert reply.content == "The US value is 42."
    assert reply.metadata["status"] == "completed"
    assert reply.metadata["run_id"] == Path(result["run_dir"]).name
    assert [(e["tool"], e["status"]) for e in project_turn(cli.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results] == [("lookup", "ok")]


def test_cli_turn_without_a_session_id_runs_unrecorded(cli):
    result = cli.run("Quote Apple", "")

    assert result["status"] == "success"
    assert cli.llm.requests[0]["messages"][-1]["content"].endswith("Quote Apple")
    assert list(cli.sessions.iterdir()) == []


def test_repl_turn_records_one_user_row_and_one_reply_row(cli, monkeypatch):
    monkeypatch.setattr(_cmd_rail, 'RailRunDashboard', lambda prompt, max_iter: _QuietDashboard())
    ctx = cli_main.InteractiveContext(max_iter=8)

    cli_main._run_one_turn("Quote Apple", ctx)

    assert ctx.session_id
    rows = cli.rows(ctx.session_id)
    assert [(m.role, m.content) for m in rows] == [
        ("user", "Quote Apple"),
        ("assistant", "The US value is 42."),
    ]
    assert [i.type for i in cli.thread(ctx.session_id)][-1] == "turn_end"
    assert ctx.transcript == [
        {"role": "user", "content": "Quote Apple"},
        {"role": "assistant", "content": "The US value is 42."},
    ]


class _QuietDashboard:
    """Dashboard stand-in: the REPL path only needs it to accept events."""

    live = None
    iterations = 0

    def render(self):
        return ""

    def handle_event(self, event_type: str, data: dict) -> None:
        del event_type, data

    def finish(self, result: dict, elapsed: float) -> None:
        del result, elapsed

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# A resumed CLI session replays tool calls and results
# ---------------------------------------------------------------------------


def test_resumed_cli_session_replays_the_earlier_tool_call_and_result(cli):
    sid = cli.new_session()
    cli.run("Quote Apple", sid)
    assert len(cli.lookup_calls) == 1
    first_requests = len(cli.llm.requests)

    cli.run("What was its value?", sid)

    request = cli.llm.requests[first_requests]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    called = [
        call["function"]["name"]
        for m in request
        if m.get("role") == "assistant"
        for call in m.get("tool_calls") or []
    ]
    assert called == ["lookup"]
    assert len(cli.llm.requests) == first_requests + 1
    assert len(cli.lookup_calls) == 1


def test_repl_resume_in_a_new_process_state_replays_the_earlier_results(cli, monkeypatch):
    monkeypatch.setattr(_cmd_rail, 'RailRunDashboard', lambda prompt, max_iter: _QuietDashboard())
    sid = cli.new_session()
    cli.run("Quote Apple", sid)
    first_requests = len(cli.llm.requests)

    # What ``vibe-trading resume <id>`` builds: a fresh context bound to the id.
    ctx = cli_main.InteractiveContext(max_iter=8, session_id=sid)
    ctx.transcript = cli_main._session_transcript(cli.store, sid)
    assert cli_main._prior_turns(ctx.transcript) == 1
    cli_main._run_one_turn("What was its value?", ctx)

    request = cli.llm.requests[first_requests]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    assert len(cli.lookup_calls) == 1
    rows = cli.rows(sid)
    assert [m.role for m in rows] == ["user", "assistant", "user", "assistant"]


def test_history_is_not_capped_at_the_last_six_messages(cli):
    sid = cli.new_session()
    for number in range(8):
        cli.run(f"question {number}", sid)
    before = len(cli.llm.requests)

    cli.run("question 8", sid)

    texts = " ".join(str(m.get("content")) for m in cli.llm.requests[before]["messages"])
    for number in range(8):
        assert f"question {number}" in texts


def test_cmd_session_chat_replays_the_session_thread(cli, monkeypatch):
    sid = cli.new_session()
    cli.run("Quote Apple", sid)
    first_requests = len(cli.llm.requests)
    replies = iter(["What was its value?", "q"])
    from cli import input as cli_input

    monkeypatch.setattr(cli_input, "get_user_input", lambda session: next(replies))
    monkeypatch.setattr(cli_input, "make_session", lambda: None)

    _cmd_sessions.cmd_session_chat(sid, 8)

    request = cli.llm.requests[first_requests]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    assert len(cli.lookup_calls) == 1
    assert [m.role for m in cli.rows(sid)] == ["user", "assistant", "user", "assistant"]


def test_cmd_interactive_keeps_one_session_and_replays_it(cli, monkeypatch):
    replies = iter(["Quote Apple", "What was its value?", "q"])
    monkeypatch.setattr("src.preflight.run_preflight", lambda console: [])
    from cli import input as cli_input

    monkeypatch.setattr(cli_input, "get_user_input", lambda session: next(replies))
    monkeypatch.setattr(cli_input, "make_session", lambda: None)
    monkeypatch.setattr(_cmd_rail, 'RailRunDashboard', lambda prompt, max_iter: _QuietDashboard())

    cli_main._interactive_loop(8)

    (session,) = cli.store.list_sessions()
    request = cli.llm.requests[2]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    assert len(cli.lookup_calls) == 1
    assert [m.role for m in cli.rows(session.session_id)] == ["user", "assistant", "user", "assistant"]


# ---------------------------------------------------------------------------
# Sessions recorded before thread.jsonl
# ---------------------------------------------------------------------------


def test_migrated_session_resume_replays_old_turns_then_continues_on_the_thread(cli):
    sid = cli.new_session("legacy")
    run_id = "20261026_230021_46_a7d6f2"
    stamps = [f"2026-10-26T23:{minute:02d}:00+00:00" for minute in range(12)]
    rows = []
    for pair in range(5):
        rows.append(Message(session_id=sid, role="user", content=f"old question {pair}",
                            created_at=stamps[pair * 2]))
        rows.append(Message(session_id=sid, role="assistant", content=f"old answer {pair}",
                            metadata={"run_id": run_id}, created_at=stamps[pair * 2 + 1]))
    log = cli.store.thread_log(sid)
    for pair in range(5):
        turn = f"old-{pair}"
        prompt = rows[pair * 2].content
        log.append("turn_start", turn, prompt=prompt)
        log.append("user", turn, content=prompt, llm_content=prompt)
        log.append("assistant", turn, content=f"[prev_run: {run_id}]\nold answer {pair}", phase="final")
        log.append("turn_end", turn, status="completed")

    cli.run("Quote Apple", sid)
    cli.run("What was its value?", sid)

    legacy = []
    for pair in range(5):
        legacy.append({"role": "user", "content": f"old question {pair}"})
        legacy.append({"role": "assistant", "content": f"[prev_run: {run_id}]\nold answer {pair}"})
    first, second = (r["messages"] for r in cli.llm.requests[:2])
    third = cli.llm.requests[2]["messages"]
    # All ten legacy rows are there: nothing is cut at the old last-six.
    assert first[1:11] == legacy
    assert first[-1]["content"].endswith("Quote Apple")
    assert second[1:11] == legacy
    assert third[1:11] == legacy
    # The turn recorded on the thread replays once after the legacy prefix:
    # its user row in messages.jsonl is not also read as legacy text.
    assert [m["content"] for m in _tool_messages(third, "lookup")] == [LOOKUP_PAYLOAD]
    assert sum("Quote Apple" in str(m.get("content")) for m in third) == 1
    assert len(cli.lookup_calls) == 1


# ---------------------------------------------------------------------------
# The continue command
# ---------------------------------------------------------------------------


def test_continue_command_on_a_session_replays_its_thread(cli, capsys):
    assert _cmd_execution.cmd_run("Quote Apple", 8, json_mode=True) == _cmd_common.EXIT_SUCCESS
    (session,) = cli.store.list_sessions()
    sid = session.session_id
    first_requests = len(cli.llm.requests)

    assert _cmd_execution.cmd_continue(sid, "What was its value?", 8, json_mode=True) == _cmd_common.EXIT_SUCCESS

    request = cli.llm.requests[first_requests]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    assert len(cli.lookup_calls) == 1
    assert [m.role for m in cli.rows(sid)] == ["user", "assistant", "user", "assistant"]
    capsys.readouterr()


def test_repeated_continue_of_a_run_id_accumulates_one_session(cli, tmp_path, capsys):
    run_dir = tmp_path / "runs" / "run-xyz"
    run_dir.mkdir(parents=True)

    assert _cmd_execution.cmd_continue("run-xyz", "Quote Apple", 8, json_mode=True) == _cmd_common.EXIT_SUCCESS
    first_requests = len(cli.llm.requests)
    assert _cmd_execution.cmd_continue("run-xyz", "What was its value?", 8, json_mode=True) == _cmd_common.EXIT_SUCCESS

    request = cli.llm.requests[first_requests]["messages"]
    assert [m["content"] for m in _tool_messages(request, "lookup")] == [LOOKUP_PAYLOAD]
    assert len(cli.lookup_calls) == 1
    assert [m.role for m in cli.rows("run-run-xyz")] == ["user", "assistant", "user", "assistant"]
    capsys.readouterr()


# ---------------------------------------------------------------------------
# Stopped turns
# ---------------------------------------------------------------------------


def test_stopped_cli_turn_keeps_its_results_and_text_and_the_next_turn_sees_them(cli):
    sid = cli.new_session()

    def policy(llm, messages, tools, on_text):
        del tools
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-first", "lookup", key="us"),))
        if step == 2:
            on_text("Two of three markets are loaded")
            cli.agents[-1].cancel()
            return _response(calls=(_call("c-second", "lookup", key="hk"),))
        llm.follow_up = messages
        return _response(content="Continuing from the US value.")

    cli.llm.policy = policy

    result = cli.run("Compare three markets", sid)

    assert result["status"] == "cancelled"
    reply = cli.rows(sid)[-1]
    assert reply.metadata["status"] == "cancelled"
    assert reply.content == f"Two of three markets are loaded\n\n{STOPPED_MARKER}"
    assert [e["call_id"] for e in project_turn(cli.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results] == ["c-first"]
    assert cli.thread(sid)[-1].get("status") == "cancelled"

    cli.run("continue", sid)

    follow_up = cli.llm.follow_up
    assert [m["content"] for m in _tool_messages(follow_up, "lookup")] == [LOOKUP_PAYLOAD]
    note = {"role": "user", "content": STOPPED_TURN_NOTES["cancelled"]}
    assert note in follow_up


def test_forced_quit_closes_the_turn_so_the_next_one_replays_it_as_stopped(cli):
    sid = cli.new_session()

    def policy(llm, messages, tools, on_text):
        del tools, on_text
        step = len(llm.requests)
        if step == 1:
            return _response(calls=(_call("c-first", "lookup", key="us"),))
        if step == 2:
            raise KeyboardInterrupt  # the second Ctrl+C of the CLI's SIGINT handler
        llm.follow_up = messages
        return _response(content="ok")

    cli.llm.policy = policy

    with pytest.raises(KeyboardInterrupt):
        cli.run("Quote Apple", sid)

    assert cli.store.thread_log(sid).open_turns() == []
    assert cli.thread(sid)[-1].get("status") == "cancelled"
    reply = cli.rows(sid)[-1]
    assert reply.metadata["status"] == "cancelled" and reply.content == STOPPED_MARKER
    assert [e["call_id"] for e in project_turn(cli.store.thread_log(reply.session_id).read(), reply.linked_attempt_id).tool_results] == ["c-first"]

    cli.run("again", sid)

    follow_up = cli.llm.follow_up
    assert [m["content"] for m in _tool_messages(follow_up, "lookup")] == [LOOKUP_PAYLOAD]
    assert {"role": "user", "content": STOPPED_TURN_NOTES["cancelled"]} in follow_up


def test_failed_loop_result_is_recorded_as_a_failed_turn_with_its_reason(cli):
    sid = cli.new_session()

    def policy(llm, messages, tools, on_text):
        del llm, messages, tools, on_text
        raise RuntimeError("provider down")

    cli.llm.policy = policy

    result = cli.run("Quote Apple", sid)

    assert result["status"] == "failed"
    assert cli.thread(sid)[-1].get("status") == "failed"
    reply = cli.rows(sid)[-1]
    assert reply.metadata["status"] == "failed"
    assert reply.content.startswith("Execution failed:") and "provider down" in reply.content


def test_an_exception_out_of_the_run_closes_the_turn_as_failed(cli, monkeypatch):
    sid = cli.new_session()

    def broken(*args: Any, **kwargs: Any) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(_cmd_execution, "_run_with_graceful_cancel", broken)

    with pytest.raises(RuntimeError, match="boom"):
        cli.run("Quote Apple", sid)

    assert cli.store.thread_log(sid).open_turns() == []
    assert cli.thread(sid)[-1].get("status") == "failed"
    assert cli.rows(sid)[-1].content == "Execution failed: boom"


def test_a_turn_a_dead_cli_left_open_is_closed_as_interrupted_by_the_next_cli_turn(cli):
    sid = cli.new_session()
    thread = cli.store.thread_log(sid)
    thread.append("turn_start", "dead", prompt="Compare")
    thread.append("user", "dead", content="Compare", llm_content="Compare")
    thread.append("assistant", "dead", content=None, phase="commentary", tool_calls=[
        {"id": "c-read", "type": "function", "function": {"name": "lookup", "arguments": '{"key": "us"}'}},
    ])
    thread.append("tool_result", "dead", tool_call_id="c-read", name="lookup", content=LOOKUP_PAYLOAD, status="ok")
    thread.append("assistant", "dead", content=None, phase="commentary", tool_calls=[
        {"id": "c-write", "type": "function", "function": {"name": "lookup", "arguments": '{"key": "hk"}'}},
    ])
    assert thread.open_turns() == ["dead"]

    cli.run("What happened?", sid)

    assert thread.open_turns() == []
    request = cli.llm.requests[0]["messages"]
    write = next(m for m in request if m.get("tool_call_id") == "c-write")
    assert write["content"] == INTERRUPTED_RESULT_CONTENT
    assert {"role": "user", "content": STOPPED_TURN_NOTES["interrupted"]} in request


# ---------------------------------------------------------------------------
# The session list and /clear
# ---------------------------------------------------------------------------


def test_sessions_list_counts_user_visible_messages_not_thread_items(cli, monkeypatch):
    from rich.console import Console

    sid = cli.new_session("counted")
    cli.run("Quote Apple", sid)
    assert len(cli.thread(sid)) > 4
    recorded = Console(record=True, width=160, force_terminal=False)
    monkeypatch.setattr(_cmd_common, "console", recorded)

    _cmd_sessions.cmd_sessions()

    row = next(line for line in recorded.export_text().splitlines() if sid in line)
    assert row.split("│")[4].strip() == "2"


def test_clear_leaves_the_session_so_the_model_forgets_the_conversation(cli, monkeypatch):
    from cli.commands.chat import cmd_clear

    monkeypatch.setattr(_cmd_rail, 'RailRunDashboard', lambda prompt, max_iter: _QuietDashboard())
    ctx = cli_main.InteractiveContext(max_iter=8)
    cli_main._run_one_turn("Quote Apple", ctx)
    old_session = ctx.session_id
    cmd_clear(ctx)

    assert ctx.session_id is None and ctx.transcript == []
    before = len(cli.llm.requests)
    cli_main._run_one_turn("What was its value?", ctx)

    assert ctx.session_id and ctx.session_id != old_session
    request = cli.llm.requests[before]["messages"]
    assert _tool_messages(request, "lookup") == []
    assert len(cli.lookup_calls) == 2


def test_cli_question_survives_thread_projection_and_json_output(cli, monkeypatch, capsys):
    from src.tools.ask_user_tool import AskUserTool

    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(AskUserTool())
    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: registry)
    cli.llm.policy = lambda *args: _response(
        calls=(_call("q", "ask_user", prompt="Which period?", options=["Day", "Week"]),)
    )
    sid = cli.new_session()
    result = cli.run("Ask for a period", sid)
    assert result["status"] == "waiting_user"
    assert cli.thread(sid)[-1].get("status") == "waiting_user"
    assert cli.rows(sid)[-1].content == "Which period?\n1. Day\n2. Week"
    _cmd_execution._print_json_result(result)
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["content"] == cli.rows(sid)[-1].content
    assert _cmd_execution._result_exit_code(result) == _cmd_common.EXIT_SUCCESS


def test_cli_abort_redacts_the_persisted_exception(cli, monkeypatch):
    sid = cli.new_session()

    def broken(*args, **kwargs):
        raise RuntimeError("api_key=private-cli-detail")

    monkeypatch.setattr(_cmd_execution, "_run_with_graceful_cancel", broken)
    with pytest.raises(RuntimeError):
        cli.run("Analyze", sid)
    assert "private-cli-detail" not in (cli.sessions / sid / "thread.jsonl").read_text()
    assert "private-cli-detail" not in cli.rows(sid)[-1].content


def test_reused_loop_finishes_the_turn_after_a_question(cli, tmp_path):
    from src.tools.ask_user_tool import AskUserTool

    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(AskUserTool())
    loop = AgentRuntime(registry=registry, llm=cli.llm, max_iterations=4)
    loop.memory.run_dir = tmp_path / "runs" / "reused"
    cli.llm.policy = lambda *args: _response(
        calls=(_call("q", "ask_user", prompt="Which period?", options=["Day", "Week"]),)
    )
    assert loop.run("Ask for a period")["status"] == "waiting_user"
    cli.llm.policy = lambda *args: _response(content="Weekly report.")
    assert loop.run("Week")["status"] == "success"
