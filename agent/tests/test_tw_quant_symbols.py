"""Phase 01 Taiwan symbol and routing tests."""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _detect_market
from backtest.loaders.base import NoAvailableSourceError
from backtest.loaders.registry import get_loader_cls_with_fallback
from backtest.runner import _create_market_engine, _detect_source, _group_codes_by_market, _normalize_codes
from src.tw_quant.market.symbols import SymbolParseError, parse_symbol


@pytest.mark.parametrize(
    ("raw", "local_code", "market", "canonical"),
    [
        ("2330.TW", "2330", "TWSE", "2330.TW"),
        ("6488.TWO", "6488", "TPEX", "6488.TWO"),
        ("2330.tw", "2330", "TWSE", "2330.TW"),
    ],
)
def test_parse_canonical_symbols(raw: str, local_code: str, market: str, canonical: str) -> None:
    parsed = parse_symbol(raw)
    assert parsed.local_code == local_code
    assert parsed.market == market
    assert parsed.canonical == canonical


def test_parse_bare_code_requires_explicit_market_hint() -> None:
    with pytest.raises(SymbolParseError):
        parse_symbol("2330")
    assert parse_symbol("2330", "TWSE").canonical == "2330.TW"
    assert parse_symbol("6488", "TPEX").canonical == "6488.TWO"


@pytest.mark.parametrize("raw", ["", "2330.US", "23.TW", "2330.TW.extra", "ABCD.TW"])
def test_parse_rejects_invalid_or_unknown_symbols(raw: str) -> None:
    with pytest.raises(SymbolParseError):
        parse_symbol(raw)


def test_taiwan_market_detection_and_source_mapping() -> None:
    assert _detect_market("2330.TW") == "taiwan_equity"
    assert _detect_market("6488.TWO") == "taiwan_equity"
    assert _detect_market("2330", market_hint="tw") == "taiwan_equity"
    assert _detect_source("2330.TW") == "tw_snapshot"
    assert _group_codes_by_market(["2330.TW", "6488.TWO"]) == {
        "taiwan_equity": ["2330.TW", "6488.TWO"]
    }


def test_tw_snapshot_normalizes_explicit_bare_code() -> None:
    assert _normalize_codes(["2330"], "tw_snapshot", market_hint="TWSE") == ["2330.TW"]


def test_taiwan_engine_path_fails_closed_until_rule_engine_exists() -> None:
    with pytest.raises(ValueError, match="not implemented in Phase 01"):
        _create_market_engine("tw_snapshot", {"market": "TWSE"}, ["2330"])


def test_taiwan_snapshot_source_never_falls_back_to_network(monkeypatch) -> None:
    monkeypatch.delenv("TW_QUANT_SNAPSHOT_ID", raising=False)
    with pytest.raises(NoAvailableSourceError, match="tw_snapshot"):
        get_loader_cls_with_fallback("tw_snapshot")
