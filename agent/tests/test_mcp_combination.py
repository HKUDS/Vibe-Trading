"""Factor combination round-trips through the real registry and MCP protocol."""

import asyncio
import json

import numpy as np
from fastmcp import Client

import mcp_server
from src.tools import build_registry


def test_factor_combination_without_shell_tools_over_mcp(monkeypatch):
    registry = build_registry(include_shell_tools=False)
    monkeypatch.setattr(mcp_server, "_registry", registry)
    rng = np.random.default_rng(2210)
    dates = ["2026-10-19", "2026-10-20", "2026-10-21"]
    columns = [f"asset{i}" for i in range(8)]

    def panel(values):
        return {
            "__dataframe__": {
                "index": dates,
                "columns": columns,
                "data": np.asarray(values).tolist(),
            }
        }

    first = rng.normal(size=(len(dates), len(columns)))
    second = rng.normal(size=(len(dates), len(columns)))
    args = {
        "action": "call",
        "module": "combination",
        "function": "combine_factors",
        "kwargs": {
            "panels": {"momentum": panel(first), "value": panel(second)},
            "method": "equal",
        },
    }

    async def run():
        async with Client(mcp_server.mcp) as client:
            expected = json.loads(registry.execute("quantlib_call", args))
            response = await client.call_tool("quantlib_call", args)
            actual = json.loads(response.content[0].text)
            ref = actual.pop("_result_file")
            from pathlib import Path
            assert json.loads(Path(ref["path"]).read_text()) == expected
            assert actual == expected
            assert actual["ok"]
            result = actual["result"]
            assert set(result) == {"composite", "weights", "diagnostics", "method"}
            composite = result["composite"]["__dataframe__"]
            assert composite["columns"] == columns
            assert len(composite["data"]) == len(dates)
            weights = result["weights"]["__dataframe__"]
            assert weights["columns"] == ["momentum", "value"]
            assert result["diagnostics"]["n_factors"] == 2

    asyncio.run(run())
