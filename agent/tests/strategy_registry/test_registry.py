"""Tests for StrategyRegistry: load, list, get, query, health."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.skills.strategy_registry.registry import StrategyRegistry
from src.skills.strategy_registry.registry.models import Scenario


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestLoad:
    """Tests for StrategyRegistry.load()."""

    def test_load_returns_count(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """load() should return the number of successfully loaded entries."""
        count = StrategyRegistry.load(temp_seed_dir)
        assert count == 2
    def test_load_populates_registry(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """After load(), the registry should contain the loaded entries."""
        StrategyRegistry.load(temp_seed_dir)
        assert len(StrategyRegistry._builtin) == 2
        assert "quantsplaybook_ffscore" in StrategyRegistry._builtin
        assert "quantsplaybook_relstrength" in StrategyRegistry._builtin

    def test_load_nonexistent_dir(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() with a nonexistent directory should return 0."""
        non_existent = tmp_path / "no_such_dir"
        count = StrategyRegistry.load(non_existent)
        assert count == 0

    def test_load_empty_dir(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() with an empty directory should return 0."""
        empty_dir = tmp_path / "empty_seed"
        empty_dir.mkdir()
        count = StrategyRegistry.load(empty_dir)
        assert count == 0

    def test_load_skips_invalid_yaml(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() should skip YAML files that fail validation."""
        seed_dir = tmp_path / "bad_seed"
        seed_dir.mkdir()

        # Valid file
        (seed_dir / "valid.yaml").write_text(
            "strategy_id: valid_strategy\nname: Valid\nsource: builtin\narea: factor\ndescription: OK.\n",
            encoding="utf-8",
        )
        # Invalid: missing required field (name)
        (seed_dir / "invalid.yaml").write_text(
            "strategy_id: invalid_strategy\nsource: builtin\narea: factor\ndescription: Missing name.\n",
            encoding="utf-8",
        )

        count = StrategyRegistry.load(seed_dir)
        assert count == 1
        assert "valid_strategy" in StrategyRegistry._builtin
        assert "invalid_strategy" not in StrategyRegistry._builtin

    def test_load_skips_non_dict_yaml(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() should skip YAML files whose root is not a dict."""
        seed_dir = tmp_path / "list_seed"
        seed_dir.mkdir()

        (seed_dir / "list.yaml").write_text("- item1\n- item2\n", encoding="utf-8")

        count = StrategyRegistry.load(seed_dir)
        assert count == 0

    def test_load_duplicate_ids_skips_second(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() should skip the second file with a duplicate strategy_id."""
        seed_dir = tmp_path / "dup_seed"
        seed_dir.mkdir()

        yaml_content = (
            "strategy_id: dup_strategy\nname: Duplicate\nsource: builtin\narea: factor\n"
            "description: Duplicate entry.\n"
        )
        (seed_dir / "first.yaml").write_text(yaml_content, encoding="utf-8")
        (seed_dir / "second.yaml").write_text(yaml_content, encoding="utf-8")

        count = StrategyRegistry.load(seed_dir)
        assert count == 1  # first loaded, second skipped

    def test_load_oversized_yaml_rejected(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() should reject YAML files larger than 5 MB."""
        seed_dir = tmp_path / "big_seed"
        seed_dir.mkdir()

        big_file = seed_dir / "big.yaml"
        header = "strategy_id: big_strategy\nname: Big\nsource: builtin\narea: factor\ndescription: Big file.\n"
        padding_size = 5_000_001 - len(header)
        big_file.write_text(header + "#" * padding_size, encoding="utf-8")

        count = StrategyRegistry.load(seed_dir)
        assert count == 0

    def test_load_safe_load_rejects_unsafe_tags(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() uses yaml.safe_load which rejects !!python/object tags."""
        seed_dir = tmp_path / "unsafe_seed"
        seed_dir.mkdir()

        (seed_dir / "unsafe.yaml").write_text(
            "strategy_id: unsafe_test\n"
            "name: Unsafe\n"
            "source: builtin\n"
            "area: factor\n"
            "description: Testing unsafe YAML.\n"
            "!!python/object:__main__.Exploit {}\n",
            encoding="utf-8",
        )

        count = StrategyRegistry.load(seed_dir)
        assert count == 0

    def test_load_yaml_parse_error_skipped(self, isolated_registry: None, tmp_path: Path) -> None:
        """load() should skip files with YAML parse errors."""
        seed_dir = tmp_path / "bad_parse"
        seed_dir.mkdir()

        (seed_dir / "bad.yaml").write_text(
            "strategy_id: bad\nname: [unclosed\n  - list\n",
            encoding="utf-8",
        )

        count = StrategyRegistry.load(seed_dir)
        assert count == 0


# ---------------------------------------------------------------------------
# ensure_loaded() / bundled seed data
# ---------------------------------------------------------------------------


class TestBundledSeed:
    """The shipped seed catalog must be reachable without an explicit load()."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        """Force a cold registry so ensure_loaded() has to do the work."""
        StrategyRegistry._builtin = {}
        StrategyRegistry._loaded = False
        yield
        StrategyRegistry._builtin = {}
        StrategyRegistry._loaded = False

    def test_query_auto_loads_bundled_seed(self) -> None:
        """A read on a cold registry should auto-load the bundled seed files."""
        results = StrategyRegistry.query(source="builtin", limit=50)
        assert len(results) == 15

    def test_bundled_seed_declares_market_universe(self) -> None:
        """Bundled entries must carry a universe so the market filter can match."""
        results = StrategyRegistry.query(source="builtin", market="china_a", limit=50)
        assert len(results) == 15

    def test_bundled_bear_market_query(self) -> None:
        """The scenario the issue calls out must resolve to real strategies."""
        results = StrategyRegistry.query(
            scenario="bear_market_defense",
            market="china_a",
            min_sharpe=0.0,
            decay_status="active",
            source="builtin",
            limit=5,
        )
        assert [r.strategy_id for r in results] == [
            "quantsplaybook_csvc",
            "quantsplaybook_ffscore",
            "quantsplaybook_relstrength",
        ]

    def test_get_auto_loads_bundled_seed(self) -> None:
        """get() on a cold registry should resolve a bundled strategy id."""
        entry = StrategyRegistry.get("quantsplaybook_csvc")
        assert entry is not None
        assert entry.source == "builtin"


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------


class TestList:
    """Tests for StrategyRegistry.list()."""

    def test_list_returns_all_entries(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list() should return all loaded entries."""
        StrategyRegistry.load(temp_seed_dir)
        entries = StrategyRegistry.list()
        assert len(entries) == 2

    def test_list_is_sorted_by_id(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list() results should be sorted by strategy_id."""
        StrategyRegistry.load(temp_seed_dir)
        entries = StrategyRegistry.list()
        ids = [e.strategy_id for e in entries]
        assert ids == sorted(ids)

    def test_list_pagination_limit(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list() should respect the limit parameter."""
        StrategyRegistry.load(temp_seed_dir)
        entries = StrategyRegistry.list(limit=1)
        assert len(entries) == 1

    def test_list_pagination_offset(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list() should respect the offset parameter."""
        StrategyRegistry.load(temp_seed_dir)
        all_entries = StrategyRegistry.list()
        page = StrategyRegistry.list(limit=1, offset=1)
        assert len(page) == 1
        assert page[0].strategy_id != all_entries[0].strategy_id

    def test_list_empty_registry(self, isolated_registry: None) -> None:
        """list() on an empty registry should return an empty list."""
        entries = StrategyRegistry.list()
        assert entries == []


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    """Tests for StrategyRegistry.get()."""

    def test_get_existing(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """get() should return the entry for an existing strategy_id."""
        StrategyRegistry.load(temp_seed_dir)
        entry = StrategyRegistry.get("quantsplaybook_ffscore")
        assert entry is not None
        assert entry.strategy_id == "quantsplaybook_ffscore"
        assert entry.source == "builtin"

    def test_get_nonexistent(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """get() should return None for a non-existent strategy_id."""
        StrategyRegistry.load(temp_seed_dir)
        entry = StrategyRegistry.get("nonexistent_id")
        assert entry is None

    def test_get_empty_registry(self, isolated_registry: None) -> None:
        """get() on an empty registry should return None."""
        entry = StrategyRegistry.get("any_id")
        assert entry is None


# ---------------------------------------------------------------------------
# query()
# ---------------------------------------------------------------------------


class TestQuery:
    """Tests for StrategyRegistry.query()."""

    @pytest.fixture(autouse=True)
    def _setup(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """Load seed data before each query test."""
        StrategyRegistry.load(temp_seed_dir)

    def test_query_no_filters(self) -> None:
        """query() with no filters should return all entries."""
        results = StrategyRegistry.query()
        assert len(results) == 2

    def test_query_by_scenario_string(self) -> None:
        """query() should filter by scenario string."""
        results = StrategyRegistry.query(scenario="bear_market_defense")
        assert len(results) == 2
        for r in results:
            assert Scenario.BEAR_MARKET_DEFENSE in r.effective_scenarios

    def test_query_by_scenario_enum(self) -> None:
        """query() should filter by Scenario enum."""
        results = StrategyRegistry.query(scenario=Scenario.BEAR_MARKET_DEFENSE)
        assert len(results) == 2

    def test_query_by_scenario_one_match(self) -> None:
        """query() by a scenario that only one strategy has."""
        results = StrategyRegistry.query(scenario="high_volatility_regime")
        assert len(results) == 1
        assert results[0].strategy_id == "quantsplaybook_relstrength"

    def test_query_unknown_scenario_ignored(self) -> None:
        """query() with an unknown scenario should log warning and ignore filter."""
        results = StrategyRegistry.query(scenario="nonexistent_scenario")
        # Unknown scenario → filter ignored → all entries returned
        assert len(results) == 2

    def test_query_by_source_builtin(self) -> None:
        """query() by source='builtin' should return only builtin entries."""
        results = StrategyRegistry.query(source="builtin")
        assert len(results) == 2
        for r in results:
            assert r.source == "builtin"

    def test_query_by_source_sdm(self) -> None:
        """query() by source='sdm' should return only SDM entries."""
        results = StrategyRegistry.query(source="sdm")
        # No SDM entries in our test data (mocked)
        assert len(results) == 0

    def test_query_by_min_sharpe(self) -> None:
        """query() should filter by min_sharpe."""
        results = StrategyRegistry.query(min_sharpe=0.5)
        # Only ffscore has sharpe > 0.5
        assert len(results) == 1
        assert results[0].strategy_id == "quantsplaybook_ffscore"

    def test_query_by_min_sharpe_no_match(self) -> None:
        """query() with high min_sharpe should return empty."""
        results = StrategyRegistry.query(min_sharpe=10.0)
        assert len(results) == 0

    def test_query_by_market_excludes_entries_without_universe(self) -> None:
        """query() with market filter should drop entries that carry no universe."""
        results = StrategyRegistry.query(market="china_a")
        # Fixture entries have no implementation.universe → nothing matches
        assert len(results) == 0

    def test_query_by_market_matches_builtin_universe(self) -> None:
        """query() with market filter should match builtin entries by universe."""
        entry = StrategyRegistry._builtin["quantsplaybook_ffscore"]
        StrategyRegistry._builtin["quantsplaybook_ffscore"] = entry.model_copy(
            update={"implementation": {**(entry.implementation or {}), "universe": "china_a"}}
        )

        results = StrategyRegistry.query(market="china_a")
        assert [r.strategy_id for r in results] == ["quantsplaybook_ffscore"]
        assert StrategyRegistry.query(market="us") == []

    def test_query_combined_filters(self) -> None:
        """query() should support combined filters."""
        results = StrategyRegistry.query(
            scenario="bear_market_defense",
            source="builtin",
            min_sharpe=0.5,
        )
        assert len(results) == 1
        assert results[0].strategy_id == "quantsplaybook_ffscore"

    def test_query_pagination(self) -> None:
        """query() should support limit and offset."""
        results = StrategyRegistry.query(limit=1, offset=0)
        assert len(results) == 1

        results_page2 = StrategyRegistry.query(limit=1, offset=1)
        assert len(results_page2) == 1
        assert results_page2[0].strategy_id != results[0].strategy_id

    def test_query_empty_registry(self, isolated_registry: None) -> None:
        """query() on an empty registry should return empty list."""
        # Note: autouse _setup also runs, but we re-clear via isolated_registry
        # which is already active. Just clear _builtin explicitly.
        StrategyRegistry._builtin = {}
        results = StrategyRegistry.query()
        assert results == []

    def test_query_by_decay_status(self) -> None:
        """query() should filter by lifecycle status; builtin entries are active."""
        assert len(StrategyRegistry.query(decay_status="active")) == 2
        assert StrategyRegistry.query(decay_status="decayed") == []

    def test_query_matches_issue_scenario(self) -> None:
        """The issue's canonical compound query should return the ffscore entry."""
        entry = StrategyRegistry._builtin["quantsplaybook_ffscore"]
        StrategyRegistry._builtin["quantsplaybook_ffscore"] = entry.model_copy(
            update={"implementation": {**(entry.implementation or {}), "universe": "china_a"}}
        )

        results = StrategyRegistry.query(
            scenario="bear_market_defense",
            market="china_a",
            min_sharpe=0.0,
            decay_status="active",
            limit=5,
        )
        assert [r.strategy_id for r in results] == ["quantsplaybook_ffscore"]


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for StrategyRegistry.health()."""

    def test_health_after_load(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """health() should return correct counts after load."""
        StrategyRegistry.load(temp_seed_dir)
        h = StrategyRegistry.health()
        assert h["builtin_loaded"] == 2
        assert h["total"] == 2
        assert isinstance(h["sdm_available"], bool)

    def test_health_empty_registry(self, isolated_registry: None) -> None:
        """health() on an empty registry should return zeros."""
        h = StrategyRegistry.health()
        assert h["builtin_loaded"] == 0
        assert h["total"] == 0

    def test_health_has_expected_keys(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """health() should return a dict with expected keys."""
        StrategyRegistry.load(temp_seed_dir)
        h = StrategyRegistry.health()
        assert set(h.keys()) == {"builtin_loaded", "sdm_available", "total"}


# ---------------------------------------------------------------------------
# _load_yaml_file (internal)
# ---------------------------------------------------------------------------


class TestLoadYamlFile:
    """Tests for StrategyRegistry._load_yaml_file()."""

    def test_load_valid_yaml(self, isolated_registry: None, tmp_path: Path) -> None:
        """Should parse a valid YAML file into a StrategyEntry."""
        yaml_file = tmp_path / "valid.yaml"
        yaml_file.write_text(
            "strategy_id: test_valid_yaml\nname: Test\nsource: builtin\narea: factor\ndescription: Test.\n",
            encoding="utf-8",
        )
        entry = StrategyRegistry._load_yaml_file(yaml_file)
        assert entry.strategy_id == "test_valid_yaml"

    def test_load_non_dict_yaml(self, isolated_registry: None, tmp_path: Path) -> None:
        """Should raise ValueError for non-dict root."""
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- item1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            StrategyRegistry._load_yaml_file(yaml_file)

    def test_load_oversized_yaml(self, isolated_registry: None, tmp_path: Path) -> None:
        """Should raise ValueError for files > 5 MB."""
        yaml_file = tmp_path / "big.yaml"
        header = "strategy_id: big_test\nname: Big\nsource: builtin\narea: factor\ndescription: Big.\n"
        padding_size = 5_000_001 - len(header)
        yaml_file.write_text(header + "#" * padding_size, encoding="utf-8")
        with pytest.raises(ValueError, match="B exceeds"):
            StrategyRegistry._load_yaml_file(yaml_file)
