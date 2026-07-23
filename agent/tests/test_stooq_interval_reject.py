"""Stooq must reject non-daily intervals instead of silently returning day bars."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backtest.loaders import stooq_loader as sq


def test_unsupported_interval_does_not_hit_api() -> None:
    """Runner ``1H`` must not fall through to Stooq daily CSV."""
    with patch.object(sq, "throttled_get") as mock_get:
        out = sq.DataLoader().fetch(
            ["AAPL.US"], "2024-01-01", "2024-01-31", interval="1H"
        )
    assert out == {}
    mock_get.assert_not_called()


def test_four_hour_interval_also_rejected() -> None:
    with patch.object(sq, "throttled_get") as mock_get:
        out = sq.DataLoader().fetch(
            ["AAPL.US"], "2024-01-01", "2024-01-31", interval="4H"
        )
    assert out == {}
    mock_get.assert_not_called()


def test_daily_interval_still_fetches() -> None:
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-02,100,110,99,105,1000\n"
    )
    mock_resp = MagicMock()
    mock_resp.text = csv
    mock_resp.status_code = 200
    mock_resp.raise_for_status = lambda: None
    with patch.object(sq, "throttled_get", return_value=mock_resp) as mock_get:
        out = sq.DataLoader().fetch(
            ["AAPL.US"], "2024-01-01", "2024-01-31", interval="1D"
        )
    assert "AAPL.US" in out
    mock_get.assert_called_once()
