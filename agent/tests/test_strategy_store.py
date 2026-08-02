"""Unit tests for the Strategy Development Manager store and tools."""

from __future__ import annotations

import json
import pytest

from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchResult,
    BenchCategory,
    DecaySnapshot,
    DecaySignal,
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
            store.record_decay_snapshot(DecaySnapshot(artifact_id=aid, ic_ratio=0.9 - i * 0.1))
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

        SdmRegisterTool().execute(artifact_type="factor", name="f1", universe="CSI300")
        result = json.loads(SdmStatusTool().execute(action="list"))
        assert result["status"] == "ok"
        assert result["count"] == 1

    def test_status_tool_detail(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg_result = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="f1", universe="CSI300"))
        aid = reg_result["artifact"]["id"]
        result = json.loads(SdmStatusTool().execute(action="detail", artifact_id=aid))
        assert result["status"] == "ok"
        assert result["artifact"]["name"] == "f1"
        assert "bench_history" in result
        assert "decay_history" in result

    def test_status_tool_disable_enable(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="f1", universe="CSI300"))
        aid = reg["artifact"]["id"]

        # Disable
        dis = json.loads(SdmStatusTool().execute(action="disable", artifact_id=aid, reason="testing"))
        assert dis["status"] == "ok"
        assert dis["artifact"]["status"] == "disabled"

        # Enable
        en = json.loads(SdmStatusTool().execute(action="enable", artifact_id=aid))
        assert en["status"] == "ok"
        assert en["artifact"]["status"] == "active"

    def test_status_tool_decay_check_insufficient(self):
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_status_tool import SdmStatusTool

        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="f1", universe="CSI300"))
        aid = reg["artifact"]["id"]
        result = json.loads(SdmStatusTool().execute(action="decay_check", artifact_id=aid))
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
        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="f1", universe="CSI300"))
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        store.update_status(aid, ArtifactStatus.ACTIVE)

        # Add 3+ bench results so it's not insufficient_data
        for i in range(5):
            store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.05 - i * 0.01))

        result = json.loads(SdmDecayScanTool().execute(dry_run=True))
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["transitions_applied"] == 0
        assert result["summary"]["total_scanned"] == 1

    def test_register_tool_duplicate_rejected(self):
        """Registering the same (name, universe) twice returns an error."""
        from src.tools.sdm_register_tool import SdmRegisterTool

        first = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="dup_tool", universe="CSI300"))
        assert first["status"] == "ok"
        second = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="dup_tool", universe="CSI300"))
        assert second["status"] == "error"
        assert "already exists" in second["error"]

    def test_decay_scan_no_evaluable_metrics_insufficient(self):
        """3+ bench rows with all-None metrics report insufficient_data, not HEALTHY."""
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="metricless", universe="CSI300"))
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

        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="metricless2", universe="CSI300"))
        aid = reg["artifact"]["id"]

        import src.strategy_store._shared as shared

        store = shared._store
        assert store is not None
        for _ in range(4):
            store.record_bench(BenchResult(artifact_id=aid))

        result = json.loads(SdmStatusTool().execute(action="decay_check", artifact_id=aid))
        assert result["status"] == "ok"
        assert result["signal"] == "insufficient_data"

    def test_decay_scan_tool_active_to_monitoring_transition(self):
        """Non-dry-run scan transitions active → monitoring after 3+ warnings."""
        from src.tools.sdm_register_tool import SdmRegisterTool
        from src.tools.sdm_decay_scan_tool import SdmDecayScanTool

        reg = json.loads(SdmRegisterTool().execute(artifact_type="factor", name="decay_factor", universe="CSI300"))
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
        store.record_decay_snapshot(DecaySnapshot(artifact_id=aid, ic_ratio=0.5, decay_signal=DecaySignal.WARNING))
        store.record_decay_snapshot(DecaySnapshot(artifact_id=aid, ic_ratio=0.5, decay_signal=DecaySignal.WARNING))

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
        self.store.register_artifact(_make_artifact(name="dup_factor", universe="SP500"))

    def test_list_with_filters(self):
        """List with type/status/universe filters."""
        self.store.register_artifact(_make_artifact(name="f1", artifact_type=ArtifactType.FACTOR, universe="CSI300"))
        self.store.register_artifact(_make_artifact(name="s1", artifact_type=ArtifactType.STRATEGY, universe="SP500"))
        self.store.register_artifact(_make_artifact(name="f2", artifact_type=ArtifactType.FACTOR, universe="SP500"))

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
        disabled = self.store.update_status(aid, ArtifactStatus.DISABLED, reason="testing")
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
            self.store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.01 * (i + 1)))
        history = self.store.get_bench_history(aid)
        assert len(history) == 3
        # Newest first — last inserted has highest id
        assert history[0].id > history[1].id > history[2].id

    def test_bench_history_limit(self):
        """Bench history respects limit."""
        aid = self.store.register_artifact(_make_artifact(name="bench_limit"))
        for i in range(5):
            self.store.record_bench(BenchResult(artifact_id=aid, ic_mean=0.01 * (i + 1)))
        history = self.store.get_bench_history(aid, limit=2)
        assert len(history) == 2

    def test_bench_result_with_category(self):
        """Bench result with BenchCategory enum round-trips."""
        aid = self.store.register_artifact(_make_artifact(name="cat_factor"))
        self.store.record_bench(
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
            self.store.record_decay_snapshot(DecaySnapshot(artifact_id=aid, ic_ratio=0.9 - i * 0.1))
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
        self.store.record_decay_snapshot(DecaySnapshot(artifact_id=aid, ic_ratio=0.8))

        # Delete the artifact directly via SQL
        with self.store._write_transaction():
            self.store._conn.execute("DELETE FROM artifacts WHERE id = ?", (aid,))

        assert self.store.get_bench_history(aid) == []
        assert self.store.get_decay_history(aid) == []
