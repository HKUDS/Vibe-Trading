from __future__ import annotations

import inspect

import mcp_server
from src.tools.alpha_bench_tool import AlphaBenchTool
from src.tools.alpha_zoo_tool import AlphaZooTool


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
            name
            for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
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

    _ALPHA_BENCH(
        universe="sp500",
        period="2018-2025",
        zoo="alpha101",
        top=10,
        output_dir="/tmp/reports",
    )

    assert registry.calls == [
        (
            "alpha_bench",
            {
                "universe": "sp500",
                "period": "2018-2025",
                "top": 10,
                "zoo": "alpha101",
                "output_dir": "/tmp/reports",
            },
        )
    ]
