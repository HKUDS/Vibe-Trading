from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.factors import bench_runner, bench_runner_strict
from src.factors.compare_runner import compare_alphas
from src.tools import alpha_bench_tool
from src.tools.alpha_bench_tool import (
    AlphaBenchTool,
    _UNIVERSE_TAG,
    _load_universe_panel,
)
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

    for universe in _UNIVERSE_TAG:
        assert universe in description
    assert "btc-usdt is single-asset" in description
    assert "fund:*" in description


def test_alpha_zoo_skill_describes_actual_universe_limits() -> None:
    skill = (
        Path(__file__).parents[1] / "src" / "skills" / "alpha-zoo" / "SKILL.md"
    ).read_text(encoding="utf-8")
    purpose = skill.split("## Purpose", 1)[1].split("## Tools Available", 1)[0]
    constraints = skill.split("## Constraints", 1)[1].split("## Common Pitfalls", 1)[0]

    assert "CSI 300" in purpose
    assert "S&P 500" in purpose
    assert "NIFTY 100" in purpose
    assert "BTC-USDT" not in purpose
    for universe in _UNIVERSE_TAG:
        assert f"`{universe}`" in constraints
    for expected in (
        "`btc-usdt` is recognized but cannot be benched",
        "Unknown universe names are rejected",
        "single-asset",
        "NIFTY 100 results are survivorship-biased",
        "fund:*",
        "survivorship-biased",
        "requested_instruments",
        "fetched_instruments",
        "missing_instruments",
    ):
        assert expected in constraints
    assert "not yet implemented" not in constraints


def test_alpha_bench_internal_docs_describe_supported_universes() -> None:
    docs = (
        alpha_bench_tool.__doc__ or "",
        bench_runner.run_bench.__doc__ or "",
        bench_runner_strict.run_bench_strict.__doc__ or "",
        compare_alphas.__doc__ or "",
    )

    for universe in _UNIVERSE_TAG:
        for doc in docs:
            assert f"`{universe}`" in doc
    for stale in ("W2 scaffold", "W4", "not yet implemented"):
        assert stale not in docs[0]
