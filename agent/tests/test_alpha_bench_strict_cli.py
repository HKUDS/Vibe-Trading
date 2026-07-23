"""Tests for the ``alpha bench --strict`` CLI wiring (issue #773)."""

from __future__ import annotations

import argparse
import json

import pytest

from src.factors import cli_handlers


def _ns(**overrides):
    base = dict(
        zoo="alpha101",
        universe="csi300",
        period="2020-2025",
        top=20,
        yes=True,
        strict=False,
        oos_split=None,
        random_seeds=5,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _strict_result():
    return {
        "status": "ok",
        "confirmed_alive": 2,
        "train_only": 1,
        "reversed_strict": 0,
        "noise": 5,
        "oos_split": "2023-01-01",
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
            }
        ],
        "skipped": [],
        "wall_seconds": 1.0,
    }


def _legacy_result():
    return {
        "status": "ok",
        "alive": 3,
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


def _envelope(out: str) -> dict:
    """Extract the JSON envelope from mixed stdout (banner lines + JSON)."""
    start = out.find("\n{")
    if start < 0:
        start = out.find("{") if out.lstrip().startswith("{") else -1
        if start < 0:
            raise AssertionError(f"no JSON envelope in stdout: {out[:200]!r}")
    else:
        start += 1
    return json.loads(out[start:])


class _FakeReg:
    def list(self, zoo=None):
        return ["alpha001", "alpha002"]

    def get(self, aid):
        class _Entry:
            zoo = "alpha101"
            meta = {"theme": ["momentum"], "formula_latex": "x"}

        return _Entry()


@pytest.fixture()
def _no_report(monkeypatch, tmp_path):
    """Keep the HTML report side effect contained."""
    import src.tools.alpha_bench_tool as tool

    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path)


@pytest.fixture()
def _reg(monkeypatch):
    monkeypatch.setattr(cli_handlers, "Registry", _FakeReg)


def _run(capsys, args, monkeypatch):
    import src.factors.bench_runner_strict as strict_mod

    called = {}

    def fake_strict(zoo, universe, period, **kwargs):
        called.update(kwargs)
        return _strict_result()

    monkeypatch.setattr(strict_mod, "run_bench_strict", fake_strict)
    rc = cli_handlers.cmd_alpha_bench(args)
    return rc, called, capsys.readouterr()


def test_strict_routes_to_strict_runner(capsys, monkeypatch, _reg, _no_report):
    rc, called, cap = _run(capsys, _ns(strict=True, oos_split="2023-01-01", random_seeds=3), monkeypatch)
    assert rc == 0
    assert called["random_control"] is True
    assert called["oos_split"] == "2023-01-01"
    assert called["n_random_seeds"] == 3
    envelope = _envelope(cap.out)
    assert envelope["strict"] is True
    assert envelope["confirmed_alive"] == 2
    assert envelope["noise"] == 5
    assert envelope["oos_split"] == "2023-01-01"
    assert envelope["top"][0]["category"] == "confirmed_alive"


def test_default_routes_to_legacy_runner(capsys, monkeypatch, _reg, _no_report):
    import src.factors.bench_runner as legacy_mod

    called = {}

    def fake_legacy(**kwargs):
        called.update(kwargs)
        return _legacy_result()

    monkeypatch.setattr(legacy_mod, "run_bench", fake_legacy)
    rc = cli_handlers.cmd_alpha_bench(_ns())
    assert rc == 0
    assert called["zoo"] == "alpha101"
    envelope = _envelope(capsys.readouterr().out)
    assert "strict" not in envelope
    assert envelope["top"][0]["category"] == "alive"


def test_oos_split_without_strict_is_rejected(capsys, monkeypatch, _reg):
    rc = cli_handlers.cmd_alpha_bench(_ns(oos_split="2023-01-01"))
    assert rc == 1
    assert "--strict" in capsys.readouterr().err


def test_strict_argparse_flags():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    alpha_parser = cli_handlers.add_subparser(sub)
    args = parser.parse_args(
        ["alpha", "bench", "--zoo", "alpha101", "--strict", "--oos-split", "2023-01-01", "--random-seeds", "3"]
    )
    assert args.strict is True
    assert args.oos_split == "2023-01-01"
    assert args.random_seeds == 3
    args_default = parser.parse_args(["alpha", "bench", "--zoo", "alpha101"])
    assert args_default.strict is False
    assert args_default.oos_split is None
    assert args_default.random_seeds == 5
    assert alpha_parser is not None


def test_strict_result_envelope_marks_counts(capsys, monkeypatch, _reg, _no_report):
    rc, called, cap = _run(capsys, _ns(strict=True), monkeypatch)
    assert rc == 0
    assert called["random_control"] is True
    assert called["oos_split"] is None
    assert called["n_random_seeds"] == 5
