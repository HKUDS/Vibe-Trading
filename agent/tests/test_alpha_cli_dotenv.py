"""Regression: ``alpha bench`` / ``alpha compare`` must load .env before config reads.

The ``alpha`` dispatch path skips ``cli._legacy._ensure_cli_env``, so the
pip-installed CLI never loaded ``~/.vibe-trading/.env`` on this path and the
csi300 universe failed with "TUSHARE_TOKEN not in agent/.env or environment".
"""

from __future__ import annotations

import argparse
import os

import pytest

from src.factors import cli_handlers


class _FakeReg:
    def list(self, zoo=None):
        return ["alpha001", "alpha002"]


@pytest.fixture()
def _reg(monkeypatch):
    monkeypatch.setattr(cli_handlers, "Registry", _FakeReg)


@pytest.fixture()
def _no_report(monkeypatch, tmp_path):
    """Keep the HTML report side effect contained."""
    import src.tools.alpha_bench_tool as tool

    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path)


@pytest.fixture()
def _order(monkeypatch):
    """Record the call order of dotenv loading vs. the actual work."""
    import src.providers.llm as llm

    order: list[str] = []
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: order.append("env"))
    return order


def _ns_bench(**overrides):
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
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _ns_compare(**overrides):
    base = dict(
        alpha_ids=["alpha001", "alpha002"],
        zoo=None,
        universe="csi300",
        period="2020-2025",
        sort="ir",
        compare_all=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _legacy_result():
    return {
        "status": "ok",
        "alive": 2,
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


def _compare_envelope():
    return {
        "status": "ok",
        "n_compared": 2,
        "n_skipped": 0,
        "winner": "alpha001",
        "ranking": [
            {
                "rank": 1,
                "id": "alpha001",
                "zoo": "alpha101",
                "ic_mean": 0.05,
                "ic_std": 0.01,
                "ir": 0.9,
                "ic_positive_ratio": 0.7,
                "ic_count": 100,
                "delta_ir_vs_best": 0.0,
            },
            {
                "rank": 2,
                "id": "alpha002",
                "zoo": "alpha101",
                "ic_mean": 0.03,
                "ic_std": 0.01,
                "ir": 0.6,
                "ic_positive_ratio": 0.6,
                "ic_count": 100,
                "delta_ir_vs_best": -0.3,
            },
        ],
    }


def test_bench_loads_dotenv_before_runner(capsys, monkeypatch, _reg, _no_report, _order):
    """The token must be loaded before the bench runner reads the universe."""
    import src.factors.bench_runner as legacy_mod

    order = _order

    def fake_legacy(**kwargs):
        order.append("run")
        return _legacy_result()

    monkeypatch.setattr(legacy_mod, "run_bench", fake_legacy)
    rc = cli_handlers.cmd_alpha_bench(_ns_bench())
    assert rc == 0
    assert order.count("env") >= 1
    assert order.index("env") < order.index("run")


def test_compare_loads_dotenv_before_compare(capsys, monkeypatch, _reg, _order):
    """``alpha compare`` benches too, so it needs the same guard."""
    order = _order

    def fake_compare(targets, universe, period, sort, registry):
        order.append("run")
        return _compare_envelope()

    monkeypatch.setattr(cli_handlers, "compare_alphas", fake_compare)
    rc = cli_handlers.cmd_alpha_compare(_ns_compare())
    assert rc == 0
    assert order.count("env") >= 1
    assert order.index("env") < order.index("run")


def test_load_cli_env_swallows_dotenv_errors(monkeypatch):
    """A broken .env must not crash the command; the downstream error does."""
    import src.providers.llm as llm

    def boom():
        raise RuntimeError("dotenv unreadable")

    monkeypatch.setattr(llm, "_ensure_dotenv", boom)
    cli_handlers._load_cli_env()  # must not raise


def test_load_cli_env_reads_dotenv_file(monkeypatch, tmp_path):
    """End-to-end: a token present only in .env reaches get_env_config()."""
    import src.providers.llm as llm

    from src.config.accessor import get_env_config

    dotenv = tmp_path / ".env"
    token = "cli_dotenv_regression_token"
    dotenv.write_text(f"TUSHARE_TOKEN={token}\n", encoding="utf-8")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(llm, "_ENV_CANDIDATES", [dotenv])
    monkeypatch.setattr(llm, "_dotenv_loaded", False)

    try:
        cli_handlers._load_cli_env()
        assert os.environ.get("TUSHARE_TOKEN") == token
        assert get_env_config().data.tushare_token == token
    finally:
        os.environ.pop("TUSHARE_TOKEN", None)
