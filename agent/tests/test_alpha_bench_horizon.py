"""Threading tests for monthly-horizon IC support (issue #1789 follow-up #1).

Covers the ``horizon`` parameter end to end without touching the network:
run_bench / run_bench_strict result meta, run_alpha_bench parameter
validation, and the CLI ``--horizon`` surface. Engine internals are
monkeypatched with fakes following the existing bench-test patterns
(test_bench_multiple_testing.py / test_alpha_bench_strict_cli.py).
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.factors import cli_handlers
from src.factors.bench_runner import run_bench
from src.factors.bench_runner_strict import run_bench_strict
from src.tools.alpha_bench_tool import _validate_horizon, run_alpha_bench


# ── run_bench meta ──────────────────────────────────────────────────────────


def _make_panel(n_symbols: int = 6, n_days: int = 60) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    symbols = [f"SYM{i:03d}" for i in range(n_symbols)]
    close = pd.DataFrame(
        np.cumsum(rng.standard_normal((n_days, n_symbols)), axis=0) + 100,
        index=dates,
        columns=symbols,
    )
    return {"close": close, "open": close, "high": close, "low": close, "volume": close}


def _setup_bench(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> MagicMock:
    panel = _make_panel()
    rng = np.random.default_rng(7)

    reg = MagicMock()
    reg.list.return_value = ["alpha_0", "alpha_1"]
    reg.get.return_value = MagicMock(meta={"theme": ["test"], "formula_latex": ""})
    reg.compute.side_effect = lambda aid, p: pd.DataFrame(
        rng.standard_normal(p["close"].shape),
        index=p["close"].index,
        columns=p["close"].columns,
    )

    def fake_fwd(p: dict[str, pd.DataFrame], horizon: int = 1) -> pd.DataFrame:
        captured["horizon"] = horizon
        return p["close"].pct_change(fill_method=None).shift(-1)

    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", lambda u, p: panel)
    monkeypatch.setattr("src.factors.bench_runner._compute_forward_returns", fake_fwd)
    monkeypatch.setattr("src.factors.bench_runner.get_default_registry", lambda: reg)
    return reg


def test_run_bench_default_meta_says_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    reg = _setup_bench(monkeypatch, captured)

    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)

    assert result["status"] == "ok"
    assert result["horizon"] == 1
    assert result["forward_return_sampling"] == "daily"
    assert captured["horizon"] == 1


def test_run_bench_horizon_meta_says_non_overlapping(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    reg = _setup_bench(monkeypatch, captured)

    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg, horizon=21)

    assert result["status"] == "ok"
    assert result["horizon"] == 21
    assert result["forward_return_sampling"] == "non_overlapping"
    assert captured["horizon"] == 21


def test_run_bench_invalid_horizon_errors_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    # No fake for _compute_forward_returns here: the real engine validation
    # must turn horizon=0 into a clean error entry, not a traceback.
    monkeypatch.setattr(
        "src.factors.bench_runner._load_universe_panel", lambda u, p: _make_panel()
    )
    reg = MagicMock()
    reg.list.return_value = ["alpha_0"]
    reg.get.return_value = MagicMock(meta={"theme": ["test"], "formula_latex": ""})

    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg, horizon=0)

    assert result["status"] == "error"
    assert "horizon" in result["error"]


# ── run_bench_strict meta ───────────────────────────────────────────────────


class _StubRegistry:
    def list(self, *, zoo: str) -> list[str]:  # noqa: ARG002
        return ["test_signal"]

    def get(self, aid: str) -> Any:  # noqa: ARG002
        class _Handle:
            meta = {"theme": ["test"], "formula_latex": "stub"}

        return _Handle()

    def compute(self, aid: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:  # noqa: ARG002
        return panel["close"].pct_change(5)


def _setup_strict(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=80, freq="D")
    cols = [f"S{i}" for i in range(8)]
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(size=(80, 8)), axis=0), index=idx, columns=cols
    )
    panel = {
        "close": close, "high": close * 1.01, "low": close * 0.99,
        "open": close, "volume": close * 0 + 1_000_000,
        "vwap": close, "amount": close * 1_000_000,
    }
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )

    def fake_fwd(p: dict[str, pd.DataFrame], horizon: int = 1) -> pd.DataFrame:
        captured["horizon"] = horizon
        return p["close"].pct_change(fill_method=None).shift(-1)

    monkeypatch.setattr(
        "src.factors.bench_runner_strict._compute_forward_returns",
        fake_fwd,
    )


def test_run_bench_strict_accepts_horizon_and_carries_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _setup_strict(monkeypatch, captured)

    result = run_bench_strict(
        zoo="alpha101", universe="csi300", period="2024-2024",
        random_control=False, registry=_StubRegistry(), horizon=21,
    )

    assert result["status"] == "ok"
    assert result["horizon"] == 21
    assert result["forward_return_sampling"] == "non_overlapping"
    assert captured["horizon"] == 21


def test_run_bench_strict_default_meta_says_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _setup_strict(monkeypatch, captured)

    result = run_bench_strict(
        zoo="alpha101", universe="csi300", period="2024-2024",
        random_control=False, registry=_StubRegistry(),
    )

    assert result["status"] == "ok"
    assert result["horizon"] == 1
    assert result["forward_return_sampling"] == "daily"
    assert captured["horizon"] == 1


# ── Tool-level parameter validation ─────────────────────────────────────────


@pytest.mark.parametrize("bad", [0, -1, 253, "21", 1.5, True])
def test_run_alpha_bench_rejects_invalid_horizon_before_touching_the_engine(bad: object) -> None:
    # Validation must fire before registry init / panel load so this stays
    # offline-safe with a real-looking universe and period.
    envelope = run_alpha_bench(
        universe="sp500", period="2020-2024", zoo="alpha101", horizon=bad
    )

    assert envelope["status"] == "error"
    assert "horizon" in envelope["error"]


def test_validate_horizon_accepts_in_range_values() -> None:
    assert _validate_horizon(1) == 1
    assert _validate_horizon(21) == 21
    assert _validate_horizon(252) == 252
    assert _validate_horizon(None) == 1


@pytest.mark.parametrize("bad", [0, -1, 253, "21", 1.5, True])
def test_validate_horizon_rejects_out_of_range_or_non_int(bad: object) -> None:
    with pytest.raises(ValueError, match="horizon"):
        _validate_horizon(bad)


# ── CLI surface ─────────────────────────────────────────────────────────────


def _ns(**overrides: Any) -> argparse.Namespace:
    base = dict(
        zoo="alpha101",
        universe="csi300",
        period="2020-2025",
        top=20,
        yes=True,
        strict=False,
        oos_split=None,
        training_cutoff=None,
        random_seeds=5,
        horizon=1,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _legacy_result() -> dict[str, Any]:
    return {
        "status": "ok",
        "alive": 1,
        "rows": [
            {
                "id": "alpha001",
                "ic_mean": 0.05,
                "ic_std": 0.01,
                "ir": 0.9,
                "ic_positive_ratio": 0.7,
                "ic_count": 100,
                "theme": ["momentum"],
                "formula_latex": "x",
                "_category": "alive",
            }
        ],
        "skipped": [],
        "wall_seconds": 1.0,
    }


def _strict_result() -> dict[str, Any]:
    return {
        "status": "ok",
        "confirmed_alive": 1,
        "train_only": 0,
        "reversed_strict": 0,
        "noise": 0,
        "rows": [
            {
                "id": "alpha001",
                "ic_mean": 0.05,
                "ic_std": 0.01,
                "ir": 0.9,
                "ic_positive_ratio": 0.7,
                "ic_count": 100,
                "theme": ["momentum"],
                "formula_latex": "x",
                "_category": "confirmed_alive",
                "alpha_t_full": 2.7,
                "alpha_t_train": None,
                "alpha_t_test": None,
                "random_ic_mean": 0.0,
            }
        ],
        "skipped": [],
        "wall_seconds": 1.0,
    }


class _FakeReg:
    def list(self, zoo=None):  # noqa: ARG002
        return ["alpha001"]

    def get(self, aid):  # noqa: ARG002
        class _Entry:
            zoo = "alpha101"
            meta = {"theme": ["momentum"], "formula_latex": "x"}

        return _Entry()


@pytest.fixture()
def _reg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_handlers, "Registry", _FakeReg)


@pytest.fixture()
def _no_report(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import src.tools.alpha_bench_tool as tool

    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path)


def test_cli_horizon_reaches_legacy_runner(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    import src.factors.bench_runner as legacy_mod

    called: dict[str, Any] = {}

    def fake_legacy(**kwargs):
        called.update(kwargs)
        return _legacy_result()

    monkeypatch.setattr(legacy_mod, "run_bench", fake_legacy)
    rc = cli_handlers.cmd_alpha_bench(_ns(horizon=21))

    assert rc == 0
    assert called["horizon"] == 21
    capsys.readouterr()


def test_cli_horizon_default_reaches_legacy_runner_as_one(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    import src.factors.bench_runner as legacy_mod

    called: dict[str, Any] = {}

    def fake_legacy(**kwargs):
        called.update(kwargs)
        return _legacy_result()

    monkeypatch.setattr(legacy_mod, "run_bench", fake_legacy)
    rc = cli_handlers.cmd_alpha_bench(_ns())

    assert rc == 0
    assert called["horizon"] == 1
    capsys.readouterr()


def test_cli_horizon_reaches_strict_runner(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    import src.factors.bench_runner_strict as strict_mod

    called: dict[str, Any] = {}

    def fake_strict(zoo, universe, period, **kwargs):  # noqa: ARG001
        called.update(kwargs)
        return _strict_result()

    monkeypatch.setattr(strict_mod, "run_bench_strict", fake_strict)
    rc = cli_handlers.cmd_alpha_bench(_ns(strict=True, horizon=21))

    assert rc == 0
    assert called["horizon"] == 21
    assert called["random_control"] is True
    capsys.readouterr()


def test_cli_rejects_horizon_below_one_with_usage_exit_code(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg
) -> None:
    rc = cli_handlers.cmd_alpha_bench(_ns(horizon=0))

    assert rc == 2
    assert "--horizon" in capsys.readouterr().err


def test_horizon_namespace_without_attribute_defaults_to_one(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    # Pre-existing callers/tests build Namespaces without a horizon attribute;
    # the handler must fall back to 1 rather than raise AttributeError.
    import src.factors.bench_runner as legacy_mod

    called: dict[str, Any] = {}

    def fake_legacy(**kwargs):
        called.update(kwargs)
        return _legacy_result()

    monkeypatch.setattr(legacy_mod, "run_bench", fake_legacy)
    ns = _ns()
    del ns.horizon
    rc = cli_handlers.cmd_alpha_bench(ns)

    assert rc == 0
    assert called["horizon"] == 1
    capsys.readouterr()


def test_horizon_argparse_parses_and_rejects() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    cli_handlers.add_subparser(sub)

    args = parser.parse_args(["alpha", "bench", "--zoo", "alpha101", "--horizon", "21"])
    assert args.horizon == 21

    args_default = parser.parse_args(["alpha", "bench", "--zoo", "alpha101"])
    assert args_default.horizon == 1

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["alpha", "bench", "--zoo", "alpha101", "--horizon", "0"])
    assert excinfo.value.code == 2

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["alpha", "bench", "--zoo", "alpha101", "--horizon", "abc"])
    assert excinfo.value.code == 2


def test_json_envelope_still_parses_with_horizon(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    import src.factors.bench_runner as legacy_mod

    monkeypatch.setattr(legacy_mod, "run_bench", lambda **kw: _legacy_result())
    rc = cli_handlers.cmd_alpha_bench(_ns(horizon=21))
    assert rc == 0

    out = capsys.readouterr().out
    start = out.find("\n{")
    assert start >= 0
    envelope = json.loads(out[start + 1 :])
    assert envelope["status"] == "ok"


def test_json_envelope_discloses_horizon_and_exclusions(
    capsys, monkeypatch: pytest.MonkeyPatch, _reg, _no_report
) -> None:
    import src.factors.bench_runner as legacy_mod

    result = _legacy_result()
    result.update(
        {
            "horizon": 21,
            "forward_return_sampling": "non_overlapping",
            "universe_excluded": ["fund_roa"],
        }
    )
    monkeypatch.setattr(legacy_mod, "run_bench", lambda **kw: result)
    rc = cli_handlers.cmd_alpha_bench(_ns(horizon=21))
    assert rc == 0

    out = capsys.readouterr().out
    envelope = json.loads(out[out.find("\n{") + 1 :])
    assert envelope["horizon"] == 21
    assert envelope["forward_return_sampling"] == "non_overlapping"
    assert envelope["universe_excluded"] == ["fund_roa"]


def test_parser_rejects_horizon_above_the_cap() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli_handlers.add_subparser(sub)

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["alpha", "bench", "--zoo", "alpha101", "--horizon", "253"])
    assert excinfo.value.code == 2


def test_cli_rejects_horizon_above_cap_with_usage_exit_code(capsys, _reg) -> None:
    rc = cli_handlers.cmd_alpha_bench(_ns(horizon=253))

    assert rc == 2
    assert "--horizon" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [253, 10_000, True, "21"])
def test_run_bench_rejects_out_of_range_horizon_before_panel_load(
    monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    from unittest.mock import Mock

    fetch = Mock()
    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", fetch)
    reg = MagicMock()
    reg.list.return_value = ["alpha_0"]
    reg.get.return_value = MagicMock(meta={"theme": ["test"], "formula_latex": ""})

    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg, horizon=bad)

    assert result["status"] == "error"
    assert "horizon" in result["error"]
    fetch.assert_not_called()


def test_multi_zoo_aggregate_discloses_horizon_and_exclusions() -> None:
    """The all-zoos aggregation must not drop the per-sub-run disclosure keys."""
    import time
    from types import SimpleNamespace

    reg = SimpleNamespace(
        get=lambda aid: SimpleNamespace(zoo="fundamental"),
        list=lambda zoo=None: ["fund_cn"],
    )

    def fake_run_bench(**_kw: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "rows": [{"id": "fund_cn", "ir": 0.5}],
            "skipped": [],
            "horizon": 21,
            "forward_return_sampling": "non_overlapping",
            "universe_excluded": ["fund_us"],
        }

    out = cli_handlers._run_all_zoos_with_progress(
        target_ids=["fund_cn"],
        universe="csi300",
        period="2020-2021",
        top=5,
        start_ts=time.monotonic(),
        reg=reg,
        run_bench=fake_run_bench,
    )

    assert out["status"] == "ok"
    assert out["horizon"] == 21
    assert out["forward_return_sampling"] == "non_overlapping"
    assert out["universe_excluded"] == ["fund_us"]
