"""Post-416/420 security regression coverage for IRR-AGL v1.2.1."""

from __future__ import annotations

import inspect
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from backtest.loaders import registry as loader_registry
from backtest.loaders.base import NoAvailableSourceError
from src.agent.tools import BaseTool, ToolRegistry
from src.api.evidence_routes import register_evidence_routes
from src.core.runner import Runner
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import PolicyDecision
from src.governance.evidence_identity import hash_params
from src.governance.runtime import GovernedToolRegistry, PolicyDenied, RuntimeContext, manifest_for_tool
from src.reliability.quant.scorecard_policy import ScorecardPolicyEngine


ROOT = Path(__file__).resolve().parents[3]
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{16,}|"
    r"(api[_-]?key|token|password|credential|secret)\s*[:=]\s*[^,\s\"']+)"
)
EVIDENCE_GET_PATHS = {
    "/research/evidence/{run_id}",
    "/research/evidence/{run_id}/verify",
    "/research/artifacts/{artifact_id}/lineage",
    "/governance/policy-decisions",
    "/research/claims/{run_id}",
    "/research/methodology-facts/{run_id}",
}


def test_no_raw_secret_in_trace_artifact_card_api_ui_fixtures() -> None:
    paths = [
        *(ROOT / "agent/tests/fixtures").glob("**/*.json"),
        *(ROOT / "agent/examples/irr_agl_demos").glob("**/expected_output.json"),
        ROOT / "frontend/src/components/research/fixtures.ts",
    ]

    leaks = [
        str(path.relative_to(ROOT))
        for path in paths
        if path.exists() and SECRET_VALUE_RE.search(path.read_text(encoding="utf-8"))
    ]

    assert leaks == []


def test_malicious_scorecard_yaml_cannot_execute_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    policy_path = tmp_path / "malicious.yaml"
    policy_path.write_text(
        f"!!python/object/apply:os.system ['echo pwned > {marker}']\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid scorecard policy YAML"):
        ScorecardPolicyEngine.from_yaml(policy_path)

    assert not marker.exists()


def test_no_eval_exec_compile_in_scorecard_policy_path() -> None:
    import src.reliability.quant.scorecard_policy as scorecard_policy

    source = inspect.getsource(scorecard_policy)

    assert "eval(" not in source
    assert "exec(" not in source
    assert "compile(" not in source
    assert "importlib" not in source


def test_subprocess_env_excludes_llm_api_broker_live_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_env = {
        "OPENAI_API_KEY": "sk-post416-secret",
        "LANGCHAIN_API_KEY": "langchain-secret",
        "VIBE_TRADING_API_TOKEN": "api-secret",
        "BROKER_CLIENT_SECRET": "broker-secret",
        "LIVE_ORDER_TOKEN": "live-secret",
        "VIBE_TRADING_LIVE_MANDATE_TOKEN": "mandate-secret",
    }
    for key, value in secret_env.items():
        monkeypatch.setenv(key, value)

    env = Runner()._build_runtime_env(tmp_path)

    assert env["PYTHONUNBUFFERED"] == "1"
    for key in secret_env:
        assert key not in env


def test_local_source_failure_does_not_network_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_no_write_methods_in_new_evidence_api_routes() -> None:
    app = FastAPI()
    register_evidence_routes(app)

    routes = {route.path: route.methods for route in app.routes if route.path in EVIDENCE_GET_PATHS}

    assert set(routes) == EVIDENCE_GET_PATHS
    assert all(methods == {"GET"} for methods in routes.values())


def test_openapi_snapshot_marks_evidence_routes_get_only() -> None:
    api_server = _load_real_api_server_module()

    schema = api_server.app.openapi()

    for path in EVIDENCE_GET_PATHS:
        assert path in schema["paths"]
        assert set(schema["paths"][path]) == {"get"}


def test_unclassified_tool_not_promoted_to_safe_by_fallback() -> None:
    class UnclassifiedWriteTool(BaseTool):
        name = "opaque_mutation"
        is_readonly = False

        def execute(self, **kwargs: Any) -> str:
            return json.dumps({"status": "ok", "kwargs": kwargs})

    manifest = manifest_for_tool(UnclassifiedWriteTool())

    assert manifest.risk_level != "R1_READ"
    assert manifest.is_readonly is False


def test_manifest_discovery_classifies_unknown_high_risk_fail_closed() -> None:
    class UnknownBrokerOrderTool(BaseTool):
        name = "unknown_broker_order_write"
        is_readonly = False

        def __init__(self) -> None:
            self.execution_counter = 0

        def execute(self, **kwargs: Any) -> str:
            del kwargs
            self.execution_counter += 1
            return json.dumps({"status": "executed"})

    tool = UnknownBrokerOrderTool()
    raw_registry = ToolRegistry()
    raw_registry.register(tool)
    governed = GovernedToolRegistry(raw_registry, context=RuntimeContext(mode="observe", surface="remote_api"))

    with pytest.raises(PolicyDenied) as denied:
        governed.execute(tool.name, {"symbol": "AAPL", "qty": 1})

    assert tool.execution_counter == 0
    assert denied.value.envelope.deny_barrier_engaged is True
    assert denied.value.envelope.inner_tool_executed is False


def test_policy_decision_params_hash_matches_executed_params_hash() -> None:
    params = {"symbol": "AAPL", "qty": 3, "nested": {"b": 2, "a": 1}}
    decision = PolicyDecision(
        tool_name="read_only_probe",
        action="allow",
        risk_level="R1_READ",
        reasons=[],
        policy_engine_version="pytest-post416",
    )

    envelope = DecisionRecorder().prepare(
        decision,
        params=params,
        context=RuntimeContext(mode="observe", surface="pytest", run_id="run_params_hash"),
    )

    assert envelope.params_hash == hash_params(params)


def _load_real_api_server_module():
    module_name = "_phase10_real_api_server"
    module_path = ROOT / "agent" / "api_server.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load api_server from {module_path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    previous_api_server = sys.modules.get("api_server")
    sys.modules[module_name] = module
    sys.modules["api_server"] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        if previous_api_server is not None and hasattr(previous_api_server, "app"):
            sys.modules["api_server"] = previous_api_server
