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

    def test_interval_is_1H(self) -> None:
        cfg = load_config()
        assert cfg.interval == "1H"

    def test_horizons_match_factor_extended_defaults(self) -> None:
        """factor_extended.py hardcoded [8, 24, 72, 168]; config must match."""
        cfg = load_config()
        assert cfg.horizons_h == [8, 24, 72, 168]

    def test_fees_match_setup_bear_values(self) -> None:
        """setup_bear.py hardcoded maker=0.0002, taker=0.00055, slip=0.0005."""
        cfg = load_config()
        assert cfg.fees.maker_rate == pytest.approx(0.0002)
        assert cfg.fees.taker_rate == pytest.approx(0.00055)
        assert cfg.fees.slippage == pytest.approx(0.0005)

    def test_engine_is_set(self) -> None:
        cfg = load_config()
        assert cfg.engine in {"daily", "hourly"}

    def test_data_source_is_set(self) -> None:
        cfg = load_config()
        assert cfg.data_source  # non-empty string


# ─── Unit: minimal valid fixture ─────────────────────────────────────────────

class TestMinimalValidFixture:
    def test_loads_from_fixture(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert isinstance(cfg, ResearchConfig)

    def test_fees_parsed(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert isinstance(cfg.fees, FeesConfig)
        assert cfg.fees.maker_rate == pytest.approx(0.0002)

    def test_horizons_parsed(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert cfg.horizons_h == [8, 24, 72, 168]


# ─── Unit: symbol prefix logic ───────────────────────────────────────────────

class TestSymbolPrefix:
    def test_single_symbol_prefix(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        assert cfg.symbols[0].prefix == "btc_"

    def test_multi_symbol_prefixes(self, tmp_path: Path) -> None:
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
        # symbol_prefixes() returns bare names
        assert cfg.symbol_prefixes() == ["btc", "eth"]

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

    def test_iter_symbols(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(p)
        syms = list(cfg.iter_symbols())
        assert len(syms) == 1
        assert isinstance(syms[0], SymbolConfig)


# ─── Unit: error cases ───────────────────────────────────────────────────────

class TestMissingFile:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="research_config.yaml not found"):
            load_config(missing)


class TestMissingTopLevelKey:
    @pytest.mark.parametrize("missing_key", [
        "symbols", "period", "interval", "data_source", "engine", "fees", "horizons_h"
    ])
    def test_raises_key_error_for_missing_key(self, tmp_path: Path, missing_key: str) -> None:
        import yaml as _yaml

        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base[missing_key]

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_key):
            load_config(p)


class TestMissingSymbolKey:
    @pytest.mark.parametrize("missing_sym_key", ["name", "okx_swap", "ccxt_bybit"])
    def test_raises_key_error_for_missing_symbol_field(
        self, tmp_path: Path, missing_sym_key: str
    ) -> None:
        import yaml as _yaml

        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base["symbols"][0][missing_sym_key]

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_sym_key):
            load_config(p)


class TestMissingFeeKey:
    @pytest.mark.parametrize("missing_fee_key", ["maker_rate", "taker_rate", "slippage"])
    def test_raises_key_error_for_missing_fee_field(
        self, tmp_path: Path, missing_fee_key: str
    ) -> None:
        import yaml as _yaml

        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        del base["fees"][missing_fee_key]

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(KeyError, match=missing_fee_key):
            load_config(p)


class TestTypeErrors:
    def test_symbols_not_list_raises_type_error(self, tmp_path: Path) -> None:
        import yaml as _yaml
        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["symbols"] = "btc"  # string instead of list

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="symbols"):
            load_config(p)

    def test_horizons_not_list_raises_type_error(self, tmp_path: Path) -> None:
        import yaml as _yaml
        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["horizons_h"] = 8  # scalar instead of list

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(TypeError, match="horizons_h"):
            load_config(p)

    def test_empty_symbols_raises_value_error(self, tmp_path: Path) -> None:
        import yaml as _yaml
        base = _yaml.safe_load(textwrap.dedent(MINIMAL_VALID_YAML))
        base["symbols"] = []

        import yaml
        p = tmp_path / "research_config.yaml"
        p.write_text(yaml.dump(base), encoding="utf-8")

        with pytest.raises(ValueError, match="empty"):
            load_config(p)
