"""Tests for the run card's structured_metrics block.

`write_run_card` stores only scalar metrics in `card["metrics"]`. Non-scalar
metrics are carried under a sibling `structured_metrics` key so that a value the
engine authors for card readers cannot be silently discarded.
"""

from __future__ import annotations

import json
from pathlib import Path

from backtest.run_card import write_run_card


def test_structured_metrics_survive_without_widening_metrics(tmp_path: Path) -> None:
    """#1235/#1274: a dropped sleeve must stay visible by name in the card.

    `metrics` is a scalar-only surface, so a dict-shaped rejection map is
    filtered out of it. It must not vanish from the card altogether: the
    scalar count alone cannot say *which* sleeve was dropped.
    """
    metrics = {
        "sharpe": 1.42,
        "unfilled_plan_rejections": 551,
        "unfilled_plan_rejections_by_symbol": {"BIL": {"zero_size": 12}},
        "dropped_target_adjustments": [],
    }

    card = write_run_card(tmp_path, {"codes": ["BIL"], "source": "auto"}, metrics)

    # the scalar surface is unchanged - anything asserting on it still holds
    assert card["metrics"] == {
        "sharpe": 1.42,
        "unfilled_plan_rejections": 551,
    }
    # ...but the named evidence is now carried, not discarded
    assert card["structured_metrics"]["unfilled_plan_rejections_by_symbol"] == {"BIL": {"zero_size": 12}}
    assert card["structured_metrics"]["dropped_target_adjustments"] == []

    on_disk = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert on_disk["structured_metrics"]["unfilled_plan_rejections_by_symbol"] == {"BIL": {"zero_size": 12}}
    md = (tmp_path / "run_card.md").read_text(encoding="utf-8")
    # Rendering must be driven by the structured block, not by the config summary:
    # the symbol alone also appears under ## Backtest, so assert the rendered value.
    assert "## Structured metrics" in md
    assert 'unfilled_plan_rejections_by_symbol: {"BIL": {"zero_size": 12}}' in md


def test_oversized_structured_metric_is_omitted_and_named(tmp_path: Path) -> None:
    """The card is read on every run; a structured metric must not grow it unbounded.

    A large map is named under `_omitted` rather than silently carried, so the
    card stays bounded without the data disappearing unannounced.
    """
    from backtest.run_card import _STRUCTURED_METRIC_MAX_BYTES

    big = {"k%04d" % i: i for i in range(_STRUCTURED_METRIC_MAX_BYTES)}
    metrics = {
        "sharpe": 1.0,
        "unfilled_plan_rejections_by_symbol": {"BIL": {"zero_size": 12}},
        "by_symbol": big,
    }

    card = write_run_card(tmp_path, {"codes": ["BIL"], "source": "auto"}, metrics)

    assert card["metrics"] == {"sharpe": 1.0}
    assert card["structured_metrics"]["unfilled_plan_rejections_by_symbol"] == {"BIL": {"zero_size": 12}}
    assert card["structured_metrics"]["_omitted"] == ["by_symbol"]
    assert "by_symbol" not in card["structured_metrics"]


def test_unserialisable_structured_metric_cannot_fail_the_run(tmp_path: Path) -> None:
    """The card is written after the run completes; it must never raise.

    `write_run_card` runs at the end of a finished backtest, so a pathological
    structured metric must degrade to an omission, not lose the whole card.
    """
    circular: dict[str, object] = {}
    circular["self"] = circular

    card = write_run_card(
        tmp_path,
        {"codes": ["BIL"], "source": "auto"},
        {"sharpe": 1.0, "circular": circular, "nan_map": {"a": float("nan")}},
    )

    assert card["metrics"] == {"sharpe": 1.0}
    assert card["structured_metrics"]["_omitted"] == ["circular"]
    # a NaN inside a retained map is nulled by _json_safe, not left non-JSON
    assert card["structured_metrics"]["nan_map"] == {"a": None}
    assert (tmp_path / "run_card.json").exists()


def test_validation_is_carried_once_and_not_also_in_metrics(tmp_path: Path) -> None:
    """`card["validation"] = metrics["validation"]` - the same object.

    So it belongs under its own key only, never a second time in the metrics
    or structured blocks.
    """
    card = write_run_card(
        tmp_path,
        {"codes": ["SPY"], "source": "auto"},
        {"sharpe": 1.0, "validation": {"consistency": True}},
    )

    assert card["validation"] == {"consistency": True}
    assert card["metrics"] == {"sharpe": 1.0}
    assert "validation" not in card.get("structured_metrics", {})


def test_engine_warnings_are_not_mistaken_for_the_card_warnings(tmp_path: Path) -> None:
    """Sharing a name is not sharing a value.

    The card's top-level `warnings` comes from `config["content_filter_warnings"]`,
    but the options engine puts its own annualisation warnings under
    `metrics["warnings"]`. Those must reach the card - dropping them for sharing
    a name would be the very silent loss this block exists to prevent.
    """
    engine_warnings = ["Annual return requires at least two observations."]
    card = write_run_card(
        tmp_path,
        {"codes": ["SPY"], "source": "auto"},
        {"sharpe": None, "warnings": engine_warnings},
        warnings=["from config: content filter"],
    )

    assert card["warnings"] == ["from config: content filter"]
    assert card.get("structured_metrics", {}).get("warnings") == engine_warnings


def test_bound_is_measured_in_bytes_of_the_written_json(tmp_path: Path) -> None:
    """The guard's unit must match its name: CJK is three bytes per character.

    ``len()`` on ``json.dumps(..., ensure_ascii=False)`` counts characters, so a
    value of 1400 CJK characters measures ~1400 there while occupying ~4200
    UTF-8 bytes in the written card - past a bound named ``..._MAX_BYTES``. The
    card is also written indented, which a compact dump understates again.
    """
    from backtest.run_card import _STRUCTURED_METRIC_MAX_BYTES, _serialised_size

    assert _serialised_size({"note": "键" * 100}) < _STRUCTURED_METRIC_MAX_BYTES
    assert _serialised_size({"note": "键" * 1400}) > _STRUCTURED_METRIC_MAX_BYTES

    card = write_run_card(
        tmp_path,
        {"codes": ["BIL"], "source": "auto"},
        {"sharpe": 1.0, "cjk": {"note": "键" * 1400}},
    )

    assert card["structured_metrics"]["_omitted"] == ["cjk"]


def test_markdown_section_survives_a_backtick_in_a_metric(tmp_path: Path) -> None:
    """A backtick inside a value must not close a rendered span early.

    An inline code span would be terminated by the first backtick in the value,
    corrupting the rest of the section - the JSON is emitted inline instead.
    """
    write_run_card(
        tmp_path,
        {"codes": ["BIL"], "source": "auto"},
        {"sharpe": 1.0, "note": {"text": "ends`here"}},
    )

    md = (tmp_path / "run_card.md").read_text(encoding="utf-8")
    line = next(line for line in md.splitlines() if line.startswith("- note:"))
    # emitted verbatim, with no code span to be closed early by the backtick
    assert line == '- note: {"text": "ends`here"}'


def test_the_omitted_record_cannot_be_overwritten_by_a_metric(tmp_path: Path) -> None:
    """``_omitted`` names what the block dropped, so a metric may not claim it.

    Publishing a metric literally called ``_omitted`` would let one metric be
    silently reinterpreted as the drop record - and change its type doing so.
    """
    circular: dict[str, object] = {}
    circular["self"] = circular

    card = write_run_card(
        tmp_path,
        {"codes": ["BIL"], "source": "auto"},
        {"sharpe": 1.0, "_omitted": {"real": 1}, "circ": circular},
    )

    assert card["structured_metrics"]["_omitted"] == ["_omitted", "circ"]
