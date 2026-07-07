from __future__ import annotations

import json
import platform
import statistics
import time

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import RuntimeContext
from src.governance.discovery import ManifestCache
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine
from src.governance.runtime import GovernedToolRegistry


class _FastTool(BaseTool):
    name = "fast_read"
    description = "fast"
    parameters = {"type": "object", "properties": {}}
    is_readonly = True
    repeatable = True

    def execute(self, **kwargs):
        return json.dumps({"status": "ok"})


def _pctl(values: list[float], percentile: float) -> float:
    return statistics.quantiles(values, n=100)[int(percentile) - 1]


@pytest.mark.performance
def test_governance_overhead_under_threshold() -> None:
    manifest = ToolManifest(
        name="fast_read",
        surface=ToolSurface.MCP_STDIO,
        readonly=True,
        repeatable=True,
        risk_level=RiskLevel.R0_READ,
        requires_auth=False,
        requires_consent=False,
        allowed_modes=["research"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=[],
    )
    context = RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="enforce")
    engine = PolicyEngine()

    eval_times: list[float] = []
    for _ in range(300):
        start = time.perf_counter()
        engine.evaluate(name="fast_read", params={}, manifest=manifest, context=context)
        eval_times.append((time.perf_counter() - start) * 1000)

    inner = ToolRegistry()
    inner.register(_FastTool())
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({"fast_read": manifest}, surface=ToolSurface.MCP_STDIO),
        context=context,
        policy=engine,
    )
    overhead_times: list[float] = []
    for _ in range(300):
        start = time.perf_counter()
        governed.execute("fast_read", {})
        overhead_times.append((time.perf_counter() - start) * 1000)

    if platform.system().lower().startswith("win"):
        assert _pctl(eval_times, 95) < 30
        assert _pctl(overhead_times, 99) < 50
    else:
        assert _pctl(eval_times, 95) < 10
        assert _pctl(overhead_times, 99) < 15
