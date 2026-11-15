"""Generic grounding gaps found while grounding real multi-tool reports.

Each case pairs the accepted shape with the near miss that must stay rejected:
a currency-stamped period valuation, thousands grouped by periods, a compact
year-horizon label, and a derived percent difference over percent-named fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.grounding import GroundingLedger
from evals.grounding.figures import parse_figures_block, scan_figures

pytestmark = pytest.mark.unit


def _ledger(
    tmp_path: Path, payload: dict, tool: str = "account_summary"
) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the figures.")
    ledger.ingest_tool_result(
        tool_name=tool,
        arguments={},
        result=json.dumps(payload),
        call_id="c1",
        success=True,
    )
    return ledger


def _answer(prose: str, *lines: str) -> str:
    return prose + "\n\n```figures\n" + "\n".join(lines) + "\n```"


def _reasons(result) -> list[str]:
    return [issue.get("reason") or issue.get("code") for issue in result.issues]


# -- period valuation stamped with the currency its own object declares ------------

ACCOUNT = {
    "status": "ok",
    "data": {
        "account": {"value_start": 1250.75, "value_end": 1400.25, "currency": "USD"}
    },
}


def test_period_valuation_takes_the_currency_its_object_declares(
    tmp_path: Path,
) -> None:
    result = _ledger(tmp_path, ACCOUNT).validate_final_answer(
        _answer(
            "Opened at 1250.75 USD and closed at 1400.25 USD.",
            "1250.75 | observed | opening value | c1::data.account.value_start",
            "1400.25 | observed | closing value | c1::data.account.value_end",
        )
    )

    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    ("prose", "line"),
    [
        (
            "Opened at 1250.75 EUR.",
            "1250.75 | observed | opening | c1::data.account.value_start",
        ),
        (
            "Opened at 1251.75 USD.",
            "1251.75 | observed | opening | c1::data.account.value_start",
        ),
        (
            "Closed at 1250.75 USD.",
            "1250.75 | observed | closing | c1::data.account.value_end",
        ),
    ],
)
def test_period_valuation_stays_closed_to_other_currency_value_and_field(
    tmp_path: Path, prose: str, line: str
) -> None:
    result = _ledger(tmp_path, ACCOUNT).validate_final_answer(_answer(prose, line))

    assert result.valid is False


def test_declared_currency_does_not_leak_to_non_amount_leaves(tmp_path: Path) -> None:
    payload = {
        "status": "ok",
        "data": {"account": {"currency": "USD", "positions": 12}},
    }
    ledger = _ledger(tmp_path, payload)

    assert {record.field: record.currency for record in ledger._evidence} == {
        "data.account.positions": None
    }


def test_declared_currency_is_scoped_to_its_own_object(tmp_path: Path) -> None:
    payload = {
        "status": "ok",
        "data": {
            "usd": {"value_end": 10.0, "currency": "USD"},
            "other": {"value_end": 20.0},
        },
    }
    ledger = _ledger(tmp_path, payload)

    assert {record.field: record.currency for record in ledger._evidence} == {
        "data.usd.value_end": "USD",
        "data.other.value_end": None,
    }


# -- thousands grouped by periods ---------------------------------------------------

REPORT = {"status": "ok", "data": {"net_income_millions": 1618596}}


def test_period_grouped_thousands_read_as_one_figure() -> None:
    text = "Resultado neto: 1.618.596 millones."
    measured = [
        f
        for f in scan_figures(text, parse_figures_block(text))
        if f.shape == "measured"
    ]

    assert [(f.text, f.value) for f in measured] == [("1.618.596", 1618596.0)]


def test_period_grouped_thousands_ground_against_observed_value(tmp_path: Path) -> None:
    result = _ledger(tmp_path, REPORT).validate_final_answer(
        _answer(
            "Resultado neto: 1.618.596 millones.",
            "1618596 | observed | net income | c1::data.net_income_millions",
        )
    )

    assert result.valid is True, result.issues


def test_period_grouped_thousands_stay_closed_to_a_wrong_value(tmp_path: Path) -> None:
    result = _ledger(tmp_path, REPORT).validate_final_answer(
        _answer(
            "Resultado neto: 1.628.596 millones.",
            "1628596 | observed | net income | c1::data.net_income_millions",
        )
    )

    assert result.valid is False


def test_a_single_period_group_keeps_its_decimal_reading() -> None:
    text = "El ratio fue 45.850 veces."
    figures = scan_figures(text, parse_figures_block(text))

    assert [f.value for f in figures] == [45.85]


@pytest.mark.parametrize("text", ["1.618.5", "1.61.596", "1.618.5960"])
def test_malformed_period_groups_are_not_thousands(text: str) -> None:
    figures = scan_figures(f"Valor {text}.", parse_figures_block(f"Valor {text}."))

    assert 1618596.0 not in {f.value for f in figures}
    assert 16185960.0 not in {f.value for f in figures}


# -- compact year-horizon table labels ---------------------------------------------


def _table_shapes(table: str) -> dict[str, str]:
    return {f.text: f.shape for f in scan_figures(table, parse_figures_block(table))}


@pytest.mark.parametrize("label", ["1Y", "5y", "10Y"])
def test_year_horizon_label_is_not_a_measurement(label: str) -> None:
    shapes = _table_shapes(f"| Horizon | Return |\n|---|---|\n| {label} | 0.5 |")

    assert shapes[label.rstrip("Yy")] == "bare"
    assert shapes["0.5"] == "measured"


@pytest.mark.parametrize("cell", ["5M", "1.5Y"])
def test_other_suffixed_cells_are_still_measured(cell: str) -> None:
    shapes = _table_shapes(f"| Horizon | Return |\n|---|---|\n| {cell} | 0.5 |")

    assert "measured" in {shape for text, shape in shapes.items() if text != "0.5"}


def test_year_horizon_label_does_not_exempt_the_return_it_labels(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, {"status": "ok", "data": {"r": 0.5}})
    table = "| Horizon | Return |\n|---|---|\n| 1Y | 0.9 |\n"
    result = ledger.validate_final_answer(
        _answer(table, "0.9 | observed | return | c1::data.r")
    )

    assert result.valid is False


# -- derived percent difference over percent-named fields ---------------------------

RISK = {"data": {"snapshot_id": "s", "top1_pct": 20.36, "top5_pct": 61.56}}
REFS = "c1::data.top5_pct; c1::data.top1_pct"


def test_derived_percent_over_exact_percent_refs_reads_as_points(
    tmp_path: Path,
) -> None:
    result = _ledger(tmp_path, RISK, tool="concentration_report").validate_final_answer(
        _answer("Spread: 41.2%.", f"41.2% | derived | 61.56 - 20.36 | {REFS}")
    )

    assert result.valid is True, result.issues


def test_derived_percent_over_exact_percent_refs_rejects_the_100x_reading(
    tmp_path: Path,
) -> None:
    result = _ledger(tmp_path, RISK, tool="concentration_report").validate_final_answer(
        _answer("Spread: 4120%.", f"4120% | derived | 61.56 - 20.36 | {REFS}")
    )

    assert result.valid is False


def test_derived_percent_rejects_a_wrong_difference(tmp_path: Path) -> None:
    result = _ledger(tmp_path, RISK, tool="concentration_report").validate_final_answer(
        _answer("Spread: 40.2%.", f"40.2% | derived | 61.56 - 20.36 | {REFS}")
    )

    assert result.valid is False


def test_missing_ref_is_not_substituted_for_the_operand(tmp_path: Path) -> None:
    result = _ledger(tmp_path, RISK, tool="concentration_report").validate_final_answer(
        _answer(
            "Spread: 41.2%.",
            "41.2% | derived | 61.56 - 20.36 | c1::data.top5_pct; c1::data.ghost_pct",
        )
    )

    assert result.valid is False


def test_plain_ref_fields_keep_the_fraction_reading(tmp_path: Path) -> None:
    payload = {"data": {"top5_weight": 61.56, "top1_weight": 20.36}}
    plain_refs = "c1::data.top5_weight; c1::data.top1_weight"
    ledger = _ledger(tmp_path, payload, tool="concentration_report")

    points = ledger.validate_final_answer(
        _answer("Spread: 41.2%.", f"41.2% | derived | 61.56 - 20.36 | {plain_refs}")
    )

    assert points.valid is False


@pytest.mark.parametrize("nested", [{"value_end": 20.0}, [{"value_end": 20.0}]])
def test_currency_does_not_cross_into_nested_objects(tmp_path, nested):
    ledger = _ledger(tmp_path, {"data": {"currency": "USD", "value_end": 10.0, "child": nested}})
    currencies = {record.field: record.currency for record in ledger._evidence}
    assert currencies.pop("data.value_end") == "USD"
    assert set(currencies.values()) == {None}
