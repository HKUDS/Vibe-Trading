"""Risk contributions use the same sample and signed exposure as the x-ray."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from backtest.risk_xray import (
    compute_risk_xray,
    render_risk_xray_markdown,
    write_risk_xray,
)
from src.agent.grounding import GroundingLedger
from src.tools.portfolio_risk_tool import PortfolioRiskXrayTool


def _panel(returns):
    changes = np.array(list(returns.values()), dtype=float).T
    values = np.vstack([np.ones(len(returns)), np.cumprod(1 + changes, axis=0)])
    return pd.DataFrame(
        values * 100,
        index=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        columns=list(returns),
    )


def _correlated_panel():
    return _panel({"AAA": [0.1, -0.1, 0.1, -0.1], "BBB": [0.2, -0.2, 0.2, -0.2]})


def _by_symbol(report):
    return {row["symbol"]: row for row in report["risk_contributions"]["assets"]}


def test_components_add_to_reported_volatility_and_shares_sum_to_100():
    report = compute_risk_xray(
        _correlated_panel(), {"AAA": 0.75, "BBB": 0.25}, min_history=2
    )
    risk = report["risk_contributions"]
    rows = _by_symbol(report)
    assert risk["status"] == "ok"
    assert rows["AAA"]["contribution_pct"] == pytest.approx(60)
    assert rows["BBB"]["contribution_pct"] == pytest.approx(40)
    assert sum(row["risk_contribution"] for row in rows.values()) == pytest.approx(
        report["volatility"]["annualized_vol"]
    )
    assert risk["annualized_volatility"] == pytest.approx(
        math.sqrt(252 * 4 / 3) * 0.125
    )


def test_uncorrelated_assets_are_split_by_risk_not_capital_weight():
    closes = _panel({"AAA": [0.1, -0.1, 0.1, -0.1], "BBB": [0.2, 0.2, -0.2, -0.2]})
    rows = _by_symbol(
        compute_risk_xray(closes, {"AAA": 0.5, "BBB": 0.5}, min_history=2)
    )
    assert rows["AAA"]["contribution_pct"] == pytest.approx(20)
    assert rows["BBB"]["contribution_pct"] == pytest.approx(80)


def test_non_finite_returns_have_no_numeric_contributions():
    closes = pd.DataFrame(
        {"AAA": [100.0, 0.0, 100.0]}, index=pd.date_range("2026-01-01", periods=3)
    )
    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    risk = report["risk_contributions"]
    assert risk["status"] == "non_finite_returns"
    assert risk["annualized_volatility"] is None
    assert _by_symbol(report)["AAA"]["risk_contribution"] is None
    assert _by_symbol(report)["AAA"]["contribution_pct"] is None
    json.dumps(report, allow_nan=False)


def test_hedges_keep_negative_contributions_and_leverage_scale():
    small = _by_symbol(
        compute_risk_xray(_correlated_panel(), {"AAA": 1.5, "BBB": -0.5}, min_history=2)
    )
    large = _by_symbol(
        compute_risk_xray(_correlated_panel(), {"AAA": 3.0, "BBB": -1.0}, min_history=2)
    )
    assert small["AAA"]["contribution_pct"] == pytest.approx(300)
    assert small["BBB"]["contribution_pct"] == pytest.approx(-200)
    for symbol, row in small.items():
        assert large[symbol]["contribution_pct"] == pytest.approx(
            row["contribution_pct"]
        )
        assert large[symbol]["risk_contribution"] == pytest.approx(
            2 * row["risk_contribution"]
        )


@pytest.mark.parametrize("weights", [{"AAA": 1.0}, {"AAA": 1.0, "BBB": 0.0}])
def test_single_active_asset_owns_all_risk(weights):
    report = compute_risk_xray(_correlated_panel(), weights, min_history=2)
    rows = _by_symbol(report)
    assert rows["AAA"]["contribution_pct"] == pytest.approx(100)
    assert rows["AAA"]["risk_contribution"] == pytest.approx(
        report["volatility"]["annualized_vol"]
    )
    if "BBB" in weights:
        assert rows["BBB"]["risk_contribution"] == 0.0


def test_exactly_hedged_portfolio_has_zero_components_but_no_risk_shares():
    closes = _panel({"AAA": [0.1, -0.1], "BBB": [0.1, -0.1]})
    report = compute_risk_xray(closes, {"AAA": 1.0, "BBB": -1.0}, min_history=2)
    risk = report["risk_contributions"]
    assert risk["status"] == "zero_variance"
    assert risk["annualized_volatility"] == 0.0
    assert all(row["risk_contribution"] == 0.0 for row in risk["assets"])
    assert all(row["contribution_pct"] is None for row in risk["assets"])
    json.dumps(report, allow_nan=False)


def test_one_return_observation_does_not_invent_a_decomposition():
    report = compute_risk_xray(_panel({"AAA": [0.1]}), {"AAA": 1}, min_history=2)
    risk = report["risk_contributions"]
    assert risk["status"] == "insufficient_observations"
    assert risk["annualized_volatility"] is None
    assert _by_symbol(report)["AAA"]["risk_contribution"] is None
    assert _by_symbol(report)["AAA"]["contribution_pct"] is None


def test_contributions_follow_gap_filter_and_calendar_annualization():
    closes = _correlated_panel()
    closes.loc[closes.index[2], "BBB"] = np.nan
    report = compute_risk_xray(
        closes, {"AAA": 0.5, "BBB": 0.5}, min_history=2, periods_per_year=None
    )
    assert report["inputs"]["return_observations"] == 2
    assert sum(
        row["risk_contribution"] for row in _by_symbol(report).values()
    ) == pytest.approx(report["volatility"]["annualized_vol"])


def test_history_filter_excludes_thin_symbols_from_contributions():
    closes = _correlated_panel()
    closes["THIN"] = [10.0, np.nan, np.nan, np.nan, np.nan]
    report = compute_risk_xray(
        closes, {"AAA": 0.5, "BBB": 0.25, "THIN": 0.25}, min_history=2
    )
    rows = _by_symbol(report)
    assert set(rows) == {"AAA", "BBB"}
    assert rows["AAA"]["contribution_pct"] == pytest.approx(50)
    assert rows["BBB"]["contribution_pct"] == pytest.approx(50)


def test_json_artifact_and_markdown_keep_hedging_sign(tmp_path):
    report = compute_risk_xray(
        _correlated_panel(), {"AAA": 1.5, "BBB": -0.5}, min_history=2
    )
    path = tmp_path / "risk.json"
    write_risk_xray(path, report)
    assert _by_symbol(json.loads(path.read_text()))["BBB"][
        "contribution_pct"
    ] == pytest.approx(-200)
    markdown = render_risk_xray_markdown(report)
    assert "Risk contributions" in markdown
    assert "BBB" in markdown
    assert "-200.00%" in markdown
    assert "offset" in markdown


def test_agent_tool_exposes_groundable_per_asset_contributions(tmp_path):
    closes = _panel({"AAA": [0.01, -0.01] * 20, "BBB": [0.02, -0.02] * 20})

    def fetcher(**kwargs):
        return {
            symbol: [
                {"date": date.isoformat(), "close": value}
                for date, value in closes[symbol].items()
            ]
            for symbol in kwargs["codes"]
        }

    arguments = dict(
        symbols=["AAA", "BBB"],
        weights={"AAA": 0.75, "BBB": 0.25},
        start_date="2026-01-01",
        end_date="2026-02-15",
    )
    result = PortfolioRiskXrayTool(data_fetcher=fetcher).execute(**arguments)
    envelope = json.loads(result)
    assert envelope["status"] == "ok"
    rows = _by_symbol(envelope["data"])
    assert rows["AAA"]["contribution_pct"] == pytest.approx(60)
    assert rows["BBB"]["contribution_pct"] == pytest.approx(40)
    ledger = GroundingLedger(
        run_dir=tmp_path, user_message="Compare AAA and BBB risk contributions"
    )
    ledger.ingest_tool_result(
        tool_name="portfolio_risk_xray",
        arguments=arguments,
        result=result,
        call_id="risk-call",
        success=True,
    )
    claim = (
        "AAA has risk contribution 60%.\n\n```figures\n60% | observed | contribution | "
    )
    ref = "risk-call::data.risk_contributions.assets[0].contribution_pct\n```"
    check = ledger.validate_final_answer(claim + ref)
    assert check.valid, check.issues
    wrong_ref = ref.replace("assets[0]", "assets[1]")
    assert not ledger.validate_final_answer(claim + wrong_ref).valid
