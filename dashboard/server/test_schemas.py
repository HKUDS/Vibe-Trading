"""Tests for the manifest schemas — the cross-workstream contract.

These tests verify real behaviour:
- every committed sample manifest parses & validates against its schema,
- required fields are enforced,
- enums reject invalid values,
- nullable fields (cross_regime_ic, stability, oos, ...) accept null.

They do NOT test gate/verdict computation — that is task 2.12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from datetime import datetime

from schemas import (
    FATAL_GATE_CHECKS,
    GATE_MAX_DRAWDOWN,
    GATE_MIN_PROFIT_FACTOR,
    GATE_MIN_SHARPE,
    GATE_MIN_TRADES,
    GATE_MIN_WALK_FORWARD_SHARPE,
    FactorManifest,
    FactorVerdict,
    LiveStatus,
    RecommendedAction,
    RedFlagCode,
    SelectionManifest,
    AlertSeverity,
    StrategyManifest,
    TestnetStatus,
)

# Sample data lives in the committed dashboard/sample_data/ tree.
SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "sample_data"
MANIFEST_DIR = SAMPLE_ROOT / "research" / "manifests"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Sample fixtures exist on disk
# ---------------------------------------------------------------------------


def test_sample_data_tree_exists():
    assert SAMPLE_ROOT.is_dir(), f"missing sample_data dir: {SAMPLE_ROOT}"
    assert (MANIFEST_DIR / "factor_btc.json").is_file()
    assert (MANIFEST_DIR / "selection.json").is_file()


# ---------------------------------------------------------------------------
# Factor manifest
# ---------------------------------------------------------------------------


def test_factor_manifest_sample_validates():
    manifest = FactorManifest.model_validate(_load(MANIFEST_DIR / "factor_btc.json"))
    assert manifest.symbol == "BTC"
    assert len(manifest.factors) == 3
    # ic_by_horizon keys coerce to ints.
    funding = next(f for f in manifest.factors if f.name == "funding_rate")
    assert set(funding.ic_by_horizon.keys()) == {8, 24, 72, 168}


def test_factor_manifest_has_null_cross_regime_entry():
    """At least one factor must exercise the 'cross-regime not done' state."""
    manifest = FactorManifest.model_validate(_load(MANIFEST_DIR / "factor_btc.json"))
    null_cross_regime = [f for f in manifest.factors if f.cross_regime_ic is None]
    assert null_cross_regime, "expected a factor with cross_regime_ic=null"
    for factor in null_cross_regime:
        # When cross_regime_ic is null, stability must also be null.
        assert factor.stability is None


def test_factor_entry_nullable_fields_accept_null():
    entry = {
        "name": "test_factor",
        "ic_by_horizon": {"24": 0.07},
        "ir": 0.5,
        "sample_size": 1000,
        "cross_regime_ic": None,
        "stability": None,
        "verdict": "ensemble_only",
    }
    manifest = FactorManifest.model_validate(
        {
            "symbol": "BTC",
            "generated_at": "2026-05-12T00:00:00Z",
            "period_days": 730,
            "horizons_h": [24],
            "factors": [entry],
        }
    )
    assert manifest.factors[0].cross_regime_ic is None
    assert manifest.factors[0].stability is None


def test_factor_verdict_rejects_invalid_enum_value():
    bad = {
        "symbol": "BTC",
        "generated_at": "2026-05-12T00:00:00Z",
        "period_days": 730,
        "horizons_h": [24],
        "factors": [
            {
                "name": "f",
                "ic_by_horizon": {"24": 0.07},
                "ir": 0.5,
                "sample_size": 1000,
                "verdict": "maybe_use",  # not a valid FactorVerdict
            }
        ],
    }
    with pytest.raises(ValidationError):
        FactorManifest.model_validate(bad)


def test_factor_manifest_missing_required_field_raises():
    bad = {
        "symbol": "BTC",
        "generated_at": "2026-05-12T00:00:00Z",
        "period_days": 730,
        "horizons_h": [24],
        "factors": [
            {
                # 'name' is missing
                "ic_by_horizon": {"24": 0.07},
                "ir": 0.5,
                "sample_size": 1000,
                "verdict": "reject",
            }
        ],
    }
    with pytest.raises(ValidationError):
        FactorManifest.model_validate(bad)


def test_factor_manifest_rejects_unknown_field():
    bad = {
        "symbol": "BTC",
        "generated_at": "2026-05-12T00:00:00Z",
        "period_days": 730,
        "horizons_h": [24],
        "factors": [],
        "typo_field": 1,
    }
    with pytest.raises(ValidationError):
        FactorManifest.model_validate(bad)


# ---------------------------------------------------------------------------
# Strategy manifests — three gate states
# ---------------------------------------------------------------------------

STRATEGY_FILES = {
    "btc_s1_funding_carry": MANIFEST_DIR / "btc_s1_funding_carry" / "manifest.json",
    "btc_s2_oi_momentum": MANIFEST_DIR / "btc_s2_oi_momentum" / "manifest.json",
    "eth_s3_fng_reversal": MANIFEST_DIR / "eth_s3_fng_reversal" / "manifest.json",
}


@pytest.mark.parametrize("strategy_id,path", list(STRATEGY_FILES.items()))
def test_strategy_manifest_sample_validates(strategy_id, path):
    manifest = StrategyManifest.model_validate(_load(path))
    assert manifest.strategy_id == strategy_id
    # Every backtest block carries a source_run.
    assert manifest.backtest is not None
    assert manifest.backtest.in_sample.source_run
    assert manifest.gate is not None
    for threshold in manifest.gate.thresholds:
        assert isinstance(threshold.passed, bool)


def test_passing_strategy_gate_state():
    manifest = StrategyManifest.model_validate(
        _load(STRATEGY_FILES["btc_s1_funding_carry"])
    )
    assert manifest.gate.overall_pass is True
    assert manifest.gate.fatal_fail is False
    assert manifest.gate.red_flags == []


def test_non_fatal_failing_strategy_gate_state():
    """overall_pass false, fatal_fail false — exercises the soft-block path."""
    manifest = StrategyManifest.model_validate(
        _load(STRATEGY_FILES["btc_s2_oi_momentum"])
    )
    assert manifest.gate.overall_pass is False
    assert manifest.gate.fatal_fail is False
    # Both fatal gates still pass for a non-fatal failure.
    fatal = [t for t in manifest.gate.thresholds if t.fatal]
    assert fatal and all(t.passed for t in fatal)
    assert RedFlagCode.TOO_FEW_TRADES in manifest.gate.red_flags


def test_fatal_failing_strategy_gate_state():
    """fatal_fail true — exercises the hard-block path."""
    manifest = StrategyManifest.model_validate(
        _load(STRATEGY_FILES["eth_s3_fng_reversal"])
    )
    assert manifest.gate.overall_pass is False
    assert manifest.gate.fatal_fail is True
    fatal_failed = [t for t in manifest.gate.thresholds if t.fatal and not t.passed]
    assert fatal_failed, "fatal_fail=true requires at least one failed fatal gate"
    assert manifest.diagnosis.recommended_action in RecommendedAction


def test_strategy_oos_block_is_nullable():
    """A stage-2 manifest may have only spec, with oos/backtest still null."""
    manifest = StrategyManifest.model_validate(
        {
            "strategy_id": "btc_s9_early",
            "symbol": "BTC",
            "generated_at": "2026-05-14T00:00:00Z",
            "pipeline_stage": 2,
            "spec": {
                "strategy_id": "btc_s9_early",
                "symbol": "BTC",
                "spec_yaml": "research/strategies/btc_s9_early.yaml",
            },
        }
    )
    assert manifest.backtest is None
    assert manifest.gate is None
    assert manifest.diagnosis is None


def test_strategy_manifest_missing_spec_raises():
    bad = {
        "strategy_id": "x",
        "symbol": "BTC",
        "generated_at": "2026-05-14T00:00:00Z",
        "pipeline_stage": 2,
        # 'spec' is required and missing
    }
    with pytest.raises(ValidationError):
        StrategyManifest.model_validate(bad)


def test_strategy_pipeline_stage_out_of_range_raises():
    bad = {
        "strategy_id": "x",
        "symbol": "BTC",
        "generated_at": "2026-05-14T00:00:00Z",
        "pipeline_stage": 9,  # must be 1-5
        "spec": {
            "strategy_id": "x",
            "symbol": "BTC",
            "spec_yaml": "research/strategies/x.yaml",
        },
    }
    with pytest.raises(ValidationError):
        StrategyManifest.model_validate(bad)


def test_recommended_action_rejects_invalid_enum_value():
    with pytest.raises(ValidationError):
        StrategyManifest.model_validate(
            {
                "strategy_id": "x",
                "symbol": "BTC",
                "generated_at": "2026-05-14T00:00:00Z",
                "pipeline_stage": 3,
                "spec": {
                    "strategy_id": "x",
                    "symbol": "BTC",
                    "spec_yaml": "research/strategies/x.yaml",
                },
                "diagnosis": {
                    "recommended_action": "give_up",  # invalid
                },
            }
        )


def test_red_flag_rejects_invalid_code():
    bad_gate = {
        "thresholds": [
            {"name": "min_sharpe", "threshold": 1.5, "actual": 2.0, "passed": True}
        ],
        "overall_pass": True,
        "fatal_fail": False,
        "red_flags": ["not_a_real_flag"],
    }
    with pytest.raises(ValidationError):
        StrategyManifest.model_validate(
            {
                "strategy_id": "x",
                "symbol": "BTC",
                "generated_at": "2026-05-14T00:00:00Z",
                "pipeline_stage": 5,
                "spec": {
                    "strategy_id": "x",
                    "symbol": "BTC",
                    "spec_yaml": "research/strategies/x.yaml",
                },
                "gate": bad_gate,
            }
        )


# ---------------------------------------------------------------------------
# Selection manifest
# ---------------------------------------------------------------------------


def test_selection_manifest_sample_validates():
    manifest = SelectionManifest.model_validate(_load(MANIFEST_DIR / "selection.json"))
    assert len(manifest.ranking) == 3
    ranks = [e.rank for e in manifest.ranking]
    assert ranks == sorted(ranks)
    selected = [e for e in manifest.ranking if e.selected]
    assert len(selected) == 1


# ---------------------------------------------------------------------------
# Testnet status
# ---------------------------------------------------------------------------


def test_testnet_status_sample_validates():
    path = (
        SAMPLE_ROOT
        / "runs"
        / "testnet"
        / "btc_s1_funding_carry_001"
        / "testnet_status.json"
    )
    status = TestnetStatus.model_validate(_load(path))
    assert status.strategy_id == "btc_s1_funding_carry"
    assert status.live.status == "running"
    assert status.killswitch.triggered is False
    assert len(status.alerts) == 2


def test_testnet_vs_backtest_is_nullable():
    """A freshly started testnet may have no vs_backtest comparison yet."""
    status = TestnetStatus.model_validate(
        {
            "testnet_id": "t1",
            "strategy_id": "btc_s1_funding_carry",
            "symbol": "BTC",
            "live": {
                "started_at": "2026-05-21T00:00:00Z",
                "updated_at": "2026-05-21T00:05:00Z",
                "status": "running",
            },
            "killswitch": {},
        }
    )
    assert status.vs_backtest is None
    assert status.alerts == []


# ---------------------------------------------------------------------------
# Canonical constants — the contract pins the gate thresholds
# NOTE (M6): the three tests below intentionally pin contract values.
# Changing any of these assertions is a BREAKING schema change affecting all
# workstreams; update the schema_version and notify all consumers.
# ---------------------------------------------------------------------------


def test_canonical_gate_constants():
    assert GATE_MIN_SHARPE == 1.5
    assert GATE_MAX_DRAWDOWN == 0.10
    assert GATE_MIN_TRADES == 100
    assert GATE_MIN_PROFIT_FACTOR == 1.5
    assert GATE_MIN_WALK_FORWARD_SHARPE == 1.0


def test_fatal_gate_checks_are_the_two_canonical_ones():
    assert set(FATAL_GATE_CHECKS) == {
        "oos_sharpe_positive",
        "alpha_not_fee_illusion",
    }


def test_factor_verdict_enum_has_three_values():
    assert {v.value for v in FactorVerdict} == {
        "single_use",
        "ensemble_only",
        "reject",
    }


def test_red_flag_enum_has_six_codes():
    assert len(list(RedFlagCode)) == 6


# ---------------------------------------------------------------------------
# I1 — FactorEntry cross-regime consistency validator
# ---------------------------------------------------------------------------


def test_factor_entry_stability_without_cross_regime_ic_raises():
    """stability must be null when cross_regime_ic is null (I1)."""
    bad = {
        "symbol": "BTC",
        "generated_at": "2026-05-12T00:00:00Z",
        "period_days": 730,
        "horizons_h": [24],
        "factors": [
            {
                "name": "f",
                "ic_by_horizon": {"24": 0.07},
                "ir": 0.5,
                "sample_size": 1000,
                "cross_regime_ic": None,
                "stability": "regime_stable",  # must be null when cross_regime_ic is null
                "verdict": "ensemble_only",
            }
        ],
    }
    with pytest.raises(ValidationError, match="stability must be null"):
        FactorManifest.model_validate(bad)


def test_factor_entry_stability_with_cross_regime_ic_is_valid():
    """stability may be set when cross_regime_ic is also set (I1 — positive case)."""
    good = {
        "symbol": "BTC",
        "generated_at": "2026-05-12T00:00:00Z",
        "period_days": 730,
        "horizons_h": [24],
        "factors": [
            {
                "name": "f",
                "ic_by_horizon": {"24": 0.12},
                "ir": 1.1,
                "sample_size": 2000,
                "cross_regime_ic": {"bull": 0.14, "bear": 0.09},
                "stability": "regime_stable",
                "verdict": "single_use",
            }
        ],
    }
    manifest = FactorManifest.model_validate(good)
    assert manifest.factors[0].stability.value == "regime_stable"


# ---------------------------------------------------------------------------
# I2 — GateBlock overall_pass / fatal_fail consistency validator
# ---------------------------------------------------------------------------

_BASE_STRATEGY = {
    "strategy_id": "x",
    "symbol": "BTC",
    "generated_at": "2026-05-14T00:00:00Z",
    "pipeline_stage": 5,
    "spec": {
        "strategy_id": "x",
        "symbol": "BTC",
        "spec_yaml": "research/strategies/x.yaml",
    },
}


def test_gate_overall_pass_true_with_failing_threshold_raises():
    """overall_pass=True is invalid when any threshold has passed=False (I2)."""
    bad_gate = {
        "thresholds": [
            {"name": "min_sharpe", "threshold": 1.5, "actual": 2.0, "passed": True},
            {"name": "min_trades", "threshold": 100, "actual": 50, "passed": False},
        ],
        "overall_pass": True,  # wrong — min_trades failed
        "fatal_fail": False,
    }
    with pytest.raises(ValidationError, match="overall_pass"):
        StrategyManifest.model_validate({**_BASE_STRATEGY, "gate": bad_gate})


def test_gate_fatal_fail_true_with_no_failed_fatal_threshold_raises():
    """fatal_fail=True is invalid when no fatal threshold failed (I2)."""
    bad_gate = {
        "thresholds": [
            {"name": "oos_sharpe_positive", "threshold": 0.0, "actual": 1.5,
             "passed": True, "fatal": True},
        ],
        "overall_pass": True,
        "fatal_fail": True,  # wrong — no fatal failed
    }
    with pytest.raises(ValidationError, match="fatal_fail"):
        StrategyManifest.model_validate({**_BASE_STRATEGY, "gate": bad_gate})


def test_gate_fatal_fail_false_with_failed_fatal_threshold_raises():
    """fatal_fail=False is invalid when a fatal threshold did fail (I2)."""
    bad_gate = {
        "thresholds": [
            {"name": "oos_sharpe_positive", "threshold": 0.0, "actual": -0.5,
             "passed": False, "fatal": True},
        ],
        "overall_pass": False,
        "fatal_fail": False,  # wrong — a fatal threshold failed
    }
    with pytest.raises(ValidationError, match="fatal_fail"):
        StrategyManifest.model_validate({**_BASE_STRATEGY, "gate": bad_gate})


# ---------------------------------------------------------------------------
# I3 — timestamp fields coerce to datetime
# ---------------------------------------------------------------------------


def test_factor_manifest_generated_at_coerces_to_datetime():
    """generated_at accepts an ISO-8601 string and stores it as datetime (I3)."""
    manifest = FactorManifest.model_validate(
        {
            "symbol": "BTC",
            "generated_at": "2026-05-12T08:00:00Z",
            "period_days": 730,
            "horizons_h": [24],
            "factors": [],
        }
    )
    assert isinstance(manifest.generated_at, datetime)


def test_testnet_live_timestamps_coerce_to_datetime():
    """started_at and updated_at coerce to datetime (I3)."""
    status = TestnetStatus.model_validate(
        {
            "testnet_id": "t1",
            "strategy_id": "btc_s1_funding_carry",
            "symbol": "BTC",
            "live": {
                "started_at": "2026-05-21T00:00:00Z",
                "updated_at": "2026-05-21T00:05:00Z",
                "status": "running",
            },
            "killswitch": {},
        }
    )
    assert isinstance(status.live.started_at, datetime)
    assert isinstance(status.live.updated_at, datetime)


def test_testnet_alert_timestamp_coerces_to_datetime():
    """TestnetAlert.timestamp coerces to datetime (I3)."""
    status = TestnetStatus.model_validate(
        {
            "testnet_id": "t1",
            "strategy_id": "s1",
            "symbol": "BTC",
            "live": {
                "started_at": "2026-05-21T00:00:00Z",
                "updated_at": "2026-05-21T00:05:00Z",
                "status": "running",
            },
            "killswitch": {},
            "alerts": [
                {
                    "timestamp": "2026-05-18T14:20:00Z",
                    "severity": "warning",
                    "message": "test alert",
                }
            ],
        }
    )
    assert isinstance(status.alerts[0].timestamp, datetime)


def test_strategy_generated_at_coerces_to_datetime():
    """StrategyManifest.generated_at coerces to datetime (I3)."""
    manifest = StrategyManifest.model_validate(
        {
            "strategy_id": "btc_s9_early",
            "symbol": "BTC",
            "generated_at": "2026-05-14T00:00:00Z",
            "pipeline_stage": 2,
            "spec": {
                "strategy_id": "btc_s9_early",
                "symbol": "BTC",
                "spec_yaml": "research/strategies/btc_s9_early.yaml",
            },
        }
    )
    assert isinstance(manifest.generated_at, datetime)


# ---------------------------------------------------------------------------
# M1 — LiveStatus and AlertSeverity enums
# ---------------------------------------------------------------------------


def test_live_status_enum_rejects_invalid_value():
    """LiveBlock.status must be a valid LiveStatus enum value (M1)."""
    with pytest.raises(ValidationError):
        TestnetStatus.model_validate(
            {
                "testnet_id": "t1",
                "strategy_id": "s1",
                "symbol": "BTC",
                "live": {
                    "started_at": "2026-05-21T00:00:00Z",
                    "updated_at": "2026-05-21T00:05:00Z",
                    "status": "exploding",  # not valid
                },
                "killswitch": {},
            }
        )


def test_alert_severity_enum_rejects_invalid_value():
    """TestnetAlert.severity must be a valid AlertSeverity value (M1)."""
    with pytest.raises(ValidationError):
        TestnetStatus.model_validate(
            {
                "testnet_id": "t1",
                "strategy_id": "s1",
                "symbol": "BTC",
                "live": {
                    "started_at": "2026-05-21T00:00:00Z",
                    "updated_at": "2026-05-21T00:05:00Z",
                    "status": "running",
                },
                "killswitch": {},
                "alerts": [
                    {
                        "timestamp": "2026-05-18T14:20:00Z",
                        "severity": "extreme",  # not valid
                        "message": "test",
                    }
                ],
            }
        )


def test_live_status_enum_covers_known_values():
    """LiveStatus enum must cover running / paused / stopped (M1)."""
    values = {v.value for v in LiveStatus}
    assert {"running", "paused", "stopped"}.issubset(values)


def test_alert_severity_enum_covers_known_values():
    """AlertSeverity enum must cover info / warning / critical (M1)."""
    values = {v.value for v in AlertSeverity}
    assert {"info", "warning", "critical"}.issubset(values)


# ---------------------------------------------------------------------------
# M2 — BacktestMetrics physical bounds
# ---------------------------------------------------------------------------


def _make_strategy_with_in_sample(metrics: dict) -> dict:
    return {
        "strategy_id": "x",
        "symbol": "BTC",
        "generated_at": "2026-05-14T00:00:00Z",
        "pipeline_stage": 3,
        "spec": {
            "strategy_id": "x",
            "symbol": "BTC",
            "spec_yaml": "research/strategies/x.yaml",
        },
        "backtest": {"in_sample": metrics},
    }


def test_backtest_win_rate_above_one_raises():
    """win_rate > 1.0 is physically impossible (M2)."""
    bad = {"source_run": "r1", "win_rate": 1.5}
    with pytest.raises(ValidationError, match="win_rate"):
        StrategyManifest.model_validate(_make_strategy_with_in_sample(bad))


def test_backtest_win_rate_below_zero_raises():
    """win_rate < 0.0 is physically impossible (M2)."""
    bad = {"source_run": "r1", "win_rate": -0.1}
    with pytest.raises(ValidationError, match="win_rate"):
        StrategyManifest.model_validate(_make_strategy_with_in_sample(bad))


def test_backtest_profit_factor_below_zero_raises():
    """profit_factor < 0.0 is physically impossible (M2)."""
    bad = {"source_run": "r1", "profit_factor": -1.0}
    with pytest.raises(ValidationError, match="profit_factor"):
        StrategyManifest.model_validate(_make_strategy_with_in_sample(bad))


def test_backtest_max_drawdown_above_one_raises():
    """max_drawdown > 1.0 is physically impossible (M2)."""
    bad = {"source_run": "r1", "max_drawdown": 1.2}
    with pytest.raises(ValidationError, match="max_drawdown"):
        StrategyManifest.model_validate(_make_strategy_with_in_sample(bad))


def test_backtest_max_drawdown_below_zero_raises():
    """max_drawdown < 0.0 is physically impossible (M2)."""
    bad = {"source_run": "r1", "max_drawdown": -0.05}
    with pytest.raises(ValidationError, match="max_drawdown"):
        StrategyManifest.model_validate(_make_strategy_with_in_sample(bad))
