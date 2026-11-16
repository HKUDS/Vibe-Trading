"""Both factor transforms round-trip through the real registry and MCP protocol."""

import asyncio
import json

import numpy as np
from fastmcp import Client

import mcp_server
from src.tools import build_registry


def test_factor_transforms_without_shell_tools_over_mcp(monkeypatch):
    registry = build_registry(include_shell_tools=False)
    monkeypatch.setattr(mcp_server, "_registry", registry)
    rng = np.random.default_rng(1817)
    x, y = rng.normal(size=(2, 20))

    def panel(values):
        return {
            "__dataframe__": {
                "index": ["2026-10-18T09:30:00Z"],
                "columns": [f"asset{i}" for i in range(20)],
                "data": [values.tolist()],
            }
        }

    async def run():
        async with Client(mcp_server.mcp) as client:
            for function, kwargs in (
                (
                    "neutralize_factor",
                    {"factor": panel(2 * x + y), "controls": {"x": panel(x)}},
                ),
                (
                    "pca_factors",
                    {"factors": {"x": panel(x), "y": panel(y)}, "n_components": 2},
                ),
            ):
                args = {
                    "action": "call",
                    "module": "neutralization",
                    "function": function,
                    "kwargs": kwargs,
                }
                expected = json.loads(registry.execute("quantlib_call", args))
                response = await client.call_tool("quantlib_call", args)
                actual = json.loads(response.content[0].text)
                ref = actual.pop("_result_file")
                from pathlib import Path
                assert json.loads(Path(ref["path"]).read_text()) == expected
                assert actual == expected
                assert actual["ok"]
                assert actual["result"]["diagnostics"][0]["fit_count"] == 20
                assert actual["result"]["diagnostics"][0]["status"] == "ok"

    asyncio.run(run())
