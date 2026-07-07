from __future__ import annotations

from src.evals.agent_eval.prompt_hash import PromptHashInput, compute_prompt_hash


def _input(**updates) -> PromptHashInput:
    payload = {
        "system_prompt": "system",
        "developer_prompt": "project",
        "user_prompt": "user asks for a backtest",
        "prior_turns_summary": "previous research summary",
        "tool_schema_hash": "toolhash-v1",
        "governance_policy_version": "policy-v1",
        "manifest_version": "manifest-v1",
        "research_protocol_schema_version": "rp-1.0.0",
        "scorecard_schema_version": "scorecard-1.0.0",
        "stub_prompt_contract_version": "stub-contract-v1",
    }
    payload.update(updates)
    return PromptHashInput(**payload)


def test_prompt_hash_changes_when_tool_schema_changes() -> None:
    original = compute_prompt_hash(_input())
    changed = compute_prompt_hash(_input(tool_schema_hash="toolhash-v2"))

    assert changed != original


def test_prompt_hash_covers_contract_and_schema_versions() -> None:
    original = compute_prompt_hash(_input())

    assert compute_prompt_hash(_input(system_prompt="other")) != original
    assert compute_prompt_hash(_input(developer_prompt="other")) != original
    assert compute_prompt_hash(_input(user_prompt="other")) != original
    assert compute_prompt_hash(_input(prior_turns_summary="other")) != original
    assert compute_prompt_hash(_input(tool_schema_version="tools-v2")) != original
    assert compute_prompt_hash(_input(governance_policy_version="policy-v2")) != original
    assert compute_prompt_hash(_input(manifest_version="manifest-v2")) != original
    assert compute_prompt_hash(_input(research_protocol_schema_version="rp-2")) != original
    assert compute_prompt_hash(_input(scorecard_schema_version="scorecard-2")) != original
    assert compute_prompt_hash(_input(stub_prompt_contract_version="stub-contract-v2")) != original


def test_prompt_hash_is_canonical_for_dict_order() -> None:
    first = _input(tool_schema_hash={"b": 2, "a": 1})
    second = _input(tool_schema_hash={"a": 1, "b": 2})

    assert compute_prompt_hash(first) == compute_prompt_hash(second)
