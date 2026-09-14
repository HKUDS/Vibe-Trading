"""Regression: a count or a span is not a magnitude (#1420).

``_metric_kind_for_path`` classifies an evidence leaf by scanning its tokens for
a metric alias.  Two shapes slipped through and made the ledger certify numbers
no tool ever measured as that metric:

* The leaf's **head noun** was metadata while the metric token beside it
  supplied the identity: ``return_observations`` is a count of observations,
  ``max_drawdown_duration`` is a span in periods, ``episode_count`` is a tally —
  all three were ingested as metric magnitudes, so a count of 81 observations
  grounded ``Annual return: 81%``.
* The trailing fallback handed the **whole dotted path** to the text scanner, so
  a parent key naming a metric made every descendant leaf that metric:
  ``drawdown_distribution_analysis.ulcer_index`` and ``...episode_count`` were
  both recorded as drawdowns.

Both are reachable without a synthetic tool.  ``quantlib_call`` is one of the
four tool names whose results enter the ledger, and its real
``drawdown_distribution_analysis`` returns ``max_drawdown_duration`` (periods)
and ``episode_count`` (a tally) beside the actual ``max_drawdown``.

The classification table below is pinned in **both** directions: metadata leaves
must resolve to ``None``, and the compounds the #1338 review added token
matching for — including names whose head is a qualifier rather than the alias,
such as ``annualized_return_pct`` — must keep resolving.  A rule that fixes the
first column by breaking the second is not a fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import (
    _ANALYSIS_KIND_ALIASES,
    GroundingLedger,
    _metric_kind_for_path,
)


def _ledger(run_dir: Path) -> GroundingLedger:
    return GroundingLedger(run_dir=run_dir, user_message="Analyze performance.")


def _ingest(
    ledger: GroundingLedger,
    tool_name: str,
    payload: dict,
    arguments: dict | None = None,
    call_id: str = "call-1",
) -> None:
    ledger.ingest_tool_result(
        tool_name=tool_name,
        arguments=arguments or {},
        result=json.dumps(payload),
        call_id=call_id,
        success=True,
    )


# --------------------------------------------------------------------------
# A count/span leaf must not name a metric kind.
# --------------------------------------------------------------------------

METADATA_LEAVES = [
    # the field names in #1420
    "data.inputs.return_observations",
    "data.metrics.trade_count",
    "data.inputs.aligned_days",
    # the same shape, other metrics
    "data.metrics.return_window",
    "data.metrics.vol_lookback",
    "data.metrics.sharpe_observations",
    "data.metrics.win_rate_samples",
    # a leading count quantifier, head noun notwithstanding
    "data.metrics.n_returns",
    "data.metrics.num_returns",
    "data.metrics.count_returns",
    # bare metadata
    "data.metrics.observations",
    "data.metrics.count",
    # real keys from the shipping modules whose values are extents, not levels:
    # an MA window, an annualization factor, a duration in periods
    "data.metrics.vol_ma_period",
    "data.metrics.sharpe_annualization_bars",
    "data.metrics.money_weighted_return_period",
    # real quantlib_call output keys (drawdown_distribution_analysis)
    "drawdown_distribution_analysis.max_drawdown_duration",
    "drawdown_distribution_analysis.avg_drawdown_duration",
    "drawdown_distribution_analysis.episode_count",
    "drawdown_distribution_analysis.episodes[7].duration",
]


@pytest.mark.parametrize("path", METADATA_LEAVES)
def test_metadata_leaves_do_not_name_a_metric(path: str) -> None:
    """A count of returns is not a return."""
    assert _metric_kind_for_path(path) is None


# --------------------------------------------------------------------------
# Recall: everything the scan was added for must still resolve.
# --------------------------------------------------------------------------

LEGITIMATE_LEAVES = [
    # verbatim aliases
    ("data.metrics.annual_return", "return"),
    ("data.metrics.total_return", "return"),
    ("data.metrics.sharpe_ratio", "sharpe"),
    # the #1338 review cases: compound leaves naming the kind as a token
    ("data.metrics.strategy_max_drawdown", "drawdown"),
    ("data.metrics.reported_annualized_return", "return"),
    ("data.metrics.monthly_total_return", "return"),
    # head noun decides, not the leftmost token
    ("data.metrics.return_vol", "vol"),
    # heads that are qualifiers, where the metric token is NOT the head: these
    # are why the rule is about the head noun and not about suffix position.
    ("data.metrics.annualized_return_pct", "return"),
    ("data.metrics.total_return_pct", "return"),
    ("data.metrics.annualized_vol_pct", "vol"),
    ("data.metrics.max_drawdown_pct", "drawdown"),
    # a span noun used as a *modifier* still names the metric it modifies
    ("data.metrics.rolling_window_return", "return"),
    # the real magnitude beside the metadata keys still classifies
    ("drawdown_distribution_analysis.max_drawdown", "drawdown"),
    ("drawdown_distribution_analysis.avg_drawdown_depth", "drawdown"),
]


@pytest.mark.parametrize(("path", "kind"), LEGITIMATE_LEAVES)
def test_legitimate_compounds_still_resolve(path: str, kind: str) -> None:
    """The fix must not narrow the vocabulary the #1338 review widened."""
    assert _metric_kind_for_path(path) == kind


def test_every_alias_still_resolves_to_its_own_kind() -> None:
    """The metadata guard must not suppress the vocabulary it protects.

    The guard runs before the verbatim lookup, so an alias whose own name looks
    like metadata would silently stop grounding.  This asserts the whole table
    rather than a hand-picked sample, so adding an alias cannot reintroduce it.
    """
    suppressed = {
        alias: (kind, _metric_kind_for_path(alias))
        for alias, kind in _ANALYSIS_KIND_ALIASES.items()
        if _metric_kind_for_path(alias) != kind
    }
    assert suppressed == {}


# --------------------------------------------------------------------------
# A parent key must not lend its kind to its descendants.
# --------------------------------------------------------------------------

PARENT_KEY_CASES = [
    # the parent names a metric; the child does not.
    ("drawdown_distribution_analysis.episode_count", None),
    ("drawdown_distribution_analysis.ulcer_index", None),
    ("drawdown_distribution_analysis.pain_index", None),
    ("max_drawdown_analysis.recovery_days", None),
    ("sharpe_ratio_table.sample_size", None),
    # the parent-named case that must survive: the child names the metric too
    ("data.max_drawdown.max_drawdown_pct", "drawdown"),
]


@pytest.mark.parametrize(("path", "kind"), PARENT_KEY_CASES)
def test_a_parent_key_does_not_lend_its_kind_to_descendants(
    path: str, kind: str | None
) -> None:
    """``<metric>_analysis.episode_count`` is not a metric measurement."""
    assert _metric_kind_for_path(path) == kind


# --------------------------------------------------------------------------
# End to end, through the real ingestion path.
# --------------------------------------------------------------------------


def test_an_observation_count_cannot_ground_a_return_claim(tmp_path: Path) -> None:
    """The exact #1420 repro: a count of 81 observations must not ground 81%."""
    ledger = _ledger(tmp_path)
    _ingest(
        ledger,
        "factor_analysis",
        {"status": "ok", "return_observations": 81},
    )

    for text in ("Annual return: 81%", "Cumulative return: 81%"):
        result = ledger.validate_final_answer(text)
        assert not result.valid
        # Rejected by the analysis gate, not a neighbouring check: the field
        # produced no evidence at all, which is the point.
        assert [issue["code"] for issue in result.issues] == [
            "analysis_claim_unavailable"
        ]


def test_a_real_return_still_grounds_the_same_claim(tmp_path: Path) -> None:
    """The control for the case above: the gate is closed, not the vocabulary."""
    ledger = _ledger(tmp_path)
    _ingest(ledger, "factor_analysis", {"status": "ok", "annual_return": 81})

    assert ledger.validate_final_answer("Annual return: 81%").valid


# Verbatim scalar output of one real call on a fixed seed:
#   rng = numpy.random.RandomState(7)
#   equity = numpy.cumprod(1 + rng.normal(0.0004, 0.012, 800)) * 1e6
#   quantlib_call(action="call", module="risk",
#                 function="drawdown_distribution_analysis", data=equity)
# The durations are periods and episode_count is a tally; only max_drawdown and
# avg_drawdown_depth are drawdown magnitudes.
DRAWDOWN_DISTRIBUTION_PAYLOAD = {
    "ok": True,
    "module": "risk",
    "function": "drawdown_distribution_analysis",
    "result": {
        "max_drawdown": 0.3994061129618872,
        "max_drawdown_duration": 670,
        "avg_drawdown_depth": 0.07544875907368809,
        "avg_drawdown_duration": 17.428571428571427,
        "ulcer_index": 0.22185561845835508,
        "pain_index": 0.19247857654848297,
        "episode_count": 8,
    },
}


def test_a_drawdown_duration_cannot_ground_a_drawdown_claim(tmp_path: Path) -> None:
    """670 periods is not a 670% drawdown; 8 episodes is not an 8% drawdown."""
    ledger = _ledger(tmp_path)
    _ingest(
        ledger,
        "quantlib_call",
        DRAWDOWN_DISTRIBUTION_PAYLOAD,
        arguments={
            "action": "call",
            "module": "risk",
            "function": "drawdown_distribution_analysis",
        },
    )

    for text in ("Max drawdown: 670%", "Max drawdown: 8%", "Max drawdown: 22%"):
        result = ledger.validate_final_answer(text)
        assert not result.valid
        assert [issue["code"] for issue in result.issues] == [
            "analysis_claim_unavailable"
        ]


def test_the_real_drawdown_beside_it_still_grounds(tmp_path: Path) -> None:
    """The control: the genuine magnitude in the same payload is unaffected."""
    ledger = _ledger(tmp_path)
    _ingest(
        ledger,
        "quantlib_call",
        DRAWDOWN_DISTRIBUTION_PAYLOAD,
        arguments={
            "action": "call",
            "module": "risk",
            "function": "drawdown_distribution_analysis",
        },
    )

    assert ledger.validate_final_answer("Max drawdown: 39.94%").valid
