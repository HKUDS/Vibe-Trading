"""Replay-only deterministic LLM stub for agent evals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.evals.agent_eval.prompt_hash import PromptHashInput, compute_prompt_hash
from src.providers.chat import LLMResponse, ToolCallRequest


STUB_SCHEMA_VERSION = "1.0.0"


class StubMissError(RuntimeError):
    """Raised when a replay-only eval has no exact prompt-hash stub."""


def raise_stub_miss(prompt_hash: str) -> None:
    """Raise the standard stub miss error; never fall back to a real LLM."""
    raise StubMissError(f"stub miss for prompt_hash={prompt_hash}; replay-only evals cannot call a real LLM")


class StubLLM:
    """Hash-indexed replay stub for ``ChatLLM``-style responses."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = dict(responses or {})

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "StubLLM":
        """Load stub records from a JSONL file."""
        records: dict[str, dict[str, Any]] = {}
        path = Path(path)
        if not path.exists():
            return cls()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            prompt_hash = str(item["prompt_hash"])
            response = item.get("response")
            if not isinstance(response, dict):
                raise ValueError("stub response must be an object")
            records[prompt_hash] = response
        return cls(records)

    def chat_for_prompt(self, prompt: PromptHashInput) -> LLMResponse:
        """Return a replayed response for an exact prompt contract."""
        prompt_hash = compute_prompt_hash(prompt)
        raw = self.responses.get(prompt_hash)
        if raw is None:
            raise_stub_miss(prompt_hash)
        return _response_from_payload(raw)


def _response_from_payload(raw: dict[str, Any]) -> LLMResponse:
    calls = [
        ToolCallRequest(
            id=str(call.get("id") or f"call_{index}"),
            name=str(call["name"]),
            arguments=dict(call.get("arguments") or {}),
        )
        for index, call in enumerate(raw.get("tool_calls") or [], start=1)
    ]
    return LLMResponse(
        content=raw.get("content"),
        tool_calls=calls,
        finish_reason=str(raw.get("finish_reason") or ("tool_calls" if calls else "stop")),
    )
