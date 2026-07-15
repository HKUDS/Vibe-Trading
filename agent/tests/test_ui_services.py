"""Tests for UI-oriented run reconstruction services."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import backtest.runner as runner
from src.ui_services import reconstruct_price_series


@pytest.mark.parametrize("source", ["yahoo", "auto"])
def test_reconstruct_price_series_uses_central_fetch_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    run_dir = tmp_path / "completed-run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n    pass\n", encoding="utf-8"
    )
    (run_dir / "req.json").write_text(
        json.dumps(
            {
                "prompt": "test",
                "context": {
                    "codes": ["BTC-USDT"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "codes": ["BTC-USDT"],
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "source": source,
                "interval": "1H",
            }
        ),
        encoding="utf-8",
    )

    routed_configs: list[dict] = []
    frame = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]),
    )

    def fake_fetch_data_map(config: dict) -> SimpleNamespace:
        routed_configs.append(config)
        return SimpleNamespace(data_map={"BTC-USDT": frame})

    monkeypatch.setattr(runner, "fetch_data_map", fake_fetch_data_map)

    rows = reconstruct_price_series(run_dir)

    assert routed_configs[0]["source"] == source
    assert routed_configs[0]["interval"] == "1H"
    assert routed_configs[0]["codes"] == ["BTC-USDT"]
    assert rows[0]["code"] == "BTC-USDT"


def test_fetch_data_map_uses_registry_for_nonlegacy_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]),
    )

    class StubLoader:
        name = "yahoo"

        def fetch(self, codes, start_date, end_date, **kwargs):
            calls.append((codes, start_date, end_date, kwargs))
            return {codes[0]: frame}

    monkeypatch.setattr(runner, "_get_loader", lambda source: StubLoader)
    config = {
        "codes": ["AAPL.US"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "source": "yahoo",
        "interval": "1H",
    }
    original = dict(config)

    result = runner.fetch_data_map(config)

    assert config == original
    assert calls == [
        (
            ["AAPL.US"],
            "2026-01-01",
            "2026-01-02",
            {"fields": None, "interval": "1H"},
        )
    ]
    assert result.source == "yahoo"
    assert result.effective_sources == ["yahoo"]
    assert list(result.data_map) == ["AAPL.US"]


def test_fetch_data_map_does_not_expose_config_mutables_to_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]),
    )

    class MutatingLoader:
        name = "tushare"

        def fetch(self, codes, start_date, end_date, **kwargs):
            kwargs["fields"].append("injected")
            return {codes[0]: frame}

    monkeypatch.setattr(runner, "_get_loader", lambda source: MutatingLoader)
    config = {
        "codes": ["000001.SZ"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "source": "tushare",
        "extra_fields": ["amount"],
    }

    runner.fetch_data_map(config)

    assert config["extra_fields"] == ["amount"]


def test_fetch_data_map_delegates_auto_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]),
    )
    calls: list[tuple[list[str], dict, str]] = []

    def fake_fetch_auto(codes: list[str], config: dict, interval: str) -> dict:
        calls.append((codes, config, interval))
        return {"AAPL.US": frame}

    monkeypatch.setattr(runner, "_fetch_auto", fake_fetch_auto)
    config = {
        "codes": ["AAPL.US"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "source": "auto",
        "interval": "1D",
    }

    result = runner.fetch_data_map(config)

    assert calls == [(["AAPL.US"], config, "1D")]
    assert result.source == "auto"
    assert result.effective_sources == ["yfinance"]
