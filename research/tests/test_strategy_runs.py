"""
Tests for research/pipeline/strategy_runs.py

TDD: these tests were written BEFORE the implementation.

Runs against:
  - The real research/strategy_runs.json  (integration smoke test)
  - In-memory fixture dicts               (unit tests; no disk I/O beyond tmp)

Run from the research/ directory:
    cd research && python -m pytest tests/test_strategy_runs.py -v
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from pipeline.strategy_runs import (
    StrategyRunsEntry,
    StrategyRunsMap,
    load_strategy_runs,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def write_json(tmp_path: Path, data: object, name: str = "strategy_runs.json") -> Path:
    """Write JSON fixture to a temp file and return its path."""
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ─── Minimal valid fixture ────────────────────────────────────────────────────

MINIMAL_VALID_ENTRY = {
    "symbol": "BTC-USDT-SWAP",
    "spec_yaml": "research/strategies/strategy_S1.yaml",
    "base_run": "btc_s1_base",
    "regime_runs": {"bull": "btc_s1_bull", "bear": "btc_s1_bear", "neutral": "btc_s1_neutral"},
    "stress_runs": {"3x_fees": "btc_s1_base_stress"},
    "oos_runs": ["btc_s1_oos_2023"],
    "sweep_run": "btc_s1_sweep",
}

MINIMAL_VALID_MAP = {"btc_s1_multifactor_contrarian": MINIMAL_VALID_ENTRY}


# ─── Integration: real strategy_runs.json ────────────────────────────────────

class TestRealStrategyRuns:
    """Load the actual research/strategy_runs.json that ships with the repo."""

    def test_loads_without_error(self) -> None:
        result = load_strategy_runs()
        assert isinstance(result, StrategyRunsMap)

    def test_has_four_strategies(self) -> None:
        result = load_strategy_runs()
        assert len(result.entries) == 4, (
            f"Expected 4 strategy entries (S1-S4), got {len(result.entries)}: "
            f"{sorted(result.entries.keys())}"
        )

    def test_all_strategy_ids_have_btc_prefix(self) -> None:
        result = load_strategy_runs()
        for sid in result.entries:
            assert sid.startswith("btc_"), (
                f"strategy_id '{sid}' must start with 'btc_' (coin prefix)"
            )

    def test_all_entries_are_strategy_runs_entry(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert isinstance(entry, StrategyRunsEntry), (
                f"Entry for '{sid}' must be a StrategyRunsEntry"
            )

    def test_all_entries_have_btc_usdt_swap_symbol(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert entry.symbol == "BTC-USDT-SWAP", (
                f"Entry '{sid}' symbol must be 'BTC-USDT-SWAP', got '{entry.symbol}'"
            )

    def test_spec_yaml_paths_point_to_existing_files(self) -> None:
        result = load_strategy_runs()
        # Resolve relative to repo root (two parents above pipeline/)
        repo_root = Path(__file__).resolve().parents[2]
        for sid, entry in result.entries.items():
            spec_path = repo_root / entry.spec_yaml
            assert spec_path.exists(), (
                f"Entry '{sid}': spec_yaml '{entry.spec_yaml}' does not exist at {spec_path}"
            )

    def test_regime_runs_has_expected_keys(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert isinstance(entry.regime_runs, types.MappingProxyType), (
                f"Entry '{sid}' regime_runs must be a MappingProxyType"
            )

    def test_stress_runs_has_entries(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert isinstance(entry.stress_runs, types.MappingProxyType), (
                f"Entry '{sid}' stress_runs must be a MappingProxyType"
            )

    def test_oos_runs_is_tuple(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert isinstance(entry.oos_runs, tuple), (
                f"Entry '{sid}' oos_runs must be a tuple"
            )

    def test_sweep_run_is_str_or_none(self) -> None:
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            assert entry.sweep_run is None or isinstance(entry.sweep_run, str), (
                f"Entry '{sid}' sweep_run must be str or null"
            )

    def test_run_names_carry_coin_prefix(self) -> None:
        """All non-null run names must start with btc_ (coin prefix convention)."""
        result = load_strategy_runs()
        for sid, entry in result.entries.items():
            for run_name in [entry.base_run, entry.sweep_run]:
                if run_name is not None:
                    assert run_name.startswith("btc_"), (
                        f"Entry '{sid}': run name '{run_name}' must start with 'btc_'"
                    )
            for label, run_name in entry.regime_runs.items():
                assert run_name.startswith("btc_"), (
                    f"Entry '{sid}': regime_runs['{label}'] = '{run_name}' must start with 'btc_'"
                )
            for label, run_name in entry.stress_runs.items():
                assert run_name.startswith("btc_"), (
                    f"Entry '{sid}': stress_runs['{label}'] = '{run_name}' must start with 'btc_'"
                )
            for run_name in entry.oos_runs:
                assert run_name.startswith("btc_"), (
                    f"Entry '{sid}': oos_runs contains '{run_name}' which must start with 'btc_'"
                )


# ─── Unit: valid fixture load ─────────────────────────────────────────────────

class TestValidFixture:
    def test_loads_minimal_valid_map(self, tmp_path: Path) -> None:
        p = write_json(tmp_path, MINIMAL_VALID_MAP)
        result = load_strategy_runs(p)
        assert isinstance(result, StrategyRunsMap)

    def test_entry_fields_parsed_correctly(self, tmp_path: Path) -> None:
        p = write_json(tmp_path, MINIMAL_VALID_MAP)
        result = load_strategy_runs(p)
        entry = result.entries["btc_s1_multifactor_contrarian"]
        assert entry.symbol == "BTC-USDT-SWAP"
        assert entry.spec_yaml == "research/strategies/strategy_S1.yaml"
        assert entry.base_run == "btc_s1_base"
        assert entry.regime_runs == {"bull": "btc_s1_bull", "bear": "btc_s1_bear", "neutral": "btc_s1_neutral"}
        assert entry.stress_runs == {"3x_fees": "btc_s1_base_stress"}
        assert entry.oos_runs == ("btc_s1_oos_2023",)
        assert entry.sweep_run == "btc_s1_sweep"

    def test_sweep_run_null_is_allowed(self, tmp_path: Path) -> None:
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "sweep_run": None,
            }
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert result.entries["btc_s1_test"].sweep_run is None

    def test_empty_stress_runs_allowed(self, tmp_path: Path) -> None:
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "stress_runs": {},
            }
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert result.entries["btc_s1_test"].stress_runs == {}

    def test_empty_oos_runs_allowed(self, tmp_path: Path) -> None:
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "oos_runs": [],
            }
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert result.entries["btc_s1_test"].oos_runs == ()

    def test_multiple_entries_parsed(self, tmp_path: Path) -> None:
        entry2 = {**MINIMAL_VALID_ENTRY, "spec_yaml": "research/strategies/strategy_S2.yaml"}
        data = {
            "btc_s1_multifactor_contrarian": MINIMAL_VALID_ENTRY,
            "btc_s2_funding_mean_reversion": entry2,
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert len(result.entries) == 2
        assert "btc_s1_multifactor_contrarian" in result.entries
        assert "btc_s2_funding_mean_reversion" in result.entries

    def test_returns_immutable_entries(self, tmp_path: Path) -> None:
        """All mutable containers must be genuinely immutable after loading."""
        p = write_json(tmp_path, MINIMAL_VALID_MAP)
        result = load_strategy_runs(p)
        entry = result.entries["btc_s1_multifactor_contrarian"]

        # Frozen dataclass field — cannot reassign
        with pytest.raises((AttributeError, TypeError)):
            entry.symbol = "MODIFIED"  # type: ignore[misc]

        # oos_runs is a tuple — cannot append
        with pytest.raises((AttributeError, TypeError)):
            entry.oos_runs.append("new_run")  # type: ignore[union-attr]

        # regime_runs is a MappingProxyType — cannot set items
        with pytest.raises(TypeError):
            entry.regime_runs["x"] = "y"  # type: ignore[index]

        # stress_runs is a MappingProxyType — cannot set items
        with pytest.raises(TypeError):
            entry.stress_runs["x"] = "y"  # type: ignore[index]

        # entries top-level mapping is a MappingProxyType — cannot set items
        with pytest.raises(TypeError):
            result.entries["fake"] = entry  # type: ignore[index]


# ─── Unit: missing required key → clear error naming strategy_id + field ─────

class TestMissingRequiredKey:
    @pytest.mark.parametrize("missing_key", [
        "symbol",
        "spec_yaml",
        "base_run",
        "regime_runs",
        "stress_runs",
        "oos_runs",
        "sweep_run",
    ])
    def test_raises_key_error_naming_strategy_id_and_field(
        self, tmp_path: Path, missing_key: str
    ) -> None:
        entry = {**MINIMAL_VALID_ENTRY}
        del entry[missing_key]
        data = {"btc_s1_test": entry}
        p = write_json(tmp_path, data)

        with pytest.raises(KeyError) as exc_info:
            load_strategy_runs(p)

        msg = str(exc_info.value)
        assert "btc_s1_test" in msg, (
            f"Error message must name the offending strategy_id 'btc_s1_test', got: {msg}"
        )
        assert missing_key in msg, (
            f"Error message must name the missing field '{missing_key}', got: {msg}"
        )


# ─── Unit: wrong type → clear error naming strategy_id + field ───────────────

class TestWrongType:
    def test_symbol_not_string_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "symbol": 123}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "symbol" in msg

    def test_spec_yaml_not_string_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "spec_yaml": 42}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "spec_yaml" in msg

    def test_base_run_not_string_or_null_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "base_run": 99}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "base_run" in msg

    def test_regime_runs_not_dict_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "regime_runs": ["bull"]}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "regime_runs" in msg

    def test_stress_runs_not_dict_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "stress_runs": "3x"}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "stress_runs" in msg

    def test_oos_runs_not_list_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "oos_runs": "btc_s1_oos"}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "oos_runs" in msg

    def test_sweep_run_not_string_or_null_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": {**MINIMAL_VALID_ENTRY, "sweep_run": 7}}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "sweep_run" in msg

    def test_root_not_dict_raises_type_error(self, tmp_path: Path) -> None:
        p = write_json(tmp_path, ["btc_s1_test"])
        with pytest.raises(TypeError, match="mapping"):
            load_strategy_runs(p)

    def test_entry_not_dict_raises_type_error(self, tmp_path: Path) -> None:
        data = {"btc_s1_test": "bad_entry"}
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg

    def test_regime_runs_value_not_string_raises_type_error(self, tmp_path: Path) -> None:
        """regime_runs dict values must be strings."""
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "regime_runs": {"bull": 123, "bear": "btc_s1_bear", "neutral": "btc_s1_neutral"},
            }
        }
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "regime_runs" in msg

    def test_oos_runs_element_not_string_raises_type_error(self, tmp_path: Path) -> None:
        """oos_runs list elements must be strings."""
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "oos_runs": ["btc_s1_oos_2023", 99],
            }
        }
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "oos_runs" in msg

    def test_stress_runs_value_not_string_raises_type_error(self, tmp_path: Path) -> None:
        """stress_runs dict values must be strings — mirrors regime_runs coverage."""
        data = {
            "btc_s1_test": {
                **MINIMAL_VALID_ENTRY,
                "stress_runs": {"3x_fees": 42},
            }
        }
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "btc_s1_test" in msg
        assert "stress_runs" in msg


# ─── Unit: file not found ─────────────────────────────────────────────────────

class TestFileNotFound:
    def test_raises_file_not_found_for_missing_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="strategy_runs.json"):
            load_strategy_runs(missing)


# ─── Unit: multi-symbol prefix parsing ───────────────────────────────────────

class TestMultiSymbolPrefixes:
    def test_btc_and_eth_entries_coexist(self, tmp_path: Path) -> None:
        """Multi-symbol: btc_ and eth_ prefixed strategy_ids must both load cleanly."""
        eth_entry = {
            **MINIMAL_VALID_ENTRY,
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_S1.yaml",
            "base_run": "eth_s1_base",
            "regime_runs": {"bull": "eth_s1_bull", "bear": "eth_s1_bear", "neutral": "eth_s1_neutral"},
            "stress_runs": {"3x_fees": "eth_s1_base_stress"},
            "oos_runs": ["eth_s1_oos_2023"],
            "sweep_run": "eth_s1_sweep",
        }
        data = {
            "btc_s1_multifactor_contrarian": MINIMAL_VALID_ENTRY,
            "eth_s1_multifactor_contrarian": eth_entry,
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert len(result.entries) == 2
        assert result.entries["btc_s1_multifactor_contrarian"].symbol == "BTC-USDT-SWAP"
        assert result.entries["eth_s1_multifactor_contrarian"].symbol == "ETH-USDT-SWAP"

    def test_strategy_ids_are_dict_keys_verbatim(self, tmp_path: Path) -> None:
        """strategy_id is just the JSON key — loader does not transform it."""
        data = {"eth_s2_funding_mean_reversion": MINIMAL_VALID_ENTRY}
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert "eth_s2_funding_mean_reversion" in result.entries


# ─── Unit: _comment skip is exact-match only ─────────────────────────────────

class TestCommentSkip:
    def test_comment_key_is_skipped(self, tmp_path: Path) -> None:
        """The exact key '_comment' is silently skipped."""
        data = {
            "_comment": "This file maps strategy IDs to run directories.",
            "btc_s1_multifactor_contrarian": MINIMAL_VALID_ENTRY,
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert "_comment" not in result.entries
        assert len(result.entries) == 1

    def test_underscore_prefixed_strategy_id_is_not_dropped(self, tmp_path: Path) -> None:
        """A strategy_id like '_archived' must NOT be silently discarded.
        It should be loaded as a normal entry (since its structure is valid)."""
        data = {
            "_archived_strategy": MINIMAL_VALID_ENTRY,
            "btc_s1_multifactor_contrarian": MINIMAL_VALID_ENTRY,
        }
        p = write_json(tmp_path, data)
        result = load_strategy_runs(p)
        assert "_archived_strategy" in result.entries, (
            "strategy_id '_archived_strategy' must be loaded, not silently dropped"
        )
        assert len(result.entries) == 2

    def test_underscore_prefixed_with_invalid_structure_raises(self, tmp_path: Path) -> None:
        """A strategy_id like '_archived' with bad structure must raise, not silently vanish."""
        data = {
            "_archived_strategy": "not_a_dict",
        }
        p = write_json(tmp_path, data)
        with pytest.raises(TypeError) as exc_info:
            load_strategy_runs(p)
        msg = str(exc_info.value)
        assert "_archived_strategy" in msg
