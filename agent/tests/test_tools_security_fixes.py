"""Security regression tests for the shell-tool gate.

Issue #1 (HIGH): MCP-wrapped shell tools (a third-party MCP server advertising
a ``bash`` / ``run_command`` tool) must be gated by ``include_shell_tools``
just like local shell tools — otherwise a non-shell session can be exposed to
arbitrary command execution through an MCP wrapper.

Issue #2 (HIGH): ``check_background`` is the read half of the BG surface — a
session that opted out of shell access must not be able to retrieve the output
of background tasks (which may contain secrets dumped to stdout).

Issue #5 (HIGH): live-broker tools must be wrapped through the kill-switch /
mandate gate after the registry build. The previous control flow made the
``wrap_live_broker_tools`` call unreachable because the live-broker branch
``continue``d earlier in the loop.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config.schema import AgentConfig, MCPServerConfig
from src.live.classification import ToolClass
from src.live.registry import wrap_live_broker_tools
from src.live.order_guard import LiveOrderGuardTool
from src.tools import _SHELL_TOOL_NAMES, build_registry
from src.tools.background_tools import BackgroundManager, CheckBackgroundTool
from src.tools.mcp import MCPRemoteTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_config(servers: dict[str, dict]) -> AgentConfig:
    return AgentConfig.model_validate({"mcpServers": {n: cfg for n, cfg in servers.items()}})


def _make_fake_wrappers(server_name: str, tool_names: list[str]) -> list[MCPRemoteTool]:
    """Build lightweight MCPRemoteTool stubs with a real ``_spec.remote_name``.

    The shell-tool gate in ``build_registry`` checks ``tool._spec.remote_name``
    (the remote MCP tool's advertised name), not ``tool.name`` (the
    ``mcp_<server>_<tool>`` local name). The stub must carry the real spec so
    the gate fires.
    """
    from src.tools.mcp import MCPRemoteToolSpec

    adapter = MagicMock()
    adapter.server_name = server_name
    wrappers: list[MCPRemoteTool] = []
    for tname in tool_names:
        spec = MCPRemoteToolSpec(
            server_name=server_name,
            remote_name=tname,
            local_name=f"mcp_{server_name}_{tname}",
            description=f"Remote {tname}",
            parameters={"type": "object", "properties": {}, "required": []},
            annotations=None,
        )
        stub = MagicMock(spec=MCPRemoteTool)
        stub.name = spec.local_name
        stub.description = spec.description
        stub.parameters = spec.parameters
        stub.is_readonly = False
        stub._spec = spec
        stub._adapter = adapter
        wrappers.append(stub)
    return wrappers  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Issue #2: check_background gating
# ---------------------------------------------------------------------------


def test_shell_policy_set_includes_check_background() -> None:
    """``check_background`` is the read half of the BG surface — it must be in
    the shell-policy set so a non-shell session cannot read background-task
    output that may contain secrets."""
    assert "check_background" in _SHELL_TOOL_NAMES
    assert "bash" in _SHELL_TOOL_NAMES
    assert "background_run" in _SHELL_TOOL_NAMES


def test_check_background_excluded_when_shell_disabled() -> None:
    """``CheckBackgroundTool`` must NOT register when shell tools are off.

    Regression: previously ``_SHELL_TOOL_NAMES = {"bash", "background_run"}``
    missed ``check_background``, so a non-shell session could still call it
    and read whatever the BG subprocess had captured.
    """
    registry = build_registry(include_shell_tools=False)
    assert "check_background" not in registry.tool_names
    assert "bash" not in registry.tool_names
    assert "background_run" not in registry.tool_names


def test_check_background_included_when_shell_enabled() -> None:
    """Opt-in via ``include_shell_tools=True`` must include check_background."""
    registry = build_registry(include_shell_tools=True)
    assert "check_background" in registry.tool_names


# ---------------------------------------------------------------------------
# Issue #1: MCP-wrapped shell tools are gated by the same policy
# ---------------------------------------------------------------------------


def test_mcp_shell_tool_skipped_when_shell_disabled() -> None:
    """A third-party MCP server advertising a ``bash``-equivalent tool must
    NOT inject the shell surface into a registry built with
    ``include_shell_tools=False``. The gate must check the remote name on
    ``tool._spec``, not the local ``mcp_<server>_<tool>`` name."""
    fake_wrappers = _make_fake_wrappers("evil", ["bash", "search"])
    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"evil": {"command": "uvx", "args": []}})
        registry = build_registry(agent_config=config, include_shell_tools=False)

    # The non-shell tool from the same server is still allowed.
    assert "mcp_evil_search" in registry.tool_names
    # The shell tool is dropped.
    assert "mcp_evil_bash" not in registry.tool_names


def test_mcp_shell_tool_warns_when_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """Skipping an MCP shell tool must surface a warning so an operator can
    tell why a requested tool is absent."""
    import logging

    fake_wrappers = _make_fake_wrappers("evil", ["bash"])
    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"evil": {"command": "uvx", "args": []}})
        with caplog.at_level(logging.WARNING, logger="src.tools"):
            build_registry(agent_config=config, include_shell_tools=False)

    assert any("evil" in r.message and "bash" in r.message for r in caplog.records), (
        "Expected an operator-facing warning naming the skipped server + tool"
    )


def test_mcp_shell_tool_registered_when_shell_enabled() -> None:
    """Opt-in via ``include_shell_tools=True`` lets the MCP shell tool through."""
    fake_wrappers = _make_fake_wrappers("evil", ["bash"])
    with patch("src.tools.mcp.build_mcp_tool_wrappers", return_value=fake_wrappers):
        config = _make_agent_config({"evil": {"command": "uvx", "args": []}})
        registry = build_registry(agent_config=config, include_shell_tools=True)

    assert "mcp_evil_bash" in registry.tool_names


# ---------------------------------------------------------------------------
# Issue #3: background task output is redacted
# ---------------------------------------------------------------------------


def test_background_output_redacts_api_key() -> None:
    """A BG task whose stdout contains an ``API_KEY=...`` pair must NOT echo
    the key back through ``check_background``. Regression: previously the raw
    subprocess output was stored in ``self.tasks[task_id]['result']`` with no
    redaction, so a leaked secret in the command output was visible to the
    agent loop."""
    import time

    mgr = BackgroundManager()
    result = mgr.run('echo API_KEY=sk-test-1234567890abcdef')
    task_id = __import__("json").loads(result)["task_id"]

    # Wait for the BG thread to finish.
    for _ in range(50):
        if mgr.tasks[task_id]["status"] != "running":
            break
        time.sleep(0.05)

    out = __import__("json").loads(mgr.check(task_id))
    assert "sk-test-1234567890abcdef" not in out["result"], (
        f"API key leaked through check_background: {out['result']!r}"
    )
    assert "[REDACTED]" in out["result"]


def test_background_output_redacts_bearer_token() -> None:
    """``Bearer <token>`` strings in BG output must also be scrubbed."""
    import time

    mgr = BackgroundManager()
    result = mgr.run('echo "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"')
    task_id = __import__("json").loads(result)["task_id"]

    for _ in range(50):
        if mgr.tasks[task_id]["status"] != "running":
            break
        time.sleep(0.05)

    out = __import__("json").loads(mgr.check(task_id))
    assert "eyJhbGciOiJIUzI1NiJ9" not in out["result"]


# ---------------------------------------------------------------------------
# Issue #5: wrap_live_broker_tools is reachable from the registry path
# ---------------------------------------------------------------------------


def test_wrap_live_broker_tools_produces_gated_write_tools() -> None:
    """wrap_live_broker_tools must replace WRITE/UNKNOWN tools with a
    :class:`LiveOrderGuardTool` so the kill switch + mandate gate run before
    the broker call. The function is the safety gate that the previous
    unreachable ``if live: wrap`` block was supposed to invoke."""
    from src.trading.connectors.robinhood.classification import ROBINHOOD_TOOL_CLASS

    plain = _make_fake_wrappers("robinhood", ["place_order", "get_quote"])
    # Mark place_order as a known write via the curated map (Tier 2).
    ROBINHOOD_TOOL_CLASS["place_order"] = ToolClass.WRITE
    ROBINHOOD_TOOL_CLASS["get_quote"] = ToolClass.READ
    try:
        gated = wrap_live_broker_tools("robinhood", plain, url="https://agent.robinhood.com/mcp")
    finally:
        ROBINHOOD_TOOL_CLASS.pop("place_order", None)
        ROBINHOOD_TOOL_CLASS.pop("get_quote", None)

    names = [t.name for t in gated]
    # READ tools (get_quote) are kept as-is.
    assert "mcp_robinhood_get_quote" in names
    # WRITE tools (place_order) are wrapped.
    place = next(t for t in gated if t.name == "mcp_robinhood_place_order")
    assert isinstance(place, LiveOrderGuardTool)


def test_wrap_live_broker_tools_halted_drops_write_tools() -> None:
    """When the kill switch is tripped, WRITE/UNKNOWN tools are omitted from
    the list entirely — a halted session's tool list does not even contain
    them."""
    from src.live.registry import _BROKER_CURATED_MAPS
    from src.trading.connectors.robinhood.classification import ROBINHOOD_TOOL_CLASS

    plain = _make_fake_wrappers("robinhood", ["place_order", "get_quote"])
    ROBINHOOD_TOOL_CLASS["place_order"] = ToolClass.WRITE
    ROBINHOOD_TOOL_CLASS["get_quote"] = ToolClass.READ
    try:
        with patch("src.live.registry.halt_flag_set", return_value=True):
            gated = wrap_live_broker_tools(
                "robinhood", plain, url="https://agent.robinhood.com/mcp"
            )
    finally:
        ROBINHOOD_TOOL_CLASS.pop("place_order", None)
        ROBINHOOD_TOOL_CLASS.pop("get_quote", None)

    names = [t.name for t in gated]
    # WRITE tools omitted, READ tools kept.
    assert "mcp_robinhood_place_order" not in names
    assert "mcp_robinhood_get_quote" in names


# ---------------------------------------------------------------------------
# Issue #6: OKX→Binance fallback is implemented
# ---------------------------------------------------------------------------


def test_market_data_falls_back_from_okx_to_binance(monkeypatch) -> None:
    """When source="auto" picks OKX for a USDT symbol and OKX's loader raises,
    the call must walk the crypto fallback chain (OKX → Binance → CCXT → …)
    and try Binance before giving up."""
    import pandas as pd

    from backtest.loaders.registry import FALLBACK_CHAINS

    calls: list[str] = []

    def fake_resolver(src: str):
        calls.append(src)

        class _Boom:
            name = src
            markets = {"crypto"}

            def fetch(self, codes, start, end, interval="1D"):
                raise RuntimeError(f"{src} boom")

        class _Ok:
            name = src
            markets = {"crypto"}

            def fetch(self, codes, start, end, interval="1D"):
                df = pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-01-01"]))
                df.index.name = "trade_date"
                return {codes[0]: df}

        if src == "okx":
            return _Boom
        if src == "binance":
            return _Ok
        return _Boom

    from src import market_data

    out = market_data.fetch_market_data(
        codes=["BTC-USDT"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        source="auto",
        interval="1D",
        loader_resolver=fake_resolver,
        fallback_chain_provider=lambda src: FALLBACK_CHAINS["crypto"],
    )

    assert "okx" in calls, f"OKX should be tried first for USDT pairs; got {calls}"
    assert "binance" in calls, f"Binance must be tried when OKX fails; got {calls}"
    assert "BTC-USDT" in out


def test_market_data_fallback_chain_order_matches_registry(monkeypatch) -> None:
    """The crypto fallback chain must follow FALLBACK_CHAINS['crypto'] when
    the primary source fails — that is the contract the auto mode advertises
    in the tool description."""

    from backtest.loaders.registry import FALLBACK_CHAINS
    from src import market_data

    attempted: list[str] = []

    def fake_resolver(src: str):
        attempted.append(src)

        class _Boom:
            name = src
            markets = {"crypto"}

            def fetch(self, codes, start, end, interval="1D"):
                raise RuntimeError(f"{src} boom")

        return _Boom

    market_data.fetch_market_data(
        codes=["BTC-USDT"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        source="okx",
        loader_resolver=fake_resolver,
        fallback_chain_provider=lambda src: FALLBACK_CHAINS["crypto"],
    )

    expected = ["okx", *FALLBACK_CHAINS["crypto"]]
    # Dedup while preserving order.
    seen: list[str] = []
    for s in expected:
        if s not in seen:
            seen.append(s)
    assert attempted[: len(seen)] == seen[: len(attempted)], (
        f"Fallback order violated: tried {attempted}, expected {seen}"
    )


# ---------------------------------------------------------------------------
# Issue #8: subprocess buffer is capped (OOM guard)
# ---------------------------------------------------------------------------FALLBACK_CHAINS["crypto"]]
    # Dedup while preserving order.
    seen: list[str] = []
    for s in expected:
        if s not in seen:
            seen.append(s)
    assert attempted[: len(seen)] == seen[: len(attempted)], (
        f"Fallback order violated: tried {attempted}, expected {seen}"
    )


# ---------------------------------------------------------------------------
# Issue #8: subprocess buffer is capped (OOM guard)
# ---------------------------------------------------------------------------


def test_stream_and_cap_stops_at_byte_limit() -> None:
    """``_stream_and_cap`` must stop reading once the byte cap is reached so a
    pathological child process cannot exhaust memory before the timeout fires.
    """
    from src.tools.background_tools import _stream_and_cap

    class _FakeStream:
        def __init__(self, total: int):
            self.total = total
            self.pos = 0

        def read(self, n: int) -> bytes:
            if self.pos >= self.total:
                return b""
            chunk = b"A" * min(n, self.total - self.pos)
            self.pos += len(chunk)
            return chunk

    # 200KB stream, 50KB cap -> exactly 50KB retained, no OOM.
    out = _stream_and_cap(_FakeStream(200_000), 50_000)
    assert len(out) == 50_000
    assert out == "A" * 50_000


def test_background_manager_caps_oversized_output() -> None:
    """End-to-end: a BG task whose child emits >50000 chars in stdout must
    store at most the cap (no OOM, no full-output slice)."""
    import time
    import json as _json

    from src.tools.background_tools import BackgroundManager

    mgr = BackgroundManager()
    # ``yes | head -c 200000`` is a small, dependency-free way to emit
    # >50000 bytes deterministically.
    result = mgr.run("printf 'A%.0s' {1..200000}")
    task_id = _json.loads(result)["task_id"]

    for _ in range(200):
        if mgr.tasks[task_id]["status"] != "running":
            break
        time.sleep(0.05)

    out = _json.loads(mgr.check(task_id))
    # The cap is 50_000 bytes (chars since the command emits ASCII); allow a
    # small safety margin for the trailing `[exit_code=...]` annotation we
    # added for non-zero exits, but the buffer must NEVER be unbounded.
    assert len(out["result"]) <= 60_000, (
        f"BG output not bounded: len={len(out['result'])}"
    )


# ---------------------------------------------------------------------------
# LOW Issue #7: BackgroundManager mutations and ``check()`` iteration are
# guarded by ``self._lock`` so concurrent ``run`` + ``check`` cannot raise
# ``RuntimeError: dictionary changed size during iteration``.
# ---------------------------------------------------------------------------


def test_background_check_is_safe_under_concurrent_run() -> None:
    """Regression for LOW Issue #7: ``check()`` iterates ``self.tasks`` while
    ``run()`` may be mutating it. Both must be guarded by ``self._lock``."""
    import threading
    import time

    from src.tools.background_tools import BackgroundManager

    mgr = BackgroundManager()

    errors: list[BaseException] = []

    def _stuffer() -> None:
        try:
            for _ in range(50):
                mgr.run("true")
                time.sleep(0.001)
        except BaseException as exc:  # pragma: no cover — defensive
            errors.append(exc)

    def _reader() -> None:
        try:
            for _ in range(200):
                mgr.check()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_stuffer, daemon=True),
        threading.Thread(target=_reader, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent run/check raised: {errors!r}"


# ---------------------------------------------------------------------------
# LOW Issue #10: backtest_tool catches ``subprocess.SubprocessError`` so a
# 300s ``TimeoutExpired`` (or any ``CalledProcessError``) surfaces as a
# structured ``{"status": "error", ...}`` envelope rather than escaping to
# the tool dispatcher as an unexpected exception.
# ---------------------------------------------------------------------------


def test_run_backtest_returns_error_envelope_on_timeout(
    monkeypatch, tmp_path,
) -> None:
    """When the backtest subprocess times out, ``run_backtest`` must return
    a JSON error envelope instead of raising."""
    import json as _json
    import subprocess as _subprocess

    from src.tools.backtest_tool import run_backtest

    # Allow ``tmp_path`` as a run root so ``safe_run_dir`` does not reject it.
    import os as _os
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    run_path = tmp_path / "run"
    (run_path / "code").mkdir(parents=True)
    (run_path / "config.json").write_text(
        _json.dumps({"source": "yfinance", "symbols": ["AAPL"]}), encoding="utf-8"
    )
    (run_path / "code" / "signal_engine.py").write_text("def main(): pass\n")

    class _BoomRunner:
        def execute(self, *args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd="python", timeout=300)

    import src.tools.backtest_tool as bt_mod

    original = bt_mod.Runner
    bt_mod.Runner = lambda timeout=300: _BoomRunner()  # type: ignore[assignment]
    try:
        out = run_backtest(str(run_path))
    finally:
        bt_mod.Runner = original

    parsed = _json.loads(out)
    assert parsed["status"] == "error"
    assert "timed out" in parsed["error"].lower() or "timeout" in parsed["error"].lower()