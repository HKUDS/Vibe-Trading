"""The csi300 bench attaches a PIT SW2021 sector tag for requires_sector alphas.

csi300 was the one universe with no ``sector`` frame: the 19 alpha101
industry-neutralized alphas and the three ``fund_*_ind_neutral`` CN value
alphas SkipAlpha'd on every run. These tests extend the existing csi300 fake
pro with ``index_member_all`` and pin the attach contract: labels land outside
the pickled price panel, inherit the PIT membership mask, disclose source and
coverage in ``_meta``, stay off below the coverage gate, and never take the
bench down when the loader fails.
"""
from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from src.config.accessor import reset_env_config
from src.tools import alpha_bench_tool as tool

_ALPHA_ID = "fund_pb_ind_neutral"
_META = {"columns_required": ["val:pb"], "requires_sector": True}
_PLAIN_META = {"columns_required": ["val:pb"]}


class _StubRegistry:
    """Registry surface ``_prepare_bench_panel`` uses: ``get(aid).meta``."""

    def __init__(self, metas: dict[str, dict]) -> None:
        self._metas = metas

    def get(self, alpha_id: str) -> Any:
        return SimpleNamespace(meta=self._metas[alpha_id])


def _member_row(ts_code: str, l1_name: str) -> dict[str, Any]:
    return {
        "l1_code": f"800-{l1_name}",
        "l1_name": l1_name,
        "l2_code": "801-x",
        "l2_name": "x",
        "l3_code": "802-y",
        "l3_name": "y",
        "ts_code": ts_code,
        "name": ts_code.split(".")[0],
        "in_date": "20200101",
        "out_date": None,
        "is_new": "Y",
    }


class _FakeTusharePro:
    """The csi300 fake from test_alpha_bench_universe_metadata, plus industry
    membership and daily_basic so the whole _prepare_bench_panel path runs."""

    def __init__(self, members: list[dict[str, Any]] | Exception) -> None:
        self.members = members
        self.industry_calls: list[dict[str, Any]] = []

    def index_weight(self, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": ["20240102"] * 3,
                "con_code": ["600000.SH", "000001.SZ", "000002.SZ"],
            }
        )

    def daily(self, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": ["20240102"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "vol": [100.0],
                "amount": [105.0],
            }
        )

    def adj_factor(self, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame({"trade_date": ["20240102"], "adj_factor": [1.0]})

    def daily_basic(self, **kwargs) -> pd.DataFrame:
        code = kwargs["ts_code"]
        return pd.DataFrame(
            {"ts_code": [code], "trade_date": ["20240102"], "pb": [1.5]}
        )

    def index_member_all(self, **kwargs) -> pd.DataFrame:
        self.industry_calls.append(kwargs)
        if isinstance(self.members, Exception):
            raise self.members
        return pd.DataFrame(self.members)


def _install(
    monkeypatch: pytest.MonkeyPatch, pro: _FakeTusharePro
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "ts-test-token")
    monkeypatch.setattr(
        tool,
        "get_env_config",
        lambda: SimpleNamespace(data=SimpleNamespace(tushare_token="ts-test-token")),
    )
    monkeypatch.setitem(
        sys.modules, "tushare", SimpleNamespace(pro_api=lambda _token: pro)
    )


def _prepare(panel: dict, metas: dict[str, dict] | None = None) -> dict:
    metas = metas if metas is not None else {_ALPHA_ID: _META}
    registry = _StubRegistry(metas)
    return tool._prepare_bench_panel(
        registry, list(metas), panel, "csi300", "2024-01-01/2024-01-31"
    )


def test_sector_attaches_with_pit_labels_and_meta_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pro = _FakeTusharePro(
        [
            _member_row("600000.SH", "银行"),
            _member_row("000001.SZ", "非银金融"),
            _member_row("000002.SZ", "房地产"),
        ]
    )
    _install(monkeypatch, pro)

    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")
    # The tag must not ride inside the pickled price panel: at load time the
    # meta keys sit at their null/0.0 defaults and no sector frame exists.
    assert "sector" not in panel
    assert panel["_meta"]["sector_source"] is None
    assert panel["_meta"]["sector_coverage"] == 0.0

    enriched = _prepare(panel)

    assert "sector" in enriched
    close = enriched["close"]
    sector = enriched["sector"]
    assert sector.shape == close.shape
    assert list(sector.columns) == list(close.columns)
    assert sector.index.equals(close.index)
    assert sector.loc["2024-01-02", "600000.SH"] == "银行"
    assert sector.loc["2024-01-02", "000001.SZ"] == "非银金融"
    assert sector.loc["2024-01-02", "000002.SZ"] == "房地产"
    # The original panel (the dict that was pickled into the cache) is never
    # mutated: the attach adds keys to its own copy only.
    assert "sector" not in panel
    assert panel["_meta"]["sector_source"] is None
    assert panel["_meta"]["sector_coverage"] == 0.0
    # Inherits the PIT membership mask: a label exists only where close does.
    assert (sector.notna() <= close.notna()).all().all()
    assert enriched["_meta"]["sector_source"] == "tushare index_member_all SW2021 L1"
    assert enriched["_meta"]["sector_coverage"] == 1.0
    # The val: attach still ran first, same stage.
    assert "val:pb" in enriched


def test_low_coverage_leaves_the_tag_off_and_discloses(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """1 of 3 columns labelled < 0.9: attaching would z-score one bucket."""
    pro = _FakeTusharePro([_member_row("600000.SH", "银行")])
    _install(monkeypatch, pro)
    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    with caplog.at_level(logging.WARNING, logger=tool.logger.name):
        enriched = _prepare(panel)

    assert "sector" not in enriched
    assert enriched["_meta"]["sector_source"] is None
    assert enriched["_meta"]["sector_coverage"] == pytest.approx(0.3333, abs=1e-4)
    assert any("sector coverage" in message for message in caplog.messages)
    # The rest of the bench prep is untouched: val: columns still attach.
    assert "val:pb" in enriched


def test_loader_failure_never_takes_the_bench_down(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Placeholder token → loader RuntimeError → warn, no sector, bench proceeds."""
    pro = _FakeTusharePro(
        [
            _member_row("600000.SH", "银行"),
            _member_row("000001.SZ", "非银金融"),
            _member_row("000002.SZ", "房地产"),
        ]
    )
    _install(monkeypatch, pro)
    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")
    # Pre-attach val:pb so the token pull below isolates the sector loader
    # (the valuation loader would raise its own RuntimeError on the empty token).
    panel["val:pb"] = panel["close"].notna().astype(float).where(panel["close"].notna()) * 1.5

    monkeypatch.setenv("TUSHARE_TOKEN", "")
    reset_env_config()
    with caplog.at_level(logging.WARNING, logger=tool.logger.name):
        enriched = _prepare(panel)

    assert "sector" not in enriched
    assert enriched["_meta"]["sector_source"] is None
    assert enriched["_meta"]["sector_coverage"] == 0.0
    assert any("industry loader failed" in message for message in caplog.messages)
    assert "val:pb" in enriched


def test_provider_exception_degrades_to_no_sector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """index_member_all raising after backoff: the loader itself degrades."""
    pro = _FakeTusharePro(RuntimeError("provider down"))
    _install(monkeypatch, pro)
    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    enriched = _prepare(panel)

    assert "sector" not in enriched
    assert enriched["_meta"]["sector_source"] is None
    assert enriched["_meta"]["sector_coverage"] == 0.0


def test_no_sector_fetch_when_nothing_declares_requires_sector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The membership endpoint is only paid for when an alpha needs the tag."""
    pro = _FakeTusharePro([_member_row("600000.SH", "银行")])
    _install(monkeypatch, pro)
    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    enriched = _prepare(panel, metas={_ALPHA_ID: _PLAIN_META})

    assert pro.industry_calls == []
    assert "sector" not in enriched
    assert enriched["_meta"]["sector_source"] is None
