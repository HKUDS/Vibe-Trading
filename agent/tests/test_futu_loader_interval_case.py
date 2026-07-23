"""Futu loader interval map must accept connector-style hour/day aliases."""

from __future__ import annotations

from backtest.loaders.futu import _INTERVAL_MAP, _to_futu_ktype


def test_lowercase_hour_aliases_match_project_tokens() -> None:
    assert _INTERVAL_MAP["1h"] == _INTERVAL_MAP["1H"] == "K_60M"
    assert _INTERVAL_MAP["4h"] == _INTERVAL_MAP["4H"] == "K_240M"
    assert _INTERVAL_MAP["1d"] == _INTERVAL_MAP["1D"] == "K_DAY"


def test_to_futu_ktype_accepts_lowercase_1h(monkeypatch) -> None:
    class _KL:
        K_60M = "K_60M"
        K_240M = "K_240M"
        K_DAY = "K_DAY"

    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(KLType=_KL)
    monkeypatch.setitem(sys.modules, "futu", fake)
    assert _to_futu_ktype("1h") == "K_60M"
    assert _to_futu_ktype("4h") == "K_240M"
