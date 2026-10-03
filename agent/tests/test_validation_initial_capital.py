"""Monte Carlo path metrics must include the first trade from starting cash."""

import pandas as pd
import pytest

from backtest.models import TradeRecord
from backtest.validation import monte_carlo_test


def _trades(pnls: list[float]) -> list[TradeRecord]:
    dates = pd.date_range("2025-01-01", periods=len(pnls) + 1)
    return [
        TradeRecord(
            symbol="TEST",
            direction=1,
            entry_price=100.0,
            exit_price=100.0 + pnl,
            entry_time=dates[i],
            exit_time=dates[i + 1],
            size=1.0,
            leverage=1.0,
            pnl=pnl,
            pnl_pct=pnl,
            exit_reason="signal",
            holding_bars=1,
            commission=0.0,
        )
        for i, pnl in enumerate(pnls)
    ]


@pytest.fixture
def initial_loss_result():
    # Capital path: 100 -> 80 -> 85 -> 90. The first loss is the worst drawdown.
    return monte_carlo_test(
        _trades([-20.0, 5.0, 5.0]), 100.0, n_simulations=30, seed=42
    )


def test_monte_carlo_drawdown_includes_loss_from_starting_cash(initial_loss_result):
    assert initial_loss_result["actual_max_dd"] == pytest.approx(-0.2)


def test_monte_carlo_sharpe_includes_first_trade_return(initial_loss_result):
    # Returns are [-20/100, 5/80, 5/85], not just the two recoveries.
    # Their mean / population std * sqrt(252) is approximately -3.38782068.
    assert initial_loss_result["actual_sharpe"] == pytest.approx(-3.3878, abs=1e-4)


def test_worst_drawdown_order_is_never_better_than_a_permutation(initial_loss_result):
    # Delaying the only loss raises its pre-loss peak to 105 or 110, so every
    # ordering has a drawdown at least as good as the observed -20%.
    assert initial_loss_result["p_value_max_dd"] == 1.0


def test_monte_carlo_preserves_post_trade_path_shape(initial_loss_result):
    assert initial_loss_result["n_trades"] == 3
    assert initial_loss_result["equity_paths"]["steps"] == [1, 2, 3]
    assert initial_loss_result["equity_paths"]["actual"] == [80.0, 85.0, 90.0]


def test_monte_carlo_drawdown_still_uses_later_high_water_mark():
    # Capital path: 100 -> 120 -> 110 -> 100. The peak is 120, not 100.
    result = monte_carlo_test(
        _trades([20.0, -10.0, -10.0]), 100.0, n_simulations=30, seed=42
    )
    assert result["actual_max_dd"] == pytest.approx(-0.1667, abs=1e-4)
