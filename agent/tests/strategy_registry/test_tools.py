"""Tests for MCP tools: list_strategies, query_strategies, get_strategy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.skills.strategy_registry.registry import StrategyRegistry
from src.skills.strategy_registry.tools.registry_tools import (
    _MAX_LIMIT,
    _json_error,
    _json_ok,
    _strategy_full,
    _strategy_summary,
    get_strategy,
    list_strategies,
    query_strategies,
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


class TestSerializationHelpers:
    """Tests for _strategy_summary, _strategy_full, _json_ok, _json_error."""

    def test_json_ok_format(self) -> None:
        """_json_ok should produce valid JSON with status=ok."""
        result = _json_ok(items=[], total=5)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 5
        assert data["items"] == []

    def test_json_error_format(self) -> None:
        """_json_error should produce valid JSON with status=error."""
        result = _json_error("something went wrong", detail="bad")
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["error"] == "something went wrong"
        assert data["detail"] == "bad"

    def test_strategy_summary(self, sample_entry) -> None:
        """_strategy_summary should produce a lightweight dict."""
        summary = _strategy_summary(sample_entry)
        assert summary["strategy_id"] == "quantsplaybook_ffscore"
        assert summary["name"] == "HuaTai F-Score + Low PB Value Strategy"
        assert summary["source"] == "builtin"
        assert summary["area"] == "factor"
        assert summary["sharpe"] == 1.151
        assert "description" not in summary  # summary excludes description

    def test_strategy_summary_no_benchmark(self) -> None:
        """_strategy_summary should handle None benchmark_results."""
        from src.skills.strategy_registry.registry.models import StrategyEntry

        entry = StrategyEntry(
            strategy_id="no_bench",
            name="No Benchmark",
            source="sdm",
            area="rotation",
            description="No benchmark.",
            benchmark_results=None,
        )
        summary = _strategy_summary(entry)
        assert summary["sharpe"] is None

    def test_strategy_full(self, sample_entry) -> None:
        """_strategy_full should include all fields."""
        full = _strategy_full(sample_entry)
        assert full["strategy_id"] == "quantsplaybook_ffscore"
        assert "description" in full
        assert "tuning_hints" in full
        assert "benchmark_results" in full


# ---------------------------------------------------------------------------
# list_strategies
# ---------------------------------------------------------------------------


class TestListStrategies:
    """Tests for the list_strategies MCP tool."""

    def test_list_strategies_returns_paginated(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should return paginated JSON results."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 2
        assert data["returned"] == 2
        assert data["offset"] == 0
        assert len(data["items"]) == 2

    def test_list_strategies_limit(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should respect limit parameter."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies(limit=1)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["returned"] == 1
        assert len(data["items"]) == 1

    def test_list_strategies_offset(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should respect offset parameter."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies(limit=1, offset=1)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["returned"] == 1
        assert data["offset"] == 1

    def test_list_strategies_limit_capped(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should cap limit at _MAX_LIMIT (50)."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies(limit=999)
        data = json.loads(result)
        assert data["returned"] <= _MAX_LIMIT

    def test_list_strategies_negative_limit_clamped(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should clamp negative limit to 1."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies(limit=-5)
        data = json.loads(result)
        assert data["returned"] >= 1

    def test_list_strategies_negative_offset_clamped(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should clamp negative offset to 0."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies(offset=-10)
        data = json.loads(result)
        assert data["offset"] == 0

    def test_list_strategies_empty_registry(self, isolated_registry: None) -> None:
        """list_strategies on empty registry should return empty results."""
        result = list_strategies()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_strategies_summary_fields(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies items should have summary fields only."""
        StrategyRegistry.load(temp_seed_dir)
        result = list_strategies()
        data = json.loads(result)
        item = data["items"][0]
        assert "strategy_id" in item
        assert "name" in item
        assert "source" in item
        assert "area" in item
        assert "effective_scenarios" in item
        assert "sharpe" in item
        assert "description" not in item  # full detail excluded


# ---------------------------------------------------------------------------
# query_strategies
# ---------------------------------------------------------------------------


class TestQueryStrategies:
    """Tests for the query_strategies MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """Load fixture data before each query test."""
        StrategyRegistry.load(temp_seed_dir)

    def test_query_with_valid_scenario(self) -> None:
        """query_strategies with a valid scenario should return matching results."""
        result = query_strategies(scenario="bear_market_defense")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 2

    def test_query_with_invalid_scenario_returns_error(self) -> None:
        """query_strategies with an invalid scenario should return an error dict."""
        result = query_strategies(scenario="nonexistent_scenario")
        data = json.loads(result)
        assert data["status"] == "error"
        assert "invalid scenario" in data["error"]
        assert "valid_scenarios" in data

    def test_query_with_source_filter(self) -> None:
        """query_strategies with source='builtin' should return only builtin."""
        result = query_strategies(source="builtin")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 2

    def test_query_with_min_sharpe(self) -> None:
        """query_strategies with min_sharpe should filter results."""
        result = query_strategies(min_sharpe=1.0)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 1

    def test_query_with_combined_filters(self) -> None:
        """query_strategies with multiple filters should work."""
        result = query_strategies(
            scenario="bear_market_defense",
            source="builtin",
            min_sharpe=0.5,
        )
        data = json.loads(result)
        assert data["status"] == "ok"

    def test_query_pagination(self) -> None:
        """query_strategies should support limit and offset."""
        result = query_strategies(limit=1, offset=0)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["returned"] == 1

    def test_query_has_filters_in_response(self) -> None:
        """query_strategies response should include the filters used."""
        result = query_strategies(scenario="bear_market_defense", source="builtin")
        data = json.loads(result)
        assert data["filters"]["scenario"] == "bear_market_defense"
        assert data["filters"]["source"] == "builtin"

    def test_query_empty_registry(self) -> None:
        """query_strategies on empty registry should return empty results."""
        # autouse _setup loads data; clear it for this test
        StrategyRegistry._builtin = {}
        result = query_strategies()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total"] == 0

    def test_query_limit_capped(self) -> None:
        """query_strategies should cap limit at _MAX_LIMIT."""
        result = query_strategies(limit=999)
        data = json.loads(result)
        assert data["returned"] <= _MAX_LIMIT


# ---------------------------------------------------------------------------
# get_strategy
# ---------------------------------------------------------------------------


class TestGetStrategy:
    """Tests for the get_strategy MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """Load fixture data before each get test."""
        StrategyRegistry.load(temp_seed_dir)

    def test_get_strategy_valid_id(self) -> None:
        """get_strategy with a valid ID should return full details."""
        result = get_strategy("quantsplaybook_ffscore")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["strategy"]["strategy_id"] == "quantsplaybook_ffscore"
        assert "description" in data["strategy"]
        assert "tuning_hints" in data["strategy"]
        assert "benchmark_results" in data["strategy"]

    def test_get_strategy_nonexistent_id(self) -> None:
        """get_strategy with a non-existent ID should return error dict."""
        result = get_strategy("nonexistent_id")
        data = json.loads(result)
        assert data["status"] == "error"
        assert "not found" in data["error"]
        assert data["strategy_id"] == "nonexistent_id"

    def test_get_strategy_empty_registry(self, isolated_registry: None) -> None:
        """get_strategy on empty registry should return error."""
        result = get_strategy("any_id")
        data = json.loads(result)
        assert data["status"] == "error"
        assert "not found" in data["error"]

    def test_get_strategy_full_fields(self) -> None:
        """get_strategy response should include all StrategyEntry fields."""
        result = get_strategy("quantsplaybook_ffscore")
        data = json.loads(result)
        strategy = data["strategy"]
        expected_fields = {
            "strategy_id", "name", "source", "area", "description",
            "effective_scenarios", "failure_scenarios", "tuning_hints",
            "benchmark_results", "implementation", "status",
        }
        assert set(strategy.keys()) == expected_fields


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling in MCP tools."""

    def test_list_strategies_handles_exception(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """list_strategies should return error JSON on exception."""
        StrategyRegistry.load(temp_seed_dir)
        with patch.object(StrategyRegistry, "list", side_effect=RuntimeError("boom")):
            result = list_strategies()
            data = json.loads(result)
            assert data["status"] == "error"
            assert "boom" in data["error"]

    def test_query_strategies_handles_exception(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """query_strategies should return error JSON on exception."""
        StrategyRegistry.load(temp_seed_dir)
        with patch.object(StrategyRegistry, "query", side_effect=RuntimeError("boom")):
            result = query_strategies()
            data = json.loads(result)
            assert data["status"] == "error"

    def test_get_strategy_handles_exception(self, isolated_registry: None, temp_seed_dir: Path) -> None:
        """get_strategy should return error JSON on exception."""
        StrategyRegistry.load(temp_seed_dir)
        with patch.object(StrategyRegistry, "get", side_effect=RuntimeError("boom")):
            result = get_strategy("quantsplaybook_ffscore")
            data = json.loads(result)
            assert data["status"] == "error"
