"""Fake ``claude`` executables and payload builders for the claude-cli provider tests.

Both fakes are real scripts on ``CLAUDE_CLI_PATH``, so the provider's actual
subprocess handling runs; every call is logged to disk for the test to inspect.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable

import pytest

from src.providers import claude_cli_models

# Answers one ``claude -p`` turn from a reply list, one reply per call.
_FAKE_CLI = textwrap.dedent("""\
    #!{python}
    import json, os, sys, time
    from pathlib import Path

    log = Path(os.environ["FAKE_CLAUDE_LOG"])
    replies = json.loads(Path(os.environ["FAKE_CLAUDE_REPLIES"]).read_text())
    calls = sorted(log.glob("call-*.json"))
    n = len(calls)
    args = sys.argv[1:]
    system = Path(args[args.index("--system-prompt-file") + 1]).read_text()
    record = {{"args": args, "stdin": sys.stdin.read(), "system": system}}
    (log / f"call-{{n:03d}}.json").write_text(json.dumps(record))
    reply = replies[min(n, len(replies) - 1)]
    if reply.get("sleep"):
        time.sleep(reply["sleep"])
    if reply.get("raw") is not None:
        sys.stdout.write(reply["raw"])
    else:
        sys.stdout.write(json.dumps(reply["payload"]))
    """)

# Answers the ``initialize`` control request, surrounded by the noise a real
# CLI prints: a non-JSON line and a system event before the response.
_FAKE_INIT_CLI = textwrap.dedent("""\
    #!{python}
    import json, os, sys
    from pathlib import Path

    log = Path(os.environ["FAKE_CLAUDE_LOG"])
    n = len(list(log.glob("init-*.json")))
    record = {{"args": sys.argv[1:], "stdin": sys.stdin.read()}}
    (log / f"init-{{n:03d}}.json").write_text(json.dumps(record))
    reply = json.loads(Path(os.environ["FAKE_CLAUDE_REPLIES"]).read_text())
    if reply.get("exit"):
        sys.stderr.write("boom")
        sys.exit(reply["exit"])
    sys.stdout.write("not json at all\\n")
    sys.stdout.write(json.dumps({{"type": "system", "subtype": "hook_started"}}) + "\\n")
    response = {{"models": reply["models"]}}
    sys.stdout.write(json.dumps({{
        "type": "control_response",
        "response": {{"subtype": "success", "request_id": "x", "response": response}},
    }}) + "\\n")
    """)

SetReplies = Callable[..., None]
Calls = Callable[[], list[dict[str, Any]]]


def _install(
    script_text: str, log_glob: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Calls]:
    script = tmp_path / "claude"
    script.write_text(script_text.format(python=sys.executable))
    script.chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    reply_path = tmp_path / "replies.json"
    monkeypatch.setenv("CLAUDE_CLI_PATH", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_REPLIES", str(reply_path))

    def calls() -> list[dict[str, Any]]:
        return [json.loads(p.read_text()) for p in sorted(log.glob(log_glob))]

    return reply_path, calls


def install_fake_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SetReplies, Calls]:
    """Put a fake turn-answering ``claude`` on ``CLAUDE_CLI_PATH``.

    Args:
        tmp_path: Directory for the script, its replies and its call log.
        monkeypatch: Fixture used to point the provider at the script.

    Returns:
        ``(set_replies, calls)``: ``set_replies(*replies)`` queues one reply per
        call (the last repeats); ``calls()`` returns each logged invocation.
    """
    reply_path, calls = _install(_FAKE_CLI, "call-*.json", tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_CLI_DENY_TOOL_PREFIXES", raising=False)
    monkeypatch.delenv("CLAUDE_CLI_BASH_POLICY", raising=False)

    def set_replies(*replies: dict[str, Any]) -> None:
        reply_path.write_text(json.dumps(list(replies)))

    return set_replies, calls


def install_fake_init_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SetReplies, Calls]:
    """Put a fake ``claude`` answering the ``initialize`` request on the path.

    Also empties the provider's model-list cache so each test starts cold.

    Args:
        tmp_path: Directory for the script, its reply and its call log.
        monkeypatch: Fixture used to point the provider at the script.

    Returns:
        ``(set_reply, calls)``: ``set_reply({"models": [...]})`` or
        ``set_reply({"exit": code})`` sets the answer; ``calls()`` returns each
        logged invocation.
    """
    reply_path, calls = _install(_FAKE_INIT_CLI, "init-*.json", tmp_path, monkeypatch)
    monkeypatch.setattr(claude_cli_models, "_model_cache", {})

    def set_reply(reply: dict[str, Any]) -> None:
        reply_path.write_text(json.dumps(reply))

    return set_reply, calls


def payload(
    structured: dict[str, Any] | None,
    *,
    is_error: bool = False,
    cost_in: int = 10,
    cost_out: int = 5,
) -> dict[str, Any]:
    """Build a ``claude -p --output-format json`` result.

    Args:
        structured: The ``structured_output`` object, or ``None`` to omit it.
        is_error: Mark the result as a failed run.
        cost_in: Input tokens reported in ``usage``.
        cost_out: Output tokens reported in ``usage``.

    Returns:
        The JSON payload the CLI would print.
    """
    body: dict[str, Any] = {
        "type": "result",
        "subtype": "error_during_execution" if is_error else "success",
        "is_error": is_error,
        "result": json.dumps(structured) if structured else "",
        "usage": {
            "input_tokens": cost_in,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": cost_out,
        },
    }
    if structured is not None:
        body["structured_output"] = structured
    return body


def tool(name: str) -> dict[str, Any]:
    """Build an OpenAI-format function tool with no parameters.

    Args:
        name: Tool name, also used as its description.

    Returns:
        The tool definition.
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def use_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select claude-cli as the configured provider without reading any ``.env``.

    Args:
        monkeypatch: Fixture used to set the provider environment.
    """
    import src.providers.llm as llm

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "claude-cli")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "claude-opus-5-5")
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
