"""Tests for StrategyEntry model and Scenario enum."""

from __future__ import annotations


import pytest
from pydantic import ValidationError

from src.skills.strategy_registry.registry.models import (
    Scenario,
    StrategyEntry,
    _TYPE_TO_AREA,
)


# ---------------------------------------------------------------------------
# Scenario enum
# ---------------------------------------------------------------------------


class TestScenarioEnum:
    """Tests for the Scenario enum."""

    def test_all_scenario_values(self) -> None:
        """Verify all expected Scenario values exist."""
        expected = {
            "bear_market_defense",
            "bull_market_momentum",
            "structural_market",
            "high_volatility_regime",
            "regime_agnostic",
            "mean_reversion",
            "momentum_continuation",
            "value_rotation",
            "sector_rotation",
        }
        actual = {s.value for s in Scenario}
        assert actual == expected

    def test_scenario_from_string(self) -> None:
        """Scenario can be constructed from a valid string."""
        s = Scenario("bear_market_defense")
        assert s == Scenario.BEAR_MARKET_DEFENSE

    def test_scenario_from_invalid_string_raises(self) -> None:
        """Invalid scenario string raises ValueError."""
        with pytest.raises(ValueError):
            Scenario("nonexistent_scenario")

    def test_scenario_is_str_enum(self) -> None:
        """Scenario is a string enum, so values are strings."""
        assert isinstance(Scenario.BEAR_MARKET_DEFENSE.value, str)


# ---------------------------------------------------------------------------
# StrategyEntry — valid construction
# ---------------------------------------------------------------------------


class TestStrategyEntryValid:
    """Tests for valid StrategyEntry construction."""

    def test_minimal_entry_validates(self, entry_dict: dict) -> None:
        """A minimal valid dict should create a StrategyEntry without error."""
        entry = StrategyEntry(**entry_dict)
        assert entry.strategy_id == "test_strategy_01"
        assert entry.name == "Test Strategy"
        assert entry.source == "builtin"
        assert entry.area == "timing"

    def test_full_entry_validates(self, sample_entry: StrategyEntry) -> None:
        """A full entry with all optional fields should validate."""
        assert sample_entry.strategy_id == "quantsplaybook_ffscore"
        assert sample_entry.effective_scenarios == [
            Scenario.REGIME_AGNOSTIC,
            Scenario.VALUE_ROTATION,
            Scenario.BEAR_MARKET_DEFENSE,
        ]
        assert sample_entry.benchmark_results is not None
        assert sample_entry.benchmark_results["sharpe"] == 1.151

    def test_scenario_strings_coerced_to_enum(self) -> None:
        """String values in effective_scenarios should be coerced to Scenario enum."""
        entry = StrategyEntry(
            strategy_id="test_coerce",
            name="Coerce Test",
            source="builtin",
            area="factor",
            description="Testing string-to-enum coercion.",
            effective_scenarios=["bear_market_defense", "value_rotation"],
        )
        assert entry.effective_scenarios == [
            Scenario.BEAR_MARKET_DEFENSE,
            Scenario.VALUE_ROTATION,
        ]

    def test_none_benchmark_accepted(self) -> None:
        """benchmark_results=None should be accepted."""
        entry = StrategyEntry(
            strategy_id="no_bench",
            name="No Benchmark",
            source="sdm",
            area="rotation",
            description="No benchmark results.",
            benchmark_results=None,
        )
        assert entry.benchmark_results is None

    def test_all_source_values_accepted(self) -> None:
        """All three StrategySource values should be accepted."""
        for src in ("builtin", "sdm", "user"):
            entry = StrategyEntry(
                strategy_id=f"src_{src}",
                name=f"Source {src}",
                source=src,  # type: ignore[arg-type]
                area="factor",
                description=f"Testing source={src}.",
            )
            assert entry.source == src

    def test_all_area_values_accepted(self) -> None:
        """All five StrategyArea values should be accepted."""
        for area in ("timing", "factor", "rotation", "value", "combination"):
            entry = StrategyEntry(
                strategy_id=f"area_{area}",
                name=f"Area {area}",
                source="builtin",
                area=area,  # type: ignore[arg-type]
                description=f"Testing area={area}.",
            )
            assert entry.area == area


# ---------------------------------------------------------------------------
# StrategyEntry — validation errors
# ---------------------------------------------------------------------------


class TestStrategyEntryValidationErrors:
    """Tests for invalid StrategyEntry construction."""

    def test_invalid_strategy_id_raises(self) -> None:
        """Invalid strategy_id matching pattern should raise ValidationError."""
        invalid_ids = [
            "123invalid",        # starts with digit
            "UPPERCASE",         # has uppercase
            "has-dash",          # has dash
            "a" * 65,            # >64 chars
            "",                  # empty
        ]
        for sid in invalid_ids:
            with pytest.raises(ValidationError, match="strategy_id"):
                StrategyEntry(
                    strategy_id=sid,
                    name="Bad ID",
                    source="builtin",
                    area="timing",
                    description="Invalid strategy_id test.",
                )

    def test_missing_required_field_raises(self) -> None:
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError):
            StrategyEntry(
                strategy_id="test_missing",
                name="Missing Source",
                # source is missing
                area="timing",
                description="Missing required field.",
            )

    def test_extra_field_rejected(self) -> None:
        """Extra fields not in the model should be rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="extra"):
            StrategyEntry(
                strategy_id="extra_test",
                name="Extra Field",
                source="builtin",
                area="factor",
                description="Has extra field.",
                unknown_field="should be rejected",  # type: ignore[arg-type]
            )

    def test_description_too_long_raises(self) -> None:
        """Description > 5000 chars should raise ValidationError."""
        with pytest.raises(ValidationError, match="description"):
            StrategyEntry(
                strategy_id="long_desc",
                name="Long Description",
                source="builtin",
                area="factor",
                description="x" * 5001,
            )

    def test_description_at_max_length_ok(self) -> None:
        """Description exactly 5000 chars should be accepted."""
        entry = StrategyEntry(
            strategy_id="max_desc",
            name="Max Description",
            source="builtin",
            area="factor",
            description="x" * 5000,
        )
        assert len(entry.description) == 5000

    def test_tuning_hints_exceeds_max_raises(self) -> None:
        """tuning_hints > 10 items should raise ValidationError."""
        with pytest.raises(ValidationError, match="tuning_hints"):
            StrategyEntry(
                strategy_id="too_many_hints",
                name="Too Many Hints",
                source="builtin",
                area="factor",
                description="Too many tuning hints.",
                tuning_hints=[f"hint_{i}" for i in range(11)],
            )

    def test_tuning_hints_at_max_ok(self) -> None:
        """tuning_hints exactly 10 items should be accepted."""
        entry = StrategyEntry(
            strategy_id="max_hints",
            name="Max Hints",
            source="builtin",
            area="factor",
            description="Max tuning hints.",
            tuning_hints=[f"hint_{i}" for i in range(10)],
        )
        assert len(entry.tuning_hints) == 10

    def test_invalid_source_raises(self) -> None:
        """Invalid source value should raise ValidationError."""
        with pytest.raises(ValidationError, match="source"):
            StrategyEntry(
                strategy_id="bad_source",
                name="Bad Source",
                source="invalid_source",  # type: ignore[arg-type]
                area="factor",
                description="Invalid source.",
            )

    def test_invalid_area_raises(self) -> None:
        """Invalid area value should raise ValidationError."""
        with pytest.raises(ValidationError, match="area"):
            StrategyEntry(
                strategy_id="bad_area",
                name="Bad Area",
                source="builtin",
                area="invalid_area",  # type: ignore[arg-type]
                description="Invalid area.",
            )

    def test_invalid_scenario_in_effective_raises(self) -> None:
        """Invalid scenario string in effective_scenarios should raise ValidationError."""
        with pytest.raises(ValidationError):
            StrategyEntry(
                strategy_id="bad_scenario",
                name="Bad Scenario",
                source="builtin",
                area="factor",
                description="Invalid scenario.",
                effective_scenarios=["nonexistent_scenario"],
            )


# ---------------------------------------------------------------------------
# StrategyEntry — from_artifact()
# ---------------------------------------------------------------------------


class TestFromArtifact:
    """Tests for StrategyEntry.from_artifact()."""

    def test_from_artifact_round_trip(self) -> None:
        """from_artifact() should map a real Artifact onto a StrategyEntry."""
        from src.strategy_store.models import Artifact, ArtifactStatus, ArtifactType

        artifact = Artifact(
            id="sdm_factor_01",
            type=ArtifactType.FACTOR,
            name="SDM Factor Strategy",
            universe="china_a",
            source_paper="test paper",
            source_url="http://example.com",
            theme=("bear_market_defense", "value_rotation"),
            formula_latex="rank(close / delay(close, 20))",
            status=ArtifactStatus.ACTIVE,
        )

        entry = StrategyEntry.from_artifact(artifact)

        assert entry.strategy_id == "sdm_factor_01"
        assert entry.name == "SDM Factor Strategy"
        assert entry.source == "sdm"
        assert entry.area == "factor"
        assert entry.status == "active"
        assert entry.effective_scenarios == [
            Scenario.BEAR_MARKET_DEFENSE,
            Scenario.VALUE_ROTATION,
        ]
        assert entry.implementation == {
            "source_paper": "test paper",
            "source_url": "http://example.com",
            "universe": "china_a",
        }
        # The formula carries the logic needed for description-driven generation.
        assert "rank(close / delay(close, 20))" in entry.description

    def test_from_artifact_rejects_non_artifact(self) -> None:
        """from_artifact() should raise TypeError for non-Artifact input."""
        with pytest.raises(TypeError, match="expected Artifact"):
            StrategyEntry.from_artifact("not_an_artifact")  # type: ignore[arg-type]

    def test_from_artifact_empty_themes(self) -> None:
        """from_artifact() with empty themes should produce empty effective_scenarios."""
        from src.strategy_store.models import Artifact, ArtifactType

        artifact = Artifact(
            id="empty_theme",
            type=ArtifactType.STRATEGY,
            name="Empty Theme",
            universe="",
            theme=(),
        )

        entry = StrategyEntry.from_artifact(artifact)

        assert entry.effective_scenarios == []
        assert entry.area == "combination"
        assert entry.implementation is None
        # No rule fields stored → fall back to the display name.
        assert entry.description == "Empty Theme"

    def test_from_artifact_unknown_scenario_skipped(self) -> None:
        """from_artifact() should skip theme values that don't match any Scenario."""
        from src.strategy_store.models import Artifact, ArtifactType

        artifact = Artifact(
            id="partial_theme",
            type=ArtifactType.FACTOR,
            name="Partial Theme",
            universe="china_a",
            theme=("bear_market_defense", "unknown_theme", "value_rotation"),
        )

        entry = StrategyEntry.from_artifact(artifact)

        assert entry.effective_scenarios == [
            Scenario.BEAR_MARKET_DEFENSE,
            Scenario.VALUE_ROTATION,
        ]

    def test_from_artifact_maps_decayed_status(self) -> None:
        """A decayed artifact should surface as status='decayed'."""
        from src.strategy_store.models import Artifact, ArtifactStatus, ArtifactType

        artifact = Artifact(
            id="stale_factor",
            type=ArtifactType.FACTOR,
            name="Stale Factor",
            universe="china_a",
            status=ArtifactStatus.DECAYED,
        )

        assert StrategyEntry.from_artifact(artifact).status == "decayed"

    def test_from_artifact_maps_bench_sharpe(self) -> None:
        """A bench result should populate benchmark_results so min_sharpe can match."""
        from src.strategy_store.models import Artifact, ArtifactType, BenchResult

        artifact = Artifact(
            id="benched_strategy",
            type=ArtifactType.STRATEGY,
            name="Benched Strategy",
            universe="china_a",
            signal_definition="long when ma20 > ma60",
        )
        bench = BenchResult(
            artifact_id="benched_strategy",
            sharpe=1.42,
            max_drawdown=-0.18,
            test_start="2020-01-01",
            test_end="2026-01-01",
        )

        entry = StrategyEntry.from_artifact(artifact, bench=bench)

        assert entry.benchmark_results is not None
        assert entry.benchmark_results["sharpe"] == 1.42
        assert entry.benchmark_results["max_drawdown"] == -0.18
        assert entry.benchmark_results["period"] == "2020-01-01 to 2026-01-01"
        assert "long when ma20 > ma60" in entry.description

    def test_from_artifact_without_bench_has_no_results(self) -> None:
        """Without a bench result, benchmark_results stays None."""
        from src.strategy_store.models import Artifact, ArtifactType

        artifact = Artifact(
            id="unbenched",
            type=ArtifactType.STRATEGY,
            name="Unbenched",
            universe="china_a",
        )

        assert StrategyEntry.from_artifact(artifact).benchmark_results is None

    def test_from_artifact_type_mapping(self) -> None:
        """_TYPE_TO_AREA should map factor→factor, strategy→combination."""
        assert _TYPE_TO_AREA["factor"] == "factor"
        assert _TYPE_TO_AREA["strategy"] == "combination"


# ---------------------------------------------------------------------------
# StrategyEntry — model_dump / serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Tests for StrategyEntry serialization."""

    def test_model_dump_round_trip(self, sample_entry: StrategyEntry) -> None:
        """model_dump() should produce a dict that can be re-loaded."""
        data = sample_entry.model_dump()
        assert data["strategy_id"] == "quantsplaybook_ffscore"
        assert data["name"] == "HuaTai F-Score + Low PB Value Strategy"
        # Scenarios should be serialized as strings
        assert isinstance(data["effective_scenarios"][0], str)
        assert data["effective_scenarios"][0] == "regime_agnostic"

    def test_model_dump_json(self, sample_entry: StrategyEntry) -> None:
        """model_dump_json() should produce valid JSON."""
        json_str = sample_entry.model_dump_json()
        assert isinstance(json_str, str)
        assert "quantsplaybook_ffscore" in json_str


# ---------------------------------------------------------------------------
# StrategyEntry — strategy_id regex
# ---------------------------------------------------------------------------


class TestStrategyIdRegex:
    """Tests for the strategy_id validation pattern."""

    def test_valid_ids(self) -> None:
        """Various valid strategy_id patterns."""
        valid = [
            "a",
            "abc",
            "a1",
            "a1b2c3",
            "my_strategy_01",
            "quantsplaybook_ffscore",
            "a" * 64,  # max length
        ]
        for vid in valid:
            entry = StrategyEntry(
                strategy_id=vid,
                name="Test",
                source="builtin",
                area="factor",
                description="Valid ID test.",
            )
            assert entry.strategy_id == vid

    def test_invalid_ids(self) -> None:
        """Various invalid strategy_id patterns."""
        invalid = [
            "1abc",         # starts with digit
            "ABC",          # uppercase
            "a-b",          # dash
            "a b",          # space
            "a" * 65,       # too long
            "_start",       # starts with underscore
            "",             # empty
        ]
        for vid in invalid:
            with pytest.raises(ValidationError):
                StrategyEntry(
                    strategy_id=vid,
                    name="Test",
                    source="builtin",
                    area="factor",
                    description="Invalid ID test.",
                )
