"""Guard tests for LoadSkillTool — must reject hallucinated skill names
and redirect the LLM to get_market_data when the name looks like market data.

Risk level 3: this guard prevents the agent from retrying load_skill in a
loop with invented names (observed empirically with qwen2.5:7b inventing
"crypto-price").
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.unit
def test_load_skill_rejects_nonexistent_with_market_data_hint() -> None:
    from src.tools.load_skill_tool import LoadSkillTool

    tool = LoadSkillTool()
    raw = tool.execute(name="crypto-price")
    result = json.loads(raw)

    assert result["status"] == "error"
    body = (result.get("content") or result.get("error") or "").lower()
    assert "crypto-price" in body, "error must echo the hallucinated name"
    assert "get_market_data" in body, (
        "error must redirect the LLM to the get_market_data tool — this is "
        "the whole point of the guard."
    )


@pytest.mark.unit
def test_load_skill_existing_skill_still_works() -> None:
    """Regression: a valid skill (ccxt) must still load. The guard is narrow."""
    from src.tools.load_skill_tool import LoadSkillTool

    tool = LoadSkillTool()
    raw = tool.execute(name="ccxt")
    result = json.loads(raw)

    assert result["status"] == "ok", f"ccxt should load; got {result}"
    assert "ccxt" in (result.get("content") or "").lower()


@pytest.mark.unit
@pytest.mark.parametrize("hallucinated", [
    "crypto-price",
    "market-price",
    "btc-price",
    "price-fetcher",
])
def test_load_skill_rejects_market_data_pattern_names(hallucinated: str) -> None:
    """Any name that looks like market data → reject + redirect."""
    from src.tools.load_skill_tool import LoadSkillTool

    tool = LoadSkillTool()
    result = json.loads(tool.execute(name=hallucinated))

    assert result["status"] == "error"
    body = (result.get("content") or result.get("error") or "").lower()
    assert "get_market_data" in body
