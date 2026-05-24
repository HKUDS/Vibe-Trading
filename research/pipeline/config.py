"""
research/pipeline/config.py
────────────────────────────
Loads and validates research/research_config.yaml.

Every stage runner should import this module and call load_config() to obtain
a ResearchConfig object instead of hardcoding parameters.

Usage
-----
    from pipeline.config import load_config

    cfg = load_config()
    for sym in cfg.symbols:
        prefix = sym.prefix          # e.g. "btc_"
        okx    = sym.okx_swap        # e.g. "BTC-USDT-SWAP"
        bybit  = sym.ccxt_bybit      # e.g. "BTC/USDT:USDT"
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml

# The YAML file lives at  <repo-root>/research/research_config.yaml.
# This module is at       <repo-root>/research/pipeline/config.py.
# So repo root = two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "research" / "research_config.yaml"

# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class SymbolConfig:
    """Per-symbol seed parameters."""

    name: str          # short lowercase name used as filename prefix (e.g. "btc")
    okx_swap: str      # OKX perpetual swap ticker (e.g. "BTC-USDT-SWAP")
    ccxt_bybit: str    # ccxt-unified Bybit ticker  (e.g. "BTC/USDT:USDT")

    @property
    def prefix(self) -> str:
        """Filename/directory prefix, guaranteed lowercase with trailing underscore (e.g. 'btc_')."""
        return self.name + "_"


@dataclasses.dataclass(frozen=True)
class FeesConfig:
    """Transaction-cost seed values written into run config.json by setup_*.py."""

    maker_rate: float
    taker_rate: float
    slippage: float


@dataclasses.dataclass(frozen=True)
class ResearchConfig:
    """Top-level config object returned by load_config()."""

    symbols: tuple[SymbolConfig, ...]
    period: int              # days
    interval: str            # candle bar string, e.g. "1H"
    data_source: str         # e.g. "okx"
    engine: str              # backtest engine mode, e.g. "daily"
    fees: FeesConfig
    horizons_h: tuple[int, ...]    # forward-return horizons in hours
    discovery_cache_days: int = 7  # stage-0 cache TTL in days (0 = disabled)

    # ── Convenience helpers ──────────────────────────────────────────────────

    def symbol_names(self) -> list[str]:
        """Return the short lowercase name for each symbol (e.g. ['btc', 'eth'])."""
        return [s.name for s in self.symbols]

    def symbol_prefix_list(self) -> list[str]:
        """Return the underscore-suffixed prefix for each symbol (e.g. ['btc_', 'eth_'])."""
        return [s.prefix for s in self.symbols]


# ─── Required keys (top-level) ────────────────────────────────────────────────

_REQUIRED_TOP_LEVEL = {"symbols", "period", "interval", "data_source", "engine", "fees", "horizons_h"}
_REQUIRED_SYMBOL_KEYS = {"name", "okx_swap", "ccxt_bybit"}
_REQUIRED_FEE_KEYS = {"maker_rate", "taker_rate", "slippage"}


# ─── Loader ──────────────────────────────────────────────────────────────────

def load_config(path: Path | str | None = None) -> ResearchConfig:
    """Load and validate research_config.yaml, returning a ResearchConfig.

    Parameters
    ----------
    path:
        Path to the YAML file.  Defaults to
        ``<repo-root>/research/research_config.yaml``.
        Pass an explicit path in tests or CI to load fixture configs.

    Raises
    ------
    FileNotFoundError
        If the YAML file does not exist at the resolved path.
    TypeError
        If the YAML root is not a mapping, or a required block has the wrong type.
    KeyError
        If a required top-level key, symbol key, or fee key is absent.
    ValueError
        If a numeric field is out of range, or duplicate symbol names are found.
    """
    resolved = Path(path) if path is not None else _DEFAULT_CONFIG_PATH

    if not resolved.exists():
        raise FileNotFoundError(
            f"research_config.yaml not found at: {resolved}\n"
            "Create the file or pass an explicit path to load_config()."
        )

    with resolved.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # C1: guard against empty or non-mapping YAML
    if not isinstance(raw, dict):
        raise TypeError(
            f"research_config.yaml must be a YAML mapping at the top level, got {type(raw).__name__}."
        )

    # ── Top-level key validation ─────────────────────────────────────────────
    missing_top = _REQUIRED_TOP_LEVEL - raw.keys()
    if missing_top:
        raise KeyError(
            f"research_config.yaml is missing required key(s): {sorted(missing_top)}"
        )

    # ── symbols ──────────────────────────────────────────────────────────────
    raw_symbols = raw["symbols"]
    if not isinstance(raw_symbols, list):
        raise TypeError("'symbols' in research_config.yaml must be a list.")
    if len(raw_symbols) == 0:
        raise ValueError("'symbols' list must not be empty.")

    symbol_configs: list[SymbolConfig] = []
    for i, entry in enumerate(raw_symbols):
        # I1: guard against non-mapping symbol entries
        if not isinstance(entry, dict):
            raise TypeError(
                f"symbols[{i}] must be a YAML mapping, got {type(entry).__name__}."
            )
        missing_sym = _REQUIRED_SYMBOL_KEYS - entry.keys()
        if missing_sym:
            raise KeyError(
                f"symbols[{i}] is missing required key(s): {sorted(missing_sym)}"
            )
        symbol_configs.append(
            SymbolConfig(
                name=str(entry["name"]).lower(),
                okx_swap=str(entry["okx_swap"]),
                ccxt_bybit=str(entry["ccxt_bybit"]),
            )
        )

    # I3: duplicate symbol names
    names = [s.name for s in symbol_configs]
    seen: set[str] = set()
    duplicates = [n for n in names if n in seen or seen.add(n)]  # type: ignore[func-returns-value]
    if duplicates:
        raise ValueError(
            f"Duplicate symbol name(s) found in research_config.yaml: {sorted(set(duplicates))}"
        )

    # ── fees ─────────────────────────────────────────────────────────────────
    raw_fees = raw["fees"]
    # I1: guard against non-mapping fees block
    if not isinstance(raw_fees, dict):
        raise TypeError(
            f"'fees' in research_config.yaml must be a mapping, got {type(raw_fees).__name__}."
        )
    missing_fees = _REQUIRED_FEE_KEYS - raw_fees.keys()
    if missing_fees:
        raise KeyError(
            f"fees block is missing required key(s): {sorted(missing_fees)}"
        )

    maker_rate = float(raw_fees["maker_rate"])
    taker_rate = float(raw_fees["taker_rate"])
    slippage = float(raw_fees["slippage"])

    # I2: range validation for fee rates
    if maker_rate < 0:
        raise ValueError(f"fees.maker_rate must be >= 0, got {maker_rate}.")
    if taker_rate < 0:
        raise ValueError(f"fees.taker_rate must be >= 0, got {taker_rate}.")
    if slippage < 0:
        raise ValueError(f"fees.slippage must be >= 0, got {slippage}.")

    fees = FeesConfig(
        maker_rate=maker_rate,
        taker_rate=taker_rate,
        slippage=slippage,
    )

    # ── horizons_h ───────────────────────────────────────────────────────────
    raw_horizons = raw["horizons_h"]
    if not isinstance(raw_horizons, list):
        raise TypeError("'horizons_h' in research_config.yaml must be a list.")
    horizons = [int(h) for h in raw_horizons]

    # I2: range validation for horizons
    for h in horizons:
        if h <= 0:
            raise ValueError(
                f"Every value in horizons_h must be > 0, got {h}."
            )

    # ── period ───────────────────────────────────────────────────────────────
    period = int(raw["period"])
    # I2: range validation for period
    if period <= 0:
        raise ValueError(f"'period' must be > 0, got {period}.")

    # ── discovery_cache_days ─────────────────────────────────────────────────
    discovery_cache_days = int(raw.get("discovery_cache_days", 7))
    if discovery_cache_days < 0:
        raise ValueError(
            f"'discovery_cache_days' must be >= 0, got {discovery_cache_days}."
        )

    return ResearchConfig(
        symbols=tuple(symbol_configs),
        period=period,
        interval=str(raw["interval"]),
        data_source=str(raw["data_source"]),
        engine=str(raw["engine"]),
        fees=fees,
        horizons_h=tuple(horizons),
        discovery_cache_days=discovery_cache_days,
    )
