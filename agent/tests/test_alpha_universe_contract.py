from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.tools import alpha_bench_tool
from src.tools.alpha_bench_tool import AlphaBenchTool, _load_universe_panel
from src.tools.alpha_compare_tool import AlphaCompareTool


def test_btc_universe_is_rejected_before_cache_or_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_root = Mock(return_value=tmp_path)
    monkeypatch.setattr(alpha_bench_tool, "get_runtime_root", runtime_root)

    with pytest.raises(ValueError, match="single-asset"):
        _load_universe_panel("btc-usdt", "2024-2024")

    runtime_root.assert_not_called()


@pytest.mark.parametrize("tool_class", [AlphaBenchTool, AlphaCompareTool])
def test_tool_schema_describes_actual_universe_limits(tool_class: type) -> None:
    description = tool_class.parameters["properties"]["universe"]["description"]

    assert description.startswith("csi300 | sp500")
    assert "btc-usdt is single-asset" in description
    assert "fund:*" in description


def test_alpha_zoo_skill_describes_actual_universe_limits() -> None:
    skill = (
        Path(__file__).parents[1] / "src" / "skills" / "alpha-zoo" / "SKILL.md"
    ).read_text(encoding="utf-8")
    purpose = skill.split("## Purpose", 1)[1].split("## Tools Available", 1)[0]
    constraints = skill.split("## Constraints", 1)[1].split("## Common Pitfalls", 1)[0]

    assert "(CSI 300, S&P 500)" in purpose
    assert "BTC-USDT" not in purpose
    for expected in (
        "BTC-USDT cannot be benched",
        "fund:*",
        "survivorship-biased",
        "requested_instruments",
        "fetched_instruments",
        "missing_instruments",
    ):
        assert expected in constraints
