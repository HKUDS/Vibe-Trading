"""Longbridge loader interval map must accept connector-style 1d/1w aliases."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtest.loaders import longbridge as loader_mod
from backtest.loaders.base import NoAvailableSourceError


def test_lowercase_1d_and_1w_map_like_project_tokens() -> None:
    assert loader_mod._INTERVAL_MAP["1d"] == loader_mod._INTERVAL_MAP["1D"] == "Day"
    assert loader_mod._INTERVAL_MAP["1w"] == loader_mod._INTERVAL_MAP["1W"] == "Week"


def test_to_longport_period_accepts_lowercase_daily_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_openapi = SimpleNamespace(
        Period=SimpleNamespace(Day="day", Week="week", Min_60="m60")
    )
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)
    assert loader_mod._to_longport_period("1d") == "day"
    assert loader_mod._to_longport_period("1w") == "week"
    assert loader_mod._to_longport_period("1D") == "day"


def test_four_hour_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_openapi = SimpleNamespace(Period=SimpleNamespace(Day="day"))
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)
    with pytest.raises(NoAvailableSourceError, match="unsupported Longbridge interval"):
        loader_mod._to_longport_period("4h")
