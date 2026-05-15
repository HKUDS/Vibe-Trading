"""Guard tests for SaveSkillTool — must refuse market-data-pattern names
to prevent the LLM from inventing a skill (e.g. "crypto-price") to satisfy
a price/OHLCV request.

Risk level 3: blocks dynamic skill creation as a side channel around the
get_market_data tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.unit
def test_save_skill_blocks_crypto_price_pattern(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    import src.agent.skills as skills_module
    import src.tools.skill_writer_tool as writer_module

    importlib.reload(skills_module)
    importlib.reload(writer_module)

    tool = writer_module.SaveSkillTool()
    result = json.loads(
        tool.execute(
            name="crypto-price",
            content="---\nname: crypto-price\n---\n# body",
        )
    )

    assert result["status"] == "error"
    body = (result.get("error") or "").lower()
    assert "get_market_data" in body, (
        "rejection must redirect the LLM to the get_market_data tool."
    )

    blocked_dir = writer_module.USER_SKILLS_DIR / "crypto-price"
    assert not blocked_dir.exists(), (
        f"Guard failed: directory {blocked_dir} was created despite the block."
    )


@pytest.mark.unit
@pytest.mark.parametrize("blocked_name", [
    "crypto-price",
    "market-price",
    "price-fetcher",
    "btc-price",
    "ohlcv-fetch",
    "ticker-fetcher",
])
def test_save_skill_blocks_market_data_pattern_names(
    monkeypatch, tmp_path: Path, blocked_name: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    import src.agent.skills as skills_module
    import src.tools.skill_writer_tool as writer_module

    importlib.reload(skills_module)
    importlib.reload(writer_module)

    tool = writer_module.SaveSkillTool()
    result = json.loads(
        tool.execute(name=blocked_name, content="---\nname: x\n---\nbody")
    )
    assert result["status"] == "error", (
        f"{blocked_name!r} should be blocked but execute returned: {result}"
    )


@pytest.mark.unit
def test_save_skill_allows_unrelated_name(monkeypatch, tmp_path: Path) -> None:
    """Regression: legitimate skill names with no market-data pattern still work."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    import src.agent.skills as skills_module
    import src.tools.skill_writer_tool as writer_module

    importlib.reload(skills_module)
    importlib.reload(writer_module)

    tool = writer_module.SaveSkillTool()
    result = json.loads(
        tool.execute(
            name="momentum-rsi",
            content="---\nname: momentum-rsi\n---\n# body",
        )
    )
    assert result["status"] == "ok", f"legitimate name was blocked: {result}"
