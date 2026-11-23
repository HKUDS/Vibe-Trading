"""Guidance reaches actual agent surfaces without changing execution contracts."""

import json
from types import SimpleNamespace

from src.agent.context import ContextBuilder
from src.agent.memory import WorkspaceMemory
from src.agent.tools import ToolRegistry
from src.data_gateway.guidance import DATA_ACCESS_POLICY, MCP_DATA_GUIDANCE, SHELL_DATA_GUIDANCE
from src.swarm.models import SwarmAgentSpec
from src.swarm.worker import build_worker_prompt
from src.tools.bash_tool import BashTool
from src.tools.background_tools import BackgroundRunTool
from src.tools.mcp import MCPRemoteTool, MCPRemoteToolSpec


def test_main_system_message_contains_policy_and_no_direct_fetch_exception():
    builder = ContextBuilder(ToolRegistry(), WorkspaceMemory())
    messages = builder.build_messages("Use Python and an external MCP for this research.")
    prompt = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert DATA_ACCESS_POLICY in prompt
    assert "If you fetch via bash/yfinance instead" not in prompt
    assert "tool's returned artifact paths" in prompt
    assert "each child would\nhave its own gateway limits" in prompt


def test_workers_receive_same_policy_even_without_bar_tool():
    for tools in [["get_market_data", "bash"], ["bash"], []]:
        spec = SwarmAgentSpec(id="reader", role="Researcher", system_prompt="Analyze supplied evidence.", tools=tools)
        prompt = build_worker_prompt(spec, {}, "(no matching skills)")
        assert DATA_ACCESS_POLICY in prompt
        assert "raw yfinance scripts only" not in prompt
        assert "never invent a tool" in prompt


def test_shell_descriptions_direct_scripts_to_existing_artifacts():
    assert SHELL_DATA_GUIDANCE in BashTool.description
    assert SHELL_DATA_GUIDANCE in BackgroundRunTool.description
    assert "Heredocs" in BashTool.description
    assert "cancel_background" in BackgroundRunTool.description


def test_external_mcp_keeps_schema_dispatch_and_authorization_contract():
    calls = []

    def call_tool(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "ok", "data": {"field": "observed"}}

    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}}}
    spec = MCPRemoteToolSpec(
        server_name="external", remote_name="special_data", local_name="mcp_external_special_data",
        description="Provider's original capability and authorization instructions.", parameters=parameters,
    )
    tool = MCPRemoteTool(SimpleNamespace(call_tool=call_tool), spec)
    assert tool.description.startswith(spec.description)
    assert MCP_DATA_GUIDANCE in tool.description
    assert tool.parameters is parameters
    assert tool.is_readonly is False  # No trust elevation from the routing hint.
    result = json.loads(tool.execute(symbol="AAPL", run_dir="/local-only"))
    assert result["status"] == "ok"
    assert calls == [(("special_data", {"symbol": "AAPL"}), {"local_name": spec.local_name})]
