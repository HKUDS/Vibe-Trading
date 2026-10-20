"""Regression tests for unrecognized backtest config keys (#1934).

An agent-written ``initial_capital`` used to validate cleanly (extras are
allowed so engine keys flow through) and then be silently dropped by the
engine, so the run proceeded at 10x the intended capital while reporting
confident metrics. The lint is deliberately path-wide: a key is flagged only
when nothing on the backtest path reads it, so engine-namespaced keys like
``commission_rate`` (read by china_a, not crypto) are not false-flagged.
"""

from __future__ import annotations

from backtest.runner import _known_config_keys, _unrecognized_config_warning


def test_misspelled_capital_and_commission_keys_are_flagged() -> None:
    config = {
        "codes": ["BTC-USDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "commission_rate": 0.001,
        "source": "okx",
        "interval": "1D",
    }
    warning = _unrecognized_config_warning(config)
    assert warning is not None
    assert "'initial_capital'" in warning
    # The misspelling is pointed at the key the engine actually reads.
    assert "'initial_cash'" in warning
    # commission_rate is a real china_a engine key, so the path-wide lint must
    # not flag it on a crypto run (per-engine namespacing is a separate, wider
    # change); this case pins that conservative contract down.
    assert "'commission_rate'" not in warning


def test_engine_keys_and_runner_internals_are_not_flagged() -> None:
    config = {
        "codes": ["BTC-USDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_cash": 100000,
        "maker_rate": 0.001,
        "taker_rate": 0.002,
        "leverage": 2.0,
        "slippage": 0.0005,
        "funding_mode": "data",
        "source": "okx",
        "engine": "crypto",
        "interval": "1D",
        "_run_card_effective_sources": {"BTC-USDT": "okx"},
    }
    assert _unrecognized_config_warning(config) is None


def test_known_keys_cover_engine_and_loader_reads() -> None:
    known = _known_config_keys()
    for key in ("initial_cash", "maker_rate", "taker_rate", "slippage", "funding_rate"):
        assert key in known


def test_shared_path_config_is_not_reported_as_ignored() -> None:
    """Constraints and provenance have real readers outside engine modules."""
    assert _unrecognized_config_warning({
        "constraints": [{"type": "turnover_aware", "max_turnover": 0.1}],
        "model_training_cutoff": "2023-12-31",
    }) is None
