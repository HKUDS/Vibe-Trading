"""A session's own model selection: validation, isolation, routes, CLI and metadata."""

from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.execution as _cmd_execution
import cli.commands.providers as _cmd_providers

import asyncio
import json
import os
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import src.providers.chat as chat_module
import src.providers.settings as provider_settings
from src.config.accessor import reset_env_config
from src.kernel.contracts import LLMResponse
from src.providers.chat import ChatLLM
from src.providers.selection import (
    SESSION_CONFIG_KEY,
    ModelSelectionError,
    validate_model_selection,
)
from src.session.events import EventBus
from src.session.model_selection import (
    chat_llm_for_session,
    chat_llm_for_stored_session,
    effective_model_selection,
)
from src.session.models import Attempt, AttemptStatus, Session
from src.session.service import SessionService
from src.session.store import SessionStore

_GLOBAL = {
    "LANGCHAIN_PROVIDER": "openrouter",
    "LANGCHAIN_MODEL_NAME": "global/model",
    "LANGCHAIN_REASONING_EFFORT": "",
    "OPENROUTER_API_KEY": "sk-or-real-openrouter",
    "GROQ_API_KEY": "gsk-real-groq",
    # The configured provider's generic fallbacks. A session that selects a
    # different provider must not inherit them.
    "OPENAI_API_KEY": "sk-generic-fallback",
    "OPENAI_BASE_URL": "https://generic.invalid/v1",
    "VIBE_TRADING_DISABLE_HTTP_PROXY": "1",
}
_UNSET = (
    "OPENROUTER_BASE_URL", "GROQ_BASE_URL", "OPENAI_API_BASE", "DEEPSEEK_API_KEY",
    "OPENAI_PROXY", "OPENAI_CUSTOM_HEADERS", "LANGCHAIN_USE_RESPONSES_API",
)


@pytest.fixture
def server_settings(monkeypatch):
    """A deterministic server configuration with no `.env` file involved."""
    monkeypatch.setattr(provider_settings, "_dotenv_loaded", True)
    for key in _UNSET:
        monkeypatch.delenv(key, raising=False)
    for key, value in _GLOBAL.items():
        monkeypatch.setenv(key, value)
    reset_env_config()
    yield
    reset_env_config()


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


# ---------------------------------------------------------------------------
# Inherit vs override
# ---------------------------------------------------------------------------


def test_a_session_without_a_selection_builds_the_configured_client(server_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(chat_module, "ChatLLM", lambda *a, **k: calls.append((a, k)) or "default")

    assert chat_llm_for_session({}) == "default"
    assert chat_llm_for_session(None) == "default"
    assert chat_llm_for_session({"include_shell_tools": False}) == "default"
    assert calls == [((), {})] * 3


def test_a_session_selection_resolves_its_own_provider_without_touching_the_process(
    server_settings, monkeypatch
):
    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    before = dict(os.environ)

    llm = chat_llm_for_session(
        {SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a", "reasoning_effort": "low"}}
    )

    assert llm.config.provider == "groq"
    assert llm.config.model == "llama-a"
    assert llm.config.api_key == "gsk-real-groq"
    assert llm.config.base_url == "https://api.groq.com/openai/v1"
    assert llm.runtime_snapshot.selection == "session"
    assert llm.runtime_snapshot.reasoning_effort == "low"
    assert dict(os.environ) == before
    inherited = ChatLLM()
    assert (inherited.config.provider, inherited.config.model) == ("openrouter", "global/model")
    assert inherited.runtime_snapshot.selection == "configured"


def test_a_selection_of_the_configured_provider_keeps_its_settings(server_settings):
    _selection, config = validate_model_selection({"provider": "openrouter", "model": "other/model"})

    assert config.api_key == "sk-or-real-openrouter"
    assert config.model == "other/model"


def test_another_provider_never_borrows_the_generic_fallbacks(server_settings, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")

    with pytest.raises(ModelSelectionError, match="no credentials"):
        validate_model_selection({"provider": "groq", "model": "llama-a"})


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"provider": "nonesuch", "model": "m"}, "Unsupported LLM provider"),
        ({"provider": "groq", "model": "  "}, "Model name is required"),
        ({"provider": "groq", "model": "m", "reasoning_effort": "turbo"}, "Reasoning effort must be one of"),
        ({"provider": "groq", "model": "m", "base_url": "https://evil.invalid/v1"}, "base_url"),
        ({"provider": "groq", "model": "m", "api_key": "sk-mine"}, "api_key"),
        ({"provider": "groq", "model": "m", "headers": {"X": "1"}}, "headers"),
        ({"provider": "groq", "model": "m", "endpoint": "https://evil.invalid"}, "endpoint"),
        ({"provider": "groq", "model": 3}, "must be strings"),
        (["groq", "m"], "must be an object"),
    ],
)
def test_a_selection_outside_the_servers_providers_is_refused(server_settings, raw, message):
    with pytest.raises(ModelSelectionError, match=message):
        validate_model_selection(raw)


def test_a_provider_without_credentials_is_refused(server_settings):
    with pytest.raises(ModelSelectionError, match="anthropic has no credentials"):
        validate_model_selection({"provider": "anthropic", "model": "claude-x"})


def test_a_stored_selection_whose_credentials_were_removed_fails_the_turn(server_settings, monkeypatch):
    config = {SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a", "reasoning_effort": ""}}
    monkeypatch.delenv("GROQ_API_KEY")

    with pytest.raises(ModelSelectionError):
        chat_llm_for_session(config)


# ---------------------------------------------------------------------------
# Concurrent isolation, end to end through SessionService and real HTTP
# ---------------------------------------------------------------------------


def _sse(model: str) -> bytes:
    chunks = [
        {"id": "c", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": f"from {model}"},
                      "finish_reason": None}]},
        {"id": "c", "object": "chat.completion.chunk", "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


class _OneCallLoop:
    """Stands in for AgentRuntime: one real streamed request, then the real result dict."""

    def __init__(self, *, llm, **kwargs) -> None:
        del kwargs
        self.llm = llm

    def run(self, *, user_message: str, history, session_id: str) -> dict:
        del history, session_id
        from src.product.outcome import RunOutcome, build_result_dict

        response = self.llm.stream_chat(
            [{"role": "user", "content": user_message}], on_text_chunk=lambda _chunk: None
        )
        return build_result_dict(
            RunOutcome("success", None, "success", False), Path("/tmp/runs/model-selection"),
            1, 1, response.content or "", self.llm.runtime_snapshot,
            response.response_model, content_filter_count=0,
        )


def test_concurrent_sessions_each_reach_their_own_model(server_settings, monkeypatch, tmp_path):
    requests: list[dict] = []
    # Generous, so a loaded machine is not mistaken for crossed sessions; a
    # timeout is reported on its own instead of as a request mismatch.
    barrier = threading.Barrier(3, timeout=60)
    barrier_broken: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({
            "host": request.url.host,
            "auth": request.headers["authorization"],
            "model": body["model"],
        })
        # All three requests are in flight at once, on three threads.
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            barrier_broken.append(body["model"])
        return httpx.Response(200, content=_sse(body["model"]),
                              headers={"content-type": "text/event-stream"})

    def _mock_clients(proxy=None, *, sdk=None):
        del proxy, sdk
        return (httpx.Client(transport=httpx.MockTransport(handler)),
                httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr("src.providers.llm._build_http_clients", _mock_clients)
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.runtime.AgentRuntime", _OneCallLoop)
    monkeypatch.setattr("src.config.loader.load_runtime_agent_config", lambda overrides=None: object())
    monkeypatch.setattr(
        "src.tools.background_tools.get_background_manager",
        lambda root: SimpleNamespace(for_scope=lambda scope, on_completion: SimpleNamespace(cancel_all=lambda: None)),
    )

    store = SessionStore(tmp_path / "sessions")
    service = SessionService(store=store, event_bus=EventBus(), runs_dir=tmp_path / "runs")
    selections = {
        "groq": {"provider": "groq", "model": "llama-a", "reasoning_effort": ""},
        "openrouter": {"provider": "openrouter", "model": "vendor/model-b", "reasoning_effort": "high"},
        "inherited": None,
    }
    sessions = {}
    for name, selection in selections.items():
        config = {SESSION_CONFIG_KEY: selection} if selection else {}
        sessions[name] = Session(title=name, config=config)
        store.create_session(sessions[name])

    async def _run_all():
        await asyncio.gather(*(
            service._run_attempt(session, Attempt(session_id=session.session_id, prompt="hi"))
            for session in sessions.values()
        ))

    asyncio.run(_run_all())

    assert not barrier_broken, (
        f"the three requests were never in flight together within 60s: {barrier_broken}"
    )
    # The configured provider keeps its settings exactly as today, generic
    # OPENAI_BASE_URL fallback included; only the other provider drops it.
    assert sorted((r["host"], r["auth"], r["model"]) for r in requests) == [
        ("api.groq.com", "Bearer gsk-real-groq", "llama-a"),
        ("generic.invalid", "Bearer sk-or-real-openrouter", "global/model"),
        ("generic.invalid", "Bearer sk-or-real-openrouter", "vendor/model-b"),
    ]
    replies = {name: store.get_messages(s.session_id)[-1].metadata for name, s in sessions.items()}
    assert {k: replies["groq"][k] for k in ("provider", "configured_model", "model", "model_source")} == {
        "provider": "groq", "configured_model": "llama-a", "model": "llama-a",
        "model_source": "session_provider_response",
    }
    assert replies["openrouter"]["model"] == "vendor/model-b"
    assert replies["openrouter"]["reasoning_effort"] == "high"
    assert replies["openrouter"]["model_source"] == "session_provider_response"
    assert replies["inherited"]["model"] == "global/model"
    assert replies["inherited"]["model_source"] == "provider_response"
    assert os.environ["LANGCHAIN_MODEL_NAME"] == "global/model"
    assert os.environ["LANGCHAIN_PROVIDER"] == "openrouter"


def test_a_failed_session_selection_fails_the_attempt_instead_of_falling_back(
    server_settings, monkeypatch, tmp_path
):
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    built = []
    monkeypatch.setattr(chat_module, "ChatLLM", lambda *a, **k: built.append(k) or SimpleNamespace(aclose=AsyncMock()))
    monkeypatch.delenv("GROQ_API_KEY")
    store = SessionStore(tmp_path / "sessions")
    service = SessionService(store=store, event_bus=EventBus(), runs_dir=tmp_path / "runs")
    session = Session(config={SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})
    store.create_session(session)
    attempt = Attempt(session_id=session.session_id, prompt="hi")

    asyncio.run(service._run_attempt(session, attempt))

    assert built == []
    assert attempt.status == AttemptStatus.FAILED
    assert "groq has no credentials" in attempt.error


# ---------------------------------------------------------------------------
# Reply metadata and strategy provenance through the real AgentRuntime
# ---------------------------------------------------------------------------


class _EmptyRegistry:
    _tools = {}

    def get_definitions(self):
        return []

    def get(self, name):
        return None


@pytest.mark.parametrize(
    ("response_model", "expected_model", "expected_source"),
    [("provider-reported", "provider-reported", "session_provider_response"), (None, "llama-a", "session")],
)
def test_agent_loop_reports_a_session_selected_model_as_such(
    server_settings, monkeypatch, tmp_path, response_model, expected_model, expected_source
):
    from src.agent.runtime import AgentRuntime

    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    llm = chat_llm_for_session({SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})
    llm.stream_chat = MethodType(
        lambda self, *a, **k: LLMResponse(content="done", response_model=response_model), llm
    )
    agent = AgentRuntime(registry=_EmptyRegistry(), llm=llm, max_iterations=1)  # type: ignore[arg-type]
    assert agent._write_targets.active_model_source == "session"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run("hello")

    assert result["provider"] == "groq"
    assert result["configured_model"] == "llama-a"
    assert result["model"] == expected_model
    assert result["model_source"] == expected_source


def test_llm_usage_names_the_provider_the_client_called(server_settings, monkeypatch):
    from src.product.usage import _new_llm_usage_summary

    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    llm = chat_llm_for_session({SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})

    summary = _new_llm_usage_summary(llm)

    assert (summary["provider"], summary["model"]) == ("groq", "llama-a")


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------


@pytest.fixture
def client(server_settings, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api_server

    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    monkeypatch.setattr(api_server, "_goal_store", None)
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _new_session(client, **body) -> str:
    response = client.post("/sessions", json={"title": "model", **body})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_routes_set_show_and_clear_a_session_model(client):
    import api_server

    sid = _new_session(client)
    assert client.get(f"/sessions/{sid}/model").json() == {
        "session_id": sid, "source": "inherited", "provider": "openrouter",
        "model": "global/model", "reasoning_effort": "", "error": None,
        "turn_running": False, "applies_from": "next_turn",
    }

    put = client.put(f"/sessions/{sid}/model",
                     json={"provider": "GROQ", "model": " llama-a ", "reasoning_effort": "Low"})
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "session"
    assert (put.json()["provider"], put.json()["model"], put.json()["reasoning_effort"]) == ("groq", "llama-a", "low")
    stored = api_server._get_session_service().store.get_session(sid)
    assert stored.config[SESSION_CONFIG_KEY] == {"provider": "groq", "model": "llama-a", "reasoning_effort": "low"}
    assert client.get(f"/sessions/{sid}/model").json()["model"] == "llama-a"

    cleared = client.delete(f"/sessions/{sid}/model")
    assert cleared.status_code == 200
    assert cleared.json()["source"] == "inherited"
    assert SESSION_CONFIG_KEY not in api_server._get_session_service().store.get_session(sid).config


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"provider": "nonesuch", "model": "m"}, "Unsupported LLM provider"),
        ({"provider": "anthropic", "model": "claude-x"}, "no credentials"),
        ({"provider": "groq", "model": "m", "reasoning_effort": "turbo"}, "Reasoning effort"),
        ({"provider": "groq", "model": "m", "base_url": "https://evil.invalid/v1"}, "base_url"),
        ({"provider": "groq", "model": "m", "api_key": "sk-mine"}, "api_key"),
        ({"provider": "groq", "model": "m", "default_headers": {"X": "1"}}, "default_headers"),
    ],
)
def test_route_refuses_a_selection_the_server_does_not_offer(client, body, fragment):
    import api_server

    sid = _new_session(client)
    response = client.put(f"/sessions/{sid}/model", json=body)

    assert response.status_code == 400
    assert fragment in response.json()["detail"]
    assert SESSION_CONFIG_KEY not in api_server._get_session_service().store.get_session(sid).config


def test_create_session_holds_its_selection_to_the_same_rules(client):
    import api_server

    refused = client.post("/sessions", json={"config": {SESSION_CONFIG_KEY: {
        "provider": "groq", "model": "m", "base_url": "https://evil.invalid/v1"}}})
    assert refused.status_code == 400
    assert "base_url" in refused.json()["detail"]

    sid = _new_session(client, config={"x": 1, SESSION_CONFIG_KEY: {"provider": "Groq", "model": "llama-a"}})
    config = api_server._get_session_service().store.get_session(sid).config
    assert config == {"x": 1, SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a", "reasoning_effort": ""}}


@pytest.mark.parametrize(
    ("status", "running"),
    [
        # A pending attempt already holds the session it was sent with.
        (AttemptStatus.PENDING, True),
        (AttemptStatus.RUNNING, True),
        (AttemptStatus.COMPLETED, False),
    ],
)
def test_route_says_a_started_turn_keeps_its_model(client, status, running):
    import api_server

    sid = _new_session(client)
    store = api_server._get_session_service().store
    session = store.get_session(sid)
    attempt = Attempt(session_id=sid, prompt="turn")
    attempt.status = status
    store.create_attempt(attempt)
    session.last_attempt_id = attempt.attempt_id
    store.update_session(session)

    response = client.put(f"/sessions/{sid}/model", json={"provider": "groq", "model": "llama-a"})

    assert response.json()["turn_running"] is running
    assert response.json()["applies_from"] == "next_turn"


def test_route_unknown_session_is_404(client):
    for method in ("get", "delete"):
        assert getattr(client, method)("/sessions/abcdef012345/model").status_code == 404
    response = client.put("/sessions/abcdef012345/model", json={"provider": "groq", "model": "m"})
    assert response.status_code == 404


def test_model_routes_require_auth_when_a_key_is_configured(client, monkeypatch):
    from fastapi.testclient import TestClient

    import api_server

    sid = _new_session(client)
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")
    reset_env_config()
    remote = TestClient(api_server.app, client=("203.0.113.10", 50000))
    body = {"provider": "groq", "model": "llama-a"}

    assert remote.get(f"/sessions/{sid}/model").status_code == 401
    assert remote.put(f"/sessions/{sid}/model", json=body).status_code == 401
    assert remote.delete(f"/sessions/{sid}/model").status_code == 401
    assert SESSION_CONFIG_KEY not in api_server._get_session_service().store.get_session(sid).config
    bearer = {"Authorization": "Bearer secret"}
    assert remote.put(f"/sessions/{sid}/model", json=body, headers=bearer).status_code == 200
    assert remote.get(f"/sessions/{sid}/model", headers=bearer).json()["source"] == "session"


# ---------------------------------------------------------------------------
# CLI /model
# ---------------------------------------------------------------------------


@pytest.fixture
def cli(server_settings, tmp_path, monkeypatch):
    import importlib

    cli_main = importlib.import_module("cli.main")

    from io import StringIO

    from rich.console import Console

    store = SessionStore(tmp_path / "sessions")
    out = StringIO()
    monkeypatch.setattr(cli_main, "_SESSION_STORE_CACHE", store)
    monkeypatch.setattr(_cmd_providers, "_show_settings", lambda: None)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: _DummyIndex())
    monkeypatch.setattr("cli.commands.chat.get_console", lambda: Console(file=out, width=200))
    return SimpleNamespace(store=store, out=out)


def test_cli_model_sets_and_clears_the_current_sessions_selection(cli, tmp_path, monkeypatch):
    from cli.commands.chat import cmd_model

    cli_store = cli.store

    ctx = SimpleNamespace(session_id=None)
    assert cmd_model(ctx, "set", "groq", "llama-a", "high") == 0
    assert ctx.session_id is not None
    stored = cli_store.get_session(ctx.session_id).config[SESSION_CONFIG_KEY]
    assert stored == {"provider": "groq", "model": "llama-a", "reasoning_effort": "high"}

    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    llm = chat_llm_for_stored_session(tmp_path / "sessions", ctx.session_id)
    assert (llm.config.provider, llm.model_name, llm.runtime_snapshot.selection) == ("groq", "llama-a", "session")

    assert cmd_model(ctx) == 0
    assert "This session: groq / llama-a (effort high)" in cli.out.getvalue()

    assert cmd_model(ctx, "clear") == 0
    assert SESSION_CONFIG_KEY not in cli_store.get_session(ctx.session_id).config
    assert chat_llm_for_stored_session(tmp_path / "sessions", ctx.session_id).runtime_snapshot.selection == "configured"
    cli.out.truncate(0)
    cli.out.seek(0)
    cmd_model(ctx)
    assert "This session:" not in cli.out.getvalue()


def test_cli_model_refuses_an_unusable_selection_and_bad_usage(cli):
    from cli.commands.chat import cmd_model

    ctx = SimpleNamespace(session_id=None)
    assert cmd_model(ctx, "set", "anthropic", "claude-x") == 1
    assert cmd_model(ctx, "set", "groq") == 1
    assert cmd_model(ctx, "use", "groq", "m") == 1
    assert ctx.session_id is None


def test_effective_selection_reports_an_unreadable_stored_one():
    session = Session(config={SESSION_CONFIG_KEY: {"provider": "groq", "model": "m", "api_key": "x"}})

    view = effective_model_selection(session)

    assert view["source"] == "session"
    assert "api_key" in view["error"]


# ---------------------------------------------------------------------------
# The loop reads the session client's provider, not the server's
# ---------------------------------------------------------------------------


def test_context_window_follows_the_session_clients_provider(server_settings, monkeypatch):
    from src.agent.runtime import AgentRuntime
    from src.kernel.contracts import LLMRuntimeSnapshot

    # The server is configured for another provider; the catalog scopes this
    # model's 272K window to openai-codex only.
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
    monkeypatch.delenv("VIBE_TRADING_CONTEXT_WINDOW", raising=False)
    reset_env_config()
    llm = SimpleNamespace(
        model_name="gpt-5.5",
        runtime_snapshot=LLMRuntimeSnapshot("openai-codex", "gpt-5.5", "", "session"),
    )
    agent = AgentRuntime(registry=_EmptyRegistry(), llm=llm, max_iterations=1)  # type: ignore[arg-type]

    budget = agent._context_compactor._context_budget([])

    assert budget.window == 272_000
    assert budget.source.startswith("catalog:")


def test_empty_response_trace_names_the_session_clients_provider(server_settings, monkeypatch, tmp_path):
    from src.agent.runtime import AgentRuntime
    from tests.recording_helpers import records_at

    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    llm = chat_llm_for_session({SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})
    llm.stream_chat = MethodType(lambda self, *a, **k: LLMResponse(content=""), llm)
    agent = AgentRuntime(registry=_EmptyRegistry(), llm=llm, max_iterations=3)  # type: ignore[arg-type]
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run("hello")

    empties = [e for e in records_at(Path(result["run_dir"])) if e.get("type") == "empty_model_response"]
    assert empties
    assert {e["provider"] for e in empties} == {"groq"}


def test_strategy_provenance_records_a_session_selected_model(server_settings, monkeypatch, tmp_path):
    """Two real WriteFileTool turns on a session client, as in the provenance suite."""
    from src.product.resources.memory import WorkspaceMemory
    from src.agent.runtime import AgentRuntime
    from src.agent.tools import ToolRegistry
    from src.tools.write_file_tool import WriteFileTool

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())
    turns = iter([
        SimpleNamespace(
            content="Writing.", reasoning_content=None, usage_metadata=None,
            response_model=model, has_tool_calls=True,
            tool_calls=[SimpleNamespace(id=f"w{index}", name="write_file",
                                        arguments={"path": path, "content": "{}"})],
        )
        for index, (path, model) in enumerate([("config.json", "llama-a-0423"), ("code/signal_engine.py", None)])
    ] + [SimpleNamespace(content="Saved.", reasoning_content=None, usage_metadata=None,
                         response_model=None, has_tool_calls=False, tool_calls=[])])
    llm = chat_llm_for_session({SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})
    llm.stream_chat = MethodType(lambda self, *a, **k: next(turns), llm)
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    agent = AgentRuntime(registry=registry, llm=llm, memory=WorkspaceMemory(run_dir=str(tmp_path)),
                      max_iterations=3)

    result = agent.run(user_message="Write the strategy files.")

    assert result["status"] == "success", result
    files = json.loads((Path(result["run_dir"]) / "strategy_provenance.json").read_text())["files"]
    assert files["config.json"] == {
        "provider": "groq", "model_id": "llama-a-0423", "model_source": "session_provider_response",
    }
    assert files["code/signal_engine.py"] == {
        "provider": "groq", "model_id": "llama-a", "model_source": "session",
    }


# ---------------------------------------------------------------------------
# Keyless providers and the settings form
# ---------------------------------------------------------------------------


def test_a_keyless_provider_needs_its_own_configured_endpoint(server_settings, monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    reset_env_config()
    with pytest.raises(ModelSelectionError, match="OLLAMA_BASE_URL"):
        validate_model_selection({"provider": "ollama", "model": "qwen"})

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    reset_env_config()
    _selection, config = validate_model_selection({"provider": "ollama", "model": "qwen"})
    assert config.base_url.startswith("http://ollama.internal:11434")


def test_a_keyless_provider_the_server_runs_on_stays_selectable(server_settings, monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "ollama")
    reset_env_config()

    selection, _config = validate_model_selection({"provider": "ollama", "model": "other"})

    assert (selection.provider, selection.model) == ("ollama", "other")


@pytest.mark.parametrize(
    "extra",
    [{"base_url": "https://elsewhere.invalid/v1"}, {"api_key": "sk-new"}, {"clear_api_key": True}],
)
def test_settings_form_cannot_edit_a_custom_providers_connection(client, monkeypatch, extra):
    import src.api.settings_routes as settings_routes
    from src.providers import custom_profiles

    monkeypatch.setattr(
        custom_profiles, "active_provider_credentials",
        lambda: {"model": "alpha-model", "base_url": "https://alpha.example/v1", "api_key": "k"},
    )
    persisted = []
    monkeypatch.setattr(settings_routes, "_persist_settings_updates",
                        lambda updates, **kwargs: persisted.append(updates) or {})

    response = client.put("/settings/llm", json={"provider": "custom", "model_name": "alpha-model", **extra})

    assert response.status_code == 400
    assert "provider manager" in response.json()["detail"]
    assert persisted == []


# ---------------------------------------------------------------------------
# CLI: an unusable session model fails the turn, not the REPL
# ---------------------------------------------------------------------------


def test_cli_turn_with_an_unusable_session_model_fails_without_raising(server_settings, monkeypatch, tmp_path):

    store = SessionStore(tmp_path / "sessions")
    session = Session(title="cli", config={SESSION_CONFIG_KEY: {"provider": "groq", "model": "llama-a"}})
    store.create_session(session)
    monkeypatch.setattr(_cmd_common, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())

    def _no_registry(**kwargs):
        raise AssertionError("a turn whose model is unusable must not build the tool registry")

    monkeypatch.setattr("src.tools.build_registry", _no_registry)
    monkeypatch.delenv("GROQ_API_KEY")

    result = _cmd_execution._run_agent("hi", no_rich=True, session_id=session.session_id)

    assert result["status"] == "failed"
    assert "groq has no credentials" in result["reason"]
    assert "/model clear" in result["content"]
