"""Shared redaction helpers promoted from the swarm worker (#142 → public).

Covers ``redact_payload`` (recursive sensitive-key scrubbing),
``is_sensitive_arg`` (sink-aware key-name classification) and
``redact_tool_result`` (the single tool-result choke point), now consumed by
the swarm worker, the live-action audit ledger and the agent loop from one
module. The end-to-end tests at the bottom drive the real ``AgentLoop`` +
``TraceWriter`` and assert that a planted secret reaches neither the persisted
trace nor an event preview.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.trace import TraceWriter
from src.tools.redaction import (
    RESULT_SINK,
    is_sensitive_arg,
    redact_payload,
    redact_text,
    redact_tool_result,
)


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "Authorization",
        "  TOKEN  ",
        "password",
        "passphrase",
        "secret",
        "headers",
        "content",  # write_file(content=…) — see the sink policy below
        "env",  # never released: env values are secrets in both directions
        "api_token",  # marker substring
        "access_token",  # marker substring
        "x-authorization",  # marker substring
        "client_secret",  # marker substring
    ],
)
def test_is_sensitive_arg_matches(key: str) -> None:
    assert is_sensitive_arg(key) is True


@pytest.mark.parametrize("key", ["content", "Content", "CONTENT", "  content  "])
def test_content_is_released_in_the_result_sink_only(key: str) -> None:
    """``content`` is tool *output* in a result and tool *input* in arguments.

    In a result envelope (``read_file`` / ``read_document`` / ``read_url`` /
    ``load_skill``) it is the very text the trace exists to explain, so
    name-based redaction there is pure over-redaction. In the arguments sink
    the same key is ``write_file(content=…)`` — a whole user document, a
    generated credential, or a private skill body — so it stays redacted.
    """
    assert is_sensitive_arg(key) is True
    assert is_sensitive_arg(key, sink=RESULT_SINK) is False


@pytest.mark.parametrize("key", ["env", "ENV", "secret_content", "content_token"])
def test_result_sink_releases_nothing_else(key: str) -> None:
    """The relaxation is an exact (folded) match on ``content`` and nothing more.

    ``env`` is never released — an env dump in a result leaks exactly what an
    env argument would — and a compound name that merely contains ``content``
    keeps its credential classification.
    """
    assert is_sensitive_arg(key) is True
    assert is_sensitive_arg(key, sink=RESULT_SINK) is True


def test_unknown_sink_falls_back_to_the_strict_key_set() -> None:
    """An unrecognized sink must fail closed, never relax."""
    assert is_sensitive_arg("content", sink="typo_sink") is True


def test_redact_payload_arguments_sink_protects_write_file_content() -> None:
    """The arguments sink is the leak this policy closes: raw ``content``
    reaching the trace would persist whole documents / credentials."""
    out = redact_payload({"path": "notes.md", "content": "SECRET DOC BODY"})
    assert out == {"path": "notes.md", "content": "[redacted]"}


def test_redact_payload_result_sink_keeps_content_but_scrubs_inside_it() -> None:
    """A released ``content`` envelope is still pattern-scrubbed for secrets."""
    out = redact_payload(
        {
            "status": "ok",
            "content": "# Report\napi_key=leaked-in-doc",
            "api_key": "raw-key",
        },
        sink=RESULT_SINK,
    )
    assert out == {
        "status": "ok",
        "content": "# Report\napi_key=[redacted]",
        "api_key": "[redacted]",
    }


@pytest.mark.parametrize(
    "key",
    [
        "account_number",
        "account_id",
        "account_no",
        "account_num",
        "brokerage_account_number",
        "account_url",
        "rhs_account_number",
        "ssn",
        "social_security_number",
        "tax_id",
        "taxpayer_id",
        "tin",
        "routing_number",
        "bank_account_number",
        "  Account_Number  ",  # normalized (stripped, lower-cased)
    ],
)
def test_is_sensitive_arg_matches_account_pii(key: str) -> None:
    """H1: curated exact account/PII field names redact."""
    assert is_sensitive_arg(key) is True


@pytest.mark.parametrize("key", ["symbol", "side", "quantity", "url", "path", "query"])
def test_is_sensitive_arg_allows_benign_keys(key: str) -> None:
    assert is_sensitive_arg(key) is False


@pytest.mark.parametrize(
    "key",
    [
        "account_ref",  # opaque provenance — SPEC §5 accountability chain
        "account",  # broad token must NOT trip exact-match PII set
        "account_balance",
        "account_type",
        "account_status",
        "accounts",
    ],
)
def test_is_sensitive_arg_preserves_account_ref_and_benign_account_fields(
    key: str,
) -> None:
    """Exact-match (not substring) PII keys keep ``account_ref`` and other
    benign ``account*`` fields readable, preventing over-redaction."""
    assert is_sensitive_arg(key) is False


def test_redact_payload_keeps_account_ref_provenance() -> None:
    """``account_ref`` provenance survives while sibling account numbers/SSN are
    scrubbed (SPEC §5 mandate→consent chain)."""
    out = redact_payload(
        {
            "account_ref": "rh_ref_opaque",
            "account_number": "5XX111",
            "ssn": "123-45-6789",
            "symbol": "NVDA",
        }
    )
    assert out == {
        "account_ref": "rh_ref_opaque",
        "account_number": "[redacted]",
        "ssn": "[redacted]",
        "symbol": "NVDA",
    }


def test_redact_payload_scrubs_top_level_sensitive_keys() -> None:
    out = redact_payload(
        {"symbol": "NVDA", "authorization": "Bearer rh-oauth-token", "qty": 3}
    )
    assert out == {"symbol": "NVDA", "authorization": "[redacted]", "qty": 3}


def test_redact_payload_recurses_into_nested_structures() -> None:
    payload = {
        "broker_request": {"symbol": "AAPL", "headers": {"Authorization": "secret"}},
        "orders": [
            {"id": 1, "access_token": "leak"},
            {"id": 2, "note": "ok"},
        ],
    }
    out = redact_payload(payload)
    assert out == {
        "broker_request": {"symbol": "AAPL", "headers": "[redacted]"},
        "orders": [
            {"id": 1, "access_token": "[redacted]"},
            {"id": 2, "note": "ok"},
        ],
    }


def test_redact_payload_does_not_mutate_input() -> None:
    payload = {"token": "abc", "nested": [{"secret": "x"}]}
    out = redact_payload(payload)
    assert payload == {"token": "abc", "nested": [{"secret": "x"}]}
    assert out["token"] == "[redacted]"
    assert out["nested"][0]["secret"] == "[redacted]"


def test_redact_payload_passes_through_scalars() -> None:
    assert redact_payload("plain string") == "plain string"
    assert redact_payload(42) == 42
    assert redact_payload(None) is None


# --------------------------------------------------------------------------- #
# redact_tool_result — the single choke point for a tool result.
# --------------------------------------------------------------------------- #


def test_redact_tool_result_scrubs_json_keys_and_keeps_valid_json() -> None:
    out = redact_tool_result(
        json.dumps({"status": "ok", "api_key": "raw", "nested": {"token": "raw"}})
    )
    assert json.loads(out) == {
        "status": "ok",
        "api_key": "[redacted]",
        "nested": {"token": "[redacted]"},
    }


def test_redact_tool_result_scrubs_free_text_inside_a_json_envelope() -> None:
    """A JSON envelope routinely wraps raw output under a benign key.

    ``bash_tool`` returns ``{"status", "exit_code", "stdout", "stderr"}``, so a
    secret echoed by a shell command sits in ``stdout`` where no key-based rule
    can see it. The result sink pattern-scrubs the surviving string leaves.
    """
    envelope = json.dumps(
        {
            "status": "ok",
            "exit_code": 0,
            "stdout": "api_key=shell-leak-1\nAuthorization: Bearer shell-leak-2\n",
        }
    )
    out = redact_tool_result(envelope)
    assert "shell-leak-1" not in out and "shell-leak-2" not in out
    assert json.loads(out)["stdout"] == (
        "api_key=[redacted]\nAuthorization: Bearer [redacted]\n"
    )


def test_redact_tool_result_scrubs_plain_text_results() -> None:
    out = redact_tool_result("connection failed: api_key=plain-leak")
    assert out == "connection failed: api_key=[redacted]"


def test_redact_tool_result_keeps_document_content_readable() -> None:
    """The over-redaction the sink policy fixes: a document envelope stays legible."""
    out = redact_tool_result(
        json.dumps({"status": "ok", "path": "a.md", "content": "# Q3\nRevenue +12%"})
    )
    assert json.loads(out)["content"] == "# Q3\nRevenue +12%"


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"api_key": "raw", "stdout": "password: raw"}),
        "plain: client_secret='raw'",
        json.dumps({"content": "Authorization: Bearer raw"}),
    ],
)
def test_redact_tool_result_is_idempotent(raw: str) -> None:
    once = redact_tool_result(raw)
    assert redact_tool_result(once) == once


def test_redact_tool_result_none_and_empty_safe() -> None:
    assert redact_tool_result(None) == ""
    assert redact_tool_result("") == ""


# --------------------------------------------------------------------------- #
# End-to-end: a planted secret must reach neither the persisted trace nor an
# event preview, through the real AgentLoop + TraceWriter.
# --------------------------------------------------------------------------- #

_PLAINTEXT_KEY_SECRET = "pk-live-plaintext-9df3"
_PLAINTEXT_BEARER_SECRET = "bearer-body-77aa"
_PLAINTEXT_RESULT = (
    "connect failed\n"
    f'api_key="{_PLAINTEXT_KEY_SECRET}"\n'
    f"Authorization: Bearer {_PLAINTEXT_BEARER_SECRET}\n"
)
_WRITE_FILE_DOC_SECRET = "PRIVATE DOC BODY 4b1c-do-not-persist"


class _Tool:
    is_readonly = False
    repeatable = True


class _StubRegistry:
    """Minimal registry returning a canned result string."""

    _tools: dict[str, Any] = {}

    def __init__(self, result: str) -> None:
        self._result = result

    def get(self, tool_name: str) -> _Tool:
        del tool_name
        return _Tool()

    def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        del tool_name, args
        return self._result


def _run_one_tool_call(
    registry: _StubRegistry,
    tc: SimpleNamespace,
    run_dir: Path,
) -> tuple[list[tuple[str, dict]], list[dict], list[dict]]:
    """Drive one tool call through ``AgentLoop`` with a real ``TraceWriter``.

    Args:
        registry: Stub registry supplying the tool result.
        tc: Tool call (``id`` / ``name`` / ``arguments``).
        run_dir: Existing directory receiving ``trace.jsonl`` and sidecars.

    Returns:
        ``(events, messages, react_trace)`` — emitted SSE events, the
        LLM-facing message list, and the react trace.
    """
    events: list[tuple[str, dict]] = []
    agent = AgentLoop(
        registry=registry,  # type: ignore[arg-type]
        llm=SimpleNamespace(),
        max_iterations=1,
        event_callback=lambda event_type, data: events.append((event_type, data)),
    )
    agent.memory.run_dir = str(run_dir)
    trace = TraceWriter(run_dir)
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._execute_single(tc, ContextBuilder, messages, trace, react_trace, 1)
    trace.close()
    return events, messages, react_trace


def _persisted_text(run_dir: Path) -> str:
    """Return every byte persisted under ``run_dir`` (trace JSONL + sidecars)."""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    )


def test_plaintext_result_secret_reaches_neither_trace_nor_preview(
    tmp_path: Path,
) -> None:
    """A non-JSON tool result used to be persisted and streamed verbatim."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    tc = SimpleNamespace(id="tc_plain", name="fetch_quote", arguments={"symbol": "AAPL"})

    events, messages, react_trace = _run_one_tool_call(
        _StubRegistry(_PLAINTEXT_RESULT), tc, run_dir
    )

    persisted = _persisted_text(run_dir)
    assert _PLAINTEXT_KEY_SECRET not in persisted
    assert _PLAINTEXT_BEARER_SECRET not in persisted
    assert "[redacted]" in persisted

    entries = TraceWriter.read(run_dir, resolve_offloads=True)
    tool_result = next(entry for entry in entries if entry["type"] == "tool_result")
    assert 'api_key="[redacted]"' in tool_result["result"]
    assert "Bearer [redacted]" in tool_result["result"]
    # The failure context survives redaction — the trace stays diagnosable.
    assert "connect failed" in tool_result["result"]

    previews = [data["preview"] for event_type, data in events if event_type == "tool_result"]
    assert previews, "expected a tool_result event"
    for preview in previews + [item["result_preview"] for item in react_trace]:
        assert _PLAINTEXT_KEY_SECRET not in preview
        assert _PLAINTEXT_BEARER_SECRET not in preview

    # Deliberate boundary: the LLM still receives the real result, because the
    # model needs the unredacted text to act on it. Only persisted/streamed
    # surfaces are scrubbed.
    assert _PLAINTEXT_KEY_SECRET in messages[0]["content"]


def test_write_file_content_argument_never_lands_in_the_trace(tmp_path: Path) -> None:
    """``write_file(content=…)`` is the arguments-sink leak the policy closes."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    tc = SimpleNamespace(
        id="tc_write",
        name="write_file",
        arguments={"path": "notes.md", "content": _WRITE_FILE_DOC_SECRET},
    )

    events, _, _ = _run_one_tool_call(
        _StubRegistry(json.dumps({"status": "ok", "bytes_written": 42})), tc, run_dir
    )

    assert _WRITE_FILE_DOC_SECRET not in _persisted_text(run_dir)

    entries = TraceWriter.read(run_dir, resolve_offloads=True)
    tool_call = next(entry for entry in entries if entry["type"] == "tool_call")
    assert tool_call["args"]["content"] == "[redacted]"
    assert tool_call["args"]["path"] == "notes.md"

    call_events = [data for event_type, data in events if event_type == "tool_call"]
    assert call_events, "expected a tool_call event"
    assert _WRITE_FILE_DOC_SECRET not in json.dumps(call_events, default=str)


def test_arguments_sink_scrubs_credentials_embedded_in_benign_values() -> None:
    """Key-based classification cannot see a token inside a shell command."""
    args = {"command": 'curl -H "Authorization: Bearer arg-secret-123" https://x'}
    out = redact_payload(args)
    assert "arg-secret-123" not in out["command"]
    assert "curl" in out["command"] and "https://x" in out["command"]


def test_bare_issuer_tokens_are_scrubbed_without_a_key_label() -> None:
    """A token pasted with no ``key=`` in front of it must still go."""
    for token in (
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_" + "a" * 36,
        "xoxb-1234567890-abcdefghij",
        "AKIAIOSFODNN7EXAMPLE",
    ):
        assert token not in redact_text(f"leaked {token} here")


def test_bare_token_scrub_leaves_ordinary_output_alone() -> None:
    """Short sk-prefixed words and usage counters are not credentials."""
    text = "tokens: 1204 in / 318 out, sk-ok, account 12345"
    assert redact_text(text) == text
