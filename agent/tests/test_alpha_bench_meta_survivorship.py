"""``alpha bench`` must forward result["meta"] (issue #797).

bench_runner.run_bench forwards the sp500 loader's survivorship_bias flag as
result["meta"], and alpha_routes._result_for_wire already keeps it for the
SSE/frontend path. cmd_alpha_bench's own JSON envelope and HTML report
context were built from hand-enumerated dict literals that never included
that key, so the CLI/HTML path silently dropped the disclosure.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Rendered-output tests.
#
# The context-level tests above assert on the dict handed to the renderer, with
# _render_html stubbed out. That leaves the renderers themselves unreached: the
# disclosure could be (and was) dropped inside _render_html while every test
# above stayed green. These tests assert on the rendered HTML string instead.
# ---------------------------------------------------------------------------

import src.tools.alpha_bench_tool as tool

_RENDER_CTX = {
    "csp": tool._CSP,
    "css": tool._REPORT_CSS,
    "generated_at": "2026-01-01T00:00:00+00:00",
    "universe": "sp500",
    "period": "2020-2025",
    "n_alphas_tested": 1,
    "n_skipped": 0,
    "top": [
        {
            "id": "alpha001",
            "zoo": "alpha101",
            "theme": ["momentum"],
            "ic_mean": 0.05,
            "ic_std": 0.01,
            "ir": 0.9,
            "ic_positive_ratio": 0.7,
            "ic_count": 100,
            "formula_latex": "x",
        }
    ],
    "failures": [],
    "strict": False,
}


def _ctx(meta=None):
    ctx = dict(_RENDER_CTX)
    ctx["top"] = [dict(_RENDER_CTX["top"][0])]
    if meta is not None:
        ctx["meta"] = meta
    return ctx


@pytest.mark.parametrize("render", [tool._render_html, tool._render_html_manual])
def test_renderers_emit_survivorship_disclosure(render):
    html_out = render(_ctx(dict(_UNIVERSE_META)))
    assert "Survivorship bias" in html_out
    assert "biased upward" in html_out
    # the provenance the loader recorded reaches the reader, not just the flag
    # (escaped: the sp500 source string contains "S&P", which must render as S&amp;P)
    assert html.escape(_UNIVERSE_META["constituent_source"]) in html_out
    assert _UNIVERSE_META["constituent_source_date"] in html_out


@pytest.mark.parametrize("render", [tool._render_html, tool._render_html_manual])
def test_renderers_omit_disclosure_when_no_meta(render):
    assert "Survivorship bias" not in render(_ctx())


@pytest.mark.parametrize("render", [tool._render_html, tool._render_html_manual])
def test_renderers_omit_disclosure_when_flag_false(render):
    meta = dict(_UNIVERSE_META, survivorship_bias=False)
    assert "Survivorship bias" not in render(_ctx(meta))


@pytest.mark.parametrize("render", [tool._render_html, tool._render_html_manual])
def test_renderers_escape_untrusted_provenance(render):
    meta = dict(_UNIVERSE_META, constituent_source="<script>alert(1)</script>")
    html_out = render(_ctx(meta))
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_written_report_file_carries_the_disclosure(capsys, monkeypatch, tmp_path, _reg):
    """End-to-end: the artifact a user keeps, with no renderer stubbed."""
    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path)
    rc, cap = _run(monkeypatch, capsys, _ns(), _result(meta=dict(_UNIVERSE_META)))
    assert rc == 0
    report_path = _envelope(cap.out)["report_path"]
    written = Path(report_path).read_text(encoding="utf-8")
    assert "Survivorship bias" in written
    assert "biased upward" in written
