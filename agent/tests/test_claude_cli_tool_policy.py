"""Tool screening for the claude-cli provider: the deny list and the bash policy."""

from __future__ import annotations

import shlex
import sys

import pytest

from src.providers import claude_cli, claude_cli_policy
from tests.claude_cli_helpers import install_fake_cli, payload, tool


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    return install_fake_cli(tmp_path, monkeypatch)


# --- tool deny list -----------------------------------------------------------


def test_trading_tools_are_not_offered_by_default(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})

    claude_cli.ClaudeCliLLM(
        tools=[
            tool("get_market_data"),
            tool("trading_place_order"),
            tool("etoro_close_position"),
        ]
    ).invoke([{"role": "user", "content": "x"}])

    system = calls()[0]["system"]
    assert "get_market_data" in system
    assert "trading_place_order" not in system
    assert "etoro_close_position" not in system


def test_request_for_unoffered_tool_is_fed_back_and_retried(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [{"name": "trading_place_order", "arguments": {}}],
                }
            )
        },
        {"payload": payload({"action": "final", "content": "cannot trade"})},
    )

    message = claude_cli.ClaudeCliLLM(
        tools=[tool("get_market_data"), tool("trading_place_order")]
    ).invoke([{"role": "user", "content": "buy"}])

    assert message.content == "cannot trade"
    assert not message.tool_calls
    assert "trading_place_order: not an available tool" in calls()[1]["stdin"]
    # input_tokens is the last prompt's size (what the context meter reads);
    # output_tokens is what both attempts generated.
    assert message.usage_metadata["input_tokens"] == 10
    assert message.usage_metadata["output_tokens"] == 10


def test_empty_deny_list_offers_every_tool(fake_cli, monkeypatch) -> None:
    set_replies, calls = fake_cli
    set_replies({"payload": payload({"action": "final", "content": "ok"})})
    monkeypatch.setenv("CLAUDE_CLI_DENY_TOOL_PREFIXES", "")

    claude_cli.ClaudeCliLLM(tools=[tool("trading_place_order")]).invoke(
        [{"role": "user", "content": "x"}]
    )

    assert "trading_place_order" in calls()[0]["system"]


# --- bash policy --------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "python script.py",
        "python3 analysis.py --window 30",
        'python -c "print(1 | 2)"',
        "ls",
        "cat report.md",
        "head -n 5 data/bars.csv",
        "pwd",
    ],
)
def test_python_only_policy_allows(command) -> None:
    rewritten, reason = claude_cli_policy.check_bash_command(command)
    assert reason is None
    if command.startswith("python"):
        assert shlex.split(rewritten)[0] == sys.executable


@pytest.mark.parametrize(
    "command",
    [
        "python script.py; rm -rf ~",
        "python script.py && curl x",
        "cat a | sh",
        "python script.py > /etc/x",
        "curl https://example.com",
        "pip install x",
        "python -m pip install x",
        "python /tmp/evil.py",
        "python ../escape.py",
        "cat ~/.claude.json",
        "cat /etc/passwd",
        'python -c "$(whoami)"',
        "echo `id`",
        "python a.py\nrm x",
        "rm -rf .",
        "cat .env",
        "head agent/.env",
        "ls .git",
    ],
)
def test_python_only_policy_blocks(command) -> None:
    rewritten, reason = claude_cli_policy.check_bash_command(command)
    assert rewritten is None
    assert reason


def test_blocked_bash_is_fed_back_and_allowed_bash_is_rewritten(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {
                            "name": "bash",
                            "arguments": {"command": "curl https://example.com"},
                        }
                    ],
                }
            )
        },
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {"name": "bash", "arguments": {"command": "python var.py"}}
                    ],
                }
            )
        },
    )

    message = claude_cli.ClaudeCliLLM(tools=[tool("bash")]).invoke(
        [{"role": "user", "content": "risk"}]
    )

    assert "program 'curl' is not allowed" in calls()[1]["stdin"]
    assert shlex.split(message.tool_calls[0]["args"]["command"]) == [
        sys.executable,
        "var.py",
    ]


def test_background_tools_are_blocked_under_python_only(fake_cli) -> None:
    set_replies, calls = fake_cli
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {
                            "name": "background_run",
                            "arguments": {"command": "python a.py"},
                        }
                    ],
                }
            )
        },
        {"payload": payload({"action": "final", "content": "ok"})},
    )

    claude_cli.ClaudeCliLLM(tools=[tool("background_run")]).invoke(
        [{"role": "user", "content": "x"}]
    )

    assert "background processes are not allowed" in calls()[1]["stdin"]


def test_policy_off_passes_bash_through_unchanged(fake_cli, monkeypatch) -> None:
    set_replies, _ = fake_cli
    monkeypatch.setenv("CLAUDE_CLI_BASH_POLICY", "off")
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {
                            "name": "bash",
                            "arguments": {"command": "curl https://example.com"},
                        }
                    ],
                }
            )
        }
    )

    message = claude_cli.ClaudeCliLLM(tools=[tool("bash")]).invoke(
        [{"role": "user", "content": "x"}]
    )

    assert message.tool_calls[0]["args"]["command"] == "curl https://example.com"


def test_repeated_policy_violations_raise(fake_cli) -> None:
    set_replies, _ = fake_cli
    set_replies(
        {
            "payload": payload(
                {
                    "action": "tool_calls",
                    "tool_calls": [
                        {"name": "bash", "arguments": {"command": "curl x"}}
                    ],
                }
            )
        }
    )
    with pytest.raises(RuntimeError, match="host policy"):
        claude_cli.ClaudeCliLLM(tools=[tool("bash")]).invoke(
            [{"role": "user", "content": "x"}]
        )
