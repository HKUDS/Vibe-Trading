"""Phase 10 security regressions for IRR-AGL v1.2.1."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backtest.loaders.base import NoAvailableSourceError
from backtest.loaders import registry as loader_registry
from src.core.runner import Runner
from src.reliability.artifacts.store import resolve_under_root
from src.reliability.errors import ArtifactPathError
from src.reliability.quant.scorecard_policy import ScorecardPolicyEngine

ROOT = Path(__file__).resolve().parents[3]
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{16,}|api[_-]?key\s*[:=]\s*[^,\s\"']+|token\s*[:=]\s*[^,\s\"']+|password\s*[:=]\s*[^,\s\"']+)"
)


def test_trace_artifact_card_api_ui_fixtures_contain_no_raw_secrets() -> None:
    paths = [
        *(ROOT / "agent/tests/fixtures").glob("**/*.json"),
        *(ROOT / "agent/examples/irr_agl_demos").glob("**/expected_output.json"),
        ROOT / "frontend/src/components/research/fixtures.ts",
    ]
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if SECRET_VALUE_RE.search(text):
            leaks.append(str(path.relative_to(ROOT)))

    assert leaks == []


def test_malicious_scorecard_policy_yaml_cannot_execute_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    policy_path = tmp_path / "malicious.yaml"
    policy_path.write_text(
        f"!!python/object/apply:os.system ['echo owned > {marker}']\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid scorecard policy YAML"):
        ScorecardPolicyEngine.from_yaml(policy_path)

    assert not marker.exists()


def test_generated_subprocess_env_excludes_llm_broker_and_live_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_keys = {
        "OPENAI_API_KEY": "sk-phase10-secret",
        "LANGCHAIN_API_KEY": "langchain-secret",
        "BROKER_CLIENT_SECRET": "broker-secret",
        "LIVE_ORDER_TOKEN": "live-secret",
        "VIBE_TRADING_LIVE_MANDATE_TOKEN": "mandate-secret",
    }
    for key, value in secret_keys.items():
        monkeypatch.setenv(key, value)

    env = Runner()._build_runtime_env(tmp_path)

    for key in secret_keys:
        assert key not in env
    assert env["PYTHONUNBUFFERED"] == "1"


def test_artifact_path_containment_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(ArtifactPathError):
        resolve_under_root(tmp_path, Path("..") / "escape.json")


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
