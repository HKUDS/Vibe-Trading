from __future__ import annotations

import pandas as pd

from src.alpha_quality.masks import build_ashare_tradability_mask, coverage_by_date


def test_ashare_mask_excludes_st_suspension_limit_and_new_stock() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    symbols = ["OK", "ST", "HALT", "LIMIT", "NEW", "ILLIQ"]
    base_bool = pd.DataFrame(False, index=idx, columns=symbols)
    panel = {
        "st_flag": base_bool.copy(),
        "suspended": base_bool.copy(),
        "limit_up": base_bool.copy(),
        "limit_down": base_bool.copy(),
        "listed_days": pd.DataFrame(60, index=idx, columns=symbols),
        "amount": pd.DataFrame(10_000.0, index=idx, columns=symbols),
    }
    panel["st_flag"].loc[:, "ST"] = True
    panel["suspended"].loc[:, "HALT"] = True
    panel["limit_up"].loc[:, "LIMIT"] = True
    panel["listed_days"].loc[:, "NEW"] = 5
    panel["amount"].loc[:, "ILLIQ"] = 10.0

    mask = build_ashare_tradability_mask(
        panel,
        side="long",
        min_listing_days=20,
        min_amount=1_000.0,
    )

    assert mask.loc[idx[0], "OK"]
    for symbol in ["ST", "HALT", "LIMIT", "NEW", "ILLIQ"]:
        assert not mask.loc[idx[0], symbol]


def test_ashare_short_mask_excludes_limit_down_sell_trap() -> None:
    idx = pd.date_range("2024-01-01", periods=1, freq="D")
    symbols = ["OK", "DOWN"]
    false = pd.DataFrame(False, index=idx, columns=symbols)
    panel = {
        "st_flag": false.copy(),
        "suspended": false.copy(),
        "limit_up": false.copy(),
        "limit_down": false.copy(),
        "listed_days": pd.DataFrame(60, index=idx, columns=symbols),
        "amount": pd.DataFrame(10_000.0, index=idx, columns=symbols),
    }
    panel["limit_down"].loc[:, "DOWN"] = True

    mask = build_ashare_tradability_mask(panel, side="short")

    assert mask.loc[idx[0], "OK"]
    assert not mask.loc[idx[0], "DOWN"]


def test_coverage_by_date_reports_cross_sectional_fraction() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    mask = pd.DataFrame(
        [[True, False, True, False], [True, True, True, False]],
        index=idx,
        columns=["A", "B", "C", "D"],
    )

    coverage = coverage_by_date(mask)

    assert coverage.loc[idx[0]] == 0.5
    assert coverage.loc[idx[1]] == 0.75
