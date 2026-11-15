"""mcp_server.main() reads .env, but never takes the shell-tool switch from it."""

import os
import sys

import mcp_server
from src.providers import settings


def test_main_loads_dotenv_after_the_shell_tool_decision(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VIBE_TRADING_ENABLE_SHELL_TOOLS=1\n"
        "MARKET_DATA_ORDER_HK_EQUITY=sentinel_from_dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "_ENV_CANDIDATES", (env_file,))
    monkeypatch.setattr(settings, "_dotenv_loaded", False)
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    monkeypatch.delenv("MARKET_DATA_ORDER_HK_EQUITY", raising=False)
    monkeypatch.setattr(sys, "argv", ["vibe-trading-mcp"])
    monkeypatch.setattr(mcp_server, "_include_shell_tools", False)
    monkeypatch.setattr(mcp_server, "_registry", None)
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: None)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda *a, **k: None)

    mcp_server.main()

    assert os.environ.get("MARKET_DATA_ORDER_HK_EQUITY") == "sentinel_from_dotenv"
    assert mcp_server._include_shell_tools is False
