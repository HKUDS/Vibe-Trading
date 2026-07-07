"""Manual recording helpers for eval stubs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.evals.agent_eval.prompt_hash import PromptHashInput, compute_prompt_hash


def write_stub_record(
    *,
    prompt: PromptHashInput,
    response: dict[str, Any],
    path: str | Path,
    allow_record: bool = False,
) -> str:
    """Append one stub record only when explicitly requested by a human."""
    if not allow_record:
        raise PermissionError("stub recording requires explicit allow_record=True")
    prompt_hash = compute_prompt_hash(prompt)
    record = {
        "schema_version": "1.0.0",
        "prompt_hash": prompt_hash,
        "response": response,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return prompt_hash
