from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
import os
import re
from pathlib import Path

import mcp_server
import pytest

from src.tools.alpha_bench_tool import AlphaBenchTool
from src.tools.alpha_zoo_tool import AlphaZooTool
from src.tools import alpha_bench_tool as alpha_bench_module

_ALPHA_ZOO = getattr(mcp_server.alpha_zoo, "fn", None) or getattr(
    mcp_server.alpha_zoo, "__wrapped__", mcp_server.alpha_zoo
)
_ALPHA_BENCH = getattr(mcp_server.alpha_bench, "fn", None) or getattr(
    mcp_server.alpha_bench, "__wrapped__", mcp_server.alpha_bench
)


class _RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return '{"status":"ok"}'


def test_wrapper_signatures_match_registered_contracts() -> None:
    for wrapper, tool in (
        (_ALPHA_ZOO, AlphaZooTool),
        (_ALPHA_BENCH, AlphaBenchTool),
    ):
        signature = inspect.signature(wrapper)
        assert set(signature.parameters) == set(tool.parameters["properties"])
        required = {
            name for name, parameter in signature.parameters.items() if parameter.default is inspect.Parameter.empty
        }
        assert required == set(tool.parameters["required"])


def test_alpha_zoo_forwards_filters(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    _ALPHA_ZOO(
        action="list_alphas",
        zoo="alpha101",
        theme="momentum",
        universe="equity_us",
        limit=25,
    )

    assert registry.calls == [
        (
            "alpha_zoo",
            {
                "action": "list_alphas",
                "limit": 25,
                "zoo": "alpha101",
                "theme": "momentum",
                "universe": "equity_us",
            },
        )
    ]


def test_alpha_bench_forwards_selection(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)
    output_dir = Path.home() / ".vibe-trading" / "reports" / "alpha-zoo"

    _ALPHA_BENCH(
        universe="sp500",
        period="2018-2025",
        zoo="alpha101",
        top=10,
        output_dir=str(output_dir),
    )

    assert registry.calls == [
        (
            "alpha_bench",
            {
                "universe": "sp500",
                "period": "2018-2025",
                "top": 10,
                "zoo": "alpha101",
                "output_dir": str(output_dir.resolve()),
            },
        )
    ]


def test_skill_inventory_matches_the_whole_mcp_surface() -> None:
    """The published manifest must list every tool the server serves.

    This previously compared the manifest against ``registered - mirrored``,
    which made a mirrored tool's absence from SKILL.md the expected state. The
    manifest is what a ClawHub reader uses to decide what installing gets them,
    so excluding a served tool under-reports the product: the four
    institutional-research tools were live over MCP and absent from the
    manifest, and the contract said that was correct. Mirroring is a
    schema-sourcing detail, not a reason to hide a tool from its own manifest.
    """
    # Given the runtime MCP registration and the bundled SKILL inventory.
    registered = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    skill_text = (Path(mcp_server.__file__).parent / "SKILL.md").read_text(encoding="utf-8")

    # When the SKILL header and table are read.
    header = re.search(r"^## Available MCP Tools \((\d+)\)$", skill_text, re.MULTILINE)

    # Then they describe exactly the MCP surface, mirrored tools included.
    assert header is not None
    tool_section = skill_text[header.end() :].split("\n## ", maxsplit=1)[0]
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", tool_section, re.MULTILINE))
    assert listed == registered, (
        f"manifest/surface mismatch — missing from SKILL.md: "
        f"{sorted(registered - listed)}; listed but not served: "
        f"{sorted(listed - registered)}"
    )
    assert int(header.group(1)) == len(registered)


def test_alpha_bench_requires_a_bounded_selection(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    result = json.loads(_ALPHA_BENCH(universe="sp500", period="2018-2025"))

    assert result["status"] == "error"
    assert "alpha_id or zoo" in result["error"]
    assert registry.calls == []


def test_alpha_bench_rejects_periods_over_ten_years(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    result = json.loads(_ALPHA_BENCH(universe="sp500", period="2010-2025", zoo="alpha101"))

    assert result["status"] == "error"
    assert "10 years" in result["error"]
    assert registry.calls == []


def test_alpha_bench_rejects_conflicting_selection(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    result = json.loads(
        _ALPHA_BENCH(
            universe="sp500",
            period="2018-2025",
            alpha_id="alpha101_001",
            zoo="alpha101",
        )
    )

    assert result["status"] == "error"
    assert "mutually exclusive" in result["error"]
    assert registry.calls == []


def test_alpha_bench_rejects_unbounded_top(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    result = json.loads(
        _ALPHA_BENCH(
            universe="sp500",
            period="2018-2025",
            zoo="alpha101",
            top=101,
        )
    )

    assert result["status"] == "error"
    assert "between 1 and 100" in result["error"]
    assert registry.calls == []


def test_alpha_bench_rejects_output_outside_allowed_roots(monkeypatch) -> None:
    registry = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    result = json.loads(
        _ALPHA_BENCH(
            universe="sp500",
            period="2018-2025",
            alpha_id="alpha101_001",
            output_dir="/tmp/alpha-bench-reports",
        )
    )

    assert result["status"] == "error"
    assert "allowed" in result["error"]
    assert registry.calls == []


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation requires privileges unavailable on Windows"
)
def test_alpha_bench_does_not_follow_preexisting_report_symlink(monkeypatch, tmp_path: Path) -> None:
    class _BenchRegistry:
        def get(self, alpha_id: str) -> object:
            return object()

    class _FixedDateTime:
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz)

    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    external_target = tmp_path / "external.html"
    predictable_report_link = output_dir / "alpha_bench_20260102T030405Z.html"
    report_link = output_dir / "alpha_bench_20260102T030405Z_fixed.html"
    predictable_report_link.symlink_to(external_target)
    report_link.symlink_to(external_target)

    monkeypatch.setattr("src.factors.registry.get_default_registry", lambda: _BenchRegistry())
    monkeypatch.setattr(alpha_bench_module, "datetime", _FixedDateTime)
    monkeypatch.setattr(alpha_bench_module.secrets, "token_hex", lambda length: "fixed")
    monkeypatch.setattr(alpha_bench_module, "_load_universe_panel", lambda *args, **kwargs: {})
    monkeypatch.setattr(alpha_bench_module, "_compute_forward_returns", lambda panel: {})
    monkeypatch.setattr(
        alpha_bench_module,
        "_bench_one_alpha",
        lambda *args, **kwargs: {
            "id": "alpha101_001",
            "zoo": "alpha101",
            "theme": [],
            "formula_latex": "1",
            "ic_mean": 0.1,
            "ic_std": 0.2,
            "ir": 0.5,
            "ic_positive_ratio": 0.5,
            "ic_count": 1,
        },
    )

    result = alpha_bench_module.run_alpha_bench(
        alpha_id="alpha101_001",
        universe="sp500",
        period="2020-2021",
        output_dir=str(output_dir),
    )

    assert result["status"] == "error"
    assert "failed to write report" in result["error"]
    assert report_link.is_symlink()
    assert predictable_report_link.is_symlink()
    assert not external_target.exists()
