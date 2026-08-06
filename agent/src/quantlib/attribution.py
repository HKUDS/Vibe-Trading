"""Brinson-Fachler performance attribution with residual-free multi-period linking.

Single-period decomposition splits the active return (portfolio minus benchmark)
into three sector-level effects::

    Allocation_i  = (w_p,i - w_b,i) * (r_b,i - R_b)
    Selection_i   =  w_b,i          * (r_p,i - r_b,i)
    Interaction_i = (w_p,i - w_b,i) * (r_p,i - r_b,i)

The sum of all three over all sectors equals ``R_p - R_b`` *identically* -- there
is no residual and none is reported. The identity holds for any sector returns
whatsoever, provided only that the two weight vectors carry the same total; that
is the one precondition this module enforces (see :func:`brinson_fachler`).

Multi-period linking uses **Carino** logarithmic linking, for three reasons:

1. It is residual-free. Naively summing single-period arithmetic effects does not
   reproduce the compounded active return, because returns compound and effects
   are added; Carino's scaling factors absorb exactly that gap.
2. Its scaling factor for a period depends only on that period's total portfolio
   and benchmark return -- never on the effects being linked. Linking is therefore
   deterministic, order-independent, and cannot be steered by how the analyst
   chose to bucket sectors. Menchero's linking is likewise residual-free but
   distributes a correction term computed from the effects themselves, which adds
   machinery this module does not need.
3. It is what ``skills/performance-attribution/SKILL.md`` already prescribes, so
   the tested implementation and the documented method agree.

Carino defines a total factor ``k`` and a per-period factor ``k_t``::

    k   = (ln(1 + R_P) - ln(1 + R_B)) / (R_P - R_B)
    k_t = (ln(1 + R_p,t) - ln(1 + R_b,t)) / (R_p,t - R_b,t)

and scales every single-period effect by ``k_t / k``. Because each period's
effects sum to ``R_p,t - R_b,t``, the linked effects telescope through the
logarithms and sum to the compounded active return ``R_P - R_B`` exactly.

Only the standard library is imported here, so this module stays importable even
when an optional numerical dependency used elsewhere in ``quantlib`` is missing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: Largest tolerated difference between the portfolio and benchmark weight sums.
#: Beyond this the Brinson identity stops holding, so it is an error, not a warning.
DEFAULT_WEIGHT_SUM_TOLERANCE = 1e-9

#: Below this absolute gap between a period's portfolio and benchmark return, the
#: Carino factor is evaluated at its analytic limit rather than by a difference of
#: logarithms, which would lose precision to catastrophic cancellation.
_CARINO_LIMIT_EPS = 1e-9


@dataclass(frozen=True)
class SectorEffect:
    """One sector's single-period Brinson-Fachler decomposition.

    Attributes:
        sector: Sector label.
        portfolio_weight: Portfolio weight of the sector (``w_p,i``).
        benchmark_weight: Benchmark weight of the sector (``w_b,i``).
        portfolio_return: Portfolio return within the sector (``r_p,i``).
        benchmark_return: Benchmark return within the sector (``r_b,i``).
        allocation: Allocation effect, from over/under-weighting the sector.
        selection: Selection effect, from picking better names inside the sector.
        interaction: Interaction effect, the cross term of the two.
    """

    sector: str
    portfolio_weight: float
    benchmark_weight: float
    portfolio_return: float
    benchmark_return: float
    allocation: float
    selection: float
    interaction: float

    @property
    def total(self) -> float:
        """Return the sector's total contribution to the active return.

        Returns:
            Sum of the allocation, selection and interaction effects.
        """
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class BrinsonResult:
    """Single-period attribution for a whole portfolio.

    The three aggregate effects sum to :attr:`active_return` exactly; no residual
    term exists or is reported.

    Attributes:
        sectors: Per-sector decompositions, portfolio order first, then any
            benchmark-only sectors.
        portfolio_return: Total portfolio return ``R_p = sum(w_p,i * r_p,i)``.
        benchmark_return: Total benchmark return ``R_b = sum(w_b,i * r_b,i)``.
        active_return: ``R_p - R_b``.
        allocation: Sum of every sector's allocation effect.
        selection: Sum of every sector's selection effect.
        interaction: Sum of every sector's interaction effect.
    """

    sectors: tuple[SectorEffect, ...]
    portfolio_return: float
    benchmark_return: float
    active_return: float
    allocation: float
    selection: float
    interaction: float

    @property
    def total_effect(self) -> float:
        """Return the summed effects, which equal :attr:`active_return`.

        Returns:
            Allocation plus selection plus interaction.
        """
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class LinkedSectorEffect:
    """One sector's Carino-linked effects across every period.

    Weights and returns are deliberately absent: they compound rather than add,
    so a multi-period "weight" would have no single defensible definition.

    Attributes:
        sector: Sector label.
        allocation: Linked allocation effect.
        selection: Linked selection effect.
        interaction: Linked interaction effect.
    """

    sector: str
    allocation: float
    selection: float
    interaction: float

    @property
    def total(self) -> float:
        """Return the sector's total linked contribution.

        Returns:
            Sum of the linked allocation, selection and interaction effects.
        """
        return self.allocation + self.selection + self.interaction


@dataclass(frozen=True)
class LinkedAttribution:
    """Multi-period attribution produced by Carino linking.

    The three aggregate effects sum to :attr:`active_return`, the *compounded*
    active return, exactly.

    Attributes:
        sectors: Per-sector linked decompositions.
        portfolio_return: Compounded portfolio return over all periods.
        benchmark_return: Compounded benchmark return over all periods.
        active_return: ``portfolio_return - benchmark_return``.
        allocation: Linked allocation effect, summed over sectors.
        selection: Linked selection effect, summed over sectors.
        interaction: Linked interaction effect, summed over sectors.
        scaling_factors: The ``k_t / k`` multiplier applied to each period, in
            period order. Exposed so an attribution report can be audited.
    """

    sectors: tuple[LinkedSectorEffect, ...]
    portfolio_return: float
    benchmark_return: float
    active_return: float
    allocation: float
    selection: float
    interaction: float
    scaling_factors: tuple[float, ...]

    @property
    def total_effect(self) -> float:
        """Return the summed linked effects, which equal :attr:`active_return`.

        Returns:
            Allocation plus selection plus interaction.
        """
        return self.allocation + self.selection + self.interaction


def brinson_fachler(
    portfolio_weights: Mapping[str, float],
    benchmark_weights: Mapping[str, float],
    portfolio_returns: Mapping[str, float],
    benchmark_returns: Mapping[str, float],
    weight_sum_tolerance: float = DEFAULT_WEIGHT_SUM_TOLERANCE,
) -> BrinsonResult:
    """Decompose one period's active return into allocation, selection and interaction.

    Sector returns may be omitted only where the corresponding weight is zero; the
    missing return is then filled from the other side. That makes a benchmark-only
    sector's selection and interaction vanish and charges the whole effect to
    allocation -- you cannot show selection skill in something you did not own --
    and it treats an off-benchmark holding symmetrically. The choice never
    threatens the tie-out, which is independent of the sector returns used.

    Args:
        portfolio_weights: Sector label to portfolio weight.
        benchmark_weights: Sector label to benchmark weight.
        portfolio_returns: Sector label to within-sector portfolio return.
        benchmark_returns: Sector label to within-sector benchmark return.
        weight_sum_tolerance: Largest tolerated difference between the two weight
            sums. Defaults to :data:`DEFAULT_WEIGHT_SUM_TOLERANCE`.

    Returns:
        A :class:`BrinsonResult` whose allocation, selection and interaction sum
        to its ``active_return`` to floating-point precision, provided the two
        weight vectors really do carry the same total.

        The tie-out is exactly as good as ``weight_sum_tolerance`` allows: a
        weight-sum gap ``dW`` leaves a residual of ``-R_b * dW``, because the
        ``R_b * sum(w_p - w_b)`` term of the allocation effect no longer vanishes.
        At the default tolerance that residual is below 1e-10 and invisible.
        Loosen the tolerance and it becomes visible in basis points -- a 2%
        weight-sum gap against a 5% benchmark return is a 10bp residual -- so
        loosen it only to absorb rounding in the weights, never to force through
        two vectors that genuinely disagree.

    Raises:
        ValueError: If no sectors were supplied, if the two weight vectors do not
            sum to the same total within ``weight_sum_tolerance``, or if a sector
            carries a non-zero weight on a side but no return on that side.
    """
    ordered: list[str] = list(portfolio_weights)
    ordered.extend(sector for sector in benchmark_weights if sector not in portfolio_weights)
    if not ordered:
        raise ValueError("brinson_fachler needs at least one sector")

    portfolio_total = math.fsum(portfolio_weights.values())
    benchmark_total = math.fsum(benchmark_weights.values())
    if abs(portfolio_total - benchmark_total) > weight_sum_tolerance:
        raise ValueError(
            "portfolio and benchmark weights must sum to the same total for the Brinson "
            f"identity to hold; got {portfolio_total!r} and {benchmark_total!r} "
            f"(difference {portfolio_total - benchmark_total!r} exceeds {weight_sum_tolerance!r})"
        )

    resolved: list[tuple[str, float, float, float, float]] = []
    for sector in ordered:
        w_p = float(portfolio_weights.get(sector, 0.0))
        w_b = float(benchmark_weights.get(sector, 0.0))
        r_p = portfolio_returns.get(sector)
        r_b = benchmark_returns.get(sector)
        if r_p is None:
            if w_p != 0.0:
                raise ValueError(f"sector {sector!r} has portfolio weight {w_p!r} but no portfolio return")
            if r_b is None:
                raise ValueError(f"sector {sector!r} has no portfolio return and no benchmark return")
            r_p = r_b
        if r_b is None:
            if w_b != 0.0:
                raise ValueError(f"sector {sector!r} has benchmark weight {w_b!r} but no benchmark return")
            r_b = r_p
        resolved.append((sector, w_p, w_b, float(r_p), float(r_b)))

    total_portfolio_return = math.fsum(w_p * r_p for _, w_p, _, r_p, _ in resolved)
    total_benchmark_return = math.fsum(w_b * r_b for _, _, w_b, _, r_b in resolved)

    effects: list[SectorEffect] = []
    for sector, w_p, w_b, r_p, r_b in resolved:
        active_weight = w_p - w_b
        effects.append(
            SectorEffect(
                sector=sector,
                portfolio_weight=w_p,
                benchmark_weight=w_b,
                portfolio_return=r_p,
                benchmark_return=r_b,
                allocation=active_weight * (r_b - total_benchmark_return),
                selection=w_b * (r_p - r_b),
                interaction=active_weight * (r_p - r_b),
            )
        )

    return BrinsonResult(
        sectors=tuple(effects),
        portfolio_return=total_portfolio_return,
        benchmark_return=total_benchmark_return,
        active_return=total_portfolio_return - total_benchmark_return,
        allocation=math.fsum(effect.allocation for effect in effects),
        selection=math.fsum(effect.selection for effect in effects),
        interaction=math.fsum(effect.interaction for effect in effects),
    )


def carino_factor(portfolio_return: float, benchmark_return: float) -> float:
    """Return the Carino logarithmic scaling factor for one return pair.

    The factor is ``(ln(1 + Rp) - ln(1 + Rb)) / (Rp - Rb)``. When the two returns
    coincide that expression is 0/0, so the analytic limit ``1 / (1 + Rp)`` applies.
    It is evaluated in the equivalent symmetric form ``2 / ((1 + Rp) + (1 + Rb))``,
    which reduces to ``1 / (1 + Rp)`` when the returns are equal but stays accurate
    to second order just short of coincidence, where the difference of logarithms
    would lose most of its significant digits to cancellation.

    Args:
        portfolio_return: Portfolio return for the period, as a decimal fraction.
        benchmark_return: Benchmark return for the period, as a decimal fraction.

    Returns:
        The scaling factor.

    Raises:
        ValueError: If either return is at or below -100%, which would make the
            wealth relative non-positive and the logarithm undefined.
    """
    portfolio_wealth = 1.0 + portfolio_return
    benchmark_wealth = 1.0 + benchmark_return
    if portfolio_wealth <= 0.0 or benchmark_wealth <= 0.0:
        raise ValueError(
            "Carino linking needs returns above -100%; got portfolio "
            f"{portfolio_return!r} and benchmark {benchmark_return!r}"
        )
    if abs(portfolio_return - benchmark_return) < _CARINO_LIMIT_EPS:
        return 2.0 / (portfolio_wealth + benchmark_wealth)
    return (math.log(portfolio_wealth) - math.log(benchmark_wealth)) / (portfolio_return - benchmark_return)


def carino_link(periods: Sequence[BrinsonResult]) -> LinkedAttribution:
    """Link single-period Brinson results into a residual-free multi-period attribution.

    Every period's effects are scaled by ``k_t / k`` and summed. Because each
    period's three effects already sum to that period's active return, the linked
    effects sum to the compounded active return exactly.

    Sectors absent from a period are treated as contributing zero for that period,
    which is what a zero weight on both sides would have produced anyway.

    Args:
        periods: Single-period results in chronological order.

    Returns:
        A :class:`LinkedAttribution` whose allocation, selection and interaction
        sum to its ``active_return`` to floating-point precision.

    Raises:
        ValueError: If ``periods`` is empty, or if any period's return is at or
            below -100%, which the logarithmic linking cannot represent.
    """
    if not periods:
        raise ValueError("carino_link needs at least one period")

    portfolio_wealth = math.prod(1.0 + period.portfolio_return for period in periods)
    benchmark_wealth = math.prod(1.0 + period.benchmark_return for period in periods)
    total_portfolio_return = portfolio_wealth - 1.0
    total_benchmark_return = benchmark_wealth - 1.0
    total_factor = carino_factor(total_portfolio_return, total_benchmark_return)

    scaling_factors = tuple(
        carino_factor(period.portfolio_return, period.benchmark_return) / total_factor for period in periods
    )

    order: list[str] = []
    scaled: dict[str, list[float]] = {}
    for period, scale in zip(periods, scaling_factors, strict=True):
        for effect in period.sectors:
            if effect.sector not in scaled:
                order.append(effect.sector)
                scaled[effect.sector] = [0.0, 0.0, 0.0]
            bucket = scaled[effect.sector]
            bucket[0] += scale * effect.allocation
            bucket[1] += scale * effect.selection
            bucket[2] += scale * effect.interaction

    sectors = tuple(
        LinkedSectorEffect(
            sector=sector,
            allocation=scaled[sector][0],
            selection=scaled[sector][1],
            interaction=scaled[sector][2],
        )
        for sector in order
    )

    return LinkedAttribution(
        sectors=sectors,
        portfolio_return=total_portfolio_return,
        benchmark_return=total_benchmark_return,
        active_return=total_portfolio_return - total_benchmark_return,
        allocation=math.fsum(sector.allocation for sector in sectors),
        selection=math.fsum(sector.selection for sector in sectors),
        interaction=math.fsum(sector.interaction for sector in sectors),
        scaling_factors=scaling_factors,
    )
