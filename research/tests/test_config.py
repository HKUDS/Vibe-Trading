"""
Tests for research/pipeline/config.py

Runs against:
  - The real research/research_config.yaml  (integration smoke test)
  - In-memory fixture YAML strings          (unit tests; no network, no file I/O beyond tmp)

All tests are pure-Python; no mocks, no monkeypatching of the loader itself.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

# We run pytest from research/ so pipeline.config is importable directly.
from pipeline.config import (
    FeesConfig,
    ResearchConfig,
    SymbolConfig,
    load_config,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML fixture to a temp file and return its path."""
    p = tmp_path / "research_config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


MINIMAL_VALID_YAML = """\
    symbols:
      - name: btc
        okx_swap: "BTC-USDT-SWAP"
        ccxt_bybit: "BTC/USDT:USDT"
    period: 730
    interval: "1H"
    data_source: okx
    engine: daily
    fees:
      maker_rate: 0.0002
      taker_rate: 0.00055
      slippage: 0.0005
    horizons_h: [8, 24, 72, 168]
"""


# ─── Integration: real config file ───────────────────────────────────────────

class TestRealConfig:
    """Load the actual research_config.yaml that ships with the repo."""

    def test_loads_without_error(self) -> None:
        cfg = load_config()
        assert isinstance(cfg, ResearchConfig)

    def test_symbols_is_non_empty_list(self) -> None:
        cfg = load_config()
        assert len(cfg.symbols) >= 1
        for sym in cfg.symbols:
            assert isinstance(sym, SymbolConfig)

    def test_btc_present_with_correct_tickers(self) -> None:
        cfg = load_config()
        btc = next((s for s in cfg.symbols if s.name == "btc"), None)
        assert btc is not None, "BTC symbol must be present in research_config.yaml"
        assert btc.okx_swap == "BTC-USDT-SWAP"
        assert btc.ccxt_bybit == "BTC/USDT:USDT"

    def test_period_is_positive_int(self) -> None:
        cfg = load_config()
        assert isinstance(cfg.period, int)
        assert cfg.period > 0

    def test_horizons_all_positive(self) -> None:
        cfg = load_config()
        assert all(h > 0 for h in cfg.horizons_h)

    def test_horizons_is_non_empty(self) -> None:
        cfg = load_config()
        assert len(cfg.horizons_h) >= 1

    def test_engine_is_set(self) -> None:
        cfg = load_config()
        assert cfg.engine in {"daily", "hourly"}

    def test_data_source_is_set(self) -> None:
        cfg = load_config()
        assert cfg.data_source  # non-empty string

    def test_fees_are_non_negative(self) -> None:
        cfg = load_config()
        assert cfg.fees.maker_rate >= 0
        assert cfg.fees.taker_rate >= 0
        assert cfg.fees.slippage >= 0

    def test_symbols_field_is_tuple(self) -> None:
        cfg = load_config()
        assert isinstance(cfg.symbols, tuple)

    def test_horizons_h_field_is_tuple(self) -> None:
        cfg = load_config()
        assert isinstance(cfg.horizons_h, tuple)


# ─── Integration: exact-value pins (intentionally brittle) ───────────────────

class TestLegacyCompatibility:
    """
    WARNING: These tests intentionally pin exact values from research_config.yaml
    against downstream hardcoded constants in factor_extended.py and setup_bear.py.
    They WILL break on any intentional YAML edit to these values, and that is
    expected — update both this class and the downstream file when changing the values.
    """

    def test_interval_is_1H(self) -> None:
        cfg = load_config()
        assert cfg.interval == "1H"

    def test_horizons_match_factor_extended_defaults(self) -> None:
        """factor_extended.py hardcoded [8, 24, 72, 168]; config must match."""
        cfg = load_config()
        assert list(cfg.horizons_h) == [8, 24, 72, 168]

    def test_fees_match_setup_bear_values(self) -> None:
        """setup_bear.py hardcoded maker=0.0002, taker=0.00055, slip=0.0005."""
        cfg = load_config()
        assert cfg.fees.maker_rate == pytest.approx(0.0002)
        assert cfg.fees.taker_rate == pytest.approx(0.00055)
        assert cfg.fees.slippage == pytest.approx(0.0005)


# ─── Unit: minimal valid fixture ─────────────────────────────────────────────

@pytest.fixture
def minimal_cfg(tmp_path: Path) -> ResearchConfig:
    """Load MINIMAL_VALID_YAML once; shared by TestMinimalValidFixture methods."""
    p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
    return load_config(p)


class TestMinimalValidFixture:
    def test_loads_from_fixture(self, minimal_cfg: ResearchConfig) -> None:
        assert isinstance(minimal_cfg, ResearchConfig)

    def test_fees_parsed(self, minimal_cfg: ResearchConfig) -> None:
        assert isinstance(minimal_cfg.fees, FeesConfig)
        assert minimal_cfg.fees.maker_rate == pytest.approx(0.0002)

    def test_horizons_parsed(self, minimal_cfg: ResearchConfig) -> None:
        assert list(minimal_cfg.horizons_h) == [8, 24, 72, 168]

    def test_symbols_is_tuple(self, minimal_cfg: ResearchConfig) -> None:
        assert isinstance(minimal_cfg.symbols, tuple)

    def test_horizons_h_is_tuple(self, minimal_cfg: ResearchConfig) -> None:
        assert isinstance(minimal_cfg.horizons_h, tuple)

    def test_symbols_tuple_immutable(self, minimal_cfg: ResearchConfig) -> None:
        """Appending to cfg.symbols must fail (it is a tuple, not a list)."""
        with pytest.raises(AttributeError):
            minimal_cfg.symbols.append(None)  # type: ignore[attr-defined]

    def test_horizons_tuple_immutable(self, minimal_cfg: ResearchConfig) -> None:
        """Appending to cfg.horizons_h must fail (it is a tuple, not a list)."""
        with pytest.raises(AttributeError):
            minimal_cfg.horizons_h.append(999)  # type: ignore[attr-defined]


# ─── Unit: symbol prefix / name logic ────────────────────────────────────────

class TestSymbolPrefix:
    def test_single_symbol_prefix(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert cfg.symbols[0].prefix == "btc_"

    def test_multi_symbol_names(self, tmp_path: Path) -> None:
        yaml_content = """\
            symbols:
              - name: btc
                okx_swap: "BTC-USDT-SWAP"
                ccxt_bybit: "BTC/USDT:USDT"
              - name: eth
                okx_swap: "ETH-USDT-SWAP"
                ccxt_bybit: "ETH/USDT:USDT"
            period: 730
            interval: "1H"
            data_source: okx
            engine: daily
            fees:
              maker_rate: 0.0002
              taker_rate: 0.00055
              slippage: 0.0005
            horizons_h: [8, 24, 72, 168]
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(p)
        assert len(cfg.symbols) == 2
        prefixes = [s.prefix for s in cfg.symbols]
        assert prefixes == ["btc_", "eth_"]
        # symbol_names() returns bare short names
        assert cfg.symbol_names() == ["btc", "eth"]
        # symbol_prefix_list() returns underscore-suffixed prefixes
        assert cfg.symbol_prefix_list() == ["btc_", "eth_"]

    def test_name_forced_lowercase(self, tmp_path: Path) -> None:
        yaml_content = """\
            symbols:
              - name: BTC
                okx_swap: "BTC-USDT-SWAP"
                ccxt_bybit: "BTC/USDT:USDT"
            period: 730
            interval: "1H"
            data_source: okx
            engine: daily
            fees:
              maker_rate: 0.0002
              taker_rate: 0.00055
              slippage: 0.0005
            horizons_h: [8, 24, 72, 168]
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(p)
        assert cfg.symbols[0].name == "btc"
        assert cfg.symbols[0].prefix == "btc_"

    def test_symbol_names_method(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert cfg.symbol_names() == ["btc"]

    def test_symbol_prefix_list_method(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert cfg.symbol_prefix_list() == ["btc_"]


# ─── Unit: error cases ───────────────────────────────────────────────────────

class TestMissingFile:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="research_config.yaml not found"):
            load_config(missing)


class TestEmptyOrMalformedYaml:
    def test_empty_yaml_raises_type_error(self, tmp_path: Path) -> None:
        """Empty YAML file produces None from safe_load; must raise TypeError."""
        p = tmp_path / "research_config.yaml"
        p.write_text("", encoding="utf-8")
        with pytest.raises(TypeError, match="YAML mapping"):
            load_config(p)

    def test_list_root_yaml_raises_type_error(self, tmp_path: Path) -> None:
        """List-rooted YAML must raise TypeError, not AttributeError."""
        p = tmp_path / "research_config.yaml"
        p.write_text("- foo\n- bar\n", encoding="utf-8")
        with pytest.raises(TypeError, match="YAML mapping"):
            load_config(p)

    def test_scalar_root_yaml_raises_type_error(self, tmp_path: Path) -> None:
        """Scalar YAML must raise TypeError."""
        p = tmp_path / "research_config.yaml"
        p.write_text("just_a_string\n", encoding="utf-8")
        with pytest.raises(TypeError, match="YAML mapping"):
            load_config(p)


class TestMissingTopLevelKey:
    @pytest.mark.parametrize("missing_key", [
        "symbols", "period", "interval", "data_source", "engine", "fees", "horizons_h"
    ])
    def test_raises_key_error_for_missing_key(self, tmp_path: Path, missing_key: str) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base[missing_key]

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_key):
            load_config(p)


class TestMissingSymbolKey:
    @pytest.mark.parametrize("missing_sym_key", ["name", "okx_swap", "ccxt_bybit"])
    def test_raises_key_error_for_missing_symbol_field(
        self, tmp_path: Path, missing_sym_key: str
    ) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base["symbols"][0][missing_sym_key]

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_sym_key):
            load_config(p)


class TestMissingFeeKey:
    @pytest.mark.parametrize("missing_fee_key", ["maker_rate", "taker_rate", "slippage"])
    def test_raises_key_error_for_missing_fee_field(
        self, tmp_path: Path, missing_fee_key: str
    ) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base["fees"][missing_fee_key]

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_fee_key):
            load_config(p)


class TestTypeErrors:
    def test_symbols_not_list_raises_type_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["symbols"] = "btc"  # string instead of list

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="symbols"):
            load_config(p)

    def test_horizons_not_list_raises_type_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["horizons_h"] = 8  # scalar instead of list

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="horizons_h"):
            load_config(p)

    def test_empty_symbols_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["symbols"] = []

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="empty"):
            load_config(p)

    def test_fees_is_scalar_raises_type_error(self, tmp_path: Path) -> None:
        """fees: scalar string must raise TypeError, not AttributeError."""
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["fees"] = "cheap"

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="fees"):
            load_config(p)

    def test_symbol_entry_is_string_raises_type_error(self, tmp_path: Path) -> None:
        """A symbol entry that is a plain string must raise TypeError, not AttributeError."""
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["symbols"] = ["btc"]  # string element instead of mapping

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="symbols\\[0\\]"):
            load_config(p)


class TestRangeValidation:
    def test_negative_period_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["period"] = -1

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="period"):
            load_config(p)

    def test_zero_period_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["period"] = 0

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="period"):
            load_config(p)

    def test_negative_horizon_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["horizons_h"] = [8, -24, 72]

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="horizons_h"):
            load_config(p)

    def test_zero_horizon_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["horizons_h"] = [0, 24]

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="horizons_h"):
            load_config(p)

    def test_negative_maker_rate_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["fees"]["maker_rate"] = -0.001

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="maker_rate"):
            load_config(p)

    def test_negative_taker_rate_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["fees"]["taker_rate"] = -0.001

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="taker_rate"):
            load_config(p)

    def test_negative_slippage_raises_value_error(self, tmp_path: Path) -> None:
        base = yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["fees"]["slippage"] = -0.001

        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="slippage"):
            load_config(p)


class TestDuplicateSymbols:
    def test_duplicate_symbol_names_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            symbols:
              - name: btc
                okx_swap: "BTC-USDT-SWAP"
                ccxt_bybit: "BTC/USDT:USDT"
              - name: btc
                okx_swap: "BTC-USDT-SWAP"
                ccxt_bybit: "BTC/USDT:USDT"
            period: 730
            interval: "1H"
            data_source: okx
            engine: daily
            fees:
              maker_rate: 0.0002
              taker_rate: 0.00055
              slippage: 0.0005
            horizons_h: [8, 24, 72, 168]
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            load_config(p)
