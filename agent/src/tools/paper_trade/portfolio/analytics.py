"""Exact post-valuation NAV, exposure and concentration for pt-v2.0.

The module is a pure projection over three already-validated inputs:

* the immutable Decimal :class:`~.ledger.PortfolioLedger` after fills,
* the prepared per-bucket valuation snapshots or closed-market prior marks,
* the caller-declared direct FX snapshots.

No value is fetched, inferred or taken from an engine float NAV row. A currency
is translated only through its own direct pair; a market name never implies a
currency. Every position row carries its dated mark and FX rate identity, while
cash, per-bucket, per-currency, per-market and per-sector aggregates carry the
same provenance. Caller sectors are applied verbatim and every unmapped
position is reported under the explicit ``unclassified`` bucket.

The reported NAV is the ledger's own rounded NAV. The bridge also exposes the
exact ``Σ cash×fx + Σ qty×price×fx`` identity and the resulting rounding
residual, plus the already-settled conversion rounding in both its local
currency and base value. Conversion rounding is descriptive: it is already
inside the converted cash and is never added to NAV a second time.

The optional attribution document is the same one-day ledger replay expressed
as symbol, market and currency contributions, explicit conversion and fee
effects, and a separately computed two-decimal execution-notional rounding
residual. It is not Brinson allocation/selection/interaction, not sector
attribution and not multi-day period attribution; caller targets are published
only as declared target weights, never as promised executions.

The implementation lives in focused sibling modules (``analytics_common``,
``analytics_benchmark``, ``analytics_exposure``, ``analytics_attribution`` and
its bridge/replay/rollups/weights clusters, ``analytics_verify``,
``analytics_weight_verify``, ``analytics_build``); this facade keeps every
historic ``analytics.<symbol>`` binding path importable unchanged. The
submodules import the common helpers and each other, never this facade, so the
import graph stays acyclic.
"""

from __future__ import annotations

from .analytics_build import build_portfolio_analytics as build_portfolio_analytics
from .analytics_verify import reconcile_attribution as reconcile_attribution

__all__ = ["build_portfolio_analytics", "reconcile_attribution"]
