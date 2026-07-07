from __future__ import annotations

import json
import platform
import time
from pathlib import Path

from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import RuntimeContext
from src.governance.discovery import ManifestCache
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.runtime import GovernedToolRegistry
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.data.contracts import DataAuditReport
from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.ledger import TrialLedger
from src.research_protocol.model import ResearchProtocol


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "schema_migration"


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int((len(ordered) - 1) * 0.95)]


def _p99(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int((len(ordered) - 1) * 0.99)]


def _threshold_ms(linux_target_ms: float, windows_target_ms: float) -> float:
    return windows_target_ms if platform.system() == "Windows" else linux_target_ms


def _measure_ms(fn, *, iterations: int = 40) -> list[float]:
    samples: list[float] = []
    fn()
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def test_data_audit_10k_row_metadata_p95_baseline() -> None:
    payload = {
        "audit_id": "audit_perf_10k",
        "schema_version": "1.0.0",
        "access_contract": {
            "source": "local:perf",
            "selected_source": "local:perf",
            "request_params_hash": "0" * 64,
            "fallback_chain": ["local:perf"],
            "fetched_at": "2026-01-01T00:00:00Z",
            "explicit_local": True,
        },
        "row_count": 10_000,
        "symbol_count": 1,
        "field_coverage": {
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
    }

    samples = _measure_ms(lambda: DataAuditReport.model_validate(payload), iterations=80)

    assert _p95(samples) <= _threshold_ms(50.0, 150.0)


def test_policy_engine_evaluate_p95_baseline() -> None:
    from src.governance.policy_engine import PolicyEngine

    engine = PolicyEngine()
    context = RuntimeContext(surface=ToolSurface.REMOTE_API, mode="enforce")
    manifest = ToolManifest(
        name="bash",
        surface=ToolSurface.REMOTE_API,
        readonly=False,
        repeatable=False,
        risk_level=RiskLevel.R5_SHELL,
        requires_auth=False,
        requires_consent=True,
        allowed_modes=["research"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=["process_execution"],
    )

    samples = _measure_ms(
        lambda: engine.evaluate(name="bash", params={"api_key": "redact-me"}, manifest=manifest, context=context),
        iterations=80,
    )

    assert _p95(samples) <= _threshold_ms(10.0, 40.0)


def test_protocol_hash_p95_baseline() -> None:
    protocol = ResearchProtocol.model_validate(json.loads((FIXTURE_DIR / "protocol_v1_0.json").read_text("utf-8")))

    samples = _measure_ms(lambda: compute_protocol_hash(protocol), iterations=80)

    assert _p95(samples) <= _threshold_ms(5.0, 20.0)


def test_trial_ledger_append_p95_baseline(tmp_path: Path) -> None:
    ledger = TrialLedger(path=tmp_path / "ledger.sqlite", write_retry_count=2, write_retry_delay_ms=1)

    samples = _measure_ms(
        lambda: ledger.append(
            protocol_hash="p" * 64,
            event_type="trial_started",
            payload={"slice": "phase8"},
            artifact_refs=[],
        ),
        iterations=20,
    )

    assert _p95(samples) <= _threshold_ms(50.0, 250.0)
    assert ledger.verify().valid is True


def test_artifact_store_write_1mb_p95_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    store = ArtifactStore(root=tmp_path / "artifacts")
    payload = b"x" * (1024 * 1024)

    samples = _measure_ms(
        lambda: store.write_bytes(payload, artifact_type="tool_trace", generated_by="perf_baseline"),
        iterations=12,
    )

    assert _p95(samples) <= _threshold_ms(500.0, 1500.0)


class _NoopTool(BaseTool):
    name = "noop_read"
    description = "noop read"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs):
        return "ok"


def test_governance_wrapper_overhead_p99_baseline() -> None:
    inner = ToolRegistry()
    inner.register(_NoopTool())
    manifest = ToolManifest(
        name="noop_read",
        surface=ToolSurface.MCP_STDIO,
        readonly=True,
        repeatable=True,
        risk_level=RiskLevel.R0_READ,
        requires_auth=False,
        requires_consent=False,
        allowed_modes=["research"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=[],
    )
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({"noop_read": manifest}, surface=ToolSurface.MCP_STDIO),
        context=RuntimeContext(surface=ToolSurface.MCP_STDIO, mode="observe"),
    )

    samples = _measure_ms(lambda: governed.execute("noop_read", {}), iterations=100)

    assert _p99(samples) <= _threshold_ms(15.0, 75.0)
