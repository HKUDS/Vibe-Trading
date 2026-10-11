"""Free baostock fallback for ``val:*`` fields (#1789 follow-up #3).

Users without a TUSHARE_TOKEN used to get an all-NaN valuation panel (and
before that, a crash). This suite pins the new degradation ladder:

1. no token + baostock installed -> fields are served from baostock daily
   bars (``peTTM``/``pbMRQ``/``psTTM``);
2. a tushare outage on specific fields falls back to baostock too;
3. no token + baostock missing -> NaN frames, run survives;
4. fields baostock cannot serve (``pe`` dynamic, ``dv_ttm``) stay NaN instead
   of being fabricated from a proxy;
5. a baostock outage degrades to NaN frames instead of raising.

All baostock IO is faked via ``sys.modules`` test doubles -- no network.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backtest.loaders import valuation_loader
from backtest.loaders.valuation_loader import (
    BAOSTOCK_VALUATION_FIELDS,
    load_valuation_panel,
)

_DATES = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])


class _FakeResultData:
    def __init__(self, rows: list[list[str]]):
        self._rows = rows
        self.error_code = "0"
        self.error_msg = ""

    def next(self) -> bool:
        return bool(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows.pop(0)


class _FakeBaostock:
    """Minimal ``query_history_k_data_plus`` double backed by canned rows.

    Canned rows are per-column dicts (``{"date": ..., "pbMRQ": ...}``) so the
    double serves whatever subset of columns the loader asks for.
    """

    def __init__(self, rows_by_code: dict[str, list[dict[str, str]]]):
        self.rows_by_code = rows_by_code
        self.queries: list[str] = []

    def login(self) -> SimpleNamespace:
        return SimpleNamespace(error_code="0", error_msg="success")

    def logout(self) -> SimpleNamespace:
        return SimpleNamespace(error_code="0", error_msg="success")

    def query_history_k_data_plus(self, code: str, fields: str, **kwargs: Any) -> _FakeResultData:
        self.queries.append(code)
        wanted = fields.split(",")
        rows = [
            [row.get(column, "") for column in wanted]
            for row in self.rows_by_code.get(code, [])
        ]
        return _FakeResultData(rows)


@contextmanager
def _fake_guard(timeout: float):
    yield True


def _install_fake_baostock(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    from backtest.loaders import baostock_loader

    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr(valuation_loader, "_baostock_available", lambda: True)
    monkeypatch.setattr(baostock_loader, "_baostock_socket_guard", _fake_guard)


def test_no_token_serves_val_fields_from_baostock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a token, pe_ttm/pb/ps_ttm come from baostock daily bars."""
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    rows = {
        "sz.000001": [
            {"date": "2024-01-02", "peTTM": "5.5", "pbMRQ": "0.8", "psTTM": "1.9"},
            {"date": "2024-01-03", "peTTM": "5.6", "pbMRQ": "0.81", "psTTM": "1.91"},
            {"date": "2024-01-04", "peTTM": "5.7", "pbMRQ": "0.82", "psTTM": "1.92"},
        ]
    }
    fake = _FakeBaostock(rows)
    _install_fake_baostock(monkeypatch, fake)

    panels = load_valuation_panel(
        symbols=["000001.SZ"],
        fields=["pe_ttm", "pb", "ps_ttm"],
        start="2024-01-02",
        end="2024-01-04",
        index=_DATES,
    )

    assert fake.queries == ["sz.000001"]
    np.testing.assert_allclose(panels["pe_ttm"]["000001.SZ"].to_numpy(), [5.5, 5.6, 5.7])
    np.testing.assert_allclose(panels["pb"]["000001.SZ"].to_numpy(), [0.8, 0.81, 0.82])
    np.testing.assert_allclose(panels["ps_ttm"]["000001.SZ"].to_numpy(), [1.9, 1.91, 1.92])


def test_tushare_failure_falls_back_to_baostock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tushare API whose daily_basic always fails degrades to baostock."""
    rows = {
        "sh.600000": [
            {"date": "2024-01-02", "peTTM": "4.1", "pbMRQ": "0.5", "psTTM": "1.2"},
            {"date": "2024-01-03", "peTTM": "4.2", "pbMRQ": "0.51", "psTTM": "1.21"},
        ]
    }
    fake = _FakeBaostock(rows)
    _install_fake_baostock(monkeypatch, fake)

    class _BrokenApi:
        def daily_basic(self, **kwargs: Any):
            raise RuntimeError("server exploded")

    panels = load_valuation_panel(
        symbols=["600000.SH"],
        fields=["pb"],
        start="2024-01-02",
        end="2024-01-04",
        index=_DATES,
        api=_BrokenApi(),
    )

    assert fake.queries == ["sh.600000"]
    np.testing.assert_allclose(
        panels["pb"]["600000.SH"].to_numpy(), [0.5, 0.51, np.nan]
    )


def test_no_token_and_no_baostock_still_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    """No token and no baostock: NaN frames, no exception."""
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    monkeypatch.setattr(valuation_loader, "_baostock_available", lambda: False)

    panels = load_valuation_panel(
        symbols=["000001.SZ"],
        fields=["pb"],
        start="2024-01-02",
        end="2024-01-04",
        index=_DATES,
    )

    assert panels["pb"].isna().all().all()
    assert list(panels["pb"].index) == list(_DATES)


def test_unserved_fields_stay_nan_not_proxied() -> None:
    """pe/dv_ttm have no baostock counterpart and must stay NaN, not proxy."""
    assert "pe" not in BAOSTOCK_VALUATION_FIELDS
    assert "dv_ttm" not in BAOSTOCK_VALUATION_FIELDS
    assert set(BAOSTOCK_VALUATION_FIELDS) == {"pe_ttm", "pb", "ps_ttm"}


def test_baostock_outage_degrades_to_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    """baostock login failure yields NaN frames instead of raising."""
    monkeypatch.setenv("TUSHARE_TOKEN", "")

    class _DeadBaostock:
        def login(self) -> SimpleNamespace:
            return SimpleNamespace(error_code="10001", error_msg="network error")

        def logout(self) -> SimpleNamespace:
            return SimpleNamespace(error_code="0", error_msg="")

    _install_fake_baostock(monkeypatch, _DeadBaostock())

    panels = load_valuation_panel(
        symbols=["000001.SZ"],
        fields=["pb"],
        start="2024-01-02",
        end="2024-01-04",
        index=_DATES,
    )

    assert panels["pb"].isna().all().all()
