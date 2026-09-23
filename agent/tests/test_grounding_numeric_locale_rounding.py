"""Locale-aware numbers and rounding by the digits written.

Two general failures of the numeric gate, each reproduced on ``main`` before the fix:

1. ``_numbers`` split a decimal comma with a long fraction ("2,639499655314571") and a
   dotted-thousands number with a decimal comma ("1.234,56") into separate figures, so a
   correct Spanish answer produced ``figure_undeclared`` for the fragments.
2. A figure written rounded ("38,68" for 38.68005857...) was not linked to its precise
   declaration (matching was exact), and the evidence band was a flat 0.5%, wide enough to
   accept "38,50" for 38.6784.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import Declaration, FiguresBlock, _numbers

pytestmark = pytest.mark.unit


def _digits(text: str) -> list[str]:
    return [token.sign + token.digits for token in _numbers(text)]


def _figures(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


def _ledger(tmp_path: Path, payload: dict, tool: str = "risk_tool") -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analizá el riesgo")
    ledger.ingest_tool_result(
        tool_name=tool,
        arguments={},
        result=json.dumps(payload),
        call_id=tool,
        success=True,
    )
    return ledger


# --- 1. decimal comma -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3,17%", ["3.17"]),
        ("17,9318145214327%", ["17.9318145214327"]),
        ("2,639499655314571", ["2", "639499655314571"]),
        ("0,7239869355", ["0.7239869355"]),
        ("-18,41%", ["-18.41"]),
        ("3.17%", ["3.17"]),
        ("17.9318145214327%", ["17.9318145214327"]),
        ("-18.41%", ["-18.41"]),
        ("1,234", ["1234"]),
        ("1,234.56", ["1234.56"]),
        ("1,234,567", ["1234567"]),
        ("1.234,56", ["1234.56"]),
        ("-1.234,56", ["-1234.56"]),
        ("1.234.567,89", ["1234567.89"]),
        ("Vol 3,17% y 1.234,56 ARS", ["3.17", "1234.56"]),
        # Not decimals: unmarked long comma pairs, a year pair and dotted lists
        # keep their separate readings.
        ("1400,1777 元", ["1400", "1777"]),
        ("成交量 1000,2500 手", ["1000", "2500"]),
        ("2023,2024", ["2023", "2024"]),
        ("0.500,0.600", ["0.500", "0.600"]),
        ("1.234,5.6", ["1.234", "5.6"]),
    ],
)
def test_numbers_reads_each_localized_number_as_one_figure(
    text: str, expected: list[str]
) -> None:
    assert _digits(text) == expected


def test_a_declaration_cell_holding_only_a_decimal_comma_is_one_figure(
    tmp_path: Path,
) -> None:
    ledger = _ledger(
        tmp_path,
        {
            "concentration": {"breadth": 2.6394996},
            "vol": {"annualized_vol": 0.3854},
        },
    )
    result = ledger.validate_final_answer(
        "Breadth: 2,64. Volatilidad: 38,54%."
        + _figures(
            "38,54% | observed | annualized_vol | risk_tool",
            "2,64 | observed | breadth | risk_tool",
        )
    )
    assert result.valid is True, result.issues


def test_a_lone_list_like_cell_does_not_flip_the_document_to_decimal_commas() -> None:
    text = "| 5,20 |\nValores correctos: 234,567 y 1,410."
    assert _digits(text) == ["5", "20", "234567", "1410"]




def test_a_long_precision_spanish_percentage_is_verified_not_fragmented(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, {"volatility": {"annualized_vol": 0.38543111445957}})
    assert (
        ledger.validate_final_answer("Volatilidad anualizada: 38,543111445957%.").valid
        is True
    )


def test_a_wrong_long_precision_spanish_percentage_is_still_rejected(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, {"volatility": {"annualized_vol": 0.38543111445957}})
    assert (
        ledger.validate_final_answer("Volatilidad anualizada: 41,123456789012%.").valid
        is False
    )


# --- 2. rounding by the digits written ---------------------------------------------------

AUX = {"aux": {"annualized_vol": 0.0125}}


def _with_aux(prose: str, comma: bool) -> str:
    # A second exactly-declared percentage makes the document a decimal-comma one, so the
    # figure under test is read as a decimal and not as two bare integers.
    return prose + (" Vol diaria 1,25%." if comma else " Vol diaria 1.25%.")


@pytest.mark.parametrize(
    ("payload", "prose", "declared"),
    [
        (
            {"indicators": {"rsi_14": 38.68005857871268}},
            "RSI 14: 38,68.",
            "38.68005857871268",
        ),
        (
            {"indicators": {"rsi_14": 38.68005857871268}},
            "RSI 14: 38.68.",
            "38.68005857871268",
        ),
        (
            {"volatility": {"annualized_vol": 0.38543109}},
            "Volatilidad: 38,54%.",
            "38.543109%",
        ),
        (
            {"concentration": {"breadth": 2.63949965}},
            "Breadth: 2,64.",
            "2.63949965",
        ),
        (
            {"volatility": {"annualized_vol": 0.30205165}},
            "Volatilidad: 30,21%.",
            "30.205165%",
        ),
    ],
)
def test_rounded_prose_is_linked_to_its_precise_observation(
    tmp_path: Path, payload: dict, prose: str, declared: str
) -> None:
    leaf = next(iter(next(iter(payload.values()))))
    result = _ledger(tmp_path, {**payload, **AUX}).validate_final_answer(
        _with_aux(prose, "," in prose)
        + _figures(
            f"{declared} | observed | {leaf} | risk_tool",
            "1.25% | observed | annualized_vol | risk_tool",
        )
    )
    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    "prose", ["Volatilidad: 38,50%.", "Volatilidad: 38,90%.", "Volatilidad: 39,00%."]
)
def test_a_materially_different_figure_is_rejected_even_inside_the_old_half_percent_band(
    tmp_path: Path, prose: str
) -> None:
    result = _ledger(
        tmp_path, {"volatility": {"annualized_vol": 0.386784123}, **AUX}
    ).validate_final_answer(
        _with_aux(prose, True)
        + _figures(
            "38.6784123% | observed | annualized_vol | risk_tool",
            "1.25% | observed | annualized_vol | risk_tool",
        )
    )
    assert result.valid is False, result.issues


def test_a_value_that_rounds_the_other_way_is_rejected(tmp_path: Path) -> None:
    """30.205165 rounds to 30,21; 30,20 is 0.0052 away, outside half a unit of two decimals."""
    result = _ledger(
        tmp_path, {"volatility": {"annualized_vol": 0.30205165}, **AUX}
    ).validate_final_answer(
        _with_aux("Volatilidad: 30,20%.", True)
        + _figures(
            "30.205165% | observed | annualized_vol | risk_tool",
            "1.25% | observed | annualized_vol | risk_tool",
        )
    )
    assert result.valid is False, result.issues


@pytest.mark.parametrize(
    ("prose", "valid"),
    [
        ("Volatilidad: 38,68% y 1,25%.", True),
        ("Volatilidad: 38,50% y 1,25%.", False),
        ("Volatilidad: 38,7% y 1,25%.", True),
        ("Volatilidad: 38,5% y 1,25%.", False),
    ],
)
def test_an_undeclared_figure_is_grounded_only_within_its_own_rounding(
    tmp_path: Path, prose: str, valid: bool
) -> None:
    ledger = _ledger(tmp_path, {"volatility": {"annualized_vol": 0.386784123}, **AUX})
    result = ledger.validate_final_answer(
        prose + _figures("1.25% | observed | annualized_vol | risk_tool")
    )
    assert result.valid is valid, result.issues


@pytest.mark.parametrize(
    ("declared", "declared_percent", "written", "digits", "written_percent", "linked"),
    [
        (38.68005857871268, False, 38.68, "38.68", False, True),
        (38.68005857871268, False, 38.5, "38.5", False, False),
        (38.68005857871268, False, 38.50, "38.50", False, False),
        (38.68005857871268, False, 39.0, "39", False, False),
        (2.63949965, False, 2.64, "2.64", False, True),
        (2.6395, False, 2.50, "2.50", False, False),
        (38.543109, True, 38.54, "38.54", True, True),
        (
            38.543109,
            True,
            38.54,
            "38.54",
            False,
            False,
        ),  # 37% and 0.37 stay different assertions
        (-18.406041, True, -18.41, "18.41", True, True),
        (
            -18.406041,
            True,
            18.41,
            "18.41",
            True,
            False,
        ),  # the sign is part of the claim
    ],
)
def test_declaration_matching_follows_the_digits_written(
    declared, declared_percent, written, digits, written_percent, linked
) -> None:
    declaration = Declaration(
        index=1,
        value_text=str(declared),
        value=declared,
        percent=declared_percent,
        role="observed",
        note="",
        ref="tool",
    )
    block = FiguresBlock(True, (0, 0), "", (declaration,), ())
    assert (block.match(written, written_percent, digits) is not None) is linked


def test_an_integer_keeps_the_previous_behaviour(tmp_path: Path) -> None:
    """An integer's precision is unknown ("6,700" may be rounded to hundreds): the flat band still applies."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="precio")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {
                "AAPL.US": [
                    {
                        "trade_date": "2026-09-18T00:00:00",
                        "open": 6685.0,
                        "high": 6690.0,
                        "low": 6650.0,
                        "close": 6685.0,
                        "volume": 100,
                    }
                ]
            }
        ),
        call_id="prices",
        success=True,
    )
    # 6690 is 0.07% from the 6685 print: accepted by the flat band, as before.
    assert ledger.validate_final_answer("AAPL.US cerró en 6690 USD.").valid is True
