"""Coverage for the local Claude Code CLI provider (``claude -p`` as a decision-only model)."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import api_server  # noqa: F401
from src.api import settings_routes
from src.providers import claude_cli
from src.providers.capabilities import get_provider_capabilities
from src.providers.chat import ChatLLM
from src.swarm.models import public_provider_metadata
from tests.claude_cli_helpers import install_fake_cli, payload, tool, use_provider

_PROVIDERS_JSON = (
    Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    return install_fake_cli(tmp_path, monkeypatch)


# --- registration -----------------------------------------------------------


def test_claude_cli_is_registered_in_catalog_and_capabilities() -> None:
    entries = {
        item["name"]: item
        for item in json.loads(_PROVIDERS_JSON.read_text(encoding="utf-8"))
    }
    entry = entries["claude-cli"]
    assert entry["api_key_required"] is False
    assert entry["auth_type"] == "claude_cli"
    assert (
        get_provider_capabilities("claude-cli", "claude-opus-5-5").name == "claude-cli"
    )


def test_claude_cli_label_survives_public_run_metadata() -> None:
    assert public_provider_metadata("claude-cli") == "claude-cli"


def test_sync_provider_env_clears_openai_transport(monkeypatch) -> None:
    import src.providers.llm as llm

    use_provider(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    llm._sync_provider_env()
    import os

    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_build_llm_returns_cli_wrapper(monkeypatch) -> None:
    import src.providers.llm as llm

    use_provider(monkeypatch)
    model = llm.build_llm()
    assert isinstance(model, claude_cli.ClaudeCliLLM)
    assert model.model == "claude-opus-5-5"


# --- decision mapping ---------------------------------------------------------


def test_tool_calls_map_to_vibe_tool_call_requests(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {
                            "name": "get_market_data",
                            "arguments": {"codes": ["03988.HK"]},
                        }
                    ],
                }
            )
        }
    )
    use_provider(monkeypatch)

    response = ChatLLM().stream_chat(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "price?"}],
        tools=[tool("get_market_data")],
    )

    assert response.has_tool_calls
    call = response.tool_calls[0]
    assert call.name == "get_market_data"
    assert call.arguments == {"codes": ["03988.HK"]}
    assert call.id.startswith("ccli_")
    assert response.usage_metadata["input_tokens"] == 10


def test_final_answer_maps_to_content(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "close 6.125"})})
    use_provider(monkeypatch)

    response = ChatLLM().chat([{"role": "user", "content": "hi"}])

    assert response.content == "close 6.125"
    assert not response.has_tool_calls


def test_final_without_content_is_fed_back_and_retried(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies(
        {"payload": payload({"action": "final"})},
        {"payload": payload({"action": "final", "content": "order 42 cancelled"})},
    )

    message = claude_cli.ClaudeCliLLM(tools=[tool("get_market_data")]).invoke(
        [{"role": "user", "content": "cancel"}]
    )

    assert message.content == "order 42 cancelled"
    assert "no tool calls and no content" in calls()[1]["stdin"]
    # input_tokens is the last prompt's size (what the context meter reads);
    # output_tokens is what both attempts generated.
    assert message.usage_metadata["input_tokens"] == 10
    assert message.usage_metadata["output_tokens"] == 10


def test_final_never_echoes_the_structured_output_as_content(fake_cli) -> None:
    set_replies, _ = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "  "})})

    with pytest.raises(RuntimeError, match="without content"):
        claude_cli.ClaudeCliLLM().invoke([{"role": "user", "content": "x"}])


def test_vibe_system_prompt_is_a_verbatim_prefix_and_lone_user_is_verbatim(
    fake_cli,
) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})
    system = "## Role\n\nexact text {with braces}\n"
    user = "Report the latest close of 03988.HK."

    claude_cli.ClaudeCliLLM(tools=[tool("get_market_data")]).invoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )

    record = calls()[0]
    assert record["system"].startswith(system)
    assert "Tool-calling protocol" in record["system"]
    assert record["stdin"] == user


def test_turn_without_tools_only_allows_final(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})

    claude_cli.ClaudeCliLLM().invoke([{"role": "user", "content": "x"}])

    args = calls()[0]["args"]
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert schema["properties"]["action"]["enum"] == ["final"]
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--restricted" in args


def test_history_renders_tool_calls_and_results(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "done"})})
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "price?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_market_data", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "get_market_data",
            "content": "close=6.125",
        },
    ]

    claude_cli.ClaudeCliLLM(tools=[tool("get_market_data")]).invoke(messages)

    stdin = calls()[0]["stdin"]
    assert "[assistant tool_calls]" in stdin
    assert "[tool result: get_market_data id=c1]\nclose=6.125" in stdin


# --- error paths --------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, message",
    [
        ({"raw": "not json"}, "no JSON"),
        ({"payload": payload({"action": "final"}, is_error=True)}, "failed"),
        ({"payload": payload(None)}, "structured_output"),
    ],
)
def test_bad_cli_output_raises(fake_cli, reply, message) -> None:
    set_replies, _ = fake_cli
    set_replies(reply)
    with pytest.raises(RuntimeError, match=message):
        claude_cli.ClaudeCliLLM().invoke([{"role": "user", "content": "x"}])


def test_timeout_kills_the_child(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {"sleep": 30, "payload": payload({"action": "final", "content": "late"})}
    )
    monkeypatch.setattr(claude_cli, "_TIMEOUT_FLOOR_S", 1)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="exceeded"):
        claude_cli.ClaudeCliLLM(timeout=1).invoke([{"role": "user", "content": "x"}])
    assert time.monotonic() - started < 10


def test_cancel_event_stops_the_child(fake_cli) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {"sleep": 30, "payload": payload({"action": "final", "content": "late"})}
    )
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    started = time.monotonic()
    result = claude_cli._run_cli(
        system="S",
        user_input="x",
        allow_tools=False,
        model="m",
        timeout=60,
        cancel_event=cancel,
    )
    assert result == {"cancelled": True}
    assert time.monotonic() - started < 10


def test_slow_decision_outlives_the_stream_idle_timeout(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {"sleep": 3, "payload": payload({"action": "final", "content": "slow answer"})}
    )
    monkeypatch.setattr(claude_cli, "_HEARTBEAT_S", 0.2)
    use_provider(monkeypatch)

    response = ChatLLM().stream_chat(
        [{"role": "user", "content": "x"}], idle_timeout_s=1
    )

    assert response.content == "slow answer"


def test_stop_button_ends_a_running_decision(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {"sleep": 30, "payload": payload({"action": "final", "content": "late"})}
    )
    monkeypatch.setattr(claude_cli, "_HEARTBEAT_S", 0.2)
    use_provider(monkeypatch)
    stop_at = time.monotonic() + 1.0

    started = time.monotonic()
    response = ChatLLM().stream_chat(
        [{"role": "user", "content": "x"}],
        should_cancel=lambda: time.monotonic() > stop_at,
    )

    assert time.monotonic() - started < 10
    assert response.content == ""


def test_retries_share_one_deadline(fake_cli, monkeypatch) -> None:
    set_replies, calls = fake_cli
    set_replies({"sleep": 0.7, "payload": payload({"action": "final"})})
    monkeypatch.setattr(claude_cli, "_TIMEOUT_FLOOR_S", 1)

    with pytest.raises(RuntimeError, match="exceeded"):
        claude_cli.ClaudeCliLLM(timeout=1).invoke([{"role": "user", "content": "x"}])

    # Four attempts fit in 4 x 1s budgets but not in one shared 1s deadline.
    assert len(calls()) < 4


def test_image_input_is_refused_instead_of_dropped(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "a cat"})})
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}

    with pytest.raises(RuntimeError, match="text input only"):
        claude_cli.ClaudeCliLLM().invoke(
            [{"role": "user", "content": [{"type": "text", "text": "what?"}, image]}]
        )

    assert calls() == []


def test_lone_langchain_human_message_is_passed_verbatim(fake_cli) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})

    claude_cli.ClaudeCliLLM().invoke(
        [SystemMessage(content="SYS"), HumanMessage(content="exact prompt")]
    )

    assert calls()[0]["stdin"] == "exact prompt"


def test_unknown_bash_policy_fails_before_any_turn(fake_cli, monkeypatch) -> None:
    _, calls = fake_cli
    monkeypatch.setenv("CLAUDE_CLI_BASH_POLICY", "strict")

    with pytest.raises(RuntimeError, match="CLAUDE_CLI_BASH_POLICY"):
        claude_cli.ClaudeCliLLM()

    assert calls() == []


def test_auth_status_runs_without_the_anthropic_key(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"loggedIn": true, "authMethod": "claude.ai"}', stderr=""
        )

    monkeypatch.setenv("CLAUDE_CLI_PATH", "/bin/true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-used")
    # Replace the module's reference, not the shared ``subprocess`` module (#1123).
    monkeypatch.setattr(
        claude_cli,
        "subprocess",
        SimpleNamespace(run=fake_run, SubprocessError=subprocess.SubprocessError),
    )

    assert claude_cli.get_claude_cli_auth_status() == (True, "claude.ai")
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_missing_cli_raises_with_setup_hint(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(claude_cli.Path, "home", lambda: Path("/nonexistent-home"))
    with pytest.raises(RuntimeError, match="claude auth login"):
        claude_cli.resolve_claude_cli()


# --- settings / preflight -----------------------------------------------------


def test_settings_report_cli_login(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_cli, "get_claude_cli_auth_status", lambda: (True, "claude.ai")
    )

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "claude-cli"}
    )

    assert response.api_key_required is False
    assert response.api_key_configured is True
    assert response.api_key_hint == "claude.ai"


def test_preflight_uses_cli_login(monkeypatch) -> None:
    import src.providers.llm as llm
    from src import preflight

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "claude-cli")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "claude-opus-5-5")
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(llm, "_sync_provider_env", lambda: None)
    monkeypatch.setattr(
        llm,
        "provider_diagnostics",
        lambda: {"base_url": "", "timeout_seconds": 120, "max_retries": 2, "proxy": {}},
    )
    monkeypatch.setattr(
        claude_cli, "get_claude_cli_auth_status", lambda: (False, "not logged in")
    )

    result = preflight._check_llm_provider()

    assert result.status == "not_configured"
    assert "claude auth login" in result.impact
