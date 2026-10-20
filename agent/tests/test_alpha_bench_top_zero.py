"""``top=0`` must be rejected, not silently replaced by the default of 20."""

from __future__ import annotations

import pytest

from src.tools.alpha_bench_tool import run_alpha_bench


@pytest.mark.parametrize("bad", [0, -3, "0"])
def test_non_positive_top_is_rejected(bad):
    out = run_alpha_bench(universe="csi300", period="2020-2025", top=bad)
    assert out == {"status": "error", "error": "top must be > 0"}


@pytest.mark.parametrize("bad", ["abc", float("inf"), float("nan"), 1.5, True, [1]])
def test_non_integer_top_is_an_error_envelope(bad):
    out = run_alpha_bench(universe="csi300", period="2020-2025", top=bad)
    assert out["status"] == "error"
    assert "top" in out["error"]


def test_omitted_top_is_not_rejected_as_top():
    out = run_alpha_bench(universe="csi300", period="2020-2025")
    assert "top must" not in out.get("error", "")
