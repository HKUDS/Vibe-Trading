"""``alpha bench`` must forward result["meta"] (issue #797).

bench_runner.run_bench forwards the sp500 loader's survivorship_bias flag as
result["meta"], and alpha_routes._result_for_wire already keeps it for the
SSE/frontend path. cmd_alpha_bench's own JSON envelope and HTML report
context were built from hand-enumerated dict literals that never included
that key, so the CLI/HTML path silently dropped the disclosure.
"""

from __future__ import annotations

import argparse
import json

import pytest

from src.factors import cli_handlers


def _ns(**overrides):
    base = dict(
        zoo="alpha101",
        universe="sp500",
        period="2020-2025",
        top=20,
        yes=True,
        strict=False,
        oos_split=None,
        random_seeds=5,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _result(**overrides):
    base = {
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
    base.update(overrides)
    return base


_UNIVERSE_META = {
    "universe": "sp500",
    "survivorship_bias": True,
    "constituent_source": "current wiki S&P 500 list",
    "constituent_source_date": "2026-01-01",
    "constituent_count": 500,
}


class _FakeReg:
    def list(self, zoo=None):
        return ["alpha001"]

    def get(self, aid):
        class _Entry:
            zoo = "alpha101"
            meta = {"theme": ["momentum"], "formula_latex": "x"}

        return _Entry()


def _envelope(out: str) -> dict:
    start = out.find("\n{")
    if start < 0:
        start = out.find("{") if out.lstrip().startswith("{") else -1
        if start < 0:
            raise AssertionError(f"no JSON envelope in stdout: {out[:200]!r}")
    else:
        start += 1
    return json.loads(out[start:])


@pytest.fixture()
def _reg(monkeypatch):
    monkeypatch.setattr(cli_handlers, "Registry", _FakeReg)


@pytest.fixture()
def _captured_html_context(monkeypatch):
    """Capture the context dict handed to the HTML renderer, write nothing."""
    import src.tools.alpha_bench_tool as tool

    captured = {}

    def fake_render_html(context):
        captured.update(context)
        return "<html></html>"

    monkeypatch.setattr(tool, "_render_html", fake_render_html)
    return captured


def _run(monkeypatch, capsys, args, result):
    import src.factors.bench_runner as legacy_mod

    monkeypatch.setattr(legacy_mod, "run_bench", lambda **kw: result)
    rc = cli_handlers.cmd_alpha_bench(args)
    return rc, capsys.readouterr()


def test_envelope_includes_universe_meta_when_present(capsys, monkeypatch, _reg, _captured_html_context):
    rc, cap = _run(monkeypatch, capsys, _ns(), _result(meta=dict(_UNIVERSE_META)))
    assert rc == 0
    envelope = _envelope(cap.out)
    assert envelope["meta"] == _UNIVERSE_META


def test_html_context_includes_universe_meta_when_present(capsys, monkeypatch, _reg, _captured_html_context):
    rc, _cap = _run(monkeypatch, capsys, _ns(), _result(meta=dict(_UNIVERSE_META)))
    assert rc == 0
    assert _captured_html_context["meta"] == _UNIVERSE_META


def test_meta_key_absent_from_envelope_and_context_when_loader_has_none(capsys, monkeypatch, _reg, _captured_html_context):
    """Loaders without _meta must not gain a stray downstream key."""
    rc, cap = _run(monkeypatch, capsys, _ns(universe="btc-usdt"), _result())
    assert rc == 0
    envelope = _envelope(cap.out)
    assert "meta" not in envelope
    assert "meta" not in _captured_html_context
