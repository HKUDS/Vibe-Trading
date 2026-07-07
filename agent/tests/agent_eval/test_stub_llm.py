from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evals.agent_eval.prompt_hash import PromptHashInput, compute_prompt_hash
from src.evals.agent_eval.record import write_stub_record
from src.evals.agent_eval.stub_llm import StubLLM, StubMissError, raise_stub_miss


def _prompt() -> PromptHashInput:
    return PromptHashInput(
        system_prompt="system",
        user_prompt="hello",
        tool_schema_hash="tools",
        governance_policy_version="policy",
        manifest_version="manifest",
        research_protocol_schema_version="rp",
        scorecard_schema_version="scorecard",
        stub_prompt_contract_version="stub-v1",
    )


def test_stub_hash_exact_match_returns_response(tmp_path: Path) -> None:
    prompt = _prompt()
    prompt_hash = compute_prompt_hash(prompt)
    (tmp_path / "stubs.jsonl").write_text(
        json.dumps(
            {
                "prompt_hash": prompt_hash,
                "response": {
                    "content": "done",
                    "tool_calls": [
                        {"id": "call_1", "name": "backtest", "arguments": {"source": "local"}}
                    ],
                    "finish_reason": "tool_calls",
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    response = StubLLM.from_jsonl(tmp_path / "stubs.jsonl").chat_for_prompt(prompt)

    assert response.content == "done"
    assert response.tool_calls[0].name == "backtest"


def test_stub_miss_raises(tmp_path: Path) -> None:
    (tmp_path / "stubs.jsonl").write_text("", encoding="utf-8")
    llm = StubLLM.from_jsonl(tmp_path / "stubs.jsonl")

    with pytest.raises(StubMissError, match="stub miss"):
        llm.chat_for_prompt(_prompt())


def test_raise_stub_miss_helper_never_falls_back() -> None:
    with pytest.raises(StubMissError):
        raise_stub_miss("abc123")


def test_record_requires_explicit_manual_action(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="explicit"):
        write_stub_record(
            prompt=_prompt(),
            response={"content": "ok"},
            path=tmp_path / "stubs.jsonl",
        )

    prompt_hash = write_stub_record(
        prompt=_prompt(),
        response={"content": "ok"},
        path=tmp_path / "stubs.jsonl",
        allow_record=True,
    )

    assert prompt_hash
    assert (tmp_path / "stubs.jsonl").exists()
