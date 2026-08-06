"""Tests for src.quantlib.valuation.comps.

The centerpiece is `test_full_hand_computed_example`: four peers and one
target, worked out with LITERAL ARITHMETIC EXPRESSIONS (e.g. ``1130 / 160``,
never a pre-rounded decimal typed by hand) so Python evaluates the same
formula the module's docstring states, independently of the module's own
code path. Percentiles are cross-checked against `_lin_percentile`, a ~10
line reimplementation of numpy's default linear-interpolation quantile,
written from the textbook formula rather than imported from the module under
test -- this is the repo's convention (see `test_attribution.py`) for how a
"hand computed" fixture stays hand computed instead of silently re-deriving
its own answer from the implementation.
"""

from __future__ import annotations

import pytest

from src.quantlib.valuation.comps import (
    CALENDARISATION_POLICIES,
    EPS_BASES,
    MIN_ROBUST_COMPS,
    MULTIPLE_NAMES,
    CompsResult,
    EVBridgeResult,
    ExcludedMultiple,
    FlowMetricPeriods,
    PeerCompany,
    TargetCompany,
    calendarise_metric,
    enterprise_value,
    equity_value_from_enterprise_value,
    run_comps,
)
from src.quantlib.valuation.contracts import MissingInputError, ValuationError

EXACT = 1e-9


def _lin_percentile(values: list[float], q: float) -> float:
    """Independent reimplementation of numpy's default ("linear") percentile.

    Textbook formula: sort, take fractional index ``q * (n - 1)``, linearly
    interpolate between its floor and ceiling. Written from scratch (not
    imported from numpy or from the module under test) so the big fixture
    below is checked against ground truth, not against its own algorithm.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return ordered[lo] + frac * (ordered[hi] - ordered[lo])


def _flow(
    last_full: float,
    *,
    ytd: float | None = None,
    prior_ytd: float | None = None,
    next_fy: float | None = None,
    month: int = 12,
) -> FlowMetricPeriods:
    """Small constructor to keep the isolated unit tests below readable."""
    return FlowMetricPeriods(
        fiscal_year_end_month=month,
        last_full_fiscal_year=last_full,
        current_year_to_date=ytd,
        prior_year_to_date=prior_ytd,
        next_full_fiscal_year=next_fy,
    )


def _baseline_peer(name: str = "PEER", **overrides: object) -> PeerCompany:
    """A self-consistent, LTM-ready peer for tests that are not about the
    big hand-computed fixture (EV bridge signs, exclusion, warnings, ...).
    """
    fields: dict[str, object] = dict(
        name=name,
        market_cap=1000.0,
        total_debt=200.0,
        cash_and_equivalents=100.0,
        ebitda=_flow(150.0, ytd=80.0, prior_ytd=70.0),  # LTM = 160
        ebit=_flow(100.0, ytd=55.0, prior_ytd=50.0),  # LTM = 105
        revenue=_flow(900.0, ytd=480.0, prior_ytd=420.0),  # LTM = 960
        diluted_eps=_flow(5.0, ytd=2.6, prior_ytd=2.2),  # LTM = 5.4
        price_per_share=54.0,
        book_value_of_equity=500.0,
        eps_basis="gaap",
    )
    fields.update(overrides)
    return PeerCompany(**fields)  # type: ignore[arg-type]


def _baseline_target(name: str = "TARGET", **overrides: object) -> TargetCompany:
    fields: dict[str, object] = dict(
        name=name,
        total_debt=150.0,
        cash_and_equivalents=60.0,
        ebitda=_flow(140.0, ytd=75.0, prior_ytd=65.0),  # LTM = 150
        ebit=_flow(95.0, ytd=52.0, prior_ytd=45.0),  # LTM = 102
        revenue=_flow(850.0, ytd=460.0, prior_ytd=400.0),  # LTM = 910
        diluted_eps=_flow(4.5, ytd=2.4, prior_ytd=2.0),  # LTM = 4.9
        diluted_shares_outstanding=100.0,
        book_value_of_equity=420.0,
        eps_basis="gaap",
    )
    fields.update(overrides)
    return TargetCompany(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# EV bridge: one test per sign.
# ---------------------------------------------------------------------------


def test_total_debt_increases_enterprise_value():
    """Debt is assumed by an acquirer of the whole enterprise -- EV rises."""
    base = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    higher_debt = enterprise_value(market_cap=1000.0, total_debt=250.0, cash_and_equivalents=100.0)
    assert higher_debt.enterprise_value == pytest.approx(base.enterprise_value + 50.0, abs=EXACT)


def test_cash_decreases_enterprise_value():
    """Cash funds part of the purchase price -- EV falls as cash rises."""
    base = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    more_cash = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=150.0)
    assert more_cash.enterprise_value == pytest.approx(base.enterprise_value - 50.0, abs=EXACT)


def test_minority_interest_increases_enterprise_value():
    """Consolidated subsidiaries carry 100% of EBITDA into the parent's
    figures -- the minority holders' claim on that 100% must be in EV too."""
    base = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    with_mi = enterprise_value(
        market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0, minority_interest=50.0
    )
    assert with_mi.enterprise_value == pytest.approx(base.enterprise_value + 50.0, abs=EXACT)
    assert "minority_interest" in base.omitted_components
    assert "minority_interest" not in with_mi.omitted_components


def test_preferred_stock_increases_enterprise_value():
    """Preferred ranks senior to common -- market cap alone underprices the
    whole enterprise by the preferred claim."""
    base = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    with_pref = enterprise_value(
        market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0, preferred_stock=30.0
    )
    assert with_pref.enterprise_value == pytest.approx(base.enterprise_value + 30.0, abs=EXACT)


def test_investments_in_associates_decreases_enterprise_value():
    """An equity-method stake's revenue/EBITDA never entered the consolidated
    operating metrics -- its value must come back out of EV."""
    base = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    with_assoc = enterprise_value(
        market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0, investments_in_associates=40.0
    )
    assert with_assoc.enterprise_value == pytest.approx(base.enterprise_value - 40.0, abs=EXACT)


def test_omitted_components_are_not_silently_zeroed():
    """An unsupplied optional item is flagged by name, distinct from an
    explicit confirmed zero."""
    omitted = enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=100.0)
    assert set(omitted.omitted_components) == {
        "minority_interest",
        "preferred_stock",
        "investments_in_associates",
    }

    explicit_zero = enterprise_value(
        market_cap=1000.0,
        total_debt=200.0,
        cash_and_equivalents=100.0,
        minority_interest=0.0,
        preferred_stock=0.0,
        investments_in_associates=0.0,
    )
    assert explicit_zero.omitted_components == ()
    # Numerically identical to the fully-omitted case (0 contributes nothing
    # either way) -- the DIFFERENCE this module guarantees is in the report,
    # not in a different number.
    assert explicit_zero.enterprise_value == pytest.approx(omitted.enterprise_value, abs=EXACT)


def test_enterprise_value_round_trips_through_equity_value_and_back():
    """`equity_value_from_enterprise_value` is the exact inverse bridge."""
    forward = enterprise_value(
        market_cap=1000.0,
        total_debt=200.0,
        cash_and_equivalents=100.0,
        minority_interest=50.0,
        preferred_stock=30.0,
        investments_in_associates=40.0,
    )
    backward = equity_value_from_enterprise_value(
        enterprise_value=forward.enterprise_value,
        total_debt=200.0,
        cash_and_equivalents=100.0,
        minority_interest=50.0,
        preferred_stock=30.0,
        investments_in_associates=40.0,
    )
    assert backward.equity_value == pytest.approx(1000.0, abs=EXACT)
    assert backward.direction == "ev_to_equity"
    assert forward.direction == "equity_to_ev"
    assert isinstance(forward, EVBridgeResult)
    assert isinstance(backward, EVBridgeResult)


def test_enterprise_value_missing_required_input_raises():
    with pytest.raises(MissingInputError) as excinfo:
        enterprise_value(market_cap=1000.0, total_debt=200.0, cash_and_equivalents=None)  # type: ignore[arg-type]
    assert "cash_and_equivalents" in excinfo.value.missing


# ---------------------------------------------------------------------------
# Calendarisation: LTM vs calendar-year, and why alignment matters.
# ---------------------------------------------------------------------------


def test_ltm_formula_is_last_full_fy_plus_current_ytd_minus_prior_ytd():
    periods = _flow(150.0, ytd=80.0, prior_ytd=70.0)
    result = calendarise_metric(periods, "ltm", metric_name="ebitda", company_name="X")
    assert result.value == pytest.approx(150.0 + 80.0 - 70.0, abs=EXACT)
    assert result.weights is None


def test_ltm_policy_is_invariant_to_fiscal_year_end_month():
    """LTM needs no month-weighting: it always trails 12 months from the
    'as of' date the YTD figures were cut at, whatever the fiscal calendar."""
    june_fye = _flow(150.0, ytd=80.0, prior_ytd=70.0, month=6)
    march_fye = _flow(150.0, ytd=80.0, prior_ytd=70.0, month=3)
    a = calendarise_metric(june_fye, "ltm", metric_name="ebitda", company_name="X")
    b = calendarise_metric(march_fye, "ltm", metric_name="ebitda", company_name="Y")
    assert a.value == pytest.approx(b.value, abs=EXACT)


def test_calendar_year_december_fye_uses_full_weight_on_last_full_year():
    periods = _flow(1200.0, month=12)
    result = calendarise_metric(periods, "calendar_year", metric_name="revenue", company_name="X")
    assert result.value == pytest.approx(1200.0, abs=EXACT)
    assert result.weights == pytest.approx((1.0, 0.0), abs=EXACT)


def test_fiscal_calendar_alignment_changes_the_comparison():
    """Requirement 4: a June-FYE company and a December-FYE company give a
    materially different conclusion unaligned vs aligned to calendar year.

    Company X: December FYE, last full fiscal year (= calendar year) revenue
    1200.
    Company Y: June FYE. Fiscal year ending June (the 'early' half of the
    blend) = 900; fiscal year ending the following June (the 'late' half) =
    1100. Calendar year revenue, assuming even monthly spread within each
    fiscal year (this module's documented convention): the first six months
    of the calendar year come from the FY ending in June of that year, the
    last six months from the FY ending the following June:

        calendar_year(Y) = 0.5 * 900 + 0.5 * 1100 = 1000
    """
    x = _flow(1200.0, month=12)
    y = _flow(900.0, next_fy=1100.0, month=6)

    x_aligned = calendarise_metric(x, "calendar_year", metric_name="revenue", company_name="X")
    y_aligned = calendarise_metric(y, "calendar_year", metric_name="revenue", company_name="Y")

    assert y_aligned.value == pytest.approx(0.5 * 900.0 + 0.5 * 1100.0, abs=EXACT)
    assert y_aligned.weights == pytest.approx((0.5, 0.5), abs=EXACT)

    # Unaligned (naive) comparison: Y's raw 'last full fiscal year' (a period
    # that ended six months before X's) against X's calendar-year figure.
    naive_ratio = y.last_full_fiscal_year / x.last_full_fiscal_year  # 900 / 1200 = 0.75
    aligned_ratio = y_aligned.value / x_aligned.value  # 1000 / 1200 = 0.8333...

    assert naive_ratio == pytest.approx(0.75, abs=EXACT)
    assert aligned_ratio == pytest.approx(1000.0 / 1200.0, abs=EXACT)
    # The two conclusions are materially different -- alignment is not a
    # rounding nicety here, it changes which company looks bigger relative
    # to the other by several points.
    assert abs(aligned_ratio - naive_ratio) > 0.05


def test_calendar_year_policy_missing_next_fiscal_year_raises():
    """A non-December FYE company that only supplied LTM-shaped fields
    (no `next_full_fiscal_year`) cannot be calendar-year aligned -- this is
    the 'do not mix conventions' rule enforced as MissingInputError rather
    than a silently partial calendarisation."""
    ltm_only = _flow(900.0, ytd=500.0, prior_ytd=430.0, month=6)
    with pytest.raises(MissingInputError) as excinfo:
        calendarise_metric(ltm_only, "calendar_year", metric_name="revenue", company_name="Y")
    assert "next_full_fiscal_year" in excinfo.value.missing


def test_ltm_policy_missing_ytd_fields_raises():
    calendar_year_only = _flow(900.0, next_fy=1100.0, month=6)
    with pytest.raises(MissingInputError) as excinfo:
        calendarise_metric(calendar_year_only, "ltm", metric_name="revenue", company_name="Y")
    assert "current_year_to_date" in excinfo.value.missing
    assert "prior_year_to_date" in excinfo.value.missing


def test_unknown_calendarisation_policy_raises():
    with pytest.raises(ValuationError):
        calendarise_metric(_flow(100.0), "quarterly", metric_name="revenue", company_name="X")


def test_fiscal_year_end_month_out_of_range_raises():
    with pytest.raises(ValuationError):
        FlowMetricPeriods(fiscal_year_end_month=13, last_full_fiscal_year=100.0)


# ---------------------------------------------------------------------------
# Multiple exclusion: negative/zero denominators are dropped, not computed.
# ---------------------------------------------------------------------------


def test_negative_ebitda_peer_is_excluded_from_ev_ebitda_and_reported():
    negative_ebitda_peer = _baseline_peer(
        name="LOSSCO", ebitda=_flow(-30.0, ytd=-10.0, prior_ytd=5.0)  # LTM = -45
    )
    healthy_peer = _baseline_peer(name="HEALTHY")
    target = _baseline_target()

    result = run_comps(target, [negative_ebitda_peer, healthy_peer], calendarisation_policy="ltm")

    ev_ebitda_dist = result.distributions["ev_ebitda"]
    assert "LOSSCO" not in ev_ebitda_dist.included
    assert "HEALTHY" in ev_ebitda_dist.included
    assert len(ev_ebitda_dist.excluded) == 1
    excluded = ev_ebitda_dist.excluded[0]
    assert isinstance(excluded, ExcludedMultiple)
    assert excluded.peer_name == "LOSSCO"
    assert excluded.multiple_name == "ev_ebitda"
    assert excluded.denominator_value == pytest.approx(-45.0, abs=EXACT)

    # The excluded peer's own multiple is None, not a negative number.
    peer_multiples_by_name = {pm.name: pm for pm in result.peer_multiples}
    assert peer_multiples_by_name["LOSSCO"].ev_ebitda is None

    # With only one included peer, the median IS that peer's own multiple --
    # LOSSCO's -45x never entered the calculation.
    assert ev_ebitda_dist.median == pytest.approx(
        peer_multiples_by_name["HEALTHY"].ev_ebitda, abs=EXACT
    )


def test_zero_ebitda_denominator_is_also_excluded():
    zero_ebitda_peer = _baseline_peer(name="FLAT", ebitda=_flow(0.0, ytd=0.0, prior_ytd=0.0))
    healthy_peer = _baseline_peer(name="HEALTHY")
    result = run_comps(_baseline_target(), [zero_ebitda_peer, healthy_peer], calendarisation_policy="ltm")
    assert "FLAT" not in result.distributions["ev_ebitda"].included


def test_all_peers_excluded_from_a_multiple_yields_no_statistics_and_a_warning():
    """Boundary: every peer excluded from one multiple. The run still
    succeeds; that multiple's distribution and implied valuation are simply
    empty/None, with a warning explaining why."""
    peer_1 = _baseline_peer(name="A", ebitda=_flow(-10.0, ytd=-5.0, prior_ytd=2.0))
    peer_2 = _baseline_peer(name="B", ebitda=_flow(-20.0, ytd=-8.0, prior_ytd=1.0))
    result = run_comps(_baseline_target(), [peer_1, peer_2], calendarisation_policy="ltm")

    dist = result.distributions["ev_ebitda"]
    assert dist.included == {}
    assert len(dist.excluded) == 2
    assert dist.minimum is None
    assert dist.median is None
    assert dist.warning is not None and "excluded" in dist.warning

    implied = result.implied_valuations["ev_ebitda"]
    assert implied.implied_ev_by_quantile is None
    assert implied.implied_equity_value_by_quantile is None
    assert implied.warning == dist.warning
    assert dist.warning in result.warnings


# ---------------------------------------------------------------------------
# Small-sample warning.
# ---------------------------------------------------------------------------


def test_fewer_than_min_robust_comps_peers_triggers_warning():
    peers = [_baseline_peer(name="A"), _baseline_peer(name="B")]
    assert len(peers) < MIN_ROBUST_COMPS
    result = run_comps(_baseline_target(), peers, calendarisation_policy="ltm")
    assert any("only 2 peer(s) supplied" in w for w in result.warnings)
    for name in MULTIPLE_NAMES:
        assert result.distributions[name].warning is not None


def test_three_or_more_peers_does_not_trigger_the_sample_size_warning():
    peers = [_baseline_peer(name=n) for n in ("A", "B", "C")]
    result = run_comps(_baseline_target(), peers, calendarisation_policy="ltm")
    assert not any("peer(s) supplied" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Structural validation.
# ---------------------------------------------------------------------------


def test_empty_peer_list_raises_missing_input_error():
    with pytest.raises(MissingInputError) as excinfo:
        run_comps(_baseline_target(), [], calendarisation_policy="ltm")
    assert "peers" in excinfo.value.missing


def test_duplicate_peer_names_raise():
    peers = [_baseline_peer(name="DUP"), _baseline_peer(name="DUP")]
    with pytest.raises(ValuationError):
        run_comps(_baseline_target(), peers, calendarisation_policy="ltm")


def test_mixed_eps_basis_across_peers_raises():
    peers = [_baseline_peer(name="A", eps_basis="gaap"), _baseline_peer(name="B", eps_basis="adjusted")]
    with pytest.raises(ValuationError):
        run_comps(_baseline_target(), peers, calendarisation_policy="ltm")


def test_target_eps_basis_must_match_peers():
    peers = [_baseline_peer(name="A", eps_basis="gaap"), _baseline_peer(name="B", eps_basis="gaap")]
    target = _baseline_target(eps_basis="adjusted")
    with pytest.raises(ValuationError):
        run_comps(target, peers, calendarisation_policy="ltm")


def test_unknown_eps_basis_rejected_at_construction():
    with pytest.raises(ValuationError):
        _baseline_peer(name="A", eps_basis="non_gaap")


def test_unknown_calendarisation_policy_in_run_comps_raises():
    peers = [_baseline_peer(name="A"), _baseline_peer(name="B"), _baseline_peer(name="C")]
    with pytest.raises(ValuationError):
        run_comps(_baseline_target(), peers, calendarisation_policy="quarterly")


def test_blank_company_name_rejected():
    with pytest.raises(ValuationError):
        _baseline_peer(name="   ")


def test_non_positive_diluted_shares_outstanding_rejected():
    with pytest.raises(ValuationError):
        _baseline_target(diluted_shares_outstanding=0.0)
    with pytest.raises(ValuationError):
        _baseline_target(diluted_shares_outstanding=-10.0)


def test_result_records_which_calendarisation_policy_and_eps_basis_were_used():
    peers = [_baseline_peer(name="A"), _baseline_peer(name="B"), _baseline_peer(name="C")]
    result = run_comps(_baseline_target(), peers, calendarisation_policy="calendar_year")
    assert result.calendarisation_policy == "calendar_year"
    assert result.eps_basis == "gaap"
    assert result.calendarisation_policy in CALENDARISATION_POLICIES
    assert result.eps_basis in EPS_BASES
    assert isinstance(result, CompsResult)


# ---------------------------------------------------------------------------
# Boundary cases named explicitly in the spec.
# ---------------------------------------------------------------------------


def test_zero_market_cap_peer_is_excluded_and_reported():
    """A zero market cap is not a cheap company, it is missing data.

    Under the two-sided rule (2026-08-06) a non-positive NUMERATOR is excluded
    just like a non-positive denominator: a 0.0x P/B dragged into a median
    distorts it exactly as much as a negative multiple would. The exclusion is
    reported with reason='non_positive_numerator' rather than silently dropped.
    """
    zero_cap_peer = _baseline_peer(name="ZERO", market_cap=0.0)
    result = run_comps(
        _baseline_target(), [zero_cap_peer, _baseline_peer(name="B"), _baseline_peer(name="C")],
        calendarisation_policy="ltm",
    )
    peer_multiples_by_name = {pm.name: pm for pm in result.peer_multiples}
    assert peer_multiples_by_name["ZERO"].pb is None
    assert "ZERO" not in result.distributions["pb"].included

    reasons = {
        (e.peer_name, e.multiple_name): e.reason
        for e in peer_multiples_by_name["ZERO"].exclusions
    }
    assert reasons[("ZERO", "pb")] == "non_positive_numerator"


def test_a_net_cash_peer_with_negative_ev_is_excluded_not_averaged_in():
    """The gap the old one-sided rule left open.

    A net-cash-rich peer can carry a negative enterprise value with perfectly
    healthy EBITDA. EV/EBITDA = -3.2x is not a valuation multiple, and letting
    it into the median pulls the whole comparable range toward a number no peer
    trades at.
    """
    # Cash far exceeding market cap plus debt drives EV negative.
    net_cash_peer = _baseline_peer(name="NETCASH", market_cap=100.0, cash_and_equivalents=10_000.0)
    result = run_comps(
        _baseline_target(),
        [net_cash_peer, _baseline_peer(name="B"), _baseline_peer(name="C")],
        calendarisation_policy="ltm",
    )
    by_name = {pm.name: pm for pm in result.peer_multiples}
    assert by_name["NETCASH"].ev_bridge.enterprise_value < 0

    assert by_name["NETCASH"].ev_ebitda is None
    assert "NETCASH" not in result.distributions["ev_ebitda"].included
    assert result.distributions["ev_ebitda"].median > 0


def test_target_negative_metric_produces_negative_implied_value_without_raising():
    """A target with negative LTM EPS produces a negative implied equity
    value via P/E -- economically odd, but the module does not fabricate an
    exclusion rule the spec does not state; it reports what falls out."""
    peers = [_baseline_peer(name="A"), _baseline_peer(name="B"), _baseline_peer(name="C")]
    losing_target = _baseline_target(diluted_eps=_flow(-2.0, ytd=-1.0, prior_ytd=0.5))  # LTM = -3.5
    result = run_comps(losing_target, peers, calendarisation_policy="ltm")

    implied = result.implied_valuations["pe"]
    assert implied.target_metric_value == pytest.approx(-3.5 * 100.0, abs=EXACT)
    assert implied.implied_equity_value_by_quantile["median"] == pytest.approx(
        result.distributions["pe"].median * implied.target_metric_value, abs=EXACT
    )
    assert implied.implied_equity_value_by_quantile["median"] < 0.0


# ---------------------------------------------------------------------------
# The full hand-computed example.
# ---------------------------------------------------------------------------


def test_full_hand_computed_example():
    """Four peers, one target, LTM policy. Every EV, every calendarised
    metric, every multiple, every distribution quantile and every implied
    valuation is asserted against a literal arithmetic expression built from
    the formulas stated in the module docstring -- never a value read back
    from the module under test.
    """
    # --- Peer AAA -----------------------------------------------------
    ev_a = 1000.0 + 200.0 - 100.0 + 50.0 + 0.0 - 20.0  # market_cap + debt - cash + MI + pref - assoc
    ebitda_a = 150.0 + 80.0 - 70.0
    ebit_a = 100.0 + 55.0 - 50.0
    revenue_a = 900.0 + 480.0 - 420.0
    eps_a = 5.0 + 2.6 - 2.2
    peer_a = PeerCompany(
        name="AAA",
        market_cap=1000.0,
        total_debt=200.0,
        cash_and_equivalents=100.0,
        minority_interest=50.0,
        preferred_stock=0.0,
        investments_in_associates=20.0,
        ebitda=_flow(150.0, ytd=80.0, prior_ytd=70.0),
        ebit=_flow(100.0, ytd=55.0, prior_ytd=50.0),
        revenue=_flow(900.0, ytd=480.0, prior_ytd=420.0),
        diluted_eps=_flow(5.0, ytd=2.6, prior_ytd=2.2),
        price_per_share=55.0,
        book_value_of_equity=520.0,
        eps_basis="gaap",
    )

    # --- Peer BBB -----------------------------------------------------
    ev_b = 1500.0 + 300.0 - 150.0 + 0.0 + 0.0 - 0.0
    ebitda_b = 200.0 + 110.0 - 90.0
    ebit_b = 140.0 + 75.0 - 65.0
    revenue_b = 1200.0 + 650.0 - 560.0
    eps_b = 6.0 + 3.2 - 2.8
    peer_b = PeerCompany(
        name="BBB",
        market_cap=1500.0,
        total_debt=300.0,
        cash_and_equivalents=150.0,
        minority_interest=0.0,
        preferred_stock=0.0,
        investments_in_associates=0.0,
        ebitda=_flow(200.0, ytd=110.0, prior_ytd=90.0),
        ebit=_flow(140.0, ytd=75.0, prior_ytd=65.0),
        revenue=_flow(1200.0, ytd=650.0, prior_ytd=560.0),
        diluted_eps=_flow(6.0, ytd=3.2, prior_ytd=2.8),
        price_per_share=67.0,
        book_value_of_equity=740.0,
        eps_basis="gaap",
    )

    # --- Peer CCC (negative LTM EBITDA -> excluded from ev_ebitda only) -
    ev_c = 800.0 + 250.0 - 50.0
    ebitda_c = -30.0 + (-10.0) - 5.0  # = -45, negative
    ebit_c = 90.0 + 48.0 - 40.0
    revenue_c = 700.0 + 380.0 - 320.0
    eps_c = 4.0 + 2.0 - 1.6
    peer_c = PeerCompany(
        name="CCC",
        market_cap=800.0,
        total_debt=250.0,
        cash_and_equivalents=50.0,
        minority_interest=0.0,
        preferred_stock=0.0,
        investments_in_associates=0.0,
        ebitda=_flow(-30.0, ytd=-10.0, prior_ytd=5.0),
        ebit=_flow(90.0, ytd=48.0, prior_ytd=40.0),
        revenue=_flow(700.0, ytd=380.0, prior_ytd=320.0),
        diluted_eps=_flow(4.0, ytd=2.0, prior_ytd=1.6),
        price_per_share=42.0,
        book_value_of_equity=410.0,
        eps_basis="gaap",
    )
    assert ebitda_c < 0.0

    # --- Peer DDD -------------------------------------------------------
    ev_d = 1200.0 + 180.0 - 80.0
    ebitda_d = 170.0 + 90.0 - 75.0
    ebit_d = 120.0 + 65.0 - 55.0
    revenue_d = 1000.0 + 540.0 - 460.0
    eps_d = 5.5 + 2.9 - 2.4
    peer_d = PeerCompany(
        name="DDD",
        market_cap=1200.0,
        total_debt=180.0,
        cash_and_equivalents=80.0,
        minority_interest=0.0,
        preferred_stock=0.0,
        investments_in_associates=0.0,
        ebitda=_flow(170.0, ytd=90.0, prior_ytd=75.0),
        ebit=_flow(120.0, ytd=65.0, prior_ytd=55.0),
        revenue=_flow(1000.0, ytd=540.0, prior_ytd=460.0),
        diluted_eps=_flow(5.5, ytd=2.9, prior_ytd=2.4),
        price_per_share=58.0,
        book_value_of_equity=590.0,
        eps_basis="gaap",
    )

    # --- Target TGT -------------------------------------------------------
    ebitda_t = 140.0 + 75.0 - 65.0
    ebit_t = 95.0 + 52.0 - 45.0
    revenue_t = 850.0 + 460.0 - 400.0
    eps_t = 4.5 + 2.4 - 2.0
    shares_t = 100.0
    net_income_t = eps_t * shares_t
    bridge_delta_t = 150.0 - 60.0 + 10.0 + 0.0 - 5.0  # debt - cash + MI + pref - assoc
    target = TargetCompany(
        name="TGT",
        total_debt=150.0,
        cash_and_equivalents=60.0,
        minority_interest=10.0,
        preferred_stock=0.0,
        investments_in_associates=5.0,
        ebitda=_flow(140.0, ytd=75.0, prior_ytd=65.0),
        ebit=_flow(95.0, ytd=52.0, prior_ytd=45.0),
        revenue=_flow(850.0, ytd=460.0, prior_ytd=400.0),
        diluted_eps=_flow(4.5, ytd=2.4, prior_ytd=2.0),
        diluted_shares_outstanding=shares_t,
        book_value_of_equity=420.0,
        eps_basis="gaap",
    )

    result = run_comps(target, [peer_a, peer_b, peer_c, peer_d], calendarisation_policy="ltm")
    assert result.calendarisation_policy == "ltm"
    assert len(result.peer_multiples) == 4

    # --- Per-peer EV bridge and calendarised metrics --------------------
    by_name = {pm.name: pm for pm in result.peer_multiples}
    assert by_name["AAA"].ev_bridge.enterprise_value == pytest.approx(ev_a, abs=EXACT)
    assert by_name["BBB"].ev_bridge.enterprise_value == pytest.approx(ev_b, abs=EXACT)
    assert by_name["CCC"].ev_bridge.enterprise_value == pytest.approx(ev_c, abs=EXACT)
    assert by_name["DDD"].ev_bridge.enterprise_value == pytest.approx(ev_d, abs=EXACT)

    assert by_name["AAA"].calendarised_ebitda.value == pytest.approx(ebitda_a, abs=EXACT)
    assert by_name["AAA"].calendarised_ebit.value == pytest.approx(ebit_a, abs=EXACT)
    assert by_name["AAA"].calendarised_revenue.value == pytest.approx(revenue_a, abs=EXACT)
    assert by_name["AAA"].calendarised_diluted_eps.value == pytest.approx(eps_a, abs=EXACT)

    # --- Per-peer multiples ------------------------------------------------
    assert by_name["AAA"].ev_ebitda == pytest.approx(ev_a / ebitda_a, abs=EXACT)
    assert by_name["AAA"].ev_ebit == pytest.approx(ev_a / ebit_a, abs=EXACT)
    assert by_name["AAA"].ev_sales == pytest.approx(ev_a / revenue_a, abs=EXACT)
    assert by_name["AAA"].pe == pytest.approx(55.0 / eps_a, abs=EXACT)
    assert by_name["AAA"].pb == pytest.approx(1000.0 / 520.0, abs=EXACT)

    assert by_name["BBB"].ev_ebitda == pytest.approx(ev_b / ebitda_b, abs=EXACT)
    assert by_name["BBB"].ev_ebit == pytest.approx(ev_b / ebit_b, abs=EXACT)
    assert by_name["BBB"].ev_sales == pytest.approx(ev_b / revenue_b, abs=EXACT)
    assert by_name["BBB"].pe == pytest.approx(67.0 / eps_b, abs=EXACT)
    assert by_name["BBB"].pb == pytest.approx(1500.0 / 740.0, abs=EXACT)

    # CCC: EBITDA negative -> ev_ebitda excluded (None); everything else computed.
    assert by_name["CCC"].ev_ebitda is None
    assert len(by_name["CCC"].exclusions) == 1
    assert by_name["CCC"].exclusions[0].multiple_name == "ev_ebitda"
    assert by_name["CCC"].exclusions[0].denominator_value == pytest.approx(ebitda_c, abs=EXACT)
    assert by_name["CCC"].ev_ebit == pytest.approx(ev_c / ebit_c, abs=EXACT)
    assert by_name["CCC"].ev_sales == pytest.approx(ev_c / revenue_c, abs=EXACT)
    assert by_name["CCC"].pe == pytest.approx(42.0 / eps_c, abs=EXACT)
    assert by_name["CCC"].pb == pytest.approx(800.0 / 410.0, abs=EXACT)

    assert by_name["DDD"].ev_ebitda == pytest.approx(ev_d / ebitda_d, abs=EXACT)
    assert by_name["DDD"].ev_ebit == pytest.approx(ev_d / ebit_d, abs=EXACT)
    assert by_name["DDD"].ev_sales == pytest.approx(ev_d / revenue_d, abs=EXACT)
    assert by_name["DDD"].pe == pytest.approx(58.0 / eps_d, abs=EXACT)
    assert by_name["DDD"].pb == pytest.approx(1200.0 / 590.0, abs=EXACT)

    # --- Distributions -------------------------------------------------
    ev_ebitda_values = [ev_a / ebitda_a, ev_b / ebitda_b, ev_d / ebitda_d]  # CCC excluded
    ev_ebit_values = [ev_a / ebit_a, ev_b / ebit_b, ev_c / ebit_c, ev_d / ebit_d]
    ev_sales_values = [ev_a / revenue_a, ev_b / revenue_b, ev_c / revenue_c, ev_d / revenue_d]
    pe_values = [55.0 / eps_a, 67.0 / eps_b, 42.0 / eps_c, 58.0 / eps_d]
    pb_values = [1000.0 / 520.0, 1500.0 / 740.0, 800.0 / 410.0, 1200.0 / 590.0]

    expected_by_multiple = {
        "ev_ebitda": ev_ebitda_values,
        "ev_ebit": ev_ebit_values,
        "ev_sales": ev_sales_values,
        "pe": pe_values,
        "pb": pb_values,
    }

    for name, expected_values in expected_by_multiple.items():
        dist = result.distributions[name]
        assert len(dist.included) == len(expected_values)
        assert dist.minimum == pytest.approx(min(expected_values), abs=EXACT)
        assert dist.maximum == pytest.approx(max(expected_values), abs=EXACT)
        assert dist.p25 == pytest.approx(_lin_percentile(expected_values, 0.25), abs=EXACT)
        assert dist.median == pytest.approx(_lin_percentile(expected_values, 0.50), abs=EXACT)
        assert dist.p75 == pytest.approx(_lin_percentile(expected_values, 0.75), abs=EXACT)

    assert result.distributions["ev_ebitda"].median == pytest.approx(ev_a / ebitda_a, abs=EXACT)
    assert len(result.distributions["ev_ebitda"].excluded) == 1
    assert result.distributions["ev_ebitda"].warning is None  # 3 included, >= MIN_ROBUST_COMPS

    # --- Implied valuations ---------------------------------------------
    for name in ("ev_ebitda", "ev_ebit", "ev_sales"):
        target_metric = {"ev_ebitda": ebitda_t, "ev_ebit": ebit_t, "ev_sales": revenue_t}[name]
        expected_values = expected_by_multiple[name]
        implied = result.implied_valuations[name]
        assert implied.target_metric_value == pytest.approx(target_metric, abs=EXACT)
        assert implied.is_ev_multiple is True

        for label, q in (("minimum", 0.0), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("maximum", 1.0)):
            multiple = (
                min(expected_values)
                if label == "minimum"
                else max(expected_values)
                if label == "maximum"
                else _lin_percentile(expected_values, q)
            )
            expected_ev = multiple * target_metric
            assert implied.implied_ev_by_quantile[label] == pytest.approx(expected_ev, abs=EXACT)
            expected_equity = expected_ev - bridge_delta_t
            assert implied.implied_equity_value_by_quantile[label] == pytest.approx(
                expected_equity, abs=EXACT
            )

    # pe: target metric is calendarised diluted EPS * diluted shares outstanding.
    pe_implied = result.implied_valuations["pe"]
    assert pe_implied.is_ev_multiple is False
    assert pe_implied.target_metric_value == pytest.approx(net_income_t, abs=EXACT)
    assert pe_implied.implied_ev_by_quantile is None
    expected_pe_median = _lin_percentile(pe_values, 0.5) * net_income_t
    assert pe_implied.implied_equity_value_by_quantile["median"] == pytest.approx(
        expected_pe_median, abs=EXACT
    )

    # pb: target metric is book value of equity directly.
    pb_implied = result.implied_valuations["pb"]
    assert pb_implied.is_ev_multiple is False
    assert pb_implied.target_metric_value == pytest.approx(420.0, abs=EXACT)
    expected_pb_median = _lin_percentile(pb_values, 0.5) * 420.0
    assert pb_implied.implied_equity_value_by_quantile["median"] == pytest.approx(
        expected_pb_median, abs=EXACT
    )

    # No small-sample warning: 4 peers >= MIN_ROBUST_COMPS, and CCC's single
    # exclusion still leaves 3 included for ev_ebitda.
    assert result.warnings == ()
