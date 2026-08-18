"""Offline contracts and reconciliation for Binance USD-M account observations."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import inspect

import pandas as pd
import pytest

import backtest.binance_account_reconciliation as reconciliation_module
from backtest.binance_account_reconciliation import (
    BinanceAccountSnapshot,
    BinancePositionSnapshot,
    ReconciliationTolerance,
    reconcile_binance_account,
)
from backtest.perpetual_risk import (
    AccountState,
    PositionRisk,
    PositionState,
    RiskSnapshot,
)


OBSERVED_AT = pd.Timestamp("2026-08-15T08:00:00Z")


def _local_cross() -> tuple[AccountState, RiskSnapshot]:
    position = PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 3.0, None)
    account = AccountState(1_000.0, (position,), "cross")
    risk = PositionRisk("BTC-USDT-PERP", 61_000.0, 6_100.0, 100.0, 610.0, 24.4, None)
    return account, RiskSnapshot(1_100.0, 610.0, 24.4, 490.0, (risk,), "healthy", (), ())


def _exchange_cross(**changes: object) -> BinanceAccountSnapshot:
    values: dict[str, object] = {
        "schema_version": "binance-usdm-account-snapshot-v1",
        "observed_at": OBSERVED_AT,
        "source": "binance-usdm",
        "source_profile": "fixture-readonly",
        "configuration_hash": "synthetic-config-v1",
        "data_status": "complete",
        "wallet_balance": 1_000.0,
        "margin_balance": 1_100.0,
        "available_balance": 490.0,
        "total_unrealized_pnl": 100.0,
        "total_initial_margin": 610.0,
        "total_maintenance_margin": 24.4,
        "positions": (
            BinancePositionSnapshot(
                symbol="BTC-USDT-PERP",
                quantity=0.1,
                entry_price=60_000.0,
                leverage=10.0,
                margin_mode="cross",
                isolated_margin=None,
                unrealized_pnl=100.0,
                initial_margin=610.0,
                maintenance_margin=24.4,
            ),
        ),
        "fidelity_flags": ("synthetic_fixture",),
    }
    values.update(changes)
    return BinanceAccountSnapshot(**values)  # type: ignore[arg-type]


def test_snapshot_contracts_are_frozen_and_reject_spot_sources() -> None:
    snapshot = _exchange_cross()

    with pytest.raises(FrozenInstanceError):
        snapshot.wallet_balance = 0.0  # type: ignore[misc]
    with pytest.raises(ValueError, match="source must be 'binance-usdm'"):
        _exchange_cross(source="binance-spot")
    with pytest.raises(ValueError, match="canonical .*USDT-PERP"):
        _exchange_cross(
            positions=(BinancePositionSnapshot("BTC", 0.1, 60_000.0, 10.0, "cross", None, 100.0, 610.0, 24.4),)
        )


def test_matching_snapshot_completes_comparison_without_validation_claim() -> None:
    account, risk = _local_cross()

    report = reconcile_binance_account(
        account,
        risk,
        _exchange_cross(),
        expected_timestamp=OBSERVED_AT,
    )

    assert report.status == "comparison_complete"
    assert report.has_drift is False
    assert report.source == "binance-usdm"
    assert report.source_profile == "fixture-readonly"
    assert report.snapshot_schema_version == "binance-usdm-account-snapshot-v1"
    assert report.snapshot_configuration_hash == "synthetic-config-v1"
    assert report.liquidation_engine_assessment == "not_assessed"
    assert report.comparison_scope == "account_snapshot_fields_only"
    assert report.missing_on_exchange == ()
    assert report.unexpected_on_exchange == ()
    assert report.structural_differences == ()
    assert all(item.within_tolerance for item in report.comparisons)
    assert "account_snapshot_comparison_only" in report.fidelity_flags


def test_matching_isolated_snapshot_compares_position_collateral() -> None:
    position = PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 3.0, 700.0)
    account = AccountState(1_000.0, (position,), "isolated")
    position_risk = PositionRisk("BTC-USDT-PERP", 61_000.0, 6_100.0, 100.0, 610.0, 24.4, 800.0)
    risk = RiskSnapshot(1_100.0, 610.0, 24.4, 490.0, (position_risk,), "healthy", (), ())
    exchange_position = BinancePositionSnapshot(
        "BTC-USDT-PERP", 0.1, 60_000.0, 10.0, "isolated", 700.0, 100.0, 610.0, 24.4
    )

    report = reconcile_binance_account(
        account,
        risk,
        _exchange_cross(positions=(exchange_position,)),
        expected_timestamp=OBSERVED_AT,
    )

    isolated = next(item for item in report.comparisons if item.field == "isolated_margin")
    assert isolated.within_tolerance is True
    assert report.has_drift is False


def test_reconciliation_reports_numeric_structural_and_symbol_drift() -> None:
    account, risk = _local_cross()
    eth = BinancePositionSnapshot("ETH-USDT-PERP", -1.0, 3_000.0, 5.0, "isolated", 600.0, 0.0, 600.0, 12.0)
    exchange = _exchange_cross(
        wallet_balance=999.0,
        positions=(
            BinancePositionSnapshot(
                "BTC-USDT-PERP",
                0.2,
                60_000.0,
                10.0,
                "isolated",
                610.0,
                100.0,
                610.0,
                24.4,
            ),
            eth,
        ),
    )

    report = reconcile_binance_account(
        account,
        risk,
        exchange,
        expected_timestamp=OBSERVED_AT,
        tolerance=ReconciliationTolerance(absolute=0.01, relative=0.0),
    )

    assert report.has_drift is True
    assert report.unexpected_on_exchange == ("ETH-USDT-PERP",)
    assert report.missing_on_exchange == ()
    assert report.structural_differences == (
        "BTC-USDT-PERP:margin_mode:local=cross:exchange=isolated",
        "BTC-USDT-PERP:isolated_margin_presence",
    )
    drifted = {(item.symbol, item.field) for item in report.comparisons if not item.within_tolerance}
    assert (None, "wallet_balance") in drifted
    assert ("BTC-USDT-PERP", "quantity") in drifted

    missing = reconcile_binance_account(
        account,
        risk,
        _exchange_cross(positions=()),
        expected_timestamp=OBSERVED_AT,
    )
    assert missing.missing_on_exchange == ("BTC-USDT-PERP",)
    assert missing.has_drift is True


@pytest.mark.parametrize(
    ("snapshot", "expected_timestamp", "match"),
    [
        (_exchange_cross(data_status="incomplete"), OBSERVED_AT, "data_status"),
        (
            _exchange_cross(),
            pd.Timestamp("2026-08-15T08:00:02Z"),
            "timestamp skew",
        ),
    ],
)
def test_reconciliation_fails_closed_on_incomplete_or_stale_observations(
    snapshot: BinanceAccountSnapshot,
    expected_timestamp: pd.Timestamp,
    match: str,
) -> None:
    account, risk = _local_cross()

    with pytest.raises(ValueError, match=match):
        reconcile_binance_account(
            account,
            risk,
            snapshot,
            expected_timestamp=expected_timestamp,
            tolerance=ReconciliationTolerance(max_timestamp_skew_seconds=1.0),
        )


def test_reconciliation_is_read_only_and_module_cannot_reach_live_connectors() -> None:
    account, risk = _local_cross()
    before = (account, risk)

    reconcile_binance_account(account, risk, _exchange_cross(), expected_timestamp=OBSERVED_AT)

    assert (account, risk) == before
    tree = ast.parse(inspect.getsource(reconciliation_module))
    forbidden_imports = ("src.live", "src.trading", "backtest.engines")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith(forbidden_imports) for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden_imports)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assert not any(isinstance(target, (ast.Attribute, ast.Subscript)) for target in targets)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
            assert name not in {"setattr", "delattr", "exec", "eval", "__import__"}
            assert attr != "__setattr__"
