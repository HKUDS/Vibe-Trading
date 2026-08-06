"""Unit tests for the Strategy Development Manager store and tools."""

from __future__ import annotations

import json
import uuid

import pytest

from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchResult,
    BenchCategory,
    DecaySnapshot,
    DecaySignal,
    ModelTier,
    ValidationStatus,
    is_four_eyes_violation,
    validate_model_registration,
    validate_validation_status_transition,
)
from src.strategy_store.store import InMemoryStrategyStore
from src.strategy_store.decay import DecayEvaluator, DecayThresholds


# ---------------------------------------------------------------------------
# Fixture: reset the shared singleton before each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store(tmp_path):
    """Reset the shared store singleton before each test."""
    import src.strategy_store._shared as shared
    from src.strategy_store.sqlite_store import SqliteStrategyStore

    shared._store = SqliteStrategyStore(db_path=tmp_path / "test.db")
    yield
    shared._store = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_artifact(
    *,
    name: str = "test_factor",
    universe: str = "CSI300",
    artifact_type: ArtifactType = ArtifactType.FACTOR,
    status: ArtifactStatus = ArtifactStatus.CREATED,
) -> Artifact:
    return Artifact(
        id="",
        type=artifact_type,
        name=name,
        universe=universe,
        status=status,
    )


def _register_active_artifact(
    store: InMemoryStrategyStore,
    *,
    name: str = "test_factor",
    universe: str = "CSI300",
    artifact_type: ArtifactType = ArtifactType.FACTOR,
) -> str:
    """Register an artifact and transition it to ACTIVE."""
    aid = store.register_artifact(_make_artifact(name=name, universe=universe, artifact_type=artifact_type))
    store.update_status(aid, ArtifactStatus.ACTIVE)
    return aid


# ===========================================================================
# TestModels
# ===========================================================================


class TestModels:
    """Tests for data-model dataclasses and enums."""

    def test_artifact_creation(self):
        art = Artifact(
            id="art_001",
            type=ArtifactType.FACTOR,
            name="momentum_20d",
            universe="CSI300",
        )
        assert art.id == "art_001"
        assert art.type == ArtifactType.FACTOR
        assert art.name == "momentum_20d"
        assert art.status == ArtifactStatus.CREATED  # default
        assert art.theme == ()
        assert art.columns_required == ()
        assert art.decay_horizon == 20
        assert art.disabled_at is None

    def test_artifact_frozen(self):
        art = Artifact(
            id="art_001",
            type=ArtifactType.FACTOR,
            name="momentum_20d",
            universe="CSI300",
        )
        with pytest.raises(AttributeError):
            art.name = "changed"  # type: ignore[misc]

    def test_artifact_type_enum(self):
        assert ArtifactType.FACTOR.value == "factor"
        assert ArtifactType.STRATEGY.value == "strategy"

    def test_artifact_status_enum(self):
        expected = {"created", "benching", "active", "monitoring", "decayed", "disabled"}
        actual = {s.value for s in ArtifactStatus}
        assert actual == expected

    def test_bench_result_creation(self):
        br = BenchResult(
            artifact_id="art_001",
            bench_type="initial",
            ic_mean=0.05,
            ic_std=0.02,
            ir=2.5,
            ic_positive_ratio=0.7,
            t_stat=3.1,
        )
        assert br.artifact_id == "art_001"
        assert br.ic_mean == 0.05
        assert br.ir == 2.5
        assert br.id is None  # not yet persisted

    def test_decay_snapshot_creation(self):
        snap = DecaySnapshot(
            artifact_id="art_001",
            rolling_ic_mean=0.04,
            rolling_ir=1.5,
            baseline_ic_mean=0.05,
            ic_ratio=0.8,
            decay_signal=DecaySignal.HEALTHY,
            consecutive_warnings=0,
        )
        assert snap.artifact_id == "art_001"
        assert snap.decay_signal == DecaySignal.HEALTHY
        assert snap.ic_ratio == 0.8


# ===========================================================================
# TestInMemoryStore
# ===========================================================================


class TestInMemoryStore:
    """Tests for the InMemoryStrategyStore reference implementation."""

    def test_register_artifact(self):
        store = InMemoryStrategyStore()
        art = _make_artifact()
        aid = store.register_artifact(art)
        assert aid.startswith("art_")
        fetched = store.get_artifact(aid)
        assert fetched is not None
        assert fetched.name == "test_factor"

    def test_register_auto_id(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        assert aid.startswith("art_")
        assert len(aid) > 4

    def test_register_auto_timestamp(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        art = store.get_artifact(aid)
        assert art is not None
        assert art.created_at != ""
        assert art.updated_at != ""

    def test_register_duplicate_name_universe_rejected(self):
        store = InMemoryStrategyStore()
        store.register_artifact(_make_artifact())
        with pytest.raises(ValueError, match="already exists"):
            store.register_artifact(_make_artifact())
        # Same name in a different universe is allowed
        store.register_artifact(_make_artifact(universe="SP500"))

    def test_list_artifacts_empty(self):
        store = InMemoryStrategyStore()
        assert store.list_artifacts() == []

    def test_list_artifacts_filter_type(self):
        store = InMemoryStrategyStore()
        store.register_artifact(_make_artifact(name="f1", artifact_type=ArtifactType.FACTOR))
        store.register_artifact(_make_artifact(name="s1", artifact_type=ArtifactType.STRATEGY))
        factors = store.list_artifacts(type=ArtifactType.FACTOR)
        assert len(factors) == 1
        assert factors[0].name == "f1"

    def test_list_artifacts_filter_status(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact(name="f1"))
        store.register_artifact(_make_artifact(name="f2"))
        store.update_status(aid, ArtifactStatus.ACTIVE)
        active = store.list_artifacts(status=ArtifactStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].name == "f1"

    def test_list_artifacts_filter_universe(self):
        store = InMemoryStrategyStore()
        store.register_artifact(_make_artifact(name="f1", universe="CSI300"))
        store.register_artifact(_make_artifact(name="f2", universe="SP500"))
        result = store.list_artifacts(universe="CSI300")
        assert len(result) == 1
        assert result[0].universe == "CSI300"

    def test_update_status(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        original = store.get_artifact(aid)
        assert original is not None
        updated = store.update_status(aid, ArtifactStatus.ACTIVE)
        assert updated is not None
        assert updated.status == ArtifactStatus.ACTIVE
        assert updated.updated_at >= original.updated_at

    def test_update_status_disable(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        store.update_status(aid, ArtifactStatus.ACTIVE)
        updated = store.update_status(aid, ArtifactStatus.DISABLED, reason="decay")
        assert updated is not None
        assert updated.status == ArtifactStatus.DISABLED
        assert updated.disabled_at is not None
        assert updated.disabled_reason == "decay"

    def test_update_status_not_found(self):
        store = InMemoryStrategyStore()
        result = store.update_status("nonexistent", ArtifactStatus.ACTIVE)
        assert result is None

    def test_record_bench(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        br = BenchResult(artifact_id=aid, ic_mean=0.05, ir=2.0)
        bid = store.record_bench(br)
        assert bid == 1  # auto-increment starts at 1

    def test_get_bench_history(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        for i in range(3):
            store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.01 * (i + 1)))
        history = store.get_bench_history(aid)
        assert len(history) == 3
        # Newest first
        assert history[0].id == 3
        assert history[2].id == 1

    def test_record_decay_snapshot(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        snap = DecaySnapshot(
            artifact_id=aid,
            ic_ratio=0.8,
            decay_signal=DecaySignal.HEALTHY,
        )
        sid = store.record_decay_snapshot(snap)
        assert sid == 1

    def test_get_decay_history(self):
        store = InMemoryStrategyStore()
        aid = store.register_artifact(_make_artifact())
        for i in range(3):
            store.record_decay_snapshot(
                DecaySnapshot(artifact_id=aid, ic_ratio=0.9 - i * 0.1)
            )
        history = store.get_decay_history(aid)
        assert len(history) == 3
        assert history[0].id == 3  # newest first
        assert history[2].id == 1


# ===========================================================================
# TestDecayEvaluator
# ===========================================================================


class TestDecayEvaluator:
    """Tests for the pure-logic DecayEvaluator state machine."""

    def test_healthy_signal(self):
        ev = DecayEvaluator()
        sig = ev.evaluate_decay(ic_ratio=0.8, ir=1.2)
        assert sig == DecaySignal.HEALTHY

    def test_warning_signal(self):
        ev = DecayEvaluator()
        sig = ev.evaluate_decay(ic_ratio=0.6)
        assert sig == DecaySignal.WARNING

    def test_decayed_signal(self):
        ev = DecayEvaluator()
        sig = ev.evaluate_decay(ic_ratio=0.4)
        assert sig == DecaySignal.DECAYED

    def test_critical_signal(self):
        ev = DecayEvaluator()
        sig = ev.evaluate_decay(ic_ratio=0.2, ir=0.05)
        assert sig == DecaySignal.CRITICAL

    def test_no_metrics_healthy(self):
        ev = DecayEvaluator()
        sig = ev.evaluate_decay()
        assert sig == DecaySignal.HEALTHY

    def test_worst_signal_wins(self):
        ev = DecayEvaluator()
        # ic_ratio=0.8 → HEALTHY, ir=0.3 → DECAYED (ir thresholds: 1.0/0.5/0.1)
        sig = ev.evaluate_decay(ic_ratio=0.8, ir=0.3)
        assert sig == DecaySignal.DECAYED

    def test_transition_active_to_monitoring(self):
        ev = DecayEvaluator()
        signals = [DecaySignal.WARNING, DecaySignal.WARNING, DecaySignal.WARNING]
        new_status = ev.should_transition(ArtifactStatus.ACTIVE, signals)
        assert new_status == ArtifactStatus.MONITORING

    def test_transition_monitoring_to_decayed(self):
        ev = DecayEvaluator()
        signals = [DecaySignal.DECAYED, DecaySignal.DECAYED]
        new_status = ev.should_transition(ArtifactStatus.MONITORING, signals)
        assert new_status == ArtifactStatus.DECAYED

    def test_transition_monitoring_to_active_recovery(self):
        ev = DecayEvaluator()
        signals = [DecaySignal.HEALTHY]
        new_status = ev.should_transition(ArtifactStatus.MONITORING, signals)
        assert new_status == ArtifactStatus.ACTIVE

    def test_transition_decayed_to_disabled(self):
        ev = DecayEvaluator()
        signals = [DecaySignal.CRITICAL, DecaySignal.CRITICAL, DecaySignal.CRITICAL]
        new_status = ev.should_transition(ArtifactStatus.DECAYED, signals)
        assert new_status == ArtifactStatus.DISABLED

    def test_no_transition_insufficient_signals(self):
        ev = DecayEvaluator()
        # Only 1 WARNING from ACTIVE needs 3 consecutive
        signals = [DecaySignal.WARNING]
        new_status = ev.should_transition(ArtifactStatus.ACTIVE, signals)
        assert new_status is None

    def test_custom_thresholds(self):
        thresholds = DecayThresholds(ic_ratio_healthy=0.9)
        ev = DecayEvaluator(thresholds)
        # ic_ratio=0.85 is below custom healthy=0.9 → WARNING
        sig = ev.evaluate_decay(ic_ratio=0.85)
        assert sig == DecaySignal.WARNING


# ===========================================================================
# TestSdmTools
# ===========================================================================


class TestSdmTools:
    """Integration tests for the three SDM BaseTool wrappers."""

    def test_register_tool_factor(self):
        from src.tools.sdm_register_tool import SdmRegisterTool

        tool = SdmRegisterTool()
        result = json.loads(
            tool.execute(
                artifact_type="factor",
                name="momentum_20d",
                universe="CSI300",
                formula_latex=r"\\frac{P_{t}}{P_{t-20}}-1",
                theme=["momentum"],
                columns_required=["close"],
            )
        )
        assert result["status"] == "ok"
        assert result["artifact"]["name"] == "momentum_20d"
        assert result["artifact"]["type"] == "factor"

    def test_register_tool_strategy(self):
        from src.tools.sdm_register_tool import SdmRegisterTool

        tool = SdmRegisterTool()
        result = json.loads(
            tool.execute(
                artifact_type="strategy",
                name="ma_crossover",
                universe="SP500",
                signal_definition="Buy when MA20 > MA50",
            )
        )
        assert result["status"] == "ok"
        assert result["artifact"]["type"] == "strategy"

    def test_register_tool_missing_required(self):
        from src.tools.sdm_register_tool import SdmRegisterTool

        tool = SdmRegisterTool()
        result = json.loads(tool.execute(artifact_type="factor"))
        assert result["status"] == "error"

    def test_status_tool_list(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        SdmRegisterTool().execute(
            artifact_type="factor", name="f1", universe="CSI300"
        )
        result = json.loads(SdmStatusTool().execute(action="list"))
        assert result["status"] == "ok"
        assert result["count"] == 1

    def test_status_tool_detail(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg_result = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="f1", universe="CSI300"
            )
        )
        aid = reg_result["artifact"]["id"]
        result = json.loads(SdmStatusTool().execute(action="detail", artifact_id=aid))
        assert result["status"] == "ok"
        assert result["artifact"]["name"] == "f1"
        assert "bench_history" in result
        assert "decay_history" in result

    def test_status_tool_disable_enable(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="f1", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]

        # Disable
        dis = json.loads(
            SdmStatusTool().execute(
                action="disable", artifact_id=aid, reason="testing"
            )
        )
        assert dis["status"] == "ok"
        assert dis["artifact"]["status"] == "disabled"

        # Enable
        en = json.loads(
            SdmStatusTool().execute(action="enable", artifact_id=aid)
        )
        assert en["status"] == "ok"
        assert en["artifact"]["status"] == "active"

    def test_status_tool_decay_check_insufficient(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="f1", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]
        result = json.loads(
            SdmStatusTool().execute(action="decay_check", artifact_id=aid)
        )
        assert result["status"] == "ok"
        assert result["signal"] == "insufficient_data"

    def test_decay_scan_tool_empty(self):
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        result = json.loads(SdmDecayScanTool().execute())
        assert result["status"] == "ok"
        assert result["summary"]["total_scanned"] == 0

    def test_decay_scan_tool_dry_run(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        # Register an ACTIVE factor with bench history
        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="f1", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        store.update_status(aid, ArtifactStatus.ACTIVE)

        # Add 3+ bench results so it's not insufficient_data
        for i in range(5):
            store.record_bench(
                BenchResult(artifact_id=aid, ic_mean=0.05 - i * 0.01)
            )

        result = json.loads(SdmDecayScanTool().execute(dry_run=True))
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["transitions_applied"] == 0
        assert result["summary"]["total_scanned"] == 1

    def test_register_tool_duplicate_rejected(self):
        """Registering the same (name, universe) twice returns an error."""
        from src.tools.sdm_register_tool import SdmRegisterTool

        first = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="dup_tool", universe="CSI300"
            )
        )
        assert first["status"] == "ok"
        second = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="dup_tool", universe="CSI300"
            )
        )
        assert second["status"] == "error"
        assert "already exists" in second["error"]

    def test_decay_scan_no_evaluable_metrics_insufficient(self):
        """3+ bench rows with all-None metrics report insufficient_data, not HEALTHY."""
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="metricless", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        store.update_status(aid, ArtifactStatus.ACTIVE)
        for _ in range(5):
            store.record_bench(BenchResult(artifact_id=aid))

        result = json.loads(SdmDecayScanTool().execute(dry_run=True))
        assert result["status"] == "ok"
        assert result["summary"]["insufficient_data"] == 1
        assert result["summary"].get("healthy", 0) == 0

    def test_status_tool_decay_check_no_evaluable_metrics(self):
        """decay_check with all-None metrics reports insufficient_data."""
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="metricless2", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        for _ in range(4):
            store.record_bench(BenchResult(artifact_id=aid))

        result = json.loads(
            SdmStatusTool().execute(action="decay_check", artifact_id=aid)
        )
        assert result["status"] == "ok"
        assert result["signal"] == "insufficient_data"

    def test_decay_scan_tool_active_to_monitoring_transition(self):
        """Non-dry-run scan transitions active → monitoring after 3+ warnings."""
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        reg = json.loads(
            SdmRegisterTool().execute(
                artifact_type="factor", name="decay_factor", universe="CSI300"
            )
        )
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        store.update_status(aid, ArtifactStatus.ACTIVE)

        # 5 baseline (high IC=0.08) + 5 rolling (low IC=0.04) → ratio ~0.5 = WARNING
        for _ in range(5):
            store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.08))
        for _ in range(5):
            store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.04))

        # Pre-populate 2 prior WARNING snapshots so the 3rd scan triggers transition
        store.record_decay_snapshot(
            DecaySnapshot(artifact_id=aid, ic_ratio=0.5, decay_signal=DecaySignal.WARNING)
        )
        store.record_decay_snapshot(
            DecaySnapshot(artifact_id=aid, ic_ratio=0.5, decay_signal=DecaySignal.WARNING)
        )

        # Third scan: now has 3 consecutive WARNING → active→monitoring
        result = json.loads(SdmDecayScanTool().execute(dry_run=False))
        assert result["status"] == "ok"
        assert result["dry_run"] is False
        assert result["summary"]["total_scanned"] == 1
        assert result["transitions_applied"] >= 1

        # Verify the artifact actually transitioned to monitoring
        artifact = store.get_artifact(aid)
        assert artifact is not None
        assert artifact.status == ArtifactStatus.MONITORING

        # Verify a decay snapshot was recorded with consecutive_warnings > 0
        snapshots = store.get_decay_history(aid, limit=1)
        assert len(snapshots) == 1
        assert snapshots[0].consecutive_warnings >= 1


# ===========================================================================
# TestSqliteStore
# ===========================================================================


class TestSqliteStore:
    """Tests specific to the SQLite store implementation."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a temporary SQLite store for each test."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        self.store = SqliteStrategyStore(db_path=tmp_path / "sqlite_test.db")

    def test_register_and_get(self):
        """Register an artifact and retrieve it."""
        art = _make_artifact(name="sqlite_factor")
        aid = self.store.register_artifact(art)
        assert aid.startswith("art_")

        fetched = self.store.get_artifact(aid)
        assert fetched is not None
        assert fetched.name == "sqlite_factor"
        assert fetched.type == ArtifactType.FACTOR
        assert fetched.universe == "CSI300"
        assert fetched.status == ArtifactStatus.CREATED

    def test_register_auto_id(self):
        """Empty ID gets auto-generated."""
        art = _make_artifact(name="auto_id_factor")
        aid = self.store.register_artifact(art)
        assert aid.startswith("art_")
        assert len(aid) > 4

    def test_register_auto_timestamp(self):
        """Timestamps auto-set when not provided."""
        art = _make_artifact(name="ts_factor")
        aid = self.store.register_artifact(art)
        fetched = self.store.get_artifact(aid)
        assert fetched is not None
        assert fetched.created_at != ""
        assert fetched.updated_at != ""

    def test_register_duplicate_name_universe_rejected(self):
        """UNIQUE(name, universe) surfaces as a friendly ValueError."""
        self.store.register_artifact(_make_artifact(name="dup_factor"))
        with pytest.raises(ValueError, match="already exists"):
            self.store.register_artifact(_make_artifact(name="dup_factor"))
        # Same name in a different universe is allowed
        self.store.register_artifact(
            _make_artifact(name="dup_factor", universe="SP500")
        )

    def test_list_with_filters(self):
        """List with type/status/universe filters."""
        self.store.register_artifact(
            _make_artifact(name="f1", artifact_type=ArtifactType.FACTOR, universe="CSI300")
        )
        self.store.register_artifact(
            _make_artifact(name="s1", artifact_type=ArtifactType.STRATEGY, universe="SP500")
        )
        self.store.register_artifact(
            _make_artifact(name="f2", artifact_type=ArtifactType.FACTOR, universe="SP500")
        )

        # Filter by type
        factors = self.store.list_artifacts(type=ArtifactType.FACTOR)
        assert len(factors) == 2

        # Filter by universe
        csi = self.store.list_artifacts(universe="CSI300")
        assert len(csi) == 1
        assert csi[0].name == "f1"

        # Filter by status
        active = self.store.list_artifacts(status=ArtifactStatus.ACTIVE)
        assert len(active) == 0

    def test_list_artifacts_limit(self):
        """List respects the limit parameter."""
        for i in range(5):
            self.store.register_artifact(_make_artifact(name=f"factor_{i}"))
        result = self.store.list_artifacts(limit=3)
        assert len(result) == 3

    def test_list_artifacts_ordering(self):
        """List returns newest first."""
        for i in range(3):
            self.store.register_artifact(_make_artifact(name=f"factor_{i}"))
        result = self.store.list_artifacts()
        assert result[0].name == "factor_2"
        assert result[2].name == "factor_0"

    def test_update_status_disable_enable(self):
        """Disable sets disabled_at, enable clears it."""
        aid = self.store.register_artifact(_make_artifact(name="toggle_factor"))
        self.store.update_status(aid, ArtifactStatus.ACTIVE)

        # Disable
        disabled = self.store.update_status(
            aid, ArtifactStatus.DISABLED, reason="testing"
        )
        assert disabled is not None
        assert disabled.status == ArtifactStatus.DISABLED
        assert disabled.disabled_at is not None
        assert disabled.disabled_reason == "testing"

        # Re-enable
        enabled = self.store.update_status(aid, ArtifactStatus.ACTIVE)
        assert enabled is not None
        assert enabled.status == ArtifactStatus.ACTIVE
        assert enabled.disabled_at is None
        assert enabled.disabled_reason is None

    def test_update_status_not_found(self):
        """update_status returns None for unknown artifact."""
        result = self.store.update_status("nonexistent", ArtifactStatus.ACTIVE)
        assert result is None

    def test_update_artifact(self):
        """update_artifact replaces the record."""
        aid = self.store.register_artifact(_make_artifact(name="orig_name"))
        fetched = self.store.get_artifact(aid)
        assert fetched is not None

        from dataclasses import replace

        updated_art = replace(fetched, name="new_name", decay_horizon=30)
        result = self.store.update_artifact(updated_art)
        assert result is not None
        assert result.name == "new_name"
        assert result.decay_horizon == 30

    def test_update_artifact_not_found(self):
        """update_artifact returns None for unknown artifact."""
        art = Artifact(
            id="nonexistent",
            type=ArtifactType.FACTOR,
            name="ghost",
            universe="CSI300",
        )
        result = self.store.update_artifact(art)
        assert result is None

    def test_bench_history_ordering(self):
        """Bench history returned newest-first."""
        aid = self.store.register_artifact(_make_artifact(name="bench_factor"))
        for i in range(3):
            self.store.record_bench(
                BenchResult(artifact_id=aid, ic_mean=0.01 * (i + 1))
            )
        history = self.store.get_bench_history(aid)
        assert len(history) == 3
        # Newest first — last inserted has highest id
        assert history[0].id > history[1].id > history[2].id

    def test_bench_history_limit(self):
        """Bench history respects limit."""
        aid = self.store.register_artifact(_make_artifact(name="bench_limit"))
        for i in range(5):
            self.store.record_bench(
                BenchResult(artifact_id=aid, ic_mean=0.01 * (i + 1))
            )
        history = self.store.get_bench_history(aid, limit=2)
        assert len(history) == 2

    def test_bench_result_with_category(self):
        """Bench result with BenchCategory enum round-trips."""
        aid = self.store.register_artifact(_make_artifact(name="cat_factor"))
        bid = self.store.record_bench(
            BenchResult(
                artifact_id=aid,
                ic_mean=0.05,
                ir=2.5,
                category=BenchCategory.ALIVE,
            )
        )
        history = self.store.get_bench_history(aid)
        assert len(history) == 1
        assert history[0].category == BenchCategory.ALIVE

    def test_decay_snapshot_crud(self):
        """Record and retrieve decay snapshots."""
        aid = self.store.register_artifact(_make_artifact(name="decay_factor"))
        for i in range(3):
            self.store.record_decay_snapshot(
                DecaySnapshot(
                    artifact_id=aid,
                    ic_ratio=0.9 - i * 0.1,
                    decay_signal=DecaySignal.HEALTHY,
                    consecutive_warnings=i,
                )
            )
        history = self.store.get_decay_history(aid)
        assert len(history) == 3
        # Newest first
        assert history[0].id > history[1].id > history[2].id
        assert history[0].decay_signal == DecaySignal.HEALTHY

    def test_decay_history_limit(self):
        """Decay history respects limit."""
        aid = self.store.register_artifact(_make_artifact(name="decay_limit"))
        for i in range(5):
            self.store.record_decay_snapshot(
                DecaySnapshot(artifact_id=aid, ic_ratio=0.9 - i * 0.1)
            )
        history = self.store.get_decay_history(aid, limit=2)
        assert len(history) == 2

    def test_persistence_across_instances(self):
        """Data persists when creating a new store instance with same db_path."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = self.store.db_path
        aid = self.store.register_artifact(_make_artifact(name="persist_factor"))

        # Create a new store instance pointing to the same DB
        store2 = SqliteStrategyStore(db_path=db_path)
        fetched = store2.get_artifact(aid)
        assert fetched is not None
        assert fetched.name == "persist_factor"

    def test_json_roundtrip(self):
        """Tuple fields round-trip through JSON serialization."""
        art = Artifact(
            id="",
            type=ArtifactType.FACTOR,
            name="json_factor",
            universe="CSI300",
            theme=("momentum", "reversal"),
            columns_required=("close", "volume", "high"),
        )
        aid = self.store.register_artifact(art)
        fetched = self.store.get_artifact(aid)
        assert fetched is not None
        assert fetched.theme == ("momentum", "reversal")
        assert fetched.columns_required == ("close", "volume", "high")

    def test_protocol_satisfied(self):
        """SqliteStrategyStore satisfies StrategyStoreProtocol."""
        from src.strategy_store.store import StrategyStoreProtocol

        assert isinstance(self.store, StrategyStoreProtocol)

    def test_cascade_delete_bench_history(self):
        """Deleting an artifact cascades to bench_history."""
        aid = self.store.register_artifact(_make_artifact(name="cascade_factor"))
        self.store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.05))
        self.store.record_decay_snapshot(
            DecaySnapshot(artifact_id=aid, ic_ratio=0.8)
        )

        # Delete the artifact directly via SQL
        with self.store._write_transaction():
            self.store._conn.execute("DELETE FROM artifacts WHERE id = ?", (aid,))

        assert self.store.get_bench_history(aid) == []
        assert self.store.get_decay_history(aid) == []


# ===========================================================================
# TestModelGovernance — pure-logic ModelRecord helpers (models.py)
# ===========================================================================


class TestModelGovernance:
    """Tests for the model-governance fields and validation helpers."""

    def test_artifact_governance_defaults(self):
        """Bare Artifact construction (pre-governance call sites) is unaffected."""
        art = _make_artifact()
        assert art.developer is None
        assert art.owner is None
        assert art.validator is None
        assert art.approver is None
        assert art.model_version is None
        assert art.artifact_version is None
        assert art.model_tier is None
        assert art.intended_use is None
        assert art.limitations is None
        assert art.validation_status == ValidationStatus.UNVALIDATED
        assert art.validation_date is None

    def test_model_tier_enum(self):
        expected = {"tier_1_critical", "tier_2_significant", "tier_3_limited"}
        assert {t.value for t in ModelTier} == expected

    def test_validation_status_enum(self):
        expected = {"unvalidated", "in_validation", "validated", "approved", "rejected"}
        assert {s.value for s in ValidationStatus} == expected

    # -- four-eyes principle -------------------------------------------------

    def test_four_eyes_violation_same_person(self):
        art = _make_artifact()
        art = Artifact(**{**art.__dict__, "developer": "Alice", "approver": "Alice"})
        assert is_four_eyes_violation(art) is True

    def test_four_eyes_violation_case_and_whitespace_insensitive(self):
        art = _make_artifact()
        art = Artifact(
            **{**art.__dict__, "developer": " Alice ", "approver": "alice"}
        )
        assert is_four_eyes_violation(art) is True

    def test_four_eyes_no_violation_different_people(self):
        art = _make_artifact()
        art = Artifact(
            **{**art.__dict__, "developer": "Alice", "approver": "Bob"}
        )
        assert is_four_eyes_violation(art) is False

    def test_four_eyes_not_flagged_when_roles_unset(self):
        """With developer or approver unset there is nothing to compare — not a violation."""
        art = _make_artifact()
        assert is_four_eyes_violation(art) is False

        only_developer = Artifact(**{**art.__dict__, "developer": "Alice"})
        assert is_four_eyes_violation(only_developer) is False

    def test_four_eyes_does_not_raise(self):
        """Four-eyes detection is advisory only — it must never raise."""
        art = _make_artifact()
        art = Artifact(**{**art.__dict__, "developer": "Alice", "approver": "Alice"})
        # Calling it must not raise even though it flags a violation.
        result = is_four_eyes_violation(art)
        assert result is True

    # -- intended_use / limitations required ---------------------------------

    def test_validate_model_registration_requires_intended_use(self):
        art = _make_artifact()
        art = Artifact(**{**art.__dict__, "limitations": "US large-cap only"})
        with pytest.raises(ValueError, match="intended_use"):
            validate_model_registration(art)

    def test_validate_model_registration_requires_limitations(self):
        art = _make_artifact()
        art = Artifact(**{**art.__dict__, "intended_use": "Daily rebalance signal"})
        with pytest.raises(ValueError, match="limitations"):
            validate_model_registration(art)

    def test_validate_model_registration_rejects_blank_strings(self):
        """Whitespace-only intended_use/limitations count as empty."""
        art = _make_artifact()
        art = Artifact(
            **{**art.__dict__, "intended_use": "   ", "limitations": "   "}
        )
        with pytest.raises(ValueError):
            validate_model_registration(art)

    def test_validate_model_registration_passes_when_both_set(self):
        art = _make_artifact()
        art = Artifact(
            **{
                **art.__dict__,
                "intended_use": "Daily rebalance signal for CSI300 longs",
                "limitations": "Not validated out-of-sample post-2024",
            }
        )
        validate_model_registration(art)  # must not raise

    # -- validation state machine --------------------------------------------

    def test_unvalidated_to_approved_blocked(self):
        with pytest.raises(ValueError, match="VALIDATED"):
            validate_validation_status_transition(
                ValidationStatus.UNVALIDATED, ValidationStatus.APPROVED
            )

    def test_in_validation_to_approved_blocked(self):
        with pytest.raises(ValueError):
            validate_validation_status_transition(
                ValidationStatus.IN_VALIDATION, ValidationStatus.APPROVED
            )

    def test_rejected_to_approved_blocked(self):
        with pytest.raises(ValueError):
            validate_validation_status_transition(
                ValidationStatus.REJECTED, ValidationStatus.APPROVED
            )

    def test_validated_to_approved_allowed(self):
        validate_validation_status_transition(
            ValidationStatus.VALIDATED, ValidationStatus.APPROVED
        )  # must not raise

    def test_approved_to_approved_idempotent(self):
        validate_validation_status_transition(
            ValidationStatus.APPROVED, ValidationStatus.APPROVED
        )  # re-approval is a no-op, must not raise

    def test_non_approved_transitions_unrestricted(self):
        """The guard only restricts reaching APPROVED; other moves are free."""
        validate_validation_status_transition(
            ValidationStatus.UNVALIDATED, ValidationStatus.IN_VALIDATION
        )
        validate_validation_status_transition(
            ValidationStatus.IN_VALIDATION, ValidationStatus.VALIDATED
        )
        validate_validation_status_transition(
            ValidationStatus.VALIDATED, ValidationStatus.REJECTED
        )
        validate_validation_status_transition(
            ValidationStatus.APPROVED, ValidationStatus.UNVALIDATED
        )  # e.g. re-opening for a new review cycle


# ===========================================================================
# TestModelGovernanceStore — store-level enforcement + persistence
# ===========================================================================


class TestModelGovernanceStore:
    """Governance-field persistence and enforcement across both store backends."""

    def _governed_artifact(self, **overrides) -> Artifact:
        base = _make_artifact(name=overrides.pop("name", "governed_factor"))
        fields = {
            **base.__dict__,
            "developer": "Alice",
            "owner": "Bob",
            "validator": "Carol",
            "approver": "Dave",
            "model_version": "1.0.0",
            "artifact_version": "art-v3",
            "model_tier": ModelTier.TIER_2_SIGNIFICANT,
            "intended_use": "Daily rebalance signal for CSI300 longs",
            "limitations": "Not validated out-of-sample post-2024",
            "validation_status": ValidationStatus.VALIDATED,
            "validation_date": "2026-08-01",
        }
        fields.update(overrides)
        return Artifact(**fields)

    @pytest.mark.parametrize("backend", ["sqlite", "memory"])
    def test_governance_fields_round_trip(self, backend, tmp_path):
        store = (
            _sqlite_store(tmp_path)
            if backend == "sqlite"
            else InMemoryStrategyStore()
        )
        art = self._governed_artifact()
        aid = store.register_artifact(art)
        fetched = store.get_artifact(aid)

        assert fetched is not None
        assert fetched.developer == "Alice"
        assert fetched.owner == "Bob"
        assert fetched.validator == "Carol"
        assert fetched.approver == "Dave"
        assert fetched.model_version == "1.0.0"
        assert fetched.artifact_version == "art-v3"
        assert fetched.model_tier == ModelTier.TIER_2_SIGNIFICANT
        assert fetched.intended_use == "Daily rebalance signal for CSI300 longs"
        assert fetched.limitations == "Not validated out-of-sample post-2024"
        assert fetched.validation_status == ValidationStatus.VALIDATED
        assert fetched.validation_date == "2026-08-01"

    @pytest.mark.parametrize("backend", ["sqlite", "memory"])
    def test_register_directly_as_approved_blocked(self, backend, tmp_path):
        """A model can't be born APPROVED — it has no prior VALIDATED state."""
        store = (
            _sqlite_store(tmp_path)
            if backend == "sqlite"
            else InMemoryStrategyStore()
        )
        art = self._governed_artifact(validation_status=ValidationStatus.APPROVED)
        with pytest.raises(ValueError, match="VALIDATED"):
            store.register_artifact(art)

    @pytest.mark.parametrize("backend", ["sqlite", "memory"])
    def test_update_to_approved_requires_prior_validated(self, backend, tmp_path):
        store = (
            _sqlite_store(tmp_path)
            if backend == "sqlite"
            else InMemoryStrategyStore()
        )
        art = self._governed_artifact(validation_status=ValidationStatus.UNVALIDATED)
        aid = store.register_artifact(art)
        fetched = store.get_artifact(aid)
        assert fetched is not None

        # Still UNVALIDATED — jumping to APPROVED must be blocked.
        illegal = Artifact(**{**fetched.__dict__, "validation_status": ValidationStatus.APPROVED})
        with pytest.raises(ValueError, match="VALIDATED"):
            store.update_artifact(illegal)

        # Going through VALIDATED first works, and APPROVED after that works too.
        validated = Artifact(**{**fetched.__dict__, "validation_status": ValidationStatus.VALIDATED})
        result = store.update_artifact(validated)
        assert result is not None
        assert result.validation_status == ValidationStatus.VALIDATED

        approved = Artifact(**{**result.__dict__, "validation_status": ValidationStatus.APPROVED})
        result2 = store.update_artifact(approved)
        assert result2 is not None
        assert result2.validation_status == ValidationStatus.APPROVED

    def test_four_eyes_detectable_after_round_trip(self, tmp_path):
        """A same-person dev/approve record is registerable (not force-rejected)
        but is_four_eyes_violation must flag it after reading it back."""
        store = _sqlite_store(tmp_path)
        art = self._governed_artifact(
            name="four_eyes_factor", developer="Alice", approver="Alice"
        )
        aid = store.register_artifact(art)
        fetched = store.get_artifact(aid)
        assert fetched is not None
        assert is_four_eyes_violation(fetched) is True


def _sqlite_store(tmp_path):
    from src.strategy_store.sqlite_store import SqliteStrategyStore

    return SqliteStrategyStore(db_path=tmp_path / f"gov_{uuid.uuid4().hex[:8]}.db")


# ===========================================================================
# TestSchemaMigration — backward-compatible SQLite migration
# ===========================================================================


_LEGACY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artifacts (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL CHECK(type IN ('factor', 'strategy')),
    name            TEXT NOT NULL,
    source_paper    TEXT,
    source_url      TEXT,
    formula_latex   TEXT,
    theme           TEXT,
    columns_required TEXT,
    decay_horizon   INTEGER DEFAULT 20,
    signal_definition TEXT,
    entry_rules     TEXT,
    exit_rules      TEXT,
    position_sizing TEXT,
    universe        TEXT NOT NULL,
    signal_engine_path TEXT,
    run_dir         TEXT,
    hypothesis_id   TEXT,
    status          TEXT NOT NULL DEFAULT 'created'
                    CHECK(status IN (
                        'created','benching','active',
                        'monitoring','decayed','disabled')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    disabled_at     TEXT,
    disabled_reason TEXT,
    UNIQUE(name, universe)
);

CREATE TABLE IF NOT EXISTS bench_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id     TEXT NOT NULL
                    REFERENCES artifacts(id) ON DELETE CASCADE,
    bench_type      TEXT NOT NULL
                    CHECK(bench_type IN ('initial','periodic','manual')),
    ic_mean         REAL,
    ic_std          REAL,
    ir              REAL,
    ic_positive_ratio REAL,
    t_stat          REAL,
    sharpe          REAL,
    annual_return   REAL,
    max_drawdown    REAL,
    calmar          REAL,
    category        TEXT
                    CHECK(category IN (
                        'alive','reversed','dead',
                        'confirmed_alive','noise')),
    train_start     TEXT,
    train_end       TEXT,
    test_start      TEXT,
    test_end        TEXT,
    run_dir         TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decay_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id     TEXT NOT NULL
                    REFERENCES artifacts(id) ON DELETE CASCADE,
    rolling_ic_mean     REAL,
    rolling_ir          REAL,
    baseline_ic_mean    REAL,
    ic_ratio            REAL,
    decay_signal    TEXT
                    CHECK(decay_signal IN (
                        'healthy','warning','decayed','critical')),
    consecutive_warnings INTEGER DEFAULT 0,
    detail          TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_status
    ON artifacts(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_type
    ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_bench_artifact
    ON bench_history(artifact_id, created_at);
CREATE INDEX IF NOT EXISTS idx_decay_artifact
    ON decay_snapshots(artifact_id, created_at);
"""


def _build_legacy_db(db_path) -> None:
    """Create a pre-governance-schema database with one legacy artifact row.

    Mirrors exactly the ``_init_db`` DDL as it existed before the
    model-governance migration (no developer/owner/validator/approver/
    model_version/artifact_version/model_tier/intended_use/limitations/
    validation_status/validation_date columns).
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_LEGACY_SCHEMA_SQL)
    conn.execute("PRAGMA user_version=1")
    conn.execute(
        """
        INSERT INTO artifacts (
            id, type, name, source_paper, source_url, formula_latex,
            theme, columns_required, decay_horizon, signal_definition,
            entry_rules, exit_rules, position_sizing, universe,
            signal_engine_path, run_dir, hypothesis_id, status,
            created_at, updated_at, disabled_at, disabled_reason
        ) VALUES (
            'art_legacy001', 'factor', 'legacy_momentum', NULL, NULL, NULL,
            '[]', '[]', 20, NULL,
            NULL, NULL, NULL, 'CSI300',
            NULL, NULL, NULL, 'active',
            '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00', NULL, NULL
        )
        """
    )
    conn.commit()
    conn.close()


class TestSchemaMigration:
    """Backward-compatible migration of a pre-governance SQLite database."""

    def test_old_db_opens_and_reads_via_new_code(self, tmp_path):
        """The most important test: a DB written before governance fields
        existed must still be readable (and writable) by the new store."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = tmp_path / "legacy.db"
        _build_legacy_db(db_path)

        store = SqliteStrategyStore(db_path=db_path)
        fetched = store.get_artifact("art_legacy001")

        assert fetched is not None
        assert fetched.name == "legacy_momentum"
        assert fetched.universe == "CSI300"
        assert fetched.status == ArtifactStatus.ACTIVE
        # New governance columns default sanely for pre-existing rows.
        assert fetched.developer is None
        assert fetched.owner is None
        assert fetched.validator is None
        assert fetched.approver is None
        assert fetched.model_version is None
        assert fetched.artifact_version is None
        assert fetched.model_tier is None
        assert fetched.intended_use is None
        assert fetched.limitations is None
        assert fetched.validation_status == ValidationStatus.UNVALIDATED
        assert fetched.validation_date is None

    def test_old_db_still_writable_after_migration(self, tmp_path):
        """New writes (including governance fields) work on a migrated DB."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = tmp_path / "legacy_write.db"
        _build_legacy_db(db_path)

        store = SqliteStrategyStore(db_path=db_path)
        aid = store.register_artifact(
            Artifact(
                id="",
                type=ArtifactType.FACTOR,
                name="post_migration_factor",
                universe="CSI300",
                developer="Alice",
                intended_use="Signal for post-migration coverage",
                limitations="Untested pre-2020",
            )
        )
        fetched = store.get_artifact(aid)
        assert fetched is not None
        assert fetched.developer == "Alice"
        assert fetched.intended_use == "Signal for post-migration coverage"

        # The pre-existing legacy row is still intact and readable too.
        legacy = store.get_artifact("art_legacy001")
        assert legacy is not None
        assert legacy.name == "legacy_momentum"

    def test_old_db_update_status_still_works(self, tmp_path):
        """update_status (unrelated to governance) keeps working on a migrated row."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = tmp_path / "legacy_status.db"
        _build_legacy_db(db_path)

        store = SqliteStrategyStore(db_path=db_path)
        updated = store.update_status(
            "art_legacy001", ArtifactStatus.DISABLED, reason="migrated-test"
        )
        assert updated is not None
        assert updated.status == ArtifactStatus.DISABLED
        assert updated.disabled_reason == "migrated-test"
        # Governance fields remain untouched/default.
        assert updated.validation_status == ValidationStatus.UNVALIDATED

    def test_migration_is_idempotent(self, tmp_path):
        """Running the column-migration twice does not error or duplicate columns."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = tmp_path / "idempotent.db"
        _build_legacy_db(db_path)

        store = SqliteStrategyStore(db_path=db_path)
        # First open already ran the migration once (in __init__ -> _init_db).
        # Run it again explicitly, twice more, to prove idempotency.
        store._migrate_governance_columns()
        store._migrate_governance_columns()

        columns = [
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(artifacts)")
        ]
        # No duplicate column names.
        assert len(columns) == len(set(columns))
        assert columns.count("validation_status") == 1
        assert columns.count("developer") == 1

        # Store still functions normally after repeated migration calls.
        fetched = store.get_artifact("art_legacy001")
        assert fetched is not None

    def test_migration_idempotent_across_fresh_reopen(self, tmp_path):
        """Re-opening an already-migrated DB with a fresh store instance is safe."""
        from src.strategy_store.sqlite_store import SqliteStrategyStore

        db_path = tmp_path / "reopen.db"
        _build_legacy_db(db_path)

        store1 = SqliteStrategyStore(db_path=db_path)
        aid = store1.register_artifact(_make_artifact(name="reopen_factor"))

        # Re-open with a brand-new store instance — _init_db (and the
        # migration inside it) runs again against an already-migrated file.
        store2 = SqliteStrategyStore(db_path=db_path)
        fetched = store2.get_artifact(aid)
        assert fetched is not None
        assert fetched.name == "reopen_factor"
