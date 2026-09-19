"""A ``local:`` code is the user's own dataset, served locally or not at all (#1467).

The prefix picks the loader; the instrument is the bare symbol. The backtest
runner used to compare the local loader's ``AAPL.US`` key against the requested
``local:AAPL.US``, count a served symbol as missing, and send it down a network
fallback chain. In ``auto`` mode the prefix was ignored and the code was routed
as an A-share. The README promises that an explicit ``local:`` symbol never
silently falls back to a network source.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

import backtest.loaders.local_loader as local_loader
import backtest.runner as runner
from backtest.engines._market_hooks import _is_china_futures, code_currency
from backtest.loaders.base import NoAvailableSourceError
from backtest.loaders.registry import _ensure_registered

pytestmark = pytest.mark.unit

_START, _END = "2026-01-01", "2026-01-06"


def _configure_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, symbols: list[str]) -> None:
    """Point the local loader at a temp config serving ``symbols`` from CSV."""
    sources = []
    for symbol in symbols:
        path = tmp_path / f"{symbol}.csv"
        path.write_text(
            "date,open,high,low,close,volume\n"
            "2026-01-02,10,11,9,10.5,1000\n"
            "2026-01-05,10.5,12,10,11.5,1200\n"
            "2026-01-06,11.5,12,11,11.8,900\n",
            encoding="utf-8",
        )
        sources.append({"symbol": symbol, "type": "csv", "path": str(path)})
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config_path)


class _NetworkLoader:
    """Stands in for every network loader and records what it was asked for."""

    name = "fakenet"
    calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        type(self).calls.append(list(codes))
        index = pd.to_datetime(["2026-01-02", "2026-01-05"])
        frame = pd.DataFrame(
            {"open": [5.0, 5.2], "high": [5.5, 5.6], "low": [4.8, 5.0], "close": [5.1, 5.3], "volume": [10, 12]},
            index=index,
        )
        return {code: frame.copy() for code in codes if not code.lower().startswith("local:")}


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> type[_NetworkLoader]:
    """Route every market chain and resolver to the recording network loader."""
    _ensure_registered()
    _NetworkLoader.calls = []
    real_get_loader = runner._get_loader
    # Any non-local source resolves to the recorder, so a regression can never
    # reach a real endpoint from this suite.
    monkeypatch.setattr(
        runner, "_get_loader", lambda source: real_get_loader(source) if source == "local" else _NetworkLoader
    )
    monkeypatch.setitem(runner.LOADER_REGISTRY, "fakenet", _NetworkLoader)
    monkeypatch.setattr(runner, "FALLBACK_CHAINS", {m: ["fakenet"] for m in ("us_equity", "a_share", "hk_equity")})
    monkeypatch.setattr(runner, "resolve_loader", lambda market: _NetworkLoader())
    return _NetworkLoader


@pytest.mark.parametrize(
    ("code", "market"),
    [("local:AAPL.US", "us_equity"), ("LOCAL:00700.HK", "hk_equity"), ("local:600519.SH", "a_share")],
)
def test_market_rules_follow_the_bare_symbol(code: str, market: str) -> None:
    assert runner._detect_market(code) == market


def test_currency_and_futures_checks_follow_the_bare_symbol() -> None:
    assert code_currency("local:AAPL.US") == "USD"
    assert code_currency("local:00700.HK") == "HKD"
    assert code_currency("local:EURUSD") == "USD"  # a forex pair's quote currency is parsed from the symbol
    assert _is_china_futures("local:RB2410") is True


@pytest.mark.parametrize("source", ["local", "auto"])
def test_a_served_local_code_comes_back_as_its_bare_symbol_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: type[_NetworkLoader], source: str
) -> None:
    _configure_local(monkeypatch, tmp_path, ["AAPL.US"])

    result = runner.fetch_data_map(
        {"source": source, "codes": ["local:AAPL.US"], "start_date": _START, "end_date": _END}
    )

    assert result.codes == ["AAPL.US"]
    assert list(result.data_map) == ["AAPL.US"]
    assert list(result.data_map["AAPL.US"]["close"]) == [10.5, 11.5, 11.8]
    assert result.effective_sources == ["local"]
    assert network.calls == []


def test_auto_serves_local_codes_locally_and_the_rest_from_their_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: type[_NetworkLoader]
) -> None:
    _configure_local(monkeypatch, tmp_path, ["AAPL.US"])

    result = runner.fetch_data_map(
        {"source": "auto", "codes": ["local:AAPL.US", "MSFT.US"], "start_date": _START, "end_date": _END}
    )

    assert result.codes == ["AAPL.US", "MSFT.US"]
    assert list(result.data_map["AAPL.US"]["close"]) == [10.5, 11.5, 11.8]
    assert list(result.data_map["MSFT.US"]["close"]) == [5.1, 5.3]
    assert network.calls == [["MSFT.US"]]
    assert sorted(result.effective_sources) == ["fakenet", "local"]


def test_auto_refuses_a_local_code_the_dataset_lacks_instead_of_fetching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: type[_NetworkLoader]
) -> None:
    _configure_local(monkeypatch, tmp_path, ["AAPL.US"])

    with pytest.raises(NoAvailableSourceError, match=r"source=local; missing symbols: \['local:NOPE.US'\]"):
        runner.fetch_data_map(
            {"source": "auto", "codes": ["local:AAPL.US", "local:NOPE.US"], "start_date": _START, "end_date": _END}
        )
    assert network.calls == []


@pytest.mark.parametrize("source", ["local", "auto"])
def test_a_local_code_the_dataset_lacks_is_never_filled_from_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: type[_NetworkLoader], source: str
) -> None:
    """Stripping the prefix must not let a network chain serve the bare symbol instead."""
    _configure_local(monkeypatch, tmp_path, ["AAPL.US"])

    with pytest.raises(NoAvailableSourceError, match=r"source=local; missing symbols: \['local:MSFT.US'\]"):
        runner.fetch_data_map(
            {"source": source, "codes": ["local:AAPL.US", "local:MSFT.US"], "start_date": _START, "end_date": _END}
        )
    assert network.calls == []


def test_a_local_code_from_a_network_source_is_refused(network: type[_NetworkLoader]) -> None:
    with pytest.raises(ValueError, match="need source='local' or 'auto'"):
        runner.fetch_data_map({"source": "yahoo", "codes": ["local:AAPL.US"], "start_date": _START, "end_date": _END})
    assert network.calls == []


def test_one_symbol_with_and_without_the_prefix_is_refused(network: type[_NetworkLoader]) -> None:
    with pytest.raises(ValueError, match=r"requested more than once .*\['AAPL.US'\]"):
        runner.fetch_data_map(
            {"source": "auto", "codes": ["local:AAPL.US", "AAPL.US"], "start_date": _START, "end_date": _END}
        )
    assert network.calls == []
