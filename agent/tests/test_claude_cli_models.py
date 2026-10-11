"""Model discovery and reasoning effort for the claude-cli provider."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from src.providers import claude_cli, claude_cli_models
from tests.claude_cli_helpers import (
    install_fake_cli,
    install_fake_init_cli,
    payload,
    tool,
    use_provider,
)

_CLI_MODELS = [
    {
        "value": "default",
        "resolvedModel": "claude-opus-5-5",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"],
    },
    {
        "value": "opus",
        "resolvedModel": "claude-opus-5-5",
        "supportsEffort": True,
        "supportedEffortLevels": ["low"],
    },
    {"value": "haiku", "resolvedModel": "claude-haiku-4-5-20251001"},
    {
        "value": "claude-sonnet-4-6",
        "resolvedModel": "claude-sonnet-4-6",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high", "max"],
    },
    {"value": "broken"},
]


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    return install_fake_cli(tmp_path, monkeypatch)


@pytest.fixture
def fake_init_cli(tmp_path, monkeypatch):
    return install_fake_init_cli(tmp_path, monkeypatch)


# --- model discovery ----------------------------------------------------------


def test_model_list_dedupes_on_resolved_name_and_keeps_levels(fake_init_cli) -> None:
    set_reply, calls = fake_init_cli
    set_reply({"models": _CLI_MODELS})

    models = claude_cli_models.list_claude_cli_models()

    assert [m.model_id for m in models] == [
        "claude-opus-5-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
    ]
    assert models[0].effort_levels == ("low", "medium", "high", "xhigh", "max")
    assert models[1].effort_levels == ()
    assert models[2].effort_levels == ("low", "medium", "high", "max")
    (call,) = calls()
    assert {"--restricted", "--strict-mcp-config", "--no-session-persistence"} <= set(
        call["args"]
    )
    assert json.loads(call["stdin"])["request"] == {"subtype": "initialize"}


def test_model_list_skips_lines_that_are_not_json(fake_init_cli) -> None:
    set_reply, _ = fake_init_cli
    set_reply({"models": [_CLI_MODELS[3]]})

    models = claude_cli_models.list_claude_cli_models()

    assert [m.model_id for m in models] == ["claude-sonnet-4-6"]


def test_model_list_is_cached_until_refresh(fake_init_cli) -> None:
    set_reply, calls = fake_init_cli
    set_reply({"models": _CLI_MODELS})

    claude_cli_models.list_claude_cli_models()
    claude_cli_models.list_claude_cli_models()
    assert len(calls()) == 1

    claude_cli_models.list_claude_cli_models(refresh=True)
    assert len(calls()) == 2


@pytest.mark.parametrize("reply", [{"exit": 1}, {"models": []}])
def test_model_list_failure_raises(fake_init_cli, reply) -> None:
    set_reply, _ = fake_init_cli
    set_reply(reply)

    with pytest.raises(RuntimeError, match="model list unavailable"):
        claude_cli_models.list_claude_cli_models()


# --- reasoning effort ---------------------------------------------------------


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        ("high", ["--effort", "high"]),
        ("xhigh", ["--effort", "xhigh"]),
        ("", None),
        ("none", None),
        ("turbo", None),
    ],
)
def test_effort_reaches_the_cli_only_when_it_is_a_cli_level(
    fake_cli, effort, expected
) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})

    claude_cli.ClaudeCliLLM(reasoning_effort=effort).invoke(
        [{"role": "user", "content": "hi"}]
    )

    args = calls()[0]["args"]
    if expected is None:
        assert "--effort" not in args
    else:
        index = args.index("--effort")
        assert args[index : index + 2] == expected


def test_malformed_control_response_is_reported_not_crashed(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        line = json.dumps({"type": "control_response", "response": "oops"})
        return subprocess.CompletedProcess(cmd, 0, stdout=line + "\n", stderr="")

    monkeypatch.setenv("CLAUDE_CLI_PATH", "/bin/true")
    monkeypatch.setattr(claude_cli_models, "_model_cache", {})
    # Replace the module's reference, not the shared ``subprocess`` module (#1123).
    monkeypatch.setattr(
        claude_cli_models,
        "subprocess",
        SimpleNamespace(run=fake_run, SubprocessError=subprocess.SubprocessError),
    )

    with pytest.raises(RuntimeError, match="model list unavailable"):
        claude_cli_models.list_claude_cli_models()


@pytest.mark.parametrize("raw", ["High", " high "])
def test_build_llm_normalises_reasoning_effort(monkeypatch, raw) -> None:
    import src.providers.llm as llm

    use_provider(monkeypatch)
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", raw)

    assert llm.build_llm().reasoning_effort == "high"


def test_build_llm_passes_reasoning_effort_through_bind_tools(monkeypatch) -> None:
    import src.providers.llm as llm

    use_provider(monkeypatch)
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "xhigh")

    model = llm.build_llm()

    assert model.reasoning_effort == "xhigh"
    assert model.bind_tools([tool("get_market_data")]).reasoning_effort == "xhigh"
