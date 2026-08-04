"""MCP wrappers for the QVeris marketplace tools (#964).

The wrappers forward to the auto-discovered registry when the QVeris key is
configured, and fall through to the concrete tool class (whose envelope names
the configuration problem) when it is not.
"""

import json

import pytest

import agent.mcp_server as mcp_server
from src.tools import qveris_tool as qt


@pytest.fixture()
def paid_qveris(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Configure paid-mode QVeris against a tmp config file (never the real key)."""
    monkeypatch.setattr(qt, "QVERIS_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)
    qt._SESSION_SPEND.clear()
    qt._SESSION_RESERVED.clear()
    qt.save_qveris_config(
        qt.QVerisConfig(enabled=True, api_key="sk-test", mode="paid", budget_credits_per_session=50.0)
    )
    yield
    qt._SESSION_SPEND.clear()
    qt._SESSION_RESERVED.clear()


@pytest.fixture()
def unconfigured_qveris(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(qt, "QVERIS_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)


def test_search_forwards_query_limit_and_session(paid_qveris: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class FakeClient:
        def search(self, query: str, **kwargs):
            seen.update({"query": query, **kwargs})
            return {"results": []}

    monkeypatch.setattr(qt.QVerisSearchTool, "_client", lambda self: FakeClient())

    payload = json.loads(mcp_server.qveris_search(" realtime btc ", limit=5, session_id="sess-1"))

    assert payload["ok"] is True
    assert seen == {"query": "realtime btc", "limit": 5, "session_id": "sess-1"}


def test_inspect_forwards_ids(paid_qveris: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class FakeClient:
        def inspect(self, tool_ids, **kwargs):
            seen.update({"tool_ids": tool_ids, **kwargs})
            return {"results": []}

    monkeypatch.setattr(qt.QVerisInspectTool, "_client", lambda self: FakeClient())

    payload = json.loads(mcp_server.qveris_inspect(["tool-a"], search_id="s-7"))

    assert payload["ok"] is True
    assert seen["tool_ids"] == ["tool-a"]
    assert seen["search_id"] == "s-7"


def test_execute_forwards_call_and_quote(paid_qveris: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class FakeClient:
        def execute(self, tool_id: str, **kwargs):
            seen.update({"tool_id": tool_id, **kwargs})
            return {"results": []}

    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: FakeClient())

    payload = json.loads(
        mcp_server.qveris_execute(
            "tool-a",
            {"symbol": "BTC-USD"},
            expected_cost=0.02,
            billing_rule={"unit": "call"},
        )
    )

    assert payload["ok"] is True
    assert seen["tool_id"] == "tool-a"
    assert seen["parameters"] == {"symbol": "BTC-USD"}
    assert seen["max_response_size"] == 20480


def test_unconfigured_search_returns_clean_envelope(unconfigured_qveris: None) -> None:
    payload = json.loads(mcp_server.qveris_search("btc"))

    assert payload["ok"] is False
    assert "not configured" in payload["error"]


def test_unconfigured_execute_returns_clean_envelope(unconfigured_qveris: None) -> None:
    payload = json.loads(mcp_server.qveris_execute("tool-a", {"x": 1}))

    assert payload["ok"] is False
    assert "not configured" in payload["error"]
