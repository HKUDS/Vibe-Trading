"""Regression tests for issue #635 — MCP ``factor_analysis`` contract mismatch.

Pre-fix: the MCP wrapper forwarded ``codes``/``factor_name``/``start_date``/
``end_date``/``source``/``top_n``/``bottom_n``, but the registered
``FactorAnalysisTool`` requires ``factor_csv``/``return_csv``/``output_dir`` —
every MCP call died on ``KeyError: 'factor_csv'`` before any analysis ran.
Post-fix: the wrapper mirrors the registered tool's real contract, and these
tests pin that contract so future drift fails loudly.
"""

from __future__ import annotations

import inspect
import json

import pandas as pd

import mcp_server
from src.tools.factor_analysis_tool import FactorAnalysisTool

# fastmcp wraps the tool; reach the raw callable.
_fa = getattr(mcp_server.factor_analysis, "fn", None) or getattr(
    mcp_server.factor_analysis, "__wrapped__", mcp_server.factor_analysis
)


class _RecordingRegistry:
    """Registry stub that captures execute() calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return json.dumps({"status": "ok"})


def test_wrapper_forwards_registered_contract(monkeypatch) -> None:
    """The wrapper must forward exactly the registered tool's argument keys."""
    rec = _RecordingRegistry()
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: rec)

    _fa(factor_csv="f.csv", return_csv="r.csv", output_dir="out", n_groups=3)

    assert rec.calls == [
        (
            "factor_analysis",
            {
                "factor_csv": "f.csv",
                "return_csv": "r.csv",
                "output_dir": "out",
                "n_groups": 3,
            },
        )
    ]


def test_wrapper_signature_matches_registered_tool() -> None:
    """Drift guard: wrapper params must equal FactorAnalysisTool.parameters."""
    spec = FactorAnalysisTool.parameters
    sig = inspect.signature(_fa)

    assert set(sig.parameters) == set(spec["properties"])
    wrapper_required = {name for name, p in sig.parameters.items() if p.default is inspect.Parameter.empty}
    assert wrapper_required == set(spec["required"])


def _write_synthetic_csvs(tmp_path) -> tuple[str, str]:
    """Build minimal factor/return CSVs (6 codes x 12 days, perfectly ranked)."""
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    codes = [f"C{i}" for i in range(6)]
    factor = pd.DataFrame(
        [[float(i * 10 + j) for j in range(6)] for i in range(12)],
        index=dates,
        columns=codes,
    )
    returns = pd.DataFrame(
        [[0.01 * (j + 1) for j in range(6)] for _ in range(12)],
        index=dates,
        columns=codes,
    )
    factor_csv = tmp_path / "factor.csv"
    return_csv = tmp_path / "return.csv"
    factor.to_csv(factor_csv)
    returns.to_csv(return_csv)
    return str(factor_csv), str(return_csv)


def test_well_formed_call_runs_end_to_end(tmp_path) -> None:
    """The issue scenario: a well-formed MCP call reaches the implementation.

    Uses the real tool registry against synthetic CSVs. Pre-fix this raised
    ``KeyError: 'factor_csv'``; post-fix it returns ``status == "ok"`` and
    writes the analysis artifacts.
    """
    factor_csv, return_csv = _write_synthetic_csvs(tmp_path)
    output_dir = tmp_path / "out"

    result = json.loads(
        _fa(
            factor_csv=factor_csv,
            return_csv=return_csv,
            output_dir=str(output_dir),
            n_groups=3,
        )
    )

    assert result["status"] == "ok"
    assert result["ic_count"] == 12
    assert (output_dir / "ic_series.csv").exists()
    assert (output_dir / "ic_summary.json").exists()
    assert (output_dir / "group_equity.csv").exists()
