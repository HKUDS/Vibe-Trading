"""Independent replay of one pt-v2.0 portfolio step document.

The caller supplies the opening ``portfolio_state`` (the same object accepted by
the step request) and the returned success document. This module reconstructs
the ledger from the document's own opening buckets, caller conversions, order
plan and fills with Decimal arithmetic, then re-derives the NAV bridge,
exposure roll-ups and one-day attribution identities. It never refetches marks
or FX and never recomputes a hash whose raw layers are absent; those limits are
published in ``not_verified``.

Only the stable ``paper_trade_reconcile`` envelope leaves this module. A field
disagreement is an issue, not an exception; malformed input raises ``ValueError``
so the existing tool wrapper can emit its stable JSON error envelope.

The implementation lives in focused sibling modules (``reconcile_primitives``,
``reconcile_parse``, ``reconcile_state``, ``reconcile_conversions``,
``reconcile_fills``, ``reconcile_analytics``, ``reconcile_attribution``,
``reconcile_document``); this facade keeps every historic ``reconcile.<symbol>``
binding path importable unchanged. The submodules import the primitives and
each other, never this facade, so the import graph stays acyclic.
"""

from __future__ import annotations

from .reconcile_document import reconcile_portfolio_document as reconcile_portfolio_document

__all__ = ["reconcile_portfolio_document"]
