"""Eastmoney KLT map must accept lowercase 1d/1w like project 1D/1W tokens."""

from __future__ import annotations

from backtest.loaders.eastmoney_client import KLT_BY_INTERVAL


def test_lowercase_1d_and_1w_map_like_project_tokens() -> None:
    assert KLT_BY_INTERVAL["1d"] == KLT_BY_INTERVAL["1D"] == 101
    assert KLT_BY_INTERVAL["1w"] == KLT_BY_INTERVAL["1W"] == 102


def test_month_vs_minute_case_preserved() -> None:
    assert KLT_BY_INTERVAL["1M"] == 103
    assert KLT_BY_INTERVAL["1m"] == 1
