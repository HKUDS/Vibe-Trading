"""Phase 7 policy behavior matrix for governed runtime surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.loaders.base import NoAvailableSourceError
from backtest.loaders import registry as loader_registry
from src.config.loader import sanitize_session_overrides
from src.core.runner import Runner
from src.governance.decision_recorder import DecisionRecorder
from src.governance.route_coverage import build_governed_tool_registry
from src.governance.runtime import PolicyDenied
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.model import ClaimSet
from src.reliability.quant.methodology_facts import MethodologyFactSet
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_policy import PredicateInput, ScorecardPolicyEngine

from .fixtures.fake_tools import CountingTool, StaticDenyPolicy, registry_with


@pytest.mark.parametrize("surface", ["remote_api", "mcp_sse", "mcp_http"])
def test_r5_shell_denied_on_remote_and_mcp_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool(name="fake_shell", risk_level="R5_SHELL", is_readonly=False)
    governed = build_governed_tool_registry(
        registry_with(tool),
        surface=surface,
        mode="observe",
        run_id=f"run_{surface}",
        policy=StaticDenyPolicy(),
        decision_recorder=DecisionRecorder(artifact_store=ArtifactStore(tmp_path / surface)),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_shell", {"command": "whoami"})

    assert tool.execution_counter == 0
    envelope = exc_info.value.envelope
    assert envelope.shadow_deny is True
    assert envelope.deny_barrier_engaged is True
    assert envelope.inner_tool_executed is False
    assert envelope.surface == surface


@pytest.mark.parametrize("surface", ["scheduler", "remote_api"])
def test_r4_trade_write_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool(name="fake_trade_write", risk_level="R4_TRADE_WRITE", is_readonly=False)
    governed = build_governed_tool_registry(
        registry_with(tool),
        surface=surface,
        mode="warn",
        run_id=f"run_{surface}_trade",
        policy=StaticDenyPolicy(),
        decision_recorder=DecisionRecorder(artifact_store=ArtifactStore(tmp_path / surface)),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_trade_write", {"symbol": "AAPL", "quantity": 1})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.deny_barrier_engaged is True
    assert exc_info.value.envelope.inner_tool_executed is False
    assert exc_info.value.envelope.surface == surface


def test_swarm_prompt_supplied_mcp_url_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_SESSION_MCP_SERVERS", raising=False)

    sanitized = sanitize_session_overrides(
        {
            "mcpServers": {
                "evil": {"type": "sse", "url": "https://attacker.invalid/mcp"}
            },
            "temperature": 0,
        }
    )

    assert "mcpServers" not in sanitized
    assert sanitized == {"temperature": 0}


def test_live_connector_unknown_broker_write_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool(name="unknown_broker_place_order", risk_level="R4_TRADE_WRITE", is_readonly=False)
    governed = build_governed_tool_registry(
        registry_with(tool),
        surface="live_connector",
        mode="warn",
        run_id="run_unknown_broker",
        policy=StaticDenyPolicy(),
        decision_recorder=DecisionRecorder(artifact_store=ArtifactStore(tmp_path / "live")),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("unknown_broker_place_order", {"symbol": "AAPL", "quantity": 1})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.risk_level == "R4_TRADE_WRITE"
    assert exc_info.value.envelope.inner_tool_executed is False


def test_backtest_subprocess_env_probe_excludes_llm_broker_and_live_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_keys = {
        "OPENAI_API_KEY": "sk-should-not-leak",
        "LANGCHAIN_API_KEY": "lc-should-not-leak",
        "BROKER_CLIENT_SECRET": "broker-should-not-leak",
        "LIVE_ORDER_TOKEN": "live-should-not-leak",
        "VIBE_TRADING_LIVE_MANDATE_TOKEN": "mandate-should-not-leak",
    }
    for key, value in secret_keys.items():
        monkeypatch.setenv(key, value)

    env = Runner()._build_runtime_env(tmp_path)

    for key in secret_keys:
        assert key not in env
    assert "PYTHONUNBUFFERED" in env


def test_cli_local_source_failure_does_not_network_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnavailableLocal:
        name = "local"
        markets = {"us_equity"}

        def is_available(self) -> bool:
            return False

    class NetworkFallback:
        name = "yahoo"
        markets = {"us_equity"}

        def is_available(self) -> bool:
            return True

    monkeypatch.setattr(loader_registry, "_registered", True)
    monkeypatch.setitem(loader_registry.LOADER_REGISTRY, "local", UnavailableLocal)
    monkeypatch.setitem(loader_registry.LOADER_REGISTRY, "yahoo", NetworkFallback)

    with pytest.raises(NoAvailableSourceError, match="does not fall back to a network source"):
        loader_registry.get_loader_cls_with_fallback("local")


def test_scorecard_override_attempt_hard_fails(tmp_path: Path) -> None:
    scorecard = BacktestReliabilityScorecard(
        run_id="run_override",
        conclusion_level="paper_trade_candidate",
        override_attempted=True,
    )

    result = ScorecardPolicyEngine.default().evaluate(
        PredicateInput(
            scorecard=scorecard,
            claim_set=ClaimSet(
                claim_set_id="claims_override",
                run_id="run_override",
                extractor_version="test",
                generated_by="surface_matrix",
            ),
            methodology_facts=MethodologyFactSet(run_id="run_override"),
            artifact_store=ArtifactStore(tmp_path / "artifacts"),
        )
    )

    assert result.scorecard.conclusion_level == "not_reliable"
    assert "scorecard_override_attempt" in result.scorecard.hard_failures
    assert [rule.rule_id for rule in result.triggered_rules] == ["scorecard_override_attempt"]
