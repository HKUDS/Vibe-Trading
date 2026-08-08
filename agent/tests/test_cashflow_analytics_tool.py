"""Tests for the agent-facing cashflow_performance tool envelope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.cashflow_analytics_tool import CashFlowPerformanceTool


def _valuations() -> list[dict[str, object]]:
    """Return the fixture path: +10% on 100, 900 arrives, then -10%."""
    return [
        {"date": "2024-01-01", "value": 100.0},
        {"date": "2024-07-01", "value": 1010.0},
        {"date": "2024-12-31", "value": 909.0},
    ]


def _inline_contribution() -> list[dict[str, object]]:
    """Return the matching client contribution, holder-perspective."""
    return [
        {
            "date": "2024-07-01",
            "amount": -900.0,
            "kind": "contribution",
            "currency": "USD",
        }
    ]


def _write_flow_file(tmp_path: Path) -> Path:
    """Write a two-row broker-style cash-flow CSV.

    Args:
        tmp_path: pytest temporary directory.

    Returns:
        Path to the written file.
    """
    path = tmp_path / "client_flows.csv"
    path.write_text(
        "date,amount,kind,currency\n"
        "2024-07-01,-900.00,contribution,USD\n"
        "2024-09-01,40.00,dividend,USD\n",
        encoding="utf-8",
    )
    return path


def test_envelope_reports_all_three_measures_and_their_workings() -> None:
    """The success envelope is well formed, serializable, and self-auditing."""
    payload = json.loads(
        CashFlowPerformanceTool().execute(
            valuations=_valuations(),
            flows=_inline_contribution(),
        )
    )

    assert payload["status"] == "ok"
    assert payload["tool"] == "cashflow_performance"
    assert payload["inputs"]["flow_source"] == "inline"
    assert payload["inputs"]["currency"] == "USD"
    assert payload["inputs"]["flow_timing"] == "end"

    summary = payload["summary"]
    assert summary["start_date"] == "2024-01-01"
    assert summary["end_date"] == "2024-12-31"
    assert summary["net_external_flow"] == pytest.approx(900.0)
    assert summary["time_weighted_return"] == pytest.approx(-0.01, abs=1e-9)
    # The client's own money was far worse off than the manager's unit of capital.
    assert summary["money_weighted_return_annualized"] < -0.10
    assert summary["modified_dietz_return"] < -0.10

    assert [period["return"] for period in payload["sub_periods"]] == pytest.approx(
        [0.10, -0.10], abs=1e-9
    )
    assert payload["modified_dietz"]["flow_weights"] == [
        {"date": "2024-07-01", "amount": 900.0, "weight": pytest.approx(0.50137, abs=1e-5)}
    ]
    assert payload["money_weighted"]["solver_iterations"] > 0
    assert payload["notes"] == []
    assert payload["limitations"]


def test_flows_can_be_loaded_from_a_file_and_internal_kinds_are_ignored(
    tmp_path: Path,
) -> None:
    """A dividend row sits inside the valuations and must not be netted out."""
    payload = json.loads(
        CashFlowPerformanceTool().execute(
            valuations=_valuations(),
            flows_path=str(_write_flow_file(tmp_path)),
        )
    )

    assert payload["status"] == "ok"
    assert payload["inputs"]["flow_source"] == "flows_path"
    assert payload["inputs"]["flow_count"] == 2
    # Two rows read, one external: the dividend is internal.
    assert payload["summary"]["net_external_flow"] == pytest.approx(900.0)
    assert payload["summary"]["time_weighted_return"] == pytest.approx(-0.01, abs=1e-9)


def test_a_bad_path_returns_a_clean_error_envelope(tmp_path: Path) -> None:
    """A missing file is an explicit error, never a silent null result."""
    payload = json.loads(
        CashFlowPerformanceTool().execute(
            valuations=_valuations(),
            flows_path=str(tmp_path / "does_not_exist.csv"),
        )
    )

    assert payload["status"] == "error"
    assert payload["tool"] == "cashflow_performance"
    assert "does_not_exist.csv" in payload["error"]
    assert "money_weighted" not in payload


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"valuations": [{"date": "2024-01-01", "value": 100.0}]}, "at least two"),
        ({"valuations": _valuations(), "flow_timing": "middle"}, "flow_timing must be"),
        (
            {
                "valuations": _valuations(),
                "flows": _inline_contribution(),
                "flows_path": "somewhere.csv",
            },
            "not both",
        ),
        (
            {
                "valuations": _valuations(),
                "flows": [{"date": "2024-07-01", "amount": -900.0, "kind": "contribution"}],
            },
            "no currency",
        ),
        (
            {
                "valuations": _valuations(),
                "flows": [
                    {
                        "date": "2024-07-01",
                        "amount": 900.0,
                        "kind": "contribution",
                        "currency": "USD",
                    }
                ],
            },
            "negative (cash out)",
        ),
        (
            {
                "valuations": _valuations(),
                "flows": [
                    {
                        "date": "2024-07-01",
                        "amount": -900.0,
                        "kind": "wire_in",
                        "currency": "USD",
                    }
                ],
            },
            "neither external nor internal",
        ),
    ],
)
def test_invalid_input_returns_an_error_envelope(
    kwargs: dict[str, object], fragment: str
) -> None:
    """Every rejection path produces the same shape, with a usable message."""
    payload = json.loads(CashFlowPerformanceTool().execute(**kwargs))
    assert payload["status"] == "error"
    assert fragment in payload["error"]


def test_reclassifying_a_custom_kind_makes_it_external() -> None:
    """The escape hatch from the unclassified-kind error actually works."""
    payload = json.loads(
        CashFlowPerformanceTool().execute(
            valuations=_valuations(),
            flows=[
                {
                    "date": "2024-07-01",
                    "amount": -900.0,
                    "kind": "wire_in",
                    "currency": "USD",
                }
            ],
            external_kinds=["wire_in"],
        )
    )
    assert payload["status"] == "ok"
    assert payload["summary"]["net_external_flow"] == pytest.approx(900.0)
    assert "wire_in" in payload["inputs"]["external_kinds"]


def test_an_unsolvable_irr_is_reported_as_a_note_not_a_failure() -> None:
    """A total loss with no distributions has no IRR; the rest still ships."""
    payload = json.loads(
        CashFlowPerformanceTool().execute(
            valuations=[
                {"date": "2024-01-01", "value": 1000.0},
                {"date": "2024-12-31", "value": 0.0},
            ]
        )
    )

    assert payload["status"] == "ok"
    assert payload["summary"]["time_weighted_return"] == -1.0
    assert payload["summary"]["modified_dietz_return"] == -1.0
    assert payload["summary"]["money_weighted_return_annualized"] is None
    assert payload["money_weighted"] is None
    assert any("one-directional" in note for note in payload["notes"])


def test_the_tool_is_auto_discovered_by_the_agent_registry() -> None:
    """Creating the module is sufficient to expose the read-only agent tool."""
    from src.tools import build_registry

    registry = build_registry()
    tool = registry.get("cashflow_performance")
    assert tool is not None
    assert tool.is_readonly is True


def test_the_tool_places_no_orders() -> None:
    """Guard the red line: this is a research surface with no execution path."""
    from src.tools import cashflow_analytics_tool

    source = Path(cashflow_analytics_tool.__file__).read_text(encoding="utf-8")
    assert "place_order" not in source
    assert "cancel_order" not in source
