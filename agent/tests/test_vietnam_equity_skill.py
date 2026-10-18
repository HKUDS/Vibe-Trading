"""The vietnam-equity skill must describe the engine that actually runs.

The agent reads the skill before it writes a Vietnamese backtest, so a band,
a config key or a default that drifts from ``VietnamEquityEngine`` becomes a
wrong strategy rather than a stale sentence.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import yaml

from backtest.engines import vietnam_equity
from backtest.engines._market_hooks import _detect_market
from backtest.engines.vietnam_equity import (
    VN_EXCHANGE_BY_SUFFIX,
    VN_PRICE_BANDS,
    VietnamEquityEngine,
)

SKILL_DIR = Path(__file__).resolve().parents[1] / "src" / "skills" / "vietnam-equity"


def _text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _block(language: str) -> str:
    return _text().split(f"```{language}\n", 1)[1].split("```", 1)[0]


def test_the_band_table_matches_the_engine() -> None:
    row = r"^\| [^|]+ \| `<TICKER>(\.[A-Z]+)` \|.*?±(\d+)% \|"
    rows = re.findall(row, _text(), re.M)

    assert {suffix for suffix, _ in rows} == set(VN_EXCHANGE_BY_SUFFIX)
    for suffix, band in rows:
        assert int(band) / 100 == VN_PRICE_BANDS[VN_EXCHANGE_BY_SUFFIX[suffix]]


def test_every_config_key_the_skill_names_is_read_by_the_engine() -> None:
    named = set(re.findall(r"`(vn_[a-z_]+|price_limit|slippage|allow_short)`", _text()))
    source = inspect.getsource(vietnam_equity)

    assert {"vn_brokerage", "vn_tax_sell", "vn_settlement_bars", "price_limit"} <= named
    for key in named:
        assert f'config.get("{key}"' in source, key


def test_the_example_config_routes_to_the_engine_at_its_defaults() -> None:
    config = json.loads(_block("json"))
    engine = VietnamEquityEngine({})

    assert {_detect_market(code) for code in config["codes"]} == {"vietnam_equity"}
    assert config["slippage"] == engine.slippage_rate
    assert config["vn_brokerage"] == engine.vn_brokerage
    assert config["vn_tax_sell"] == engine.vn_tax_sell


def test_the_data_bridge_example_names_vietnamese_symbols() -> None:
    sources = yaml.safe_load(_block("yaml"))["sources"]

    assert {_detect_market(entry["symbol"]) for entry in sources} == {"vietnam_equity"}
