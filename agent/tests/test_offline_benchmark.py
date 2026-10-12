"""A declared benchmark must be honoured, or its absence reported, on every run.

``runner.main`` hands the engine a wrapper around the already-fetched
snapshot. A benchmark ticker is normally not one of the traded ``codes``, so a
source that must stay offline needs the wrapper to reach its own loader for
it; every other source keeps the plain snapshot wrapper. When the declared
benchmark still cannot be resolved, the run card has to say so, because the
benchmark-relative metrics are then graded against the equal-weight basket.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import backtest.runner as runner

_DATES = pd.bdate_range("2026-01-05", periods=5)
_STOCK_CLOSE = [100.0, 110.0, 120.0, 130.0, 140.0]
_BENCH_CLOSE = [200.0, 201.0, 202.0, 203.0, 204.0]
_BENCH = "SPY.US"
_UNRESOLVED_MARKER = "could not be resolved"


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000.0] * len(closes),
        },
        index=_DATES,
    )


class _FlatSignal:
    """Never trades, so only the benchmark side of the metrics can move."""

    def generate(self, data_map):
        return {code: pd.Series(0.0, index=df.index) for code, df in data_map.items()}


def _loader_class(source: str, frames: dict[str, pd.DataFrame], calls: list[list[str]]):
    class _RecordingLoader:
        name = source

        def is_available(self) -> bool:
            return True

        def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
            del start_date, end_date, fields, interval
            calls.append(list(codes))
            return {code: frames[code].copy() for code in codes if code in frames}

    return _RecordingLoader


def _run_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: str,
    frames: dict[str, pd.DataFrame],
) -> tuple[dict, list[list[str]]]:
    """Run ``runner.main`` end to end with a recording loader for ``source``.

    Args:
        tmp_path: Pytest temporary directory, used as the allowed run root.
        monkeypatch: Pytest monkeypatch fixture.
        source: Configured data source.
        frames: Bars the recording loader can serve, keyed by symbol.

    Returns:
        The written run card and every symbol list the loader was asked for.
    """
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n    pass\n", encoding="utf-8"
    )
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "codes": ["AAPL.US"],
                "start_date": str(_DATES[0].date()),
                "end_date": str(_DATES[-1].date()),
                "source": source,
                "benchmark": _BENCH,
                "initial_cash": 100_000.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    calls: list[list[str]] = []
    monkeypatch.setattr(
        runner, "_get_loader", lambda name: _loader_class(source, frames, calls)
    )
    monkeypatch.setattr(
        runner,
        "_load_module_from_file",
        lambda path, name: SimpleNamespace(SignalEngine=_FlatSignal),
    )
    monkeypatch.setattr(runner, "_validate_signal_engine_class", lambda cls: None)

    class _NoNetwork:
        def fetch(self, *args, **kwargs):
            return {}

    monkeypatch.setattr("backtest.benchmark.YfinanceLoader", _NoNetwork)

    runner.main(run_dir)
    card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    return card, calls


def test_offline_run_fetches_the_declared_benchmark_through_its_own_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAPL.US": _bars(_STOCK_CLOSE), _BENCH: _bars(_BENCH_CLOSE)}

    card, calls = _run_main(tmp_path, monkeypatch, source="local", frames=frames)

    assert calls == [["AAPL.US"], [_BENCH]]
    metrics = card["metrics"]
    assert metrics["benchmark_ticker"] == _BENCH
    assert metrics["benchmark_return"] == pytest.approx(
        _BENCH_CLOSE[-1] / _BENCH_CLOSE[0] - 1, abs=1e-6
    )
    assert metrics["excess_return"] == pytest.approx(
        metrics["total_return"] - metrics["benchmark_return"], abs=1e-6
    )
    assert not any(_UNRESOLVED_MARKER in w for w in card.get("warnings") or [])


def test_networked_run_keeps_the_snapshot_wrapper_away_from_its_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAPL.US": _bars(_STOCK_CLOSE), _BENCH: _bars(_BENCH_CLOSE)}

    card, calls = _run_main(tmp_path, monkeypatch, source="yahoo", frames=frames)

    assert calls == [["AAPL.US"]]
    assert "benchmark_ticker" not in card["metrics"]


def test_snapshot_wrapper_without_inner_loader_serves_only_the_snapshot() -> None:
    frame = _bars(_STOCK_CLOSE)
    loader = runner._AutoLoader({"AAPL.US": frame})

    assert loader.fetch(["AAPL.US", _BENCH], "", "") == {"AAPL.US": frame}
    assert getattr(loader, "name", None) is None


def test_unresolvable_declared_benchmark_is_reported_on_the_run_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAPL.US": _bars(_STOCK_CLOSE)}

    card, _ = _run_main(tmp_path, monkeypatch, source="local", frames=frames)

    assert "benchmark_ticker" not in card["metrics"]
    warnings = [w for w in card.get("warnings") or [] if _UNRESOLVED_MARKER in w]
    assert len(warnings) == 1
    assert repr(_BENCH) in warnings[0]
    assert "equal-weight basket" in warnings[0]


def test_inner_loader_frames_are_sanitised_like_the_snapshot() -> None:
    bench = _bars(_BENCH_CLOSE)
    bench.iloc[2, bench.columns.get_loc("high")] = 1.0  # high below low
    calls: list[list[str]] = []
    inner = _loader_class("local", {_BENCH: bench}, calls)()
    loader = runner._AutoLoader({}, inner=inner, name="local")

    served = loader.fetch([_BENCH], "", "")

    assert calls == [[_BENCH]]
    assert list(served[_BENCH].index) == [d for i, d in enumerate(_DATES) if i != 2]


@pytest.mark.parametrize("source", ["local", "qveris", "tickerall", "fmp", "nobitex", "wallex"])
@pytest.mark.parametrize("loader_name", ["same", "yahoo"])
def test_source_bound_benchmark_never_switches_provider(monkeypatch, source, loader_name):
    from backtest.benchmark import resolve_benchmark

    calls = []
    network_calls = []
    name = source if loader_name == "same" else loader_name
    loader = _loader_class(name, {}, calls)()

    class NetworkLoader:
        def fetch(self, *args, **kwargs):
            network_calls.append(args)
            return {_BENCH: _bars(_BENCH_CLOSE)}

    monkeypatch.setattr("backtest.benchmark.YfinanceLoader", NetworkLoader)
    result = resolve_benchmark(
        ["AAPL.US"], source, "2026-01-05", "2026-01-09", explicit=_BENCH, loader=loader
    )

    assert result is None
    assert calls == ([[_BENCH]] if loader_name == "same" else [])
    assert network_calls == []


@pytest.mark.parametrize("benchmark_available", [True, False])
def test_real_local_csv_benchmark_reaches_run_metrics(tmp_path, monkeypatch, benchmark_available):
    """Exercise CSV -> actual loader -> runner -> run card with no network."""
    from backtest.loaders import local_loader

    bridge = tmp_path / "bridge.json"
    symbols = [("AAPL.US", _STOCK_CLOSE)]
    if benchmark_available:
        symbols.append((_BENCH, _BENCH_CLOSE))
    sources = []
    for symbol, closes in symbols:
        path = tmp_path / f"{symbol}.csv"
        _bars(closes).rename_axis("date").to_csv(path)
        sources.append({"symbol": symbol, "type": "csv", "path": str(path)})
    bridge.write_text(json.dumps({"sources": sources}))
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", bridge)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    run = tmp_path / "run"
    (run / "code").mkdir(parents=True)
    (run / "code/signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: frame['close'] * 0 for code, frame in data_map.items()}\n"
    )
    (run / "config.json").write_text(json.dumps({
        "codes": ["AAPL.US"], "source": "local", "benchmark": _BENCH,
        "start_date": "2026-01-05", "end_date": "2026-01-09", "initial_cash": 100_000,
    }))
    network_calls = []

    class NetworkLoader:
        def fetch(self, *args, **kwargs):
            network_calls.append(args)
            return {_BENCH: _bars(_BENCH_CLOSE)}

    monkeypatch.setattr("backtest.benchmark.YfinanceLoader", NetworkLoader)
    runner.main(run)
    card = json.loads((run / "run_card.json").read_text())
    assert network_calls == []
    if benchmark_available:
        assert card["metrics"]["benchmark_ticker"] == _BENCH
        assert card["metrics"]["benchmark_return"] == pytest.approx(0.02)
        assert card["metrics"]["excess_return"] == pytest.approx(-0.02)
        assert not any(_UNRESOLVED_MARKER in w for w in card.get("warnings") or [])
    else:
        assert "benchmark_ticker" not in card["metrics"]
        assert any(_UNRESOLVED_MARKER in w for w in card["warnings"])
